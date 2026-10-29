"""可插拔检索模块：向量 / BM25 / 混合 / Rerank。

全部基于 LlamaIndex 官方组件：

    vector      -> VectorStoreIndex.as_retriever()      (VectorIndexRetriever)
    bm25        -> llama_index.retrievers.bm25.BM25Retriever（子类，补中文分词）
    hybrid      -> QueryFusionRetriever(mode=reciprocal_rerank)
    rerank      -> LLMRerank
    sentence window -> MetadataReplacementPostProcessor

关于 BM25 的中文坑（这是真实事故点，值得单独讲）：
官方 BM25Retriever 用 `token_pattern=r"(?u)\\b\\w\\w+\\b"` 切词。在 unicode 下
`\\w` 是匹配中文字符的，而中文句子没有空格，于是**整句话会被当成一个 token**，
BM25 退化成"按整句精确匹配"，分数几乎全是 0。所以中文场景必须先分词，
这里用 jieba 预处理，再交给官方的 bm25s 建索引。
"""

from __future__ import annotations

import re
import time
from dataclasses import dataclass, field
from typing import Any

import jieba
from llama_index.core.base.base_retriever import BaseRetriever
from llama_index.core.llms import MockLLM
from llama_index.core.postprocessor import (
    LLMRerank,
    MetadataReplacementPostProcessor,
)
from llama_index.core.retrievers import QueryFusionRetriever
from llama_index.core.schema import BaseNode, MetadataMode, NodeWithScore, QueryBundle
from llama_index.core.vector_stores.utils import metadata_dict_to_node, node_to_metadata_dict
from llama_index.retrievers.bm25 import BM25Retriever

from core.chunking import WINDOW_METADATA_KEY

_TOKEN_WS = re.compile(r"\S+")
_ASCII_TOKEN = re.compile(r"[A-Za-z0-9][A-Za-z0-9\-_.]*")
_HAS_CJK = re.compile(r"[\u4e00-\u9fff]")

# jieba 首次调用会加载词典，预热一下，避免第一次检索莫名其妙卡 2 秒
jieba.initialize()


def tokenize_zh(text: str) -> list[str]:
    """中文分词：英文/数字/型号整体保留，中文走 jieba。"""
    tokens = [m.group().lower() for m in _ASCII_TOKEN.finditer(text)]
    for word in jieba.cut(text):
        w = word.strip().lower()
        if w and _HAS_CJK.search(w):
            tokens.append(w)
    return tokens


class ChineseBM25Retriever(BM25Retriever):
    """官方 BM25Retriever + 中文分词。

    只改两件事：
      1. 建索引时先把节点文本用 jieba 切成空格分隔的串
      2. 检索时对 query 做同样处理
    节点正文原样保留在 corpus 里，所以展示出来的还是原文，不是带空格的乱码。
    """

    def __init__(
        self,
        nodes: list[BaseNode] | None = None,
        similarity_top_k: int = 2,
        existing_bm25: Any = None,
        **kwargs: Any,
    ) -> None:
        import bm25s

        self.stemmer = None
        self.similarity_top_k = similarity_top_k
        self.token_pattern = r"\S+"
        self.skip_stemming = True

        if existing_bm25 is not None:
            self.bm25 = existing_bm25
            self.corpus = existing_bm25.corpus
        else:
            if not nodes:
                raise ValueError("BM25 需要节点列表。")
            self.corpus = [node_to_metadata_dict(node) for node in nodes]
            corpus_tokens = bm25s.tokenize(
                [" ".join(tokenize_zh(node.get_content(metadata_mode=MetadataMode.EMBED))) for node in nodes],
                token_pattern=r"\S+",
                show_progress=False,
            )
            self.bm25 = bm25s.BM25()
            self.bm25.index(corpus_tokens, show_progress=False)

        BaseRetriever.__init__(self, **kwargs)

    def _retrieve(self, query_bundle: QueryBundle) -> list[NodeWithScore]:
        import bm25s

        tokenized = bm25s.tokenize(
            " ".join(tokenize_zh(query_bundle.query_str)),
            token_pattern=r"\S+",
            show_progress=False,
        )
        k = min(self.similarity_top_k, len(self.corpus))
        if k <= 0:
            return []
        indexes, scores = self.bm25.retrieve(tokenized, k=k, show_progress=False)

        nodes: list[NodeWithScore] = []
        for idx, score in zip(indexes[0], scores[0]):
            if isinstance(idx, dict):
                node = metadata_dict_to_node(idx)
            else:
                node_dict = self.corpus[int(idx)]
                node = metadata_dict_to_node(node_dict)
            # bm25s 对完全没命中的文档会给 0 分，这些块留着只会污染上下文
            if float(score) <= 0:
                continue
            nodes.append(NodeWithScore(node=node, score=float(score)))
        return nodes


