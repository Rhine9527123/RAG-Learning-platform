"""侧栏：API Key 快捷接口。

设计目标：**打开界面只有一个输入框** —— 粘 Key，完事。

分工已经预置成"出厂即可用"：
    对话模型  云端 OpenAI 兼容接口（用你填的那个 Key）
    向量模型  本机 fastembed（不需要 Key，首次自动从 hf-mirror 下载约 90MB）

所以：只填一个 Key，甚至**完全不填 Key 也能建库和检索**（只是生成不了答案）。
需要换供应商 / 换向量模型，才展开「高级设置」。
"""

from __future__ import annotations

import time
from html import escape

import streamlit as st

from config import (
    APP_SUBTITLE,
    APP_TITLE,
    DEFAULT_LOCAL_EMBED,
    EMBED_SOURCES,
    LOCAL_EMBED_MODELS,
    PROVIDERS,
)
from core.llm import (
    ModelSettings,
    local_model_cached,
    probe_connection,
    provider_defaults,
)

from ui.theme import icon_svg

CUSTOM = "自定义输入…"


def _init_state() -> None:
    """把 ModelSettings 的出厂值灌进各个 widget 的 session key。"""
    settings = st.session_state.get("settings") or ModelSettings.load()
    st.session_state["settings"] = settings
    provider = settings.provider if settings.provider in PROVIDERS else list(PROVIDERS)[0]
    info = provider_defaults(provider)
    is_local = settings.embed_source == "local"
    defaults = {
        "cfg_provider": provider,
        "cfg_api_key": settings.api_key,
        "cfg_base_url": settings.base_url or info["base_url"],
        "cfg_llm_model": settings.llm_model or (info["llm_models"] or [""])[0],
        "cfg_embed_source": settings.embed_source,
        "cfg_local_embed_model": settings.embed_model if is_local else DEFAULT_LOCAL_EMBED,
        "cfg_api_embed_model": "" if is_local else settings.embed_model,
        "cfg_embed_api_key": settings.embed_api_key,
        "cfg_embed_base_url": settings.embed_base_url,
        "cfg_temperature": settings.temperature,
        "cfg_max_tokens": settings.max_tokens,
    }
    if not defaults["cfg_api_embed_model"]:
        defaults["cfg_api_embed_model"] = (info["embed_models"] or [""])[0]
    for key, value in defaults.items():
        st.session_state.setdefault(key, value)


def _on_provider_change() -> None:
    """切供应商时，把接口地址和对话模型换成那家的预设。"""
    provider = st.session_state["cfg_provider"]
    info = provider_defaults(provider)
    st.session_state["cfg_base_url"] = info["base_url"]
    st.session_state["cfg_llm_model"] = (info["llm_models"] or [""])[0]
    st.session_state["cfg_api_embed_model"] = (info["embed_models"] or [""])[0]
    st.session_state["cfg_embed_base_url"] = ""
    st.session_state["cfg_embed_api_key"] = ""


def _sync(settings: ModelSettings) -> ModelSettings:
    """把 widget 状态写回 settings。widget 还没渲染的字段也能读到。"""
    settings.provider = st.session_state.get("cfg_provider", settings.provider)
    settings.api_key = (st.session_state.get("cfg_api_key") or "").strip()
    settings.base_url = (st.session_state.get("cfg_base_url") or "").strip()
    settings.llm_model = (st.session_state.get("cfg_llm_model") or "").strip()
    settings.embed_source = st.session_state.get("cfg_embed_source", "local")
    settings.embed_model = (
        st.session_state.get("cfg_local_embed_model", DEFAULT_LOCAL_EMBED)
        if settings.embed_source == "local"
        else (st.session_state.get("cfg_api_embed_model") or "").strip()
    )
    settings.embed_api_key = (st.session_state.get("cfg_embed_api_key") or "").strip()
    settings.embed_base_url = (st.session_state.get("cfg_embed_base_url") or "").strip()
    settings.temperature = st.session_state.get("cfg_temperature", settings.temperature)
    settings.max_tokens = st.session_state.get("cfg_max_tokens", settings.max_tokens)
    return settings


