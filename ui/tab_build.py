"""功能页 1：知识库 + 切片。

这一页把「选文档 → 选切片策略 → 看切片结果 → 建索引」串成一条直线，
每个策略旁边都写清楚它最适合什么文档、为什么、什么时候会失效。
"""

from __future__ import annotations

import streamlit as st

from config import CHUNK_STRATEGIES, DEFAULT_STRATEGY
from core.chunking import WINDOW_METADATA_KEY, build_nodes
from core.ingest import _sample_names, load_samples, make_document, sample_catalog
from core.kb import build_kb
import ui.theme as theme
from core.llm import ModelSettings, build_embed_model, local_model_cached


def _collect_documents() -> list:
    selected: list[str] = st.session_state.get("sample_selection", [])
    uploads = st.session_state.get("uploader") or []
    filename_sizes = tuple(sorted((f.name, f.size) for f in uploads))

    signature = (tuple(sorted(selected)), filename_sizes)
    if st.session_state.get("doc_signature") == signature:
        return st.session_state.get("docs", [])

    docs = load_samples(selected)
    problems: list[str] = []
    for uploaded in uploads:
        try:
            docs.append(make_document(uploaded.name, uploaded.getvalue()))
        except Exception as exc:  # noqa: BLE001
            problems.append(f"{uploaded.name}：{exc}")

    st.session_state["doc_signature"] = signature
    st.session_state["docs"] = docs
    st.session_state["doc_problems"] = problems
    st.session_state.pop("preview_nodes", None)
    return docs


def _slider(key: str, label: str, lo: int, hi: int, default: int, step: int = 1, help: str = "") -> int:
    """带 session_state 记忆的滑块：第一次用默认值，之后记住用户的选择。"""
    st.session_state.setdefault(key, default)
    return st.slider(label, lo, hi, step=step, key=key, help=help)


def _render_strategy_params(strategy: str) -> dict:
    params = dict(CHUNK_STRATEGIES[strategy]["params"])
    if strategy == "token":
        params["chunk_size"] = _slider(
            "param_token_chunk_size", "chunk_size（每块多少个 token）",
            64, 1024, params["chunk_size"], step=32,
            help="窗口越小越精准但上下文越碎；越大越完整但噪声越多。",
        )
        params["chunk_overlap"] = _slider(
            "param_token_chunk_overlap", "chunk_overlap（块之间重叠多少 token）",
            0, 256, params["chunk_overlap"], step=16,
            help="重叠是为了让被切断的句子至少完整出现在某一块里。",
        )
    elif strategy == "sentence_window":
        params["window_size"] = _slider(
            "param_window_size", "window_size（命中句前后各带几句）",
            1, 10, params["window_size"],
            help="1 = 前后各带 1 句。数字越大上下文越完整，索引也越大。",
        )
    elif strategy == "semantic":
        params["buffer_size"] = _slider(
            "param_buffer_size", "buffer_size（比较距离时每组几句）",
            1, 3, params["buffer_size"],
            help="1 = 逐句比较；大于 1 = 用一组句子的平均向量比较，抗噪声更强但更迟钝。",
        )
        params["breakpoint_percentile_threshold"] = _slider(
            "param_threshold", "断点阈值（百分位）",
            70, 99, params["breakpoint_percentile_threshold"],
            help="越高切得越少（只在大跳变处下刀）；越低切得越碎。",
        )
    else:
        st.caption("这个策略没有可调参数 —— 切分边界由文档自身的句子标点/标题结构决定。")
    return params


