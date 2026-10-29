"""视觉层：设计令牌 + 全局样式 + 六态视图。

这个模块只负责"长什么样"，不参与任何业务逻辑。业务侧的调用照旧
（st.button / st.text_input / build_kb ...），这里只是帮它们换一层皮。

令牌约束（与前端交付基线一致，改样式时请直接引用变量，不要写死数值）：

    间距   4 / 8 / 12 / 16 / 24 / 32 / 48 / 64
    字阶   12 / 14 / 16 / 20 / 24 / 30 / 38
    圆角   4 / 8 / 16 / 999
    动效   100 / 200 / 300 ms，并尊重 prefers-reduced-motion

颜色不在本文件里写死：一律引用 Streamlit 暴露的运行时变量
（--primary-color / --text-color / --secondary-background-color / --border-color），
所以亮暗两套由 .streamlit/config.toml 的 [theme.light] / [theme.dark] 统一控制。
唯一的例外是语义色（成功/警告/危险），它们需要亮暗各一套，写在下面的变量表里。
"""

from __future__ import annotations

from html import escape

import streamlit as st

# ---------------------------------------------------------------------------
# 令牌（Python 侧镜像，方便在代码里引用；CSS 侧是 --rag-* 变量）
# ---------------------------------------------------------------------------
SPACE = {"1": 4, "2": 8, "3": 12, "4": 16, "6": 24, "8": 32, "12": 48, "16": 64}
FONT_SIZE = {"12": 12, "14": 14, "16": 16, "20": 20, "24": 24, "30": 30, "38": 38}
RADIUS = {"4": 4, "8": 8, "16": 16, "full": 999}
DURATION = {"100": 100, "200": 200, "300": 300}


# ---------------------------------------------------------------------------
# 内联 SVG 图标（统一 24×24 网格、1.75 描边、圆角端点，可无损缩放 16/20/24）
# 刻意用内联 SVG 而不是图标字体：离线可用、颜色跟随 currentColor、不依赖 CDN。
# ---------------------------------------------------------------------------
_ICON_PATHS = {
    "empty": '<path d="M3 8.5 5.2 4.6A2 2 0 0 1 7 3.6h10a2 2 0 0 1 1.8 1L21 8.5"/>'
    '<path d="M3 8.5h5l1.2 2.4h5.6L16 8.5h5v8.9a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z"/>',
    "search": '<circle cx="10.5" cy="10.5" r="6.5"/><path d="m15.6 15.6 4.4 4.4"/>',
    "error": '<path d="M12 3.8 21 19.2a1.6 1.6 0 0 1-1.4 2.4H4.4A1.6 1.6 0 0 1 3 19.2z"/>'
    '<path d="M12 9.4v4.3"/><path d="M12 17.2h.01"/>',
    "lock": '<rect x="4.6" y="10.4" width="14.8" height="10" rx="2.4"/>'
    '<path d="M8.4 10.4V7.6a3.6 3.6 0 0 1 7.2 0v2.8"/>',
    "check": '<circle cx="12" cy="12" r="8.6"/><path d="m8.4 12.2 2.6 2.6 4.8-5.2"/>',
    "loader": '<path d="M12 3.6v3.2M12 17.2v3.2M20.4 12h-3.2M6.8 12H3.6'
    'M18.1 5.9l-2.3 2.3M8.2 15.8l-2.3 2.3M18.1 18.1l-2.3-2.3M8.2 8.2 5.9 5.9"/>',
    "info": '<circle cx="12" cy="12" r="8.6"/><path d="M12 11.2v5.2"/><path d="M12 7.9h.01"/>',
    "spark": '<path d="M12 3.6 13.9 9l5.5 1.9-5.5 1.9L12 18.4l-1.9-5.6L4.6 11 10.1 9z"/>',
    "flow": '<circle cx="6" cy="6.6" r="2.4"/><circle cx="18" cy="17.4" r="2.4"/>'
    '<path d="M8.4 6.6h5.2a2.4 2.4 0 0 1 2.4 2.4v6"/>',
}

_ICON_ALIAS = {
    "empty": "empty", "no_result": "search", "error": "error", "forbidden": "lock",
    "ready": "check", "loading": "loader", "partial": "info",
}


def icon_svg(name: str, size: int = 20, cls: str = "rag-icon") -> str:
    """返回一段内联 SVG。size 建议取 16 / 20 / 24。"""
    path = _ICON_PATHS.get(name, _ICON_PATHS["info"])
    return (
        f'<svg class="{cls}" width="{size}" height="{size}" viewBox="0 0 24 24" fill="none" '
        f'stroke="currentColor" stroke-width="1.75" stroke-linecap="round" '
        f'stroke-linejoin="round" aria-hidden="true" focusable="false">{path}</svg>'
    )