def _picker(label: str, state_key: str, options: list[str], help_text: str = "") -> None:
    """预设下拉 + 自定义输入，结果写回 st.session_state[state_key]。"""
    options = options or []
    current = st.session_state.get(state_key, "")
    if not options:
        st.text_input(label, key=f"{state_key}_free", help=help_text)
        st.session_state[state_key] = st.session_state.get(f"{state_key}_free", "")
        return

    choices = options + [CUSTOM]
    st.selectbox(
        label,
        choices,
        index=choices.index(current) if current in choices else len(choices) - 1,
        key=f"{state_key}_pick",
        help=help_text,
    )
    picked = st.session_state[f"{state_key}_pick"]
    if picked == CUSTOM:
        st.text_input(
            f"{label}（手动填写）",
            value=current if current not in options else "",
            key=f"{state_key}_custom",
        )
        st.session_state[state_key] = st.session_state.get(f"{state_key}_custom", "")
    else:
        st.session_state[state_key] = picked


def _embed_source_controls() -> None:
    """向量来源：本地模型 / 云端 API。"""
    st.radio(
        "向量来源",
        list(EMBED_SOURCES),
        format_func=lambda k: EMBED_SOURCES[k],
        key="cfg_embed_source",
        horizontal=False,
    )

    if st.session_state["cfg_embed_source"] == "local":
        st.selectbox(
            "本地向量模型",
            list(LOCAL_EMBED_MODELS),
            key="cfg_local_embed_model",
            help="第一次用会自动从 hf-mirror.com 下载，之后就完全离线可用。",
        )
        picked = st.session_state["cfg_local_embed_model"]
        meta = LOCAL_EMBED_MODELS.get(picked, {})
        st.caption(f"{meta.get('size', '')} · {meta.get('dim', '?')} 维 —— {meta.get('desc', '')}")
        if local_model_cached(picked):
            st.caption("模型已下载到本地，可直接使用")
        else:
            st.info(
                "首次使用会自动下载模型（约 90MB，走 hf-mirror 镜像）。",
                icon=":material/download:",
            )
        return

    # ---- 云端 embedding ----
    info = provider_defaults(st.session_state["cfg_provider"])
    _picker(
        "云端向量模型",
        "cfg_api_embed_model",
        info["embed_models"],
        "建库时把文字编码成向量。换模型等于换一整套坐标系，旧索引必须重建。",
    )
    if not info["embed_models"]:
        st.warning(
            f"{st.session_state['cfg_provider']} 只提供对话模型，没有 embedding 接口。"
            "请在下面单独指定一家 embedding 服务，或者干脆切回本地模型。",
            icon=":material/warning:",
        )
    with st.expander("单独配置 embedding 服务（可选）", expanded=not info["embed_models"]):
        st.text_input(
            "Embedding Base URL",
            key="cfg_embed_base_url",
            placeholder="https://api.siliconflow.cn/v1",
        )
        st.text_input("Embedding API Key", key="cfg_embed_api_key", type="password")


def _advanced() -> None:
    """高级设置：移到侧栏最底部，默认收起。"""
    with st.expander("高级设置", icon=":material/tune:"):
        st.caption("通常不用动。想换供应商、换向量模型，或调生成参数时才需要。")
        st.selectbox(
            "供应商", list(PROVIDERS), key="cfg_provider", on_change=_on_provider_change
        )
        st.text_input("Base URL", key="cfg_base_url", help="OpenAI 兼容接口地址")
        _picker(
            "对话模型",
            "cfg_llm_model",
            provider_defaults(st.session_state["cfg_provider"])["llm_models"],
        )

        st.divider()
        _embed_source_controls()

        st.divider()
        st.caption("生成参数")
        st.slider("temperature", 0.0, 1.0, step=0.05, key="cfg_temperature")
        st.slider("max_tokens", 256, 4096, step=128, key="cfg_max_tokens")


# ===========================================================================
# 侧栏渲染：扁平分区（Header → 模型服务 → 知识库 → 帮助 → 底部）
# ===========================================================================
def _flash(kind: str, text: str) -> None:
    """行内提示。必须存 session_state —— 模块级变量活不过 rerun。"""
    st.session_state["sb_flash"] = {"kind": kind, "text": text}


def _flash_note() -> None:
    """渲染当前的行内提示（不消费，直到被下一次操作覆盖）。"""
    msg = st.session_state.get("sb_flash") or {}
    if msg.get("text"):
        st.markdown(
            f'<div class="sb-note {msg.get("kind", "")}">{escape(msg["text"])}</div>',
            unsafe_allow_html=True,
        )


def _clear_flash() -> None:
    st.session_state.pop("sb_flash", None)


