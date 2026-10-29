"""功能页 2：可插拔检索模块 + 检索过程透视。

四个开关就是四个独立的检索组件，关掉任何一个都能立刻看到召回结果的变化。
这一页不生成答案，只看"检索到了什么"，方便把检索和生成两个问题分开排查。
"""

from __future__ import annotations

import pandas as pd
import streamlit as st

import ui.theme as theme
from config import MODULE_INFO
from core.llm import ModelSettings, build_llm
from core.retrievers import RetrievalConfig, retrieve


def _render_switches() -> RetrievalConfig:
    current: RetrievalConfig = st.session_state.get("retrieval_config") or RetrievalConfig()

    st.markdown("#### 可插拔检索模块")
    cols = st.columns(4)
    keys = ["vector", "bm25", "hybrid", "rerank"]
    toggles = {}
    for col, key in zip(cols, keys):
        with col:
            toggles[key] = st.toggle(
                MODULE_INFO[key]["label"],
                value=getattr(current, f"use_{key}"),
                key=f"toggle_{key}",
            )

    for key in keys:
        info = MODULE_INFO[key]
        with st.expander(
            f"{info['label']} — 它是干什么的",
            icon=":material/toggle_on:" if toggles[key] else ":material/toggle_off:",
            expanded=False,
        ):
            st.markdown(info["desc"])
            if not toggles[key]:
                st.error(f"**关掉之后**：{info['off_effect']}", icon=":material/block:")

    with st.expander("检索参数", expanded=True):
        c1, c2, c3 = st.columns(3)
        with c1:
            vector_top_k = st.slider("向量召回数", 1, 20, current.vector_top_k, key="p_vector_top_k")
        with c2:
            bm25_top_k = st.slider("BM25 召回数", 1, 20, current.bm25_top_k, key="p_bm25_top_k")
        with c3:
            fusion_top_k = st.slider("融合后保留数", 1, 20, current.fusion_top_k, key="p_fusion_top_k")
        c4, c5 = st.columns(2)
        with c4:
            rerank_candidates = st.slider(
                "送进 Rerank 的候选数", 2, 20, current.rerank_candidates, key="p_rerank_candidates",
                help="召回要宽，重排要严。候选太少会让 Rerank 无事可做。",
            )
        with c5:
            rerank_top_n = st.slider(
                "Rerank 后保留数（最终上下文）", 1, 10, current.rerank_top_n, key="p_rerank_top_n",
                help="最终塞进 prompt 的块数。太多会稀释重点，太少会漏关键信息。",
            )

    return RetrievalConfig(
        use_vector=toggles["vector"],
        use_bm25=toggles["bm25"],
        use_hybrid=toggles["hybrid"],
        use_rerank=toggles["rerank"],
        vector_top_k=vector_top_k,
        bm25_top_k=bm25_top_k,
        fusion_top_k=fusion_top_k,
        rerank_top_n=rerank_top_n,
        rerank_candidates=rerank_candidates,
    )


def _hit_table(hits, empty_text: str) -> None:
    if not hits:
        st.caption(empty_text)
        return
    df = pd.DataFrame(
        [{"#": h.rank, "分数": h.score, "内容": h.preview} for h in hits]
    )
    st.dataframe(df, width="stretch", hide_index=True)