# ---------------------------------------------------------------------------
# 检索配置
# ---------------------------------------------------------------------------
@dataclass
class RetrievalConfig:
    use_vector: bool = True
    use_bm25: bool = True
    use_hybrid: bool = True
    use_rerank: bool = True
    use_context: bool = True

    vector_top_k: int = 6
    bm25_top_k: int = 6
    fusion_top_k: int = 6
    rerank_top_n: int = 4
    rerank_candidates: int = 10

    @property
    def enabled_channels(self) -> list[str]:
        ch = []
        if self.use_vector:
            ch.append("vector")
        if self.use_bm25:
            ch.append("bm25")
        return ch

    def validate(self) -> list[str]:
        notes = []
        if not self.use_vector and not self.use_bm25:
            raise ValueError("至少要保留一个召回通道（向量 或 BM25），否则检索无输入。")
        if self.use_hybrid and len(self.enabled_channels) < 2:
            notes.append(
                "混合检索需要两个通道同时开启；当前只开了一个，已自动退化为单通道检索。"
            )
        return notes


# ---------------------------------------------------------------------------
# 检索过程追踪（教学核心：把中间结果全部摊开）
# ---------------------------------------------------------------------------
@dataclass
class ChannelHit:
    channel: str
    rank: int
    score: float
    node_id: str
    preview: str


@dataclass
class RetrievalTrace:
    stages: list[dict] = field(default_factory=list)
    channels: dict[str, list[ChannelHit]] = field(default_factory=dict)
    fused: list[ChannelHit] = field(default_factory=list)
    reranked: list[ChannelHit] = field(default_factory=list)
    final: list[NodeWithScore] = field(default_factory=list)
    effective_mode: str = ""
    notes: list[str] = field(default_factory=list)

    def add_stage(self, name: str, count: int, elapsed_ms: float, detail: str = "") -> None:
        self.stages.append(
            {"name": name, "count": count, "ms": round(elapsed_ms, 1), "detail": detail}
        )


def _preview(node: BaseNode, limit: int = 90) -> str:
    text = (node.get_content(metadata_mode=MetadataMode.NONE) or "").strip()
    text = re.sub(r"\s+", " ", text)
    return text[:limit] + ("…" if len(text) > limit else "")


def _to_hits(channel: str, items: list[NodeWithScore]) -> list[ChannelHit]:
    return [
        ChannelHit(
            channel=channel,
            rank=i + 1,
            score=round(float(it.score or 0.0), 4),
            node_id=it.node.node_id,
            preview=_preview(it.node),
        )
        for i, it in enumerate(items)
    ]


# ---------------------------------------------------------------------------
# Rerank prompt（中文）
# ---------------------------------------------------------------------------
# LLMRerank 内部固定用 {context_str} 和 {query_str} 两个变量做格式化，
# 另外两个钩子都可以替换：format_node_batch_fn 决定候选怎么编号，
# parse_choice_select_answer_fn 决定怎么读模型的回答。
RERANK_PROMPT_ZH = """你是检索结果相关性判定器。

用户的问题：{query_str}

候选资料片段（每段前面方括号里的数字是它的编号）：
{context_str}

请判断每一段资料是否**真正含有回答问题所需的具体信息**，而不仅仅是话题相近。
只输出一个 JSON 数组，元素是相关片段的编号，例如 [1, 3]。
如果没有任何一段真正相关，就输出 []。不要输出任何解释文字。
"""


def _format_candidates(nodes: list[BaseNode]) -> str:
    blocks = []
    for i, node in enumerate(nodes, start=1):
        text = (node.get_content(metadata_mode=MetadataMode.NONE) or "").strip()
        text = re.sub(r"\s+", " ", text)
        blocks.append(f"[{i}] {text[:900]}")
    return "\n\n".join(blocks)


def _parse_choices(answer: str, num_children: int) -> tuple[list[int], list[float]]:
    """从模型回答里抠出被判定为相关的编号。

    输入是 1-based 编号（与 _format_candidates 一致），LLMRerank 内部会自己减 1。
    返回空列表 = 模型认为全部不相关，上层会据此回退到召回顺序。
    """
    numbers: list[int] = []
    for token in re.findall(r"\d+", answer or ""):
        value = int(token)
        if 1 <= value <= num_children and value not in numbers:
            numbers.append(value)
    return numbers, [1.0] * len(numbers)


def build_rerank_postprocessor(llm, top_n: int, candidates: int) -> LLMRerank:
    from llama_index.core.prompts import PromptTemplate

    return LLMRerank(
        llm=llm,
        choice_select_prompt=PromptTemplate(RERANK_PROMPT_ZH),
        choice_batch_size=max(1, min(candidates, 10)),
        format_node_batch_fn=_format_candidates,
        parse_choice_select_answer_fn=_parse_choices,
        top_n=top_n,
    )