def _section(label: str) -> None:
    st.markdown(f'<div class="sb-section"><span>{label}</span></div>', unsafe_allow_html=True)


def _render_header() -> None:
    st.markdown(
        f'<div class="sb-head">'
        f'<div class="sb-glyph">R</div>'
        f"<div><div class=\"sb-head-t\">{escape(APP_TITLE)}</div>"
        f'<div class="sb-head-s">{escape(APP_SUBTITLE)}</div></div>'
        f"</div>",
        unsafe_allow_html=True,
    )


def _svc_rows(status: dict) -> str:
    """两个服务状态行。未验证=灰点灰 badge，已验证=绿点绿 badge。"""
    llm_ok = status.get("llm")
    emb_ok = status.get("embed")
    settings: ModelSettings = st.session_state.get("settings") or ModelSettings()

    def row(role: str, model: str, ok, ok_text: str, bad_text: str) -> str:
        dot = "sb-dot ok" if ok else "sb-dot"
        if ok is True:
            badge = f'<span class="sb-badge ok">{ok_text}</span>'
        elif ok is False:
            badge = f'<span class="sb-badge bad">{bad_text}</span>'
        else:
            badge = '<span class="sb-badge">未验证</span>'
        return (
            f'<div class="sb-row"><span class="{dot}"></span>'
            f'<span class="sb-role">{escape(role)}</span>'
            f'<span class="sb-model">{escape(model or "—")}</span>{badge}</div>'
        )

    return (
        '<div class="sb-svc">'
        + row("对话", settings.llm_model, llm_ok, "已连接", "连接失败")
        + row("向量", settings.embed_model, emb_ok, "本地运行", "不可用")
        + "</div>"
    )


def _render_model_service(settings: ModelSettings) -> ModelSettings:
    """模型服务区：可折叠状态机（展开表单 ↔ 折叠摘要）。"""
    status: dict = st.session_state["ms_status"]

    # ---------- 折叠态：一行摘要（markdown 呈现 + 透明按钮做整行热区） ----------
    if st.session_state["ms_collapsed"]:
        ok = bool(status.get("llm") and status.get("embed"))
        dot = "sb-dot ok" if ok else "sb-dot"
        badge = (
            '<span class="sb-badge ok">已连接</span>'
            if ok
            else '<span class="sb-badge">未验证</span>'
        )
        summary = (
            f"{settings.llm_model} · {settings.embed_model}"
            if settings.llm_model and settings.embed_model
            else "尚未配置模型"
        )
        sub = (
            "2 个服务就绪 · 点按可重新编辑"
            if ok
            else ("已填写 Key · 测试连接后可保存" if settings.api_key else "点按配置 API Key")
        )
        st.markdown(
            f'<div class="sb-row sb-summary"><span class="{dot}"></span>'
            f'<span class="sb-sm"><span class="sb-sm-t">{escape(summary)}</span>'
            f'<span class="sb-sm-d">{escape(sub)}</span></span>{badge}'
            f"</div>",
            unsafe_allow_html=True,
        )
        # 透明按钮盖在摘要行上，整行可点（CSS 里把它压平）
        if st.button("重新编辑", key="sb_summary", width="stretch"):
            st.session_state["ms_collapsed"] = False
            st.rerun()
        _flash_note()
        return settings

    # ---------- 展开态 ----------
    # 「保存并收起」的第二段：先亮一下「已保存 ✓」再折叠
    if st.session_state.get("ms_saving"):
        st.button("已保存 ✓", key="sb_saved_flash", disabled=True, width="stretch")
        time.sleep(0.65)
        st.session_state["ms_saving"] = False
        st.session_state["ms_collapsed"] = True
        _flash("ok", "配置已保存，已收起为摘要 · 点击摘要行可重新编辑")
        st.rerun()

    st.text_input(
        "API Key",
        key="cfg_api_key",
        type="password",
        placeholder="sk-...",
        label_visibility="collapsed",
        on_change=_on_key_changed,
    )

    settings = _sync(settings)
    st.markdown(_svc_rows(status), unsafe_allow_html=True)

    if settings.embed_source == "local" and not local_model_cached(settings.embed_model):
        st.markdown(
            '<div class="sb-note">首次建库会自动下载本地向量模型（约 90MB，走 hf-mirror）。</div>',
            unsafe_allow_html=True,
        )

    # 「测试连接」第二段：按钮先变成「测试中…」再执行探测
    if st.session_state["ms_testing"]:
        st.button("测试中…", key="sb_test_btn", disabled=True, width="stretch")
        result = probe_connection(settings)
        llm_ok = bool(result.get("llm", {}).get("ok"))
        emb_ok = bool(result.get("embed", {}).get("ok"))
        st.session_state["ms_status"] = {
            "llm": llm_ok,
            "embed": emb_ok,
            "detail": {
                "llm": result.get("llm", {}).get("detail", ""),
                "embed": result.get("embed", {}).get("detail", ""),
            },
        }
        st.session_state["ms_testing"] = False
        if llm_ok and emb_ok:
            _flash("ok", "连接成功 · 2 个服务就绪，可保存并收起")
        elif emb_ok:
            _flash("bad", f"对话模型未连通：{result.get('llm', {}).get('detail', '')}")
        else:
            _flash("bad", f"向量模型未连通：{result.get('embed', {}).get('detail', '')}")
        st.rerun()

    tested = status.get("llm") is not None
    c1, c2 = st.columns([1, 1])
    with c1:
        if st.button(
            "重新测试" if tested else "测试连接", key="sb_test_btn", width="stretch"
        ):
            st.session_state["ms_testing"] = True
            st.rerun()
    with c2:
        if st.button("保存并收起", key="sb_save", width="stretch", type="primary",
                     disabled=not bool(settings.api_key)):
            settings.save()
            st.session_state["ms_saving"] = True
            st.rerun()

    info = provider_defaults(settings.provider)
    if info.get("signup"):
        st.caption(f"还没有 Key？[去 {settings.provider} 申请]({info['signup']})")

    # 低调的「收起」（不保存）
    if st.button("收起", key="sb_collapse_only"):
        st.session_state["ms_collapsed"] = True
        _flash("", "已收起（未保存）· 点击摘要行可继续编辑")
        st.rerun()

    _flash_note()
    return settings


