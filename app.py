"""RAG 知识库教学教具 —— 应用入口。

启动：双击 启动.bat（或 streamlit run app.py）

页面结构刻意做成一条直线，和 RAG 的真实流程一致：

    选文档 → 切片（索引前）→ 建索引 → 插拔检索模块（索引后）→ 问答

每一页都把中间结果摊开，让「检索错 → 上下文错 → 答案错」这条因果链可见。
"""

from __future__ import annotations

import streamlit as st

st.set_page_config(
    page_title="RAG 知识库教学教具",
    page_icon="◈",
    layout="wide",
    initial_sidebar_state="expanded",
)

import ui.sidebar as sidebar
import ui.tab_flow as tab_flow
import ui.tab_qa as tab_qa
import ui.theme as theme
from config import APP_SUBTITLE, APP_TITLE
from core.llm import apply_global_settings

# 样式必须最先注入，后面的组件才能吃到令牌
theme.inject()


def main() -> None:
    settings = sidebar.render_sidebar()

    # 装一次全局 Settings 兜底（多数组件我们都显式传了模型，这只是保险）。
    # 用签名判断，避免每次重跑都重建模型客户端。
    signature = (settings.base_url, settings.llm_model, settings.embed_model, bool(settings.api_key))
    if st.session_state.get("_settings_signature") != signature:
        try:
            apply_global_settings(settings)
        except Exception:  # noqa: BLE001 - 兜底失败不应阻塞界面
            pass
        st.session_state["_settings_signature"] = signature

    tab1, tab2 = st.tabs(["流程编排", "问答与对比"])
    with tab1:
        # 画布主入口：建库 + 检索配置都在这里改，保存后写进 session_state
        tab_flow.render(settings)
    with tab2:
        # 必须放在 tab1 之后渲染：tab1 会写入 st.session_state["retrieval_config"]，
        # tab2 读它。Streamlit 的 tabs 是按代码顺序全部执行的。
        tab_qa.render(settings)


if __name__ == "__main__":
    main()