# ---------------------------------------------------------------------------
# 全局样式
# ---------------------------------------------------------------------------
_CSS = """
<style>
/* ===== 令牌 ===== */
:root {
  --rag-sp-1: 4px;  --rag-sp-2: 8px;  --rag-sp-3: 12px; --rag-sp-4: 16px;
  --rag-sp-6: 24px; --rag-sp-8: 32px; --rag-sp-12: 48px; --rag-sp-16: 64px;

  --rag-fs-12: 12px; --rag-fs-14: 14px; --rag-fs-16: 16px; --rag-fs-20: 20px;
  --rag-fs-24: 24px; --rag-fs-30: 30px; --rag-fs-38: 38px;

  --rag-r-4: 4px; --rag-r-8: 8px; --rag-r-16: 16px; --rag-r-full: 999px;

  --rag-dur-100: 100ms; --rag-dur-200: 200ms; --rag-dur-300: 300ms;
  --rag-ease: cubic-bezier(0.2, 0.8, 0.2, 1);

  /* 文本色阶：三级都保证 ≥4.5:1（含禁用态可读性） */
  --rag-text-1: #14171F;
  --rag-text-2: #4B5563;
  --rag-text-3: #6B7280;
  --rag-surface: #FFFFFF;
  --rag-surface-2: #F6F7F9;
  --rag-border: #E4E7EC;
  --rag-border-strong: #D3D8DF;

  /* 语义色（亮色） */
  --rag-ok-bg: #EEF8F1;  --rag-ok-fg: #17663A;  --rag-ok-line: #BFE3CD;
  --rag-warn-bg: #FFF7EC; --rag-warn-fg: #8A4B00; --rag-warn-line: #F3DCB8;
  --rag-err-bg: #FDF0EF; --rag-err-fg: #96231B;  --rag-err-line: #F2C9C5;
  --rag-info-bg: #EFF3FE; --rag-info-fg: #1E3FA8; --rag-info-line: #C9D6F8;

  --rag-shadow-1: 0 1px 2px rgba(16, 24, 40, 0.05);
  --rag-shadow-2: 0 4px 16px rgba(16, 24, 40, 0.08);
}

/* 暗色单独一套：主色降饱和提亮，靠描边分层而不是阴影，语义底色压暗 */
@media (prefers-color-scheme: dark) {
  :root {
    --rag-text-1: #E9ECF1; --rag-text-2: #A8B0BD; --rag-text-3: #8A93A1;
    --rag-surface: #0E1014; --rag-surface-2: #171A20;
    --rag-border: #262B34; --rag-border-strong: #333A45;
    --rag-ok-bg: #10231A;  --rag-ok-fg: #7BD3A0;  --rag-ok-line: #1F4433;
    --rag-warn-bg: #241B0F; --rag-warn-fg: #E8B571; --rag-warn-line: #4A3A1F;
    --rag-err-bg: #261414; --rag-err-fg: #F0948C;  --rag-err-line: #4C2624;
    --rag-info-bg: #121A2B; --rag-info-fg: #93AEF5; --rag-info-line: #26344F;
    --rag-shadow-1: none; --rag-shadow-2: none;
  }
}
body[data-theme="dark"], [data-theme="dark"] {
  --rag-text-1: #E9ECF1; --rag-text-2: #A8B0BD; --rag-text-3: #8A93A1;
  --rag-surface: #0E1014; --rag-surface-2: #171A20;
  --rag-border: #262B34; --rag-border-strong: #333A45;
  --rag-ok-bg: #10231A;  --rag-ok-fg: #7BD3A0;  --rag-ok-line: #1F4433;
  --rag-warn-bg: #241B0F; --rag-warn-fg: #E8B571; --rag-warn-line: #4A3A1F;
  --rag-err-bg: #261414; --rag-err-fg: #F0948C;  --rag-err-line: #4C2624;
  --rag-info-bg: #121A2B; --rag-info-fg: #93AEF5; --rag-info-line: #26344F;
  --rag-shadow-1: none; --rag-shadow-2: none;
}

/* ===== 排版 ===== */
html, body, .stApp, [data-testid="stAppViewContainer"] {
  font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", "PingFang SC",
               "Hiragino Sans GB", "Microsoft YaHei", "Source Han Sans SC", sans-serif;
  font-feature-settings: "tnum" 1;
  -webkit-font-smoothing: antialiased;
}
[data-testid="stMarkdownContainer"] p,
[data-testid="stMarkdownContainer"] li {
  font-size: var(--rag-fs-16);
  line-height: 1.68;
  color: var(--rag-text-1);
}
[data-testid="stMarkdownContainer"] p { margin-bottom: var(--rag-sp-3); }
[data-testid="stMarkdownContainer"] li { margin-bottom: var(--rag-sp-1); }
[data-testid="stMarkdownContainer"] strong { font-weight: 600; }

h1, [data-testid="stHeading"] h1 {
  font-size: var(--rag-fs-30) !important;
  font-weight: 650; letter-spacing: -0.015em; line-height: 1.25;
  padding-bottom: var(--rag-sp-2);
}
h2, [data-testid="stHeading"] h2 {
  font-size: var(--rag-fs-24) !important;
  font-weight: 620; letter-spacing: -0.01em; line-height: 1.3;
  margin-top: var(--rag-sp-2); margin-bottom: var(--rag-sp-4);
}
h3, [data-testid="stHeading"] h3 {
  font-size: var(--rag-fs-20) !important;
  font-weight: 600; line-height: 1.4; letter-spacing: -0.005em;
}
h4, [data-testid="stHeading"] h4,
[data-testid="stMarkdownContainer"] h5 {
  font-size: var(--rag-fs-16) !important;
  font-weight: 600; letter-spacing: 0;
}
[data-testid="stCaptionContainer"], [data-testid="stCaptionContainer"] p {
  font-size: var(--rag-fs-12) !important;
  color: var(--rag-text-2) !important;
  line-height: 1.6;
}
code, pre, kbd {
  font-family: "JetBrains Mono", "Cascadia Code", "SFMono-Regular", Consolas, monospace;
  font-size: var(--rag-fs-14);
}
a { text-underline-offset: 2px; }

/* ===== 布局节奏 ===== */
[data-testid="stMainBlockContainer"], .block-container {
  max-width: 1180px;
  padding-left: var(--rag-sp-6);
  padding-right: var(--rag-sp-6);
  /* Streamlit 顶栏是 fixed 的（约 3.75rem），必须留出避让，
     否则第一个元素（tabs）会被压在它下面，只剩指示条露出来 */
  padding-top: calc(3.75rem + var(--rag-sp-2));
  padding-bottom: var(--rag-sp-16);
}
[data-testid="stVerticalBlock"] { gap: var(--rag-sp-3); }
[data-testid="stHorizontalBlock"] { gap: var(--rag-sp-4); }
[data-testid="stSidebar"] > div { padding-top: var(--rag-sp-4); }
[data-testid="stSidebar"] { border-right: 1px solid var(--rag-border); }
hr, [data-testid="stDivider"] { border-color: var(--rag-border) !important; }
[data-testid="stDivider"] { margin: var(--rag-sp-6) 0; }

/* ===== 焦点：键盘可达性 ===== */
:focus-visible {
  outline: 2px solid var(--primary-color, #2B5CE6);
  outline-offset: 2px;
  border-radius: var(--rag-r-4);
}

/* ===== 按钮：default / hover / active / disabled / loading 五态 ===== */
[data-testid="stButton"] > button,
[data-testid="stDownloadButton"] > button,
[data-testid="stFormSubmitButton"] > button {
  border-radius: var(--rag-r-8);
  font-size: var(--rag-fs-14);
  font-weight: 550;
  min-height: 40px;
  padding: 0 var(--rag-sp-4);
  border: 1px solid var(--rag-border-strong);
  background: var(--rag-surface);
  color: var(--rag-text-1);
  box-shadow: var(--rag-shadow-1);
  transition: background-color var(--rag-dur-100) var(--rag-ease),
              border-color var(--rag-dur-100) var(--rag-ease),
              color var(--rag-dur-100) var(--rag-ease),
              box-shadow var(--rag-dur-200) var(--rag-ease),
              transform var(--rag-dur-100) var(--rag-ease);
}
[data-testid="stButton"] > button:hover:not(:disabled) {
  background: var(--rag-surface-2);
  border-color: var(--primary-color, #2B5CE6);
}
[data-testid="stButton"] > button:active:not(:disabled) { transform: translateY(1px); }
[data-testid="stButton"] > button:disabled {
  /* 禁用态也要可读：只降层级，不用半透明糊掉文字 */
  background: var(--rag-surface-2) !important;
  color: var(--rag-text-3) !important;
  border-color: var(--rag-border) !important;
  box-shadow: none !important;
  cursor: not-allowed;
}
/* 主按钮 */
[data-testid="stButton"] > button[kind="primary"],
[data-testid="stBaseButton-primary"] {
  background: var(--primary-color, #2B5CE6);
  border-color: var(--primary-color, #2B5CE6);
  color: #FFFFFF;
  box-shadow: var(--rag-shadow-1);
}
[data-testid="stButton"] > button[kind="primary"]:hover:not(:disabled),
[data-testid="stBaseButton-primary"]:hover:not(:disabled) {
  filter: brightness(1.08);
  border-color: var(--primary-color, #2B5CE6);
}
[data-testid="stButton"] > button[kind="primary"]:disabled,
[data-testid="stBaseButton-primary"]:disabled {
  background: var(--rag-surface-2) !important;
  color: var(--rag-text-3) !important;
  border-color: var(--rag-border) !important;
}
/* 运行中（Streamlit 在按钮内塞了 spinner）视觉上等同 loading */
[data-testid="stButton"] > button:has([data-testid="stSpinner"]) { cursor: progress; }

/* ===== 输入控件 ===== */
[data-testid="stTextInput"] input,
[data-testid="stNumberInput"] input,
[data-testid="stTextArea"] textarea {
  border-radius: var(--rag-r-8);
  font-size: var(--rag-fs-14);
  border: 1px solid var(--rag-border-strong);
  transition: border-color var(--rag-dur-100) var(--rag-ease),
              box-shadow var(--rag-dur-100) var(--rag-ease);
}
[data-testid="stTextInput"] input:focus,
[data-testid="stTextArea"] textarea:focus {
  border-color: var(--primary-color, #2B5CE6);
  box-shadow: 0 0 0 3px color-mix(in srgb, var(--primary-color, #2B5CE6) 18%, transparent);
}
[data-baseweb="select"] > div,
[data-testid="stSelectbox"] [data-baseweb="select"] > div,
[data-testid="stMultiSelect"] [data-baseweb="select"] > div {
  border-radius: var(--rag-r-8);
  border-color: var(--rag-border-strong);
  font-size: var(--rag-fs-14);
  transition: border-color var(--rag-dur-100) var(--rag-ease);
}
[data-testid="stFileUploaderDropzone"] {
  border-radius: var(--rag-r-8);
  border: 1px dashed var(--rag-border-strong);
  background: var(--rag-surface-2);
  transition: border-color var(--rag-dur-100) var(--rag-ease);
}
[data-testid="stFileUploaderDropzone"]:hover { border-color: var(--primary-color, #2B5CE6); }

/* ===== 折叠面板 ===== */
[data-testid="stExpander"] {
  border: 1px solid var(--rag-border);
  border-radius: var(--rag-r-8);
  background: var(--rag-surface);
  box-shadow: var(--rag-shadow-1);
  overflow: hidden;
}
[data-testid="stExpander"] summary {
  font-size: var(--rag-fs-14);
  font-weight: 550;
  padding: var(--rag-sp-3) var(--rag-sp-4);
  transition: background-color var(--rag-dur-100) var(--rag-ease);
}
[data-testid="stExpander"] summary:hover { background: var(--rag-surface-2); }
[data-testid="stExpander"] [data-testid="stExpanderDetails"] { padding: 0 var(--rag-sp-4) var(--rag-sp-3); }

/* ===== 提示条 ===== */
[data-testid="stAlert"] {
  border-radius: var(--rag-r-8);
  border: 1px solid var(--rag-border);
  font-size: var(--rag-fs-14);
  padding: var(--rag-sp-3) var(--rag-sp-4);
}
[data-testid="stAlert"] p { font-size: var(--rag-fs-14); line-height: 1.6; }

/* ===== 指标卡 ===== */
[data-testid="stMetric"] {
  border: 1px solid var(--rag-border);
  border-radius: var(--rag-r-8);
  background: var(--rag-surface);
  padding: var(--rag-sp-3) var(--rag-sp-4);
  box-shadow: var(--rag-shadow-1);
}
[data-testid="stMetricLabel"], [data-testid="stMetricLabel"] p {
  font-size: var(--rag-fs-12) !important;
  color: var(--rag-text-2) !important;
  font-weight: 500;
}
[data-testid="stMetricValue"] { font-size: var(--rag-fs-24) !important; font-weight: 620; }

/* ===== 进度条 ===== */
[data-testid="stProgress"] > div > div > div { border-radius: var(--rag-r-full); }
[data-testid="stProgress"] > div > div { border-radius: var(--rag-r-full); }

/* ===== 标签页 ===== */
[data-baseweb="tab-list"] {
  gap: var(--rag-sp-4);
  border-bottom: 1px solid var(--rag-border);
}
[data-baseweb="tab"] {
  font-size: var(--rag-fs-14);
  font-weight: 550;
  padding: var(--rag-sp-2) 0;
  /* 用 inherit + opacity，让颜色跟着 Streamlit 主题走。
     写死色值的话，系统亮色 + Streamlit 暗色时会出现深色字压深色底。 */
  color: inherit;
  opacity: 0.68;
  transition: opacity var(--rag-dur-100) var(--rag-ease),
              color var(--rag-dur-100) var(--rag-ease);
}
[data-baseweb="tab"]:hover { opacity: 1; }
[data-baseweb="tab"][aria-selected="true"] {
  opacity: 1;
  color: var(--primary-color, #2B5CE6);
}

/* ===== 表格 ===== */
[data-testid="stDataFrame"], [data-testid="stTable"] {
  border: 1px solid var(--rag-border);
  border-radius: var(--rag-r-8);
  overflow: hidden;
}

/* ===== 代码块 ===== */
[data-testid="stCode"] pre, [data-testid="stCodeBlock"] pre {
  border-radius: var(--rag-r-8);
  border: 1px solid var(--rag-border);
  font-size: var(--rag-fs-14);
  line-height: 1.62;
}

/* ===== 自定义：状态视图 ===== */
.rag-state {
  display: flex; flex-direction: column; align-items: center; justify-content: center;
  gap: var(--rag-sp-2);
  min-height: 168px;                     /* 固定高度，避免占位跳动 */
  padding: var(--rag-sp-6) var(--rag-sp-4);
  border: 1px dashed var(--rag-border-strong);
  border-radius: var(--rag-r-16);
  background: var(--rag-surface-2);
  text-align: center;
  box-sizing: border-box;
}
.rag-state--compact { min-height: 112px; padding: var(--rag-sp-4); }
.rag-state__icon { display: flex; opacity: 0.9; }
.rag-state__title {
  font-size: var(--rag-fs-16); font-weight: 600; color: var(--rag-text-1);
  line-height: 1.4;
}
.rag-state__desc {
  font-size: var(--rag-fs-14); color: var(--rag-text-2);
  line-height: 1.62; max-width: 46em;
}
.rag-state__hint {
  font-size: var(--rag-fs-12); color: var(--rag-text-3);
  line-height: 1.6; max-width: 46em;
}
.rag-state--empty .rag-state__icon { color: var(--rag-text-3); }
.rag-state--no_result .rag-state__icon { color: var(--rag-text-3); }
.rag-state--error .rag-state__icon { color: var(--rag-err-fg); }
.rag-state--forbidden .rag-state__icon { color: var(--rag-warn-fg); }
.rag-state--ready .rag-state__icon { color: var(--rag-ok-fg); }
.rag-state--partial .rag-state__icon { color: var(--rag-info-fg); }

/* 错误态明细（原因/影响/保留/可做/编号） */
.rag-error {
  border: 1px solid var(--rag-err-line);
  border-radius: var(--rag-r-8);
  background: var(--rag-err-bg);
  padding: var(--rag-sp-4);
  box-sizing: border-box;
}
.rag-error__head {
  display: flex; align-items: center; gap: var(--rag-sp-2);
  font-size: var(--rag-fs-16); font-weight: 600; color: var(--rag-err-fg);
  margin-bottom: var(--rag-sp-3);
}
.rag-error__grid { display: grid; gap: var(--rag-sp-2); }
.rag-error__row {
  display: grid; grid-template-columns: 92px 1fr; gap: var(--rag-sp-2);
  font-size: var(--rag-fs-14); line-height: 1.6;
}
.rag-error__key { color: var(--rag-warn-fg); font-weight: 550; }
.rag-error__val { color: var(--rag-text-1); }
.rag-error__code {
  margin-top: var(--rag-sp-3); padding-top: var(--rag-sp-2);
  border-top: 1px solid var(--rag-err-line);
  font-family: "JetBrains Mono", Consolas, monospace;
  font-size: var(--rag-fs-12); color: var(--rag-text-2);
  letter-spacing: 0.02em;
}

/* ===== 自定义：页头 ===== */
.rag-hero { padding: var(--rag-sp-2) 0 var(--rag-sp-4); border-bottom: 1px solid var(--rag-border); margin-bottom: var(--rag-sp-4); }
.rag-hero__eyebrow {
  display: inline-flex; align-items: center; gap: var(--rag-sp-2);
  font-size: var(--rag-fs-12); font-weight: 600; letter-spacing: 0.08em;
  text-transform: uppercase; color: var(--primary-color, #2B5CE6);
  margin-bottom: var(--rag-sp-2);
}
.rag-hero__title {
  font-size: var(--rag-fs-38); font-weight: 680; letter-spacing: -0.022em;
  line-height: 1.16; color: var(--rag-text-1); margin: 0 0 var(--rag-sp-2);
}
.rag-hero__sub {
  font-size: var(--rag-fs-16); color: var(--rag-text-2); line-height: 1.65;
  max-width: 62ch; margin: 0;
}

/* ===== 自定义：小节标签 ===== */
.rag-step {
  display: inline-flex; align-items: center; gap: var(--rag-sp-2);
  font-size: var(--rag-fs-12); font-weight: 600; letter-spacing: 0.06em;
  text-transform: uppercase; color: var(--rag-text-3);
  margin: var(--rag-sp-2) 0 var(--rag-sp-1);
}
.rag-step__num {
  display: inline-flex; align-items: center; justify-content: center;
  width: 20px; height: 20px; border-radius: var(--rag-r-full);
  background: var(--rag-surface-2); border: 1px solid var(--rag-border-strong);
  font-size: var(--rag-fs-12); font-weight: 600; color: var(--rag-text-2);
}

/* ===== 边界：超长内容 ===== */
[data-testid="stMarkdownContainer"] p,
[data-testid="stMarkdownContainer"] li,
[data-testid="stMarkdownContainer"] td { overflow-wrap: anywhere; }
[data-testid="stMarkdownContainer"] pre { overflow-x: auto; }
.rag-clamp-1 { display: block; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }

/* ===== 滚动条 ===== */
* { scrollbar-width: thin; scrollbar-color: var(--rag-border-strong) transparent; }
*::-webkit-scrollbar { width: 8px; height: 8px; }
*::-webkit-scrollbar-thumb { background: var(--rag-border-strong); border-radius: var(--rag-r-full); }
*::-webkit-scrollbar-track { background: transparent; }

/* ===== 流程编排页：画布填满剩余视口，页面不跟着滚 =====
   注意：组件 iframe 的实际 title 是 "ui.tab_flow.rag_flow_editor"，
   必须用后缀匹配；写全等匹配永远选不中（存量 bug）。 */
iframe[title$="rag_flow_editor"] {
  /* 画布顶边固定在 128px（header 60 + tabs 40 + 间距），底部留 8px */
  height: calc(100vh - 136px) !important;
  min-height: 520px;
  border: none;
  display: block;
}
[data-testid="stTabs"] [role="tabpanel"] { padding-top: var(--rag-sp-2); }

/* 流程编排 tab 激活时：吃掉容器底部 64px 大 padding，画布不把页面顶出滚动条 */
[data-testid="stMainBlockContainer"]:has([data-testid="stTab"]:first-child[aria-selected="true"]) {
  padding-bottom: var(--rag-sp-2);
}

/* ===== 侧栏折叠后：画布铺满整个页面 =====
   折叠标记：原生展开按钮（aria-label="Expand sidebar"）出现；
   限定第一个 tab（流程编排）处于选中态，不影响问答页排版。 */
body:has(button[aria-label="Expand sidebar"])
[data-testid="stMainBlockContainer"]:has([data-testid="stTab"]:first-child[aria-selected="true"]) {
  max-width: none;
  padding-left: var(--rag-sp-2);
  padding-right: var(--rag-sp-2);
}

/* ===================================================================
   设置侧栏：Apple 风格（iOS inset grouped 范式）
   —— 圆角分组 + 发丝线；每分区「一行状态 + 点按展开」
   —— 固定暗色，与主区主题解耦
   注意：Streamlit 1.66 实测 expander 的 <details> 没有 data-testid，
   选择器必须用 [data-testid="stSidebar"] details，不能用 stExpander
   =================================================================== */
[data-testid="stSidebar"] {
  /* 色板 —— iOS 深色体系 */
  --sb-bg:#1c1c1e; --sb-group:#2c2c2e; --sb-hover:#3a3a3c; --sb-input:#161618;
  --sb-line:rgba(255,255,255,.09); --sb-line-strong:rgba(255,255,255,.16);
  --sb-t1:rgba(255,255,255,.92); --sb-t2:rgba(255,255,255,.62); --sb-t3:rgba(255,255,255,.38);
  --sb-brand:#0a84ff; --sb-ok:#30d158; --sb-bad:#ff453a;
  --sb-ok-soft:rgba(48,209,88,.15); --sb-bad-soft:rgba(255,69,58,.12); --sb-brand-soft:rgba(10,132,255,.14);
  /* 圆角：控件 9 / 分组 12 */
  --sb-r-ctl:9px; --sb-r-box:12px;
  /* 间距 8 基准 */
  --sb-1:4px; --sb-2:8px; --sb-3:12px; --sb-4:16px; --sb-6:24px; --sb-gap:24px;
  --sb-mono:ui-monospace, "SF Mono", Menlo, Consolas, monospace;
  background: var(--sb-bg) !important;
  border-right: 1px solid var(--sb-line);
}
[data-testid="stSidebar"] > div { background: var(--sb-bg); }
[data-testid="stSidebar"] [data-testid="stSidebarContent"] { padding-top: var(--sb-4); padding-left: 14px; padding-right: 14px; }
[data-testid="stSidebar"] [data-testid="stVerticalBlock"] { gap: var(--sb-2); }

/* ---------- Header：应用图标 + 标题 ---------- */
.sb-head { display: flex; align-items: center; gap: 11px; padding: var(--sb-2) 4px var(--sb-1); }
.sb-glyph {
  width: 38px; height: 38px; border-radius: 10px; flex: 0 0 38px;
  background: linear-gradient(145deg, #0a84ff, #5e5ce6);
  display: flex; align-items: center; justify-content: center;
  font-weight: 700; font-size: 17px; color: #fff;
  box-shadow: 0 4px 14px rgba(10,132,255,.28);
}
.sb-head-t { font-size: 15px; font-weight: 600; color: var(--sb-t1); line-height: 1.3; }
.sb-head-s { font-size: 11.5px; color: var(--sb-t3); line-height: 1.5; margin-top: 2px; }

/* ---------- 分组标签：iOS 11px 小字距 caps，无延伸线 ---------- */
.sb-section {
  display: flex; align-items: center;
  margin: var(--sb-gap) 0 var(--sb-2);
  padding: 0 4px;
}
.sb-section > span {
  font-size: 11px; letter-spacing: 0.06em; text-transform: uppercase;
  color: var(--sb-t3); white-space: nowrap; font-weight: 600;
}

/* ---------- 输入框：深色内嵌，发丝线描边 ---------- */
[data-testid="stSidebar"] [data-testid="stTextInput"] input,
[data-testid="stSidebar"] [data-testid="stNumberInput"] input,
[data-testid="stSidebar"] [data-testid="stTextArea"] textarea {
  background: var(--sb-input) !important;
  border: 1px solid var(--sb-line-strong) !important;
  border-radius: var(--sb-r-ctl) !important;
  color: var(--sb-t1) !important;
  font-family: var(--sb-mono);
  font-size: 12.5px !important;
  min-height: 36px;
  transition: border-color 180ms ease-out;
}
[data-testid="stSidebar"] [data-testid="stTextInput"] input:focus {
  border-color: var(--sb-brand) !important;
  box-shadow: 0 0 0 3px var(--sb-brand-soft) !important;
}
[data-testid="stSidebar"] [data-baseweb="select"] > div {
  background: var(--sb-input) !important;
  border: 1px solid var(--sb-line-strong) !important;
  border-radius: var(--sb-r-ctl) !important;
  font-size: 12.5px !important;
  min-height: 36px;
}
[data-testid="stSidebar"] [data-testid="stWidgetLabel"] p {
  font-size: 12px !important; color: var(--sb-t3) !important;
}

/* ---------- 状态行：分组底 + 10px 圆角 ---------- */
.sb-svc { display: grid; gap: 2px; margin: var(--sb-1) 0; }
.sb-row {
  display: flex; align-items: center; gap: var(--sb-2);
  min-height: 40px; padding: 6px 12px;
  border-radius: 10px; background: var(--sb-group);
  border: 1px solid var(--sb-line);
  transition: background 180ms ease-out;
}
.sb-row:hover { background: var(--sb-hover); }
.sb-dot {
  width: 7px; height: 7px; border-radius: 50%; flex: 0 0 7px;
  background: var(--sb-t3); transition: background 180ms ease-out;
}
.sb-dot.ok { background: var(--sb-ok); box-shadow: 0 0 0 3px var(--sb-ok-soft); }
.sb-role { font-size: 12.5px; color: var(--sb-t2); flex: 0 0 auto; }
.sb-model {
  font-family: var(--sb-mono); font-size: 11.5px; color: var(--sb-t1);
  flex: 1; min-width: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap;
}
.sb-badge {
  font-size: 10.5px; font-weight: 600; letter-spacing: .02em;
  padding: 2.5px 8px; border-radius: 999px; flex: 0 0 auto;
  color: var(--sb-t2); background: var(--sb-hover);
  border: none;
}
.sb-badge.ok { color: var(--sb-ok); background: var(--sb-ok-soft); }
.sb-badge.bad { color: var(--sb-bad); background: var(--sb-bad-soft); }

/* 折叠摘要行：主标题 + 副标题两行（高度必须恒为 48px，热区按此对齐） */
.sb-summary { min-height: 48px; height: 48px; padding: 4px 12px; cursor: pointer; overflow: hidden; }
.sb-sm { flex: 1; min-width: 0; display: flex; flex-direction: column; gap: 1px; }
.sb-sm-t {
  font-size: 12px; font-weight: 500; color: var(--sb-t1); line-height: 1.3;
  font-family: var(--sb-mono);
  overflow: hidden; text-overflow: ellipsis; white-space: nowrap;
}
.sb-sm-d { font-size: 11px; color: var(--sb-t3); line-height: 1.3; }

/* ---------- 行内提示：淡色底药丸条 ---------- */
.sb-note {
  font-size: 12px; line-height: 1.6; color: var(--sb-t2);
  padding: 8px 11px; border-radius: 8px;
  background: var(--sb-brand-soft);
  animation: sb-fadein .25s ease-out;
}
.sb-note.ok { color: var(--sb-ok); background: var(--sb-ok-soft); }
.sb-note.bad { color: var(--sb-bad); background: var(--sb-bad-soft); }
@keyframes sb-fadein { from { opacity: 0; transform: translateY(-3px); } }

/* ---------- 按钮：主 / 次（无边框实底，iOS 风） ---------- */
[data-testid="stSidebar"] [data-testid="stButton"] > button {
  border-radius: var(--sb-r-ctl);
  font-size: 13px; font-weight: 600;
  min-height: 36px; padding: 0 var(--sb-3);
  background: var(--sb-hover); color: var(--sb-t1);
  border: none;
  box-shadow: none;
  transition: transform 120ms ease-out, background 180ms ease-out;
}
[data-testid="stSidebar"] [data-testid="stButton"] > button:hover:not(:disabled) {
  background: #464649;
}
[data-testid="stSidebar"] [data-testid="stButton"] > button:active:not(:disabled) {
  transform: scale(.98);
}
[data-testid="stSidebar"] [data-testid="stButton"] > button:disabled {
  background: var(--sb-hover) !important; color: var(--sb-t3) !important;
  cursor: not-allowed;
}
[data-testid="stSidebar"] [data-testid="stButton"] > button[kind="primary"],
[data-testid="stSidebar"] [data-testid="stBaseButton-primary"] {
  background: var(--sb-brand); color: #fff;
}
[data-testid="stSidebar"] [data-testid="stButton"] > button[kind="primary"]:hover:not(:disabled) {
  background: #2492ff;
}
[data-testid="stSidebar"] [data-testid="stButton"] > button[kind="primary"]:disabled {
  background: var(--sb-hover) !important; color: var(--sb-t3) !important;
}
/* 双按钮行（测试连接 / 保存并收起）：36px 高的按钮拉满整行时 16px 缝隙显挤，
   拉开到 20px 并给行本身上下留白，与相邻元素呼吸开 */
[data-testid="stSidebar"] [data-testid="stHorizontalBlock"]:has(.st-key-sb_test_btn) {
  gap: 20px;
  margin: var(--sb-1) 0;
}

/* ---------- 按钮：伪装成文字链接 ---------- */
[data-testid="stSidebar"] .st-key-sb_collapse_only button,
[data-testid="stSidebar"] .st-key-kb_cta_samples button {
  background: transparent !important;
  border: none !important;
  box-shadow: none !important;
  color: var(--sb-brand) !important;
  font-size: 12px !important;
  font-weight: 500 !important;
  min-height: 28px;
  padding: 2px 8px !important;
  justify-content: flex-start !important;
}
[data-testid="stSidebar"] .st-key-sb_collapse_only button:hover,
[data-testid="stSidebar"] .st-key-kb_cta_samples button:hover {
  background: transparent !important;
  color: #4da3ff !important;
  transform: none;
}
[data-testid="stSidebar"] .st-key-kb_cta_samples button {
  text-decoration: underline;
  text-underline-offset: 2px;
}

/* ---------- 折叠摘要行：markdown 负责视觉，透明按钮负责整行热区 ----------
   1.66 实测 .st-key-* 类名存在但压按钮不可靠，改用 :has 兄弟选择器
   （与问答页 qa-anchor 同款、已验证可用的机制）：
   摘要容器 = :has(.sb-summary)，其下一个 element-container 就是按钮容器 */
[data-testid="stSidebar"] div.element-container:has(.sb-summary) + div.element-container {
  margin-top: calc(-1 * (48px + var(--sb-2)));   /* 48px 行高 + 8px gap，压回摘要行上 */
  height: 48px;
  position: relative;
  z-index: 3;
}
/* 摘要的 element-container 高度可能塌成行高（实测 32px），强制撑到 48 保证对齐 */
[data-testid="stSidebar"] div.element-container:has(.sb-summary) { height: 48px; }
[data-testid="stSidebar"] div.element-container:has(.sb-summary) + div.element-container button {
  height: 48px; min-height: 48px;
  background: transparent !important;
  border: none !important;
  box-shadow: none !important;
  color: transparent !important;
  cursor: pointer;
  transform: none !important;
}
/* 关键：Streamlit 给按钮内的 <p> 单独上了色（不继承按钮的 transparent），
   只藏按钮本体文字会照常渲染、叠在摘要行上。必须连 <p> 一起藏；
   font-size:0 兜底保证任何字形都不渲染 */
[data-testid="stSidebar"] div.element-container:has(.sb-summary) + div.element-container button p {
  color: transparent !important;
  font-size: 0 !important;
}

/* ---------- 折叠面板（expander）→ iOS 分组行 ----------
   1.66 的 <details> 没有 data-testid="stExpander"，必须选 details 元素；
   图标是 summary 内的 [data-testid="stExpanderIcon"]（material 字形） */
[data-testid="stSidebar"] details {
  border: 1px solid var(--sb-line) !important;
  border-radius: 10px !important;
  background: var(--sb-group) !important;
  box-shadow: none !important;
  margin: 0;
  overflow: hidden;
}
[data-testid="stSidebar"] details > summary {
  list-style: none;
  display: flex; align-items: center; gap: var(--sb-2);
  min-height: 44px; padding: 6px 12px;
  font-size: 13px; font-weight: 500; color: var(--sb-t1);
  background: transparent;
  cursor: pointer;
  transition: background 180ms ease-out;
}
[data-testid="stSidebar"] details > summary::-webkit-details-marker { display: none; }
[data-testid="stSidebar"] details > summary:hover { background: var(--sb-hover); }
[data-testid="stSidebar"] [data-testid="stExpanderIcon"] {
  color: var(--sb-t2) !important; font-size: 16px !important; flex: 0 0 auto;
}
/* 右侧自绘 chevron（收合跟随 details[open]） */
[data-testid="stSidebar"] details > summary::after {
  content: ""; margin-left: auto; flex: 0 0 auto;
  width: 6px; height: 6px; border-right: 1.5px solid var(--sb-t3);
  border-bottom: 1.5px solid var(--sb-t3);
  transform: rotate(-45deg); transition: transform 180ms ease-out;
}
[data-testid="stSidebar"] details[open] > summary::after {
  transform: rotate(45deg);
}
[data-testid="stSidebar"] [data-testid="stExpanderDetails"] {
  padding: 2px 12px var(--sb-3) !important;
}
[data-testid="stSidebar"] [data-testid="stExpanderDetails"] p {
  font-size: 12.5px !important; line-height: 1.7; color: var(--sb-t2);
}
[data-testid="stSidebar"] [data-testid="stExpanderDetails"] b { color: var(--sb-t1); }

/* ---------- 「模块 ↔ 代码」键值行（替代会挤爆的 markdown 表格） ---------- */
.sb-kv { display: flex; flex-direction: column; margin: 2px 0; }
.sb-kv-row {
  display: flex; align-items: center; justify-content: space-between; gap: 12px;
  padding: 7px 0; font-size: 12px;
}
.sb-kv-row + .sb-kv-row { border-top: 1px solid var(--sb-line); }
.sb-kv-k { color: var(--sb-t1); font-weight: 500; flex: 0 0 auto; }
.sb-kv-v {
  font-family: var(--sb-mono); font-size: 10.5px; color: var(--sb-brand);
  text-align: right; word-break: break-all;
}

/* ---------- 知识库空态（虚线三件套） ---------- */
.sb-empty {
  border: 1px dashed var(--sb-line-strong); border-radius: var(--sb-r-box);
  padding: 16px 14px; text-align: center;
  transition: border-color 180ms ease-out;
  margin-bottom: var(--sb-2);
}
.sb-empty:hover { border-color: var(--sb-brand); }
.sb-empty-ico { display: flex; justify-content: center; color: var(--sb-t3); margin-bottom: var(--sb-2); }
.sb-empty-t { font-size: 13px; font-weight: 600; color: var(--sb-t1); margin-bottom: var(--sb-1); }
.sb-empty-d { font-size: 12px; color: var(--sb-t3); line-height: 1.6; }

/* ---------- 已建库状态：分组行 ---------- */
.sb-kb {
  display: flex; align-items: center; gap: var(--sb-2);
  min-height: 40px; padding: 6px 12px; border-radius: 10px;
  background: var(--sb-group); border: 1px solid var(--sb-line);
  font-size: 12px; color: var(--sb-t2);
}
.sb-kb b { color: var(--sb-t1); font-weight: 600; font-variant-numeric: tabular-nums; }

/* ---------- 底部 ---------- */
.sb-footer {
  font-size: 11px; color: var(--sb-t3); line-height: 1.7;
  padding-top: var(--sb-3); margin-top: var(--sb-gap);
  border-top: 1px solid var(--sb-line);
}

/* ---------- 侧栏内 caption 统一 ---------- */
[data-testid="stSidebar"] [data-testid="stCaptionContainer"] p,
[data-testid="stSidebar"] [data-testid="stCaptionContainer"] {
  font-size: 12px !important; color: var(--sb-t3) !important;
}
[data-testid="stSidebar"] [data-testid="stAlert"] p { font-size: 12px; }

@media (prefers-reduced-motion: reduce) {
  [data-testid="stSidebar"] * { transition-duration: .01ms !important; }
}

/* ===== 响应式：1440 / 768 / 375 ===== */
@media (max-width: 1024px) {
  [data-testid="stMainBlockContainer"], .block-container {
    padding-left: var(--rag-sp-4); padding-right: var(--rag-sp-4);
  }
  .rag-hero__title { font-size: var(--rag-fs-30); }
}
@media (max-width: 768px) {
  [data-testid="stMainBlockContainer"], .block-container { padding-top: var(--rag-sp-4); }
  .rag-hero__title { font-size: var(--rag-fs-24); }
  .rag-hero__sub { font-size: var(--rag-fs-14); }
  [data-testid="stHorizontalBlock"] { gap: var(--rag-sp-2); }
  h1, [data-testid="stHeading"] h1 { font-size: var(--rag-fs-24) !important; }
  h2, [data-testid="stHeading"] h2 { font-size: var(--rag-fs-20) !important; }
  .rag-error__row { grid-template-columns: 1fr; gap: 0; }
  .rag-state { min-height: 144px; }
}
@media (max-width: 420px) {
  [data-testid="stMainBlockContainer"], .block-container {
    padding-left: var(--rag-sp-3); padding-right: var(--rag-sp-3);
  }
  .rag-hero__title { font-size: var(--rag-fs-20); letter-spacing: -0.01em; }
  [data-testid="stMetricValue"] { font-size: var(--rag-fs-20) !important; }
}

/* ===== 动效偏好 ===== */
@media (prefers-reduced-motion: reduce) {
  *, *::before, *::after {
    animation-duration: 0.01ms !important;
    animation-iteration-count: 1 !important;
    transition-duration: 0.01ms !important;
    scroll-behavior: auto !important;
  }
}
</style>
"""