# ---------------------------------------------------------------------------
# 主检索函数
# ---------------------------------------------------------------------------
def retrieve(
    *,
    index,
    nodes: list[BaseNode],
    query: str,
    config: RetrievalConfig,
    llm=None,
) -> RetrievalTrace:
    """按配置组装检索链路，并把每一步的中间结果记进 trace。"""
    trace = RetrievalTrace()
    trace.notes.extend(config.validate())
    channels = config.enabled_channels

    vector_retriever = None
    if config.use_vector:
        vector_retriever = index.as_retriever(similarity_top_k=config.vector_top_k)

    bm25_retriever = None
    if config.use_bm25:
        bm25_retriever = ChineseBM25Retriever(
            nodes=nodes,
            similarity_top_k=min(config.bm25_top_k, max(1, len(nodes))),
        )

    # ---- 阶段 1：召回 ----------------------------------------------------
    candidates: list[NodeWithScore] = []

    if config.use_hybrid and len(channels) == 2:
        trace.effective_mode = "hybrid"
        t0 = time.perf_counter()
        # QueryFusionRetriever 在 llm=None 时会回落到全局 Settings.llm（可能未配置
        # 而直接抛错）。num_queries=1 表示不做查询改写、只用 LLM 以外的东西，
        # 所以这里塞一个 MockLLM 占位即可，不会产生额外 API 调用。
        fusion = QueryFusionRetriever(
            retrievers=[vector_retriever, bm25_retriever],
            llm=llm or MockLLM(),
            mode="reciprocal_rerank",
            similarity_top_k=config.fusion_top_k,
            num_queries=1,        # 1 = 不做查询改写，只做融合
            use_async=False,
            retriever_weights=[0.6, 0.4],
        )
        fused = fusion.retrieve(query)
        trace.add_stage(
            "混合检索（RRF 融合）",
            len(fused),
            (time.perf_counter() - t0) * 1000,
            "向量 + BM25 按排名倒数融合，两路互补",
        )
        trace.fused = _to_hits("fused", fused)
        candidates = fused

        # 混合模式下也把两路各自的原始结果单独记一份，方便对照"谁贡献了这条"
        t0 = time.perf_counter()
        trace.channels["vector"] = _to_hits("vector", vector_retriever.retrieve(query))
        trace.add_stage(
            "向量召回（对照）", len(trace.channels["vector"]), (time.perf_counter() - t0) * 1000
        )
        t0 = time.perf_counter()
        trace.channels["bm25"] = _to_hits("bm25", bm25_retriever.retrieve(query))
        trace.add_stage(
            "BM25 召回（对照）", len(trace.channels["bm25"]), (time.perf_counter() - t0) * 1000
        )
    else:
        # 非混合：各通道独立召回，按通道顺序去重拼接（naive 融合）
        trace.effective_mode = "+".join(channels) if channels else "none"
        raw: dict[str, list[NodeWithScore]] = {}
        for name, retriever in (("vector", vector_retriever), ("bm25", bm25_retriever)):
            if retriever is None:
                continue
            t0 = time.perf_counter()
            hits = retriever.retrieve(query)
            raw[name] = hits
            trace.channels[name] = _to_hits(name, hits)
            trace.add_stage(
                f"{'向量' if name == 'vector' else 'BM25'} 召回",
                len(hits),
                (time.perf_counter() - t0) * 1000,
                "未开混合检索：两路结果直接拼接去重",
            )
        merged: dict[str, NodeWithScore] = {}
        for name in ("vector", "bm25"):
            for item in raw.get(name, []):
                merged.setdefault(item.node.node_id, item)
        candidates = list(merged.values())
        trace.fused = _to_hits("naive", candidates)

    if not candidates:
        trace.notes.append("所有召回通道都没有返回结果，请检查知识库是否为空。")
        return trace

    # ---- 阶段 2：句子窗口还原 -------------------------------------------
    if any(WINDOW_METADATA_KEY in (c.node.metadata or {}) for c in candidates):
        t0 = time.perf_counter()
        candidates = MetadataReplacementPostProcessor(
            target_metadata_key=WINDOW_METADATA_KEY
        ).postprocess_nodes(candidates, query_bundle=QueryBundle(query_str=query))
        trace.add_stage(
            "句子窗口还原",
            len(candidates),
            (time.perf_counter() - t0) * 1000,
            "把命中句子的前后文窗口贴回去，句子负责找准，窗口负责读全",
        )

    # ---- 阶段 3：Rerank --------------------------------------------------
    pool = candidates[: max(config.rerank_candidates, config.rerank_top_n)]
    if config.use_rerank:
        if llm is None:
            trace.notes.append("Rerank 需要 LLM，但未配置模型，已跳过。")
        else:
            t0 = time.perf_counter()
            reranked = build_rerank_postprocessor(
                llm, config.rerank_top_n, len(pool)
            ).postprocess_nodes(pool, query_bundle=QueryBundle(query_str=query))
            trace.add_stage(
                "LLM Rerank",
                len(reranked),
                (time.perf_counter() - t0) * 1000,
                f"对 {len(pool)} 个候选逐块判定相关性，保留前 {config.rerank_top_n}",
            )
            trace.reranked = _to_hits("reranked", reranked)
            if not reranked:
                trace.notes.append(
                    "Rerank 判定所有候选都不相关，已回退到召回结果顺序。"
                )
                reranked = pool[: config.rerank_top_n]
            candidates = reranked
    else:
        candidates = pool[: config.rerank_top_n]
        trace.notes.append("Rerank 已关闭：最终上下文完全由召回分数决定。")

    trace.final = candidates
    return trace