def _on_key_changed() -> None:
    """改了 Key 就立刻回退「未验证」——圆点、badge、摘要 badge 同步转灰。"""
    st.session_state["ms_status"] = {"llm": None, "embed": None, "detail": {}}
    _flash("bad", "Key 已修改，需重新测试连接")


def _render_knowledge_base() -> None:
    # 建库失败：持久显示，不占画布空间
    if st.session_state.get("flow_build_error"):
        st.error(st.session_state["flow_build_error"], icon=":material/error:")
        if st.button("我知道了", key="dismiss_build_err", width="stretch"):
            st.session_state["flow_build_error"] = ""
            st.rerun()
    if st.session_state.get("flow_build_notice"):
        st.warning(st.session_state.pop("flow_build_notice"), icon=":material/warning:")

    kb = st.session_state.get("kb")
    if kb is not None:
        st.markdown(
            f'<div class="sb-kb">{icon_svg("empty", 16)}'
            f"<span><b>{kb.node_count}</b> 个块 · {len(kb.meta.get('files', []))} 份文档</span></div>",
            unsafe_allow_html=True,
        )
        return

    # 空态三件套
    st.markdown(
        '<div class="sb-empty">'
        f'<div class="sb-empty-ico">{icon_svg("empty", 20)}</div>'
        '<div class="sb-empty-t">尚未建立知识库</div>'
        '<div class="sb-empty-d">上传文档后自动切片、向量化并建立检索索引</div>'
        "</div>",
        unsafe_allow_html=True,
    )
    c1, c2 = st.columns([1, 1])
    with c1:
        if st.button("上传文档", key="kb_cta_upload", width="stretch", type="primary"):
            st.session_state["kb_show_upload"] = True
            st.session_state["kb_show_samples"] = False
            st.rerun()
    with c2:
        if st.button("查看示例数据集", key="kb_cta_samples", width="stretch"):
            st.session_state["kb_show_samples"] = True
            st.session_state["kb_show_upload"] = False
            st.rerun()

    if st.session_state.get("kb_show_upload"):
        uploads = st.file_uploader(
            "支持 txt / md / pdf / docx",
            type=["txt", "md", "markdown", "pdf", "docx", "csv", "json", "log"],
            accept_multiple_files=True,
            key="flow_uploader",
            label_visibility="collapsed",
        )
        st.session_state["flow_uploads"] = uploads or []
        st.caption(
            f"已加载 {len(uploads or [])} 个文件，下次点「建立索引」时一起切块。"
            if uploads
            else "选好文件后，到画布点「建立索引」模块开始建库。"
        )

    if st.session_state.get("kb_show_samples"):
        st.markdown(
            "**内置 11 份语料**：深圳信息职业技术大学校园指南\n"
            "（新生入学 / 教学 / 生活 / 奖助 / 医疗 / 运动 / 宿舍 / FAQ / 数字表 / 学院专业 / 收费）\n\n"
            "按版式归到最适合的切片策略下：\n\n"
            "- `新生入学 + 学院专业` 最长连续正文 → **Token 切片**\n"
            "- `FAQ + 数字表` 短句自足 → **句子切片**\n"
            "- `教学 / 运动 / 宿舍` 规章条款互引 → **句子窗口**\n"
            "- `生活 / 医疗` 主题一路跳转 → **语义切片**\n"
            "- `学院专业 + 奖助 + 收费` 标题层级最深 → **Markdown 切片**\n\n"
            "内容学员都熟悉，答案对不对一眼就能判断 —— 专门方便抓幻觉。\n\n"
            "在画布上单击「建立索引」模块就能选用它们。"
        )


