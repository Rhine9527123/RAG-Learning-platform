"""五种切片策略的统一入口。

对应关系（一个策略 = 一个 LlamaIndex NodeParser）：

    token            -> TokenTextSplitter
    sentence         -> SentenceWindowNodeParser(window_size=0)
    sentence_window  -> SentenceWindowNodeParser(window_size=N)
    semantic         -> SemanticSplitterNodeParser
    markdown         -> MarkdownNodeParser

教学上的关键点：
`sentence` 和 `sentence_window` 用的是**同一个** NodeParser，只差 window_size
一个参数。把它们并列摆出来，学习者能亲眼看到「换一个数字，检索效果就变了」。
"""

from __future__ import annotations

import hashlib
import re
from typing import Any, Sequence

from llama_index.core import Document
from llama_index.core.node_parser import (
    MarkdownNodeParser,
    NodeParser,
    SemanticSplitterNodeParser,
    SentenceWindowNodeParser,
    TokenTextSplitter,
)
from llama_index.core.schema import BaseNode, MetadataMode, TextNode

from config import CHUNK_STRATEGIES

# 句子窗口切片把窗口文本存在这个 metadata 键里，检索时由
# MetadataReplacementPostProcessor 换回去。
WINDOW_METADATA_KEY = "window"
ORIGINAL_TEXT_KEY = "original_text"

# 中文句末标点。刻意不包含英文句点 "."，否则 "9.9 元"、"v2.0" 会被切碎。
_SENT_END = "。！？!?；;…\n"


def split_sentences_zh(text: str) -> list[str]:
    """中文分句：逐字符扫描，遇到句末标点断句，保留标点。

    自己写而不用 nltk，是因为 nltk 的 punkt 分句器对中文近乎失效
    （中文句子之间没有空格，也没有句点）。这个函数也就是「句子切片」
    最朴素、最透明的实现。
    """
    sentences: list[str] = []
    buf: list[str] = []
    for ch in text:
        if ch == "\r":
            continue
        if ch == "\n":
            line = "".join(buf).strip()
            if line:
                sentences.append(line)
            buf.clear()
            continue
        buf.append(ch)
        if ch in _SENT_END:
            line = "".join(buf).strip()
            if line:
                sentences.append(line)
            buf.clear()
    tail = "".join(buf).strip()
    if tail:
        sentences.append(tail)
    return sentences


def _stable_id(prefix: str, text: str) -> str:
    """确定性的节点 id：同样的文档 + 同样的策略 -> 同样的 id。

    好处是重建索引后节点可以一一对应，方便教学时做「改一个参数，看哪块变了」。
    """
    digest = hashlib.sha1(text.encode("utf-8")).hexdigest()[:16]
    return f"{prefix}-{digest}"


class SentenceNodeParser(NodeParser):
    """纯句子切分：一句一个节点。

    LlamaIndex 官方没有提供「一句一节点」的 parser —— `SentenceSplitter` 其实是
    按 token 数开窗再对齐句边界，而 `SentenceWindowNodeParser` 的 window_size
    强制 ≥1（必然带上下文）。所以这里基于官方的 `NodeParser` 抽象补一个，
    只做一件事：把文本按中文句末标点切开，每句生成一个标准 TextNode。
    """

    def _parse_nodes(
        self, nodes: Sequence[BaseNode], show_progress: bool = False, **kwargs: Any
    ) -> list[BaseNode]:
        out: list[BaseNode] = []
        for node in nodes:
            text = node.get_content(metadata_mode=MetadataMode.NONE)
            for sentence in split_sentences_zh(text):
                sentence = sentence.strip()
                if not sentence:
                    continue
                out.append(TextNode(text=sentence, metadata=dict(node.metadata or {})))
        return out


def _make_parser(strategy: str, params: dict, embed_model=None):
    if strategy == "token":
        return TokenTextSplitter(
            chunk_size=int(params["chunk_size"]),
            chunk_overlap=int(params["chunk_overlap"]),
            separator="\n",
            backup_separators=["。", "！", "？", "；", "，", " "],
        )
    if strategy == "sentence":
        return SentenceNodeParser()
    if strategy == "sentence_window":
        return SentenceWindowNodeParser(
            window_size=int(params["window_size"]),
            sentence_splitter=split_sentences_zh,
            metadata_key=WINDOW_METADATA_KEY,
            original_text_metadata_key=ORIGINAL_TEXT_KEY,
        )
    if strategy == "semantic":
        if embed_model is None:
            raise ValueError("语义切片需要 embedding 模型，请先在侧栏配置 API Key。")
        return SemanticSplitterNodeParser(
            buffer_size=int(params["buffer_size"]),
            breakpoint_percentile_threshold=int(params["breakpoint_percentile_threshold"]),
            embed_model=embed_model,
            # 必须显式传中文分句器：SemanticSplitterNodeParser 默认用
            # SentenceSplitter（按 token 开窗），一段几百字的中文会被它当成
            # "一个句子"，于是永远算不出断点、整篇切成一块。
            sentence_splitter=split_sentences_zh,
        )
    if strategy == "markdown":
        return MarkdownNodeParser()
    raise ValueError(f"未知切片策略：{strategy}")


def build_nodes(
    strategy: str,
    documents: list[Document],
    params: dict | None = None,
    embed_model=None,
) -> tuple[list[BaseNode], list[str]]:
    """按策略切分文档，返回 (节点列表, 警告列表)。"""
    if strategy not in CHUNK_STRATEGIES:
        raise ValueError(f"未知切片策略：{strategy}")

    merged = {**CHUNK_STRATEGIES[strategy]["params"], **(params or {})}
    parser = _make_parser(strategy, merged, embed_model)
    warnings: list[str] = []

    if strategy == "markdown":
        has_heading = any(
            re.search(r"(?m)^\s{0,3}#{1,6}\s+", doc.text or "") for doc in documents
        )
        if not has_heading:
            warnings.append(
                "选中的文档里没有找到任何 Markdown 标题（`#`/`##`），"
                "MarkdownNodeParser 会退化成整篇一个块 —— 正是这个策略的失效场景。"
            )

    nodes = parser.get_nodes_from_documents(documents, show_progress=False)

    if strategy == "semantic" and len(nodes) <= 1:
        warnings.append(
            "只切出了 1 个块。语义切片按「相邻句子向量距离的突变点」下刀，"
            "可以试着把阈值从 95 降到 90 或 85，让断点更敏感。"
        )

    # 统一补 metadata + 稳定 id
    for idx, node in enumerate(nodes):
        node.metadata["chunk_index"] = idx
        node.metadata["chunk_strategy"] = strategy
        filename = node.metadata.get("file_name", "")
        node.metadata["chunk_source"] = filename
        node.id_ = _stable_id(f"{strategy}", f"{filename}|{node.get_content()}")

    return nodes, warnings


def strip_window_metadata(nodes: list[BaseNode]) -> None:
    """句子窗口策略在非窗口模式下不需要保留整段窗口，避免展示时重复。"""
    for node in nodes:
        node.metadata.pop(WINDOW_METADATA_KEY, None)
