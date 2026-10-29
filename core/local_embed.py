"""本地向量模型：把 fastembed 直接包成 LlamaIndex 的 BaseEmbedding。

为什么不用官方包 `llama-index-embeddings-fastembed`：
    它最新的 0.7.0 在 PyPI 上写的是 `Requires-Python >=3.10,<3.13`。
    Python 3.13 / 3.14 上 pip 只能看到远古的 0.1.2，装上会和 llama-index-core 0.14 打架，
    报错长这样：
        ERROR: Could not find a version that satisfies the requirement
               llama-index-embeddings-fastembed>=0.7.0 (from versions: 0.1.2)
    而这个类一共就 90 行，本质只是 TextEmbedding 的一层皮。
    自己收进项目里，依赖就只剩 `fastembed` 一个（它没有 Python 上限），
    3.11 / 3.12 / 3.13 都能装，也少一个会突然爆版本的第三方包。
"""

from __future__ import annotations

import asyncio
from typing import Any, List, Literal, Optional

import numpy as np
from llama_index.core.base.embeddings.base import BaseEmbedding
from llama_index.core.bridge.pydantic import ConfigDict, Field, PrivateAttr


class FastEmbedLocalEmbedding(BaseEmbedding):
    """fastembed + onnxruntime 的本地向量模型（不需要 torch、不需要 GPU、不需要 Key）。"""

    model_config = ConfigDict(
        protected_namespaces=("pydantic_model_",),
        arbitrary_types_allowed=True,
    )

    model_name: str = Field(
        default="BAAI/bge-small-zh-v1.5",
        description="fastembed 支持的模型名，例如 BAAI/bge-small-zh-v1.5",
    )
    cache_dir: Optional[str] = Field(
        default=None,
        description="模型缓存目录，建议放项目内的 data/models/fastembed",
    )
    threads: Optional[int] = Field(default=None, description="onnxruntime 线程数")
    # bge 系列对「段落 / 查询」用不同的前缀，默认 default 即可；
    # 需要区分时把 doc_embed_type 设成 "passage"。
    doc_embed_type: Literal["default", "passage"] = Field(default="default")
    providers: Optional[List[str]] = Field(
        default=None, description="onnxruntime ExecutionProvider，默认 CPU"
    )

    _model: Any = PrivateAttr()

    def __init__(
        self,
        model_name: str = "BAAI/bge-small-zh-v1.5",
        cache_dir: Optional[str] = None,
        threads: Optional[int] = None,
        doc_embed_type: Literal["default", "passage"] = "default",
        providers: Optional[List[str]] = None,
        **kwargs: Any,
    ) -> None:
        super().__init__(
            model_name=model_name,
            cache_dir=cache_dir,
            threads=threads,
            doc_embed_type=doc_embed_type,
            providers=providers,
            **kwargs,
        )

        try:
            from fastembed import TextEmbedding
        except ImportError as exc:  # pragma: no cover - 依赖缺失时的兜底提示
            raise ImportError(
                "缺少 fastembed，请先执行：pip install -r requirements.txt"
            ) from exc

        self._model = TextEmbedding(
            model_name=model_name,
            cache_dir=cache_dir,
            threads=threads,
            providers=providers,
        )

    @classmethod
    def class_name(cls) -> str:
        return "FastEmbedLocalEmbedding"

    # ---- 同步接口（BaseEmbedding 全靠这四个方法）----
    def _get_text_embedding(self, text: str) -> List[float]:
        return self._get_text_embeddings([text])[0]

    def _get_text_embeddings(self, texts: List[str]) -> List[List[float]]:
        if not texts:
            return []
        if self.doc_embed_type == "passage":
            vectors = list(self._model.passage_embed(texts))
        else:
            vectors = list(self._model.embed(texts))
        return [np.asarray(v, dtype=np.float32).tolist() for v in vectors]

    def _get_query_embedding(self, query: str) -> List[float]:
        vectors = list(self._model.query_embed(query))
        return np.asarray(vectors[0], dtype=np.float32).tolist()

    # ---- 异步接口：包一层线程池，避免阻塞 Streamlit 的事件循环 ----
    async def _aget_text_embedding(self, text: str) -> List[float]:
        return await asyncio.to_thread(self._get_text_embedding, text)

    async def _aget_text_embeddings(self, texts: List[str]) -> List[List[float]]:
        return await asyncio.to_thread(self._get_text_embeddings, texts)

    async def _aget_query_embedding(self, query: str) -> List[float]:
        return await asyncio.to_thread(self._get_query_embedding, query)