def render(settings: ModelSettings) -> None:
    # 检索按钮列与输入框底边对齐（不用 write 垫片）
    st.markdown(
        """<style>
div[data-testid="stColumn"]:has(.st-key-ret_go) > div[data-testid="stVerticalBlock"] {
  height: 100%; justify-content: flex-end;
}
</style>""",
        unsafe_allow_html=True,
    )
    st.markdown("## 第二步：插拔检索模块，看召回怎么变")

    config = _render_switches()
    st.session_state["retrieval_config"] = config

    kb = st.session_state.get("kb")
    if kb is None:
        theme.empty_state(
            "还没有知识库",
            "先到「建库与切片」页选文档、建立索引，再回来试检索。",
            "这一步只检索、不生成答案，可以放心反复试。",
        )
        return

    st.divider()
    c1, c2 = st.columns([3, 1])
    with c1:
        query = st.text_input(
            "用一个问题试试检索（不会生成答案，只看召回了什么）",
            key="probe_query",
            placeholder="例如：新生报到需要带哪些材料？",
        )
    with c2:
        # 与输入框底边对齐（样式见下方注入的 CSS），不用 write 垫片
        go = st.button(
            "检索", icon=":material/search:", key="ret_go",
            width="stretch", type="primary",
        )

    if not go or not query.strip():
        st.caption("提示：同一个问题，先关掉 BM25 试一次，再打开试一次，对比召回结果的差异。")
        return


    llm = None
    if config.use_rerank and settings.llm_ready:
        try:
            llm = build_llm(settings)
        except Exception as exc:  # noqa: BLE001
            st.warning(f"Rerank 需要 LLM，但初始化失败：{exc}")

    with st.spinner("检索中…"):
        try:
            trace = retrieve(
                index=kb.index, nodes=kb.nodes, query=query, config=config, llm=llm
            )
        except Exception as exc:  # noqa: BLE001
            theme.error_state(
                title="检索执行失败",
                reason=f"{type(exc).__name__}: {exc}",
                scope="本次检索没有返回结果，知识库本身未受影响。",
                kept="已建好的索引、检索开关与参数都还在。",
                action="确认知识库可用后重新点「检索」；"
                "若刚切换过向量模型，需要回「建库与切片」重建索引。",
                code="RAG-E3001",
                retryable=True,
            )
            return

    st.session_state["retrieval_trace"] = trace

    st.markdown("#### 这条链路走了哪些步骤")
    mode_label = {
        "hybrid": "混合检索（RRF 融合）",
        "vector": "仅向量检索",
        "bm25": "仅 BM25 检索",
        "vector+bm25": "向量 + BM25（未融合，直接拼接）",
        "none": "无通道",
    }.get(trace.effective_mode, trace.effective_mode)
    st.markdown(f"**生效模式**：`{mode_label}`")

    df = pd.DataFrame(
        [
            {"阶段": s["name"], "输出条数": s["count"], "耗时(ms)": s["ms"], "说明": s["detail"]}
            for s in trace.stages
        ]
    )
    st.dataframe(df, width="stretch", hide_index=True)
    for note in trace.notes:
        st.warning(note, icon=":material/warning:")

    st.markdown("#### 各通道分别召回了什么")
    tab_vec, tab_bm25, tab_fused, tab_rerank = st.tabs(
        ["向量检索", "BM25 检索", "融合结果", "Rerank 之后"]
    )
    with tab_vec:
        _hit_table(trace.channels.get("vector", []), "向量通道未启用，或没有召回结果。")
        st.caption("向量检索按语义相似度打分，分数在 0~1 之间，但**不同模型之间不可比**。")
    with tab_bm25:
        _hit_table(trace.channels.get("bm25", []), "BM25 通道未启用，或没有命中任何关键词。")
        st.caption(
            "BM25 分数没有上界，且只有字面重合才有分。"
            "试试搜一个型号或错误码（比如 `42902`、`XHC-100A`），BM25 会明显强于向量。"
        )
    with tab_fused:
        _hit_table(trace.fused, "没有融合结果。")
        st.caption(
            "RRF 只看排名不看分数：两条通道里都排前面的块会被顶上来。"
            "这正是混合检索比单独一路稳的原因。"
        )
    with tab_rerank:
        _hit_table(trace.reranked, "没有 Rerank 结果（可能未启用，或判定全部不相关）。")
        st.caption("Rerank 会把候选逐块判断题干是否**真的含有答案**，顺序常常和召回顺序差很远。")

    st.markdown(f"#### 最终进入 prompt 的 {len(trace.final)} 个块")
    for i, hit in enumerate(trace.final, start=1):
        source = hit.node.metadata.get("file_name", "?")
        st.markdown(f"**[{i}] {source} · 第 {hit.node.metadata.get('chunk_index', '-')} 块**")
        st.text((hit.node.get_content() or "")[:1000])