def render(settings: ModelSettings) -> None:
    st.markdown("## 第一步：选文档 + 选切片方式")

    left, right = st.columns([1, 1], gap="large")

    with left:
        st.markdown("#### 1. 选文档")
        catalog = sample_catalog()
        sample_options = [c["strategy"] for c in catalog if c["exists"]]
        st.multiselect(
            "内置示例文档（可多选）",
            sample_options,
            default=st.session_state.get("sample_selection", [DEFAULT_STRATEGY])
            or [DEFAULT_STRATEGY],
            format_func=lambda k: (
                f"{CHUNK_STRATEGIES[k]['short']} · {len(_sample_names(CHUNK_STRATEGIES[k]))} 份"
            ),
            key="sample_selection",
            help="每份文档按「版式最适合哪种切片」归到对应策略下。多选可以混搭，观察不同版式混在一起时切块会变成什么样。",
        )
        st.file_uploader(
            "或上传自己的文档（txt / md / pdf / docx，可多选）",
            type=["txt", "md", "markdown", "pdf", "docx", "csv", "json", "log"],
            accept_multiple_files=True,
            key="uploader",
        )

    with right:
        st.markdown("#### 2. 选切片方式")
        strategy = st.selectbox(
            "切片策略",
            list(CHUNK_STRATEGIES),
            index=list(CHUNK_STRATEGIES).index(st.session_state.get("chunk_strategy", DEFAULT_STRATEGY)),
            format_func=lambda k: CHUNK_STRATEGIES[k]["label"],
            key="chunk_strategy",
            help="一个策略对应 LlamaIndex 的一个 NodeParser。",
        )
        info = CHUNK_STRATEGIES[strategy]
        st.markdown(f"**底层工具**：`{info['node_parser']}`")
        names = _sample_names(info)
        if names:
            st.markdown(f"**推荐语料**（{' / '.join(names)}）")
            if info.get("sample_why"):
                st.caption(info["sample_why"])
        st.markdown(f"**适合**：{info['fits']}")
        st.markdown(f"**为什么**：{info['why']}")
        st.warning(f"**失效场景**：{info['risk']}", icon=":material/warning:")

    st.divider()

    docs = _collect_documents()
    problems = st.session_state.get("doc_problems", [])
    for problem in problems:
        st.error(f"解析失败：{problem}")

    if not docs:
        theme.empty_state(
            "还没有选择文档",
            "从上面的内置示例里挑一份，或者上传你自己的文件。",
            "选好后这里会显示每份文档的字数统计。",
        )
        return

    total_chars = sum(len(d.text or "") for d in docs)
    cols = st.columns(len(docs) if len(docs) <= 4 else 4)
    for i, doc in enumerate(docs):
        with cols[i % len(cols)]:
            st.metric(
                doc.metadata.get("file_name", "?")[:18],
                f"{len(doc.text or ''):,} 字",
                help=doc.metadata.get("file_name"),
            )
    st.caption(f"共 {len(docs)} 份文档 / {total_chars:,} 字。")

    st.markdown("#### 3. 切片参数")
    params = _render_strategy_params(strategy)

    act_a, act_b = st.columns([1, 1])
    with act_a:
        preview_clicked = st.button(
            "预览切片结果", icon=":material/content_cut:", width="stretch"
        )
    with act_b:
        build_clicked = st.button(
            "建立索引", icon=":material/database:", width="stretch", type="primary",
            disabled=not settings.embed_ready,
        )

    if not settings.embed_ready:
        st.warning(
            "向量模型未就绪，无法建立索引。请到左侧「高级设置 → 向量来源」检查配置。",
            icon=":material/memory:",
        )

    if preview_clicked:
        embed_model = build_embed_model(settings) if (strategy == "semantic" and settings.embed_ready) else None
        if strategy == "semantic" and embed_model is None:
            theme.error_state(
                title="语义切片无法执行",
                reason="这个策略要在建索引时给每一句话算向量，需要可用的向量模型。",
                scope="本次切片预览已中止，页面其它功能不受影响。",
                kept="已选文档、切片策略和阈值参数都还在，不用重新选。",
                action="到左侧「高级设置 → 向量来源」补齐配置；"
                "或改用其余四种策略（它们不需要向量模型）。",
                code="RAG-E1003",
                retryable=True,
            )
            return
        with st.spinner("正在切片…（语义切片要逐句算向量，会慢一些）"):
            try:
                nodes, warnings = build_nodes(strategy, docs, params, embed_model=embed_model)
            except Exception as exc:  # noqa: BLE001
                st.error(f"切片失败：{exc}")
                return
        st.session_state["preview_nodes"] = nodes
        st.session_state["preview_warnings"] = warnings
        st.session_state["preview_signature"] = (strategy, tuple(sorted(params.items())))

    nodes = st.session_state.get("preview_nodes") or []
    if nodes:
        if st.session_state.get("preview_signature") != (strategy, tuple(sorted(params.items()))):
            st.info(
                "参数或策略已经改过，下面是**上一次预览**的结果。重新点「预览切片结果」才会按新参数切。",
                icon=":material/refresh:",
            )
        for warning in st.session_state.get("preview_warnings", []):
            st.warning(warning, icon=":material/warning:")

        sizes = [len(n.get_content()) for n in nodes]
        m1, m2, m3, m4 = st.columns(4)
        m1.metric("块数", len(nodes))
        m2.metric("平均块长", f"{sum(sizes) // len(sizes)} 字")
        m3.metric("最长 / 最短", f"{max(sizes)} / {min(sizes)}")
        m4.metric("总占用", f"{sum(sizes):,} 字")
        st.caption(
            "块越短 → 检索越精准但上下文越碎；块越长 → 越完整但噪声越多。"
            "切换上面的策略再预览一次，对比一下这四个数字。"
        )

        with st.expander(f"查看全部 {len(nodes)} 个块", expanded=len(nodes) <= 12):
            for i, node in enumerate(nodes):
                window = node.metadata.get(WINDOW_METADATA_KEY)
                extra = f" · 窗口 {len(window)} 字" if window else ""
                header = f"块 #{i + 1} · {len(node.get_content())} 字{extra}"
                st.markdown(f"**{header}**")
                st.text(node.get_content()[:1200])

    if build_clicked:
        if not settings.embed_ready:
            theme.error_state(
                title="无法建立索引",
                reason="向量模型未就绪（当前「向量来源」配置不完整）。",
                scope="本次建库已中止，已建好的知识库不受影响。",
                kept="已选文档和切片参数都还在，不用重新选。",
                action="到左侧「高级设置 → 向量来源」补齐配置，再点「建立索引」。",
                code="RAG-E1001",
                retryable=True,
            )
            return
        embed_model = build_embed_model(settings)
        first_download = settings.embed_source == "local" and not local_model_cached(settings.embed_model)
        hint = (
            "首次使用：正在下载本地向量模型（约 90MB，走 hf-mirror 镜像，只需一次）…"
            if first_download
            else f"正在为 {len(docs)} 份文档切片并计算向量…"
        )
        try:
            with st.spinner(hint):
                kb, warnings = build_kb(
                    settings=settings,
                    embed_model=embed_model,
                    documents=docs,
                    strategy=strategy,
                    params=params,
                )
        except Exception as exc:  # noqa: BLE001
            theme.error_state(
                title="建立索引失败",
                reason=f"{type(exc).__name__}: {exc}",
                scope=f"本次 {len(docs)} 份文档没有写入索引；此前建好的知识库不受影响。",
                kept="已选文档、切片策略与参数都已保留，会话状态未清空。",
                action="确认 embedding 服务可达、API Key 有效后，重新点「建立索引」。",
                code="RAG-E1002",
                retryable=True,
            )
            return

        st.session_state["kb"] = kb
        st.session_state["retrieval_trace"] = None
        st.session_state["last_qa"] = None
        st.success(
            f"索引已建立：{kb.node_count} 个块，使用 `{CHUNK_STRATEGIES[strategy]['node_parser']}`，"
            f"已保存到 `data/storage/{kb.kb_id}`。现在去「检索模块」页试试。"
        )
        for warning in warnings:
            st.warning(warning, icon=":material/warning:")
