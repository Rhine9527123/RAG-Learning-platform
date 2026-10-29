"""知识库：构建索引、持久化、加载。

设计要点：
- 索引常驻内存（VectorStoreIndex 默认 SimpleVectorStore），重启后从
  data/storage/<kb_id>/ 恢复，不需要重新调 embedding 接口（省钱）。
- kb_id 是确定性的：同样的「文档 + 切片策略 + 参数」得到同一个 id，
  重建时原地覆盖，不会堆出一堆历史目录。
- meta.json 里记下 embedding 模型签名。换了 embedding 模型再加载旧索引
  会维度不匹配，这里提前拦住并提示重建。
"""

from __future__ import annotations

import hashlib
import json
import shutil
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from llama_index.core import Document, StorageContext, VectorStoreIndex, load_index_from_storage
from llama_index.core.schema import BaseNode

from config import STORAGE_DIR
from core.chunking import build_nodes
from core.llm import ModelSettings


@dataclass
class KnowledgeBase:
    kb_id: str
    index: VectorStoreIndex
    nodes: list[BaseNode]
    meta: dict = field(default_factory=dict)

    @property
    def persist_dir(self) -> Path:
        return STORAGE_DIR / self.kb_id

    @property
    def node_count(self) -> int:
        return len(self.nodes)


def _signature(settings: ModelSettings, strategy: str, params: dict, filenames: list[str]) -> str:
    payload = json.dumps(
        {
            "files": sorted(filenames),
            "strategy": strategy,
            "params": params,
            "embed_model": settings.embed_model,
            "embed_base": settings.effective_embed_base,
        },
        ensure_ascii=False,
        sort_keys=True,
    )
    return hashlib.sha1(payload.encode("utf-8")).hexdigest()[:10]


def build_kb(
    *,
    settings: ModelSettings,
    embed_model,
    documents: list[Document],
    strategy: str,
    params: dict,
) -> tuple[KnowledgeBase, list[str]]:
    """切片 -> 建向量索引 -> 落盘。返回知识库对象与需要提示给用户的警告。"""
    filenames = [d.metadata.get("file_name", "?") for d in documents]
    kb_id = f"kb-{strategy}-{_signature(settings, strategy, params, filenames)}"

    nodes, warnings = build_nodes(strategy, documents, params, embed_model=embed_model)
    if not nodes:
        raise ValueError("切片结果为空，无法建立索引。请检查文档内容或调整切片参数。")

    index = VectorStoreIndex(nodes, embed_model=embed_model, show_progress=False)

    meta = {
        "kb_id": kb_id,
        "strategy": strategy,
        "params": params,
        "files": [
            {
                "name": d.metadata.get("file_name"),
                "chars": len(d.text or ""),
            }
            for d in documents
        ],
        "node_count": len(nodes),
        "embed_model": settings.embed_model,
        "embed_source": settings.embed_source,
        "embed_base_url": settings.effective_embed_base if settings.embed_source == "api" else "local",
        "created_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    }

    kb = KnowledgeBase(kb_id=kb_id, index=index, nodes=nodes, meta=meta)
    persist_kb(kb)
    return kb, warnings


def persist_kb(kb: KnowledgeBase) -> None:
    kb.persist_dir.mkdir(parents=True, exist_ok=True)
    kb.index.storage_context.persist(persist_dir=str(kb.persist_dir))
    (kb.persist_dir / "meta.json").write_text(
        json.dumps(kb.meta, ensure_ascii=False, indent=2), encoding="utf-8"
    )


def read_meta(kb_id: str) -> dict | None:
    path = STORAGE_DIR / kb_id / "meta.json"
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None


def load_kb(kb_id: str, settings: ModelSettings, embed_model) -> KnowledgeBase:
    """从磁盘恢复索引。embedding 模型不一致时抛错，避免加载出维度错乱的索引。"""
    meta = read_meta(kb_id)
    if meta is None:
        raise FileNotFoundError(f"找不到知识库 {kb_id} 的元信息。")

    if meta.get("embed_model") != settings.embed_model:
        raise ValueError(
            f"该知识库是用「{meta.get('embed_model')}」建立的，当前向量模型是"
            f"「{settings.embed_model}」，两者向量维度不同，无法复用。请点「重建索引」。"
        )
    if meta.get("embed_source", "api") != settings.embed_source:
        raise ValueError(
            "该知识库建立时的向量来源（本地/云端）和当前不一致，向量空间不可比。"
            "请点「重建索引」。"
        )

    storage_context = StorageContext.from_defaults(persist_dir=str(STORAGE_DIR / kb_id))
    index = load_index_from_storage(storage_context, embed_model=embed_model)
    nodes = list(index.docstore.docs.values())
    return KnowledgeBase(kb_id=kb_id, index=index, nodes=nodes, meta=meta)


def list_kbs() -> list[dict]:
    """列出本地已持久化的知识库，按创建时间倒序。"""
    items: list[dict] = []
    if not STORAGE_DIR.exists():
        return items
    for path in STORAGE_DIR.iterdir():
        if not path.is_dir():
            continue
        meta = read_meta(path.name)
        if meta:
            items.append(meta)
    items.sort(key=lambda m: m.get("created_at", ""), reverse=True)
    return items


def delete_kb(kb_id: str) -> None:
    path = STORAGE_DIR / kb_id
    if path.exists():
        shutil.rmtree(path, ignore_errors=True)