def inject() -> None:
    """注入全局样式。必须在任何其它 st.* 组件之前调用一次。"""
    st.markdown(_CSS, unsafe_allow_html=True)


# ---------------------------------------------------------------------------
# 六态视图
# 状态一律显式声明，不靠 len(x) == 0 之类的隐式推断。
# ---------------------------------------------------------------------------
def state_card(
    kind: str,
    title: str,
    desc: str = "",
    hint: str = "",
    *,
    compact: bool = False,
) -> None:
    """kind: empty | no_result | error | forbidden | partial | ready"""
    icon_name = _ICON_ALIAS.get(kind, "info")
    cls = f"rag-state rag-state--{kind}" + (" rag-state--compact" if compact else "")
    parts = [
        f'<div class="{cls}" role="status">',
        f'<span class="rag-state__icon">{icon_svg(icon_name, 24)}</span>',
        f'<div class="rag-state__title">{escape(title)}</div>',
    ]
    if desc:
        parts.append(f'<div class="rag-state__desc">{escape(desc)}</div>')
    if hint:
        parts.append(f'<div class="rag-state__hint">{escape(hint)}</div>')
    parts.append("</div>")
    st.markdown("".join(parts), unsafe_allow_html=True)


def empty_state(title: str, desc: str = "", hint: str = "", *, compact: bool = False) -> None:
    """「还没有数据」——引导创建，与「筛选无结果」和「加载失败」严格区分。"""
    state_card("empty", title, desc, hint, compact=compact)


