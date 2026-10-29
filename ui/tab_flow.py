"""功能页 1：可视化流程编排（主入口）。

画布本身是 `ui/flow_component/index.html` —— 一个 Streamlit 静态组件，
零依赖原生 JS，通过 postMessage 与 Python 双向通信：

    拖模块 → 连线 → 单击模块改参数 → 保存 → 回传 Python → 真实检索配置生效

所以这个页面同时承担了原来「建库与切片」和「检索模块」两个 tab 的职责：
- 点「建立索引」模块 → 选文档、选切片策略、建立索引
- 点「BM25 / 向量 / 混合 / Reranker」→ 开关与召回参数
- 保存后写进 session_state，问答页立刻用新配置

三个关键点：
1. 图结构（节点位置、连线）在保存时一并回传，rerun 后能原样恢复
2. nonce 去重：组件每次 render 都会把上次的值再吐一遍，靠 nonce 判重
3. 建库要几秒，用 spinner 包住再 rerun
"""

from __future__ import annotations

from pathlib import Path

import streamlit as st
import streamlit.components.v1 as components

from core.chunking import CHUNK_STRATEGIES
from core.ingest import load_samples, make_document
from core.kb import build_kb
from core.llm import ModelSettings, build_embed_model
from core.retrievers import RetrievalConfig

_COMPONENT_DIR = Path(__file__).with_name("flow_component")
_flow_editor = components.declare_component("rag_flow_editor", path=str(_COMPONENT_DIR))


# ---------------------------------------------------------------------------
# 配置互转
# ---------------------------------------------------------------------------
def _config_to_dict(c: RetrievalConfig) -> dict:
    return {
        "use_vector": c.use_vector,
        "use_bm25": c.use_bm25,
        "use_hybrid": c.use_hybrid,
        "use_rerank": c.use_rerank,
        "use_context": c.use_context,
        "vector_top_k": c.vector_top_k,
        "bm25_top_k": c.bm25_top_k,
        "fusion_top_k": c.fusion_top_k,
        "rerank_top_n": c.rerank_top_n,
        "rerank_candidates": c.rerank_candidates,
    }


def _dict_to_config(d: dict, base: RetrievalConfig) -> RetrievalConfig:
    def num(key, fallback):
        try:
            return int(d.get(key, fallback))
        except (TypeError, ValueError):
            return fallback

    return RetrievalConfig(
        use_vector=bool(d.get("use_vector", base.use_vector)),
        use_bm25=bool(d.get("use_bm25", base.use_bm25)),
        use_hybrid=bool(d.get("use_hybrid", base.use_hybrid)),
        use_rerank=bool(d.get("use_rerank", base.use_rerank)),
        use_context=bool(d.get("use_context", base.use_context)),
        vector_top_k=num("vector_top_k", base.vector_top_k),
        bm25_top_k=num("bm25_top_k", base.bm25_top_k),
        fusion_top_k=num("fusion_top_k", base.fusion_top_k),
        rerank_top_n=num("rerank_top_n", base.rerank_top_n),
        rerank_candidates=num("rerank_candidates", base.rerank_candidates),
    )


def _slice_params(strategy: str, cfg: dict) -> dict:
    if strategy == "token":
        return {
            "chunk_size": int(cfg.get("chunk_size", 256)),
            "chunk_overlap": int(cfg.get("chunk_overlap", 32)),
        }
    if strategy == "sentence_window":
        return {"window_size": int(cfg.get("window_size", 3))}
    if strategy == "semantic":
        return {
            "buffer_size": int(cfg.get("buffer_size", 1)),
            "breakpoint_percentile_threshold": int(cfg.get("threshold", 95)),
        }
    return {}


def _derive_flags(graph: dict | None) -> dict:
    """画布即配置：图上有没有这个模块，就代表这个通道开不开。

    前端也会推导一次，这里是第二道保险 —— 万一前端漏传或图结构异常，
    以图为准，不会出现「画布上没有向量检索节点，但配置里还开着」的矛盾。
    """
    types = {n.get("type") for n in (graph or {}).get("nodes", []) if isinstance(n, dict)}
    has_hybrid = "hybrid" in types
    return {
        # 混合检索 = BM25 + 向量检索的黑盒合体：画了它，两条召回通道都视为开启，
        # 即使画布上没有显式的「向量检索 / BM25」节点（允许 问题向量化/建立索引 直连混合检索）。
        "use_vector": "vector" in types or has_hybrid,
        "use_bm25": "bm25" in types or has_hybrid,
        "use_hybrid": has_hybrid,
        "use_rerank": "rerank" in types,
        "use_context": "context" in types,
    }


def _kb_payload() -> dict:
    kb = st.session_state.get("kb")
    settings: ModelSettings = st.session_state.get("settings") or ModelSettings()
    if kb is None:
        return {"built": False, "nodes": 0, "embed": settings.embed_model, "files": 0}
    return {
        "built": True,
        "nodes": kb.node_count,
        "embed": kb.meta.get("embed_model", settings.embed_model),
        "files": len(kb.meta.get("files", [])),
    }


# ---------------------------------------------------------------------------
# 建库
# ---------------------------------------------------------------------------
def _collect_documents(samples: list[str]) -> list:
    docs = load_samples(samples)
    for up in st.session_state.get("flow_uploads") or []:
        try:
            docs.append(make_document(up.name, up.getvalue()))
        except Exception as exc:  # noqa: BLE001
            st.warning(f"{up.name} 解析失败：{exc}", icon=":material/warning:")
    return docs