def _render_help() -> None:
    with st.expander("怎么用（30 秒上手）", icon=":material/help:"):
        st.markdown(
            "1. **上面填 API Key** —— 只有一个输入框。对话模型走云端，"
            "向量模型在本机跑，不需要第二个 Key。\n"
            "2. **中间画布** —— 拖模块进来并连线。单击模块打开设置。\n"
            "3. **切到「问答与对比」** —— 提问。回来改一个参数再问同一个问题，"
            "答案和诊断分数都会变。"
        )

    with st.expander("上传自己的文档", icon=":material/upload:"):
        st.markdown(
            "在上方「知识库」小节点 **上传文档** 即可。支持 txt / md / pdf / docx，"
            "可多选；上传后会在下次「建立索引」时一起切块。"
        )

    with st.expander("图和真实代码怎么对应", icon=":material/account_tree:"):
        # 键值行替代 markdown 表格 —— 表格列宽会塌成竖排单字
        pairs = [
            ("文档输入 / 切片", "core/ingest.py · chunking.py"),
            ("向量化 / 建索引", "core/llm.py · kb.py"),
            ("问题分词", "retrievers.py · tokenize_zh()"),
            ("问题向量化", "同一个 embedding 模型"),
            ("BM25 / 向量检索", "ChineseBM25Retriever / VectorIndexRetriever"),
            ("混合检索", "QueryFusionRetriever(reciprocal_rerank)"),
            ("Reranker", "LLMRerank"),
            ("上下文拼接 / 回答生成", "core/pipeline.py"),
        ]
        rows = "".join(
            f'<div class="sb-kv-row"><span class="sb-kv-k">{escape(k)}</span>'
            f'<span class="sb-kv-v">{escape(v)}</span></div>'
            for k, v in pairs
        )
        st.markdown(f'<div class="sb-kv">{rows}</div>', unsafe_allow_html=True)

    with st.expander("为什么只填一个 Key 就够", icon=":material/key:"):
        st.markdown(
            "**对话**需要大模型，只能走云端，所以用你的 Key。\n\n"
            "**向量**只是把文字编码成一组数字，一个 90MB 的小模型在本机就能算，"
            "没必要为此再注册一个账号。模型走 `hf-mirror.com` 镜像，下完永久离线可用。"
        )


def _render_footer() -> None:
    _advanced()
    st.markdown(
        '<div class="sb-footer">画布：拖模块进来 · 单击模块改设置 · '
        "点连线可删（× / Delete / 右键） · 滚轮平移、Ctrl+滚轮缩放</div>",
        unsafe_allow_html=True,
    )


def render_sidebar() -> ModelSettings:
    _init_state()
    settings: ModelSettings = st.session_state["settings"]

    # 状态机变量
    st.session_state.setdefault("ms_collapsed", False)
    st.session_state.setdefault("ms_status", {"llm": None, "embed": None, "detail": {}})
    st.session_state.setdefault("ms_testing", False)
    st.session_state.setdefault("ms_saving", False)
    st.session_state.setdefault("kb_show_upload", False)
    st.session_state.setdefault("kb_show_samples", False)

    with st.sidebar:
        _render_header()

        _section("模型服务")
        settings = _render_model_service(settings)
        settings = _sync(settings)

        _section("知识库")
        _render_knowledge_base()

        _section("帮助")
        _render_help()

        _render_footer()

    return settings


if __name__ == "__main__":
    render_sidebar()