def no_result_state(keyword: str, desc: str = "", hint: str = "", *, compact: bool = True) -> None:
    """「筛选/检索无结果」——回显用户用的词，引导放宽条件。"""
    echoed = f"你用「{keyword}」没有找到任何结果。" if keyword else "没有找到任何结果。"
    state_card("no_result", echoed, desc, hint, compact=compact)


def loading_state(title: str = "正在处理…", desc: str = "", *, compact: bool = False) -> None:
    state_card("loading", title, desc, compact=compact)


def partial_state(title: str, desc: str = "", hint: str = "", *, compact: bool = False) -> None:
    """部分成功：一定要说清"哪部分成了、哪部分没成"。"""
    state_card("partial", title, desc, hint, compact=compact)


def forbidden_state(need: str, owner: str, eta: str, *, compact: bool = False) -> None:
    """无权限态：缺什么权限 / 找谁申请 / 多久能批。禁止只显示 403。"""
    state_card(
        "forbidden",
        f"缺少权限：{need}",
        f"需要找 {owner} 申请开通，通常 {eta} 内可以批下来。",
        compact=compact,
    )


def error_state(
    *,
    title: str,
    reason: str,
    scope: str,
    kept: str,
    action: str,
    code: str,
    retryable: bool = False,
) -> bool:
    """错误态：原因 + 影响范围 + 系统保留了什么 + 用户能做什么 + 错误编号。

    返回 retryable，方便调用方决定是否渲染重试按钮（只有可重试错误才给）。
    """
    rows = [
        ("原因", reason),
        ("影响", scope),
        ("已保留", kept),
        ("你可以", action),
    ]
    body = "".join(
        f'<div class="rag-error__row"><span class="rag-error__key">{escape(k)}</span>'
        f'<span class="rag-error__val">{escape(v)}</span></div>'
        for k, v in rows if v
    )
    st.markdown(
        f'<div class="rag-error" role="alert">'
        f'<div class="rag-error__head">{icon_svg("error", 20)}{escape(title)}</div>'
        f'<div class="rag-error__grid">{body}</div>'
        f'<div class="rag-error__code">错误编号 · {escape(code)}'
        f'{" · 可重试" if retryable else " · 重试无效，请按上面的提示处理"}</div>'
        f"</div>",
        unsafe_allow_html=True,
    )
    return retryable