def _precheck(strategy: str, docs: list, settings: ModelSettings) -> str | None:
    """切片策略和文档不匹配时，立刻报错，不要跑完才失败。

    这类不匹配是「静默劣化」：不报错，但切出来只有一整块，检索质量全废。
    所以要在花时间算向量之前就点出来。
    """
    import re

    text = "\n".join((d.text or "") for d in docs)
    if strategy == "markdown":
        if not re.search(r"(?m)^\s{0,3}#{1,6}\s+", text):
            return (
                "Markdown 切片靠 `#` 标题下刀，但当前选中的文档一个标题都没有 —— "
                "切出来只会是整整一大块，检索等于失效。"
                "请改用「Token 切片」或「句子切片」，或换成带标题的文档（比如内置的「二级学院与专业详解」）。"
            )
    if strategy == "semantic" and not settings.embed_ready:
        return (
            "语义切片要给每一句话算向量，需要一个可用的向量模型。"
            "请到左侧「高级设置 → 向量来源」确认配置。"
        )
    if strategy == "sentence" and len(text) > 20000:
        return (
            f"句子切片会把文档切成上千个极小的块（当前约 {len(text)} 字），"
            "建库和下检索都会明显变慢。建议改用句子窗口或 Token 切片。"
        )
    return None


def _do_build(cfg: dict, settings: ModelSettings) -> None:
    samples = cfg.get("samples") or ["token"]
    strategy = cfg.get("strategy", "token")
    if strategy not in CHUNK_STRATEGIES:
        strategy = "token"

    docs = _collect_documents(samples)
    if not docs:
        st.session_state["flow_build_error"] = "没有选中任何文档：先在弹窗里勾一份示例，或上传自己的文件。"
        return
    if not settings.embed_ready:
        st.session_state["flow_build_error"] = "向量模型未就绪（左侧「高级设置 → 向量来源」检查一下）。"
        return

    # 策略 / 文档不匹配 -> 在算向量之前就拦掉
    blocked = _precheck(strategy, docs, settings)
    if blocked:
        st.session_state["flow_build_error"] = blocked
        return

    try:
        embed = build_embed_model(settings)
        kb, warnings = build_kb(
            settings=settings,
            embed_model=embed,
            documents=docs,
            strategy=strategy,
            params=_slice_params(strategy, cfg),
        )
    except Exception as exc:  # noqa: BLE001
        st.session_state["flow_build_error"] = f"{type(exc).__name__}: {exc}"
        return

    st.session_state["kb"] = kb
    st.session_state["retrieval_trace"] = None
    st.session_state["last_qa"] = None
    st.session_state["flow_build_error"] = ""
    st.session_state["flow_build_ok"] = (
        f"索引已建立：{kb.node_count} 个块 · `{CHUNK_STRATEGIES[strategy]['node_parser']}`"
    )
    if warnings:
        st.session_state["flow_build_warn"] = "；".join(warnings)


# ---------------------------------------------------------------------------
# 页面
# ---------------------------------------------------------------------------
def render(settings: ModelSettings) -> None:
    config: RetrievalConfig = st.session_state.get("retrieval_config") or RetrievalConfig()
    st.session_state.setdefault("flow_config", _config_to_dict(config))

    result = _flow_editor(
        config=st.session_state["flow_config"],
        kb=_kb_payload(),
        graph=st.session_state.get("flow_graph"),
        key="rag_flow_editor",
        default=None,
    )

    # 组件每次 render 都会把上次的值再吐一遍，靠 nonce 判重
    if isinstance(result, dict):
        nonce = result.get("nonce")
        if nonce and nonce != st.session_state.get("_flow_nonce"):
            st.session_state["_flow_nonce"] = nonce
            cfg = dict(result.get("config") or {})
            graph = result.get("graph") or {}
            # 以画布为准推导启用状态（有节点 = 启用）
            cfg.update(_derive_flags(graph))

            st.session_state["flow_config"] = {**st.session_state["flow_config"], **cfg}
            st.session_state["retrieval_config"] = _dict_to_config(cfg, config)
            if graph:
                st.session_state["flow_graph"] = graph

            if result.get("action") == "build":
                from core.llm import local_model_cached

                first_time = (
                    settings.embed_source == "local"
                    and not local_model_cached(settings.embed_model)
                )
                label = (
                    "正在准备本地向量模型（首次约 90MB，从 hf-mirror 下载）…"
                    if first_time
                    else "正在建立索引…"
                )
                with st.status(label, expanded=True) as status:
                    st.write("① 读取文档，按选中的策略切片")
                    st.write("② 逐块计算向量" + ("（首次要加载模型，会慢一点）" if first_time else ""))
                    _do_build(cfg, settings)
                    err = st.session_state.get("flow_build_error")
                    done = st.session_state.get("flow_build_ok")
                    if err:
                        status.update(label="建立索引失败，原因见左侧栏", state="error", expanded=True)
                    elif done:
                        status.update(label=done, state="complete", expanded=False)
                    else:
                        status.update(label="已提交", state="complete", expanded=False)
            st.rerun()

    # 画布独占整页：任何提示都不放在这里，避免把画布推下去。
    # 建库失败由左侧栏持久显示（不占画布空间），成功用 toast。
    if st.session_state.get("flow_build_error"):
        st.toast("建立索引失败，原因见左侧栏", icon="❌")