# ---------------------------------------------------------------------------
# 页头 / 小节标题（纯视觉，替换原来的 emoji 标题）
# ---------------------------------------------------------------------------
def page_hero(title: str, subtitle: str = "", eyebrow: str = "") -> None:
    parts = ['<div class="rag-hero">']
    if eyebrow:
        parts.append(
            f'<div class="rag-hero__eyebrow">{icon_svg("spark", 16)}'
            f"<span>{escape(eyebrow)}</span></div>"
        )
    parts.append(f'<h1 class="rag-hero__title">{escape(title)}</h1>')
    if subtitle:
        parts.append(f'<p class="rag-hero__sub">{escape(subtitle)}</p>')
    parts.append("</div>")
    st.markdown("".join(parts), unsafe_allow_html=True)


def step_label(number: int, text: str) -> None:
    st.markdown(
        f'<div class="rag-step"><span class="rag-step__num">{number}</span>'
        f"<span>{escape(text)}</span></div>",
        unsafe_allow_html=True,
    )


def section_title(text: str, icon_name: str = "") -> None:
    """小标题：纯文字 + 可选线性图标，不再用 emoji。"""
    prefix = icon_svg(icon_name, 20) if icon_name else ""
    st.markdown(
        f'<h3 style="display:flex;align-items:center;gap:var(--rag-sp-2);margin:'
        f'var(--rag-sp-2) 0 var(--rag-sp-3)">{prefix}<span>{escape(text)}</span></h3>',
        unsafe_allow_html=True,
    )
