"""功能页 3：问答 + 检索质量诊断 + 实验对比。

教学里最值钱的一屏：学员改检索参数 → 提问 → 一眼看到「我的答案和标准答案差在哪」。

UI 结构（本次重构，只改呈现，不动检索/生成/评估逻辑）：

    输入区（问题 + 配置 chips + 两个开关）
      ↓
    结论条（综合分 + 等级 + 四个指标 chip）  ← 永远置顶、永远可见
      ↓
    答案对比（标准答案 vs 你的答案）        ← 一级页面直接展示，不折叠
      ↓
    01 证据   02 为什么会这样，怎么修   03 实验记录   ← 默认全部收起

三条硬规则：
1. 回答必须在一级页面出现：问答后学员不点任何东西就能看到答案对比
2. 差异不上色到文字（红底划线看不清）：只在「你的答案」整栏做背景 ——
   与标准答案一致 = 绿色，有差异 = 黄色；左栏「标准答案」恒为中性基准
3. 页面只给「数据 + 判定 + 改哪个模块」，不写原理 —— 原理由课堂承担

要点判定只在 UI 层做（difflib 对齐，确定性、零成本），
不新增模型调用、不修改 core/ 下任何检索与评估代码。
"""

from __future__ import annotations

import difflib
import re
import time
from datetime import datetime
from html import escape

import pandas as pd
import streamlit as st

import ui.theme as theme
from core.evaluate import QualityReport, compare_answers, diagnose
from core.llm import ModelSettings, build_llm
from core.pipeline import generate_answer
from core.retrievers import RetrievalConfig, retrieve


# ---------------------------------------------------------------------------
# 样式：一次注入，色值一律引用 --rag-* 令牌（亮/暗自动跟随，不写死 hex）
# ---------------------------------------------------------------------------
_QA_CSS = """
<style>
/* ===== 折叠头 ===== */
/* 锚点只做标记：自身连同其元素容器一起隐藏，不占布局槽位 */
.qa-anchor { display: none; }
div.element-container:has(.qa-anchor),
div[class*="stElementContainer"]:has(.qa-anchor) { display: none; }

/* 折叠行：全宽、左对齐、chevron 用 CSS 画（不依赖字体字形） */
div.element-container:has(.qa-anchor:not(.qa-anchor--ghost)) + div.element-container [data-testid="stButton"] > button,
div[class*="stElementContainer"]:has(.qa-anchor:not(.qa-anchor--ghost)) + div [data-testid="stButton"] > button,
div:has(.qa-anchor:not(.qa-anchor--ghost)) + div [data-testid="stButton"] > button {
  display: flex; align-items: center;
  width: 100%; min-height: 0; margin-top: -6px;
  padding: var(--rag-sp-2) var(--rag-sp-3);
  font-size: var(--rag-fs-14); font-weight: 550; line-height: 1.5;
  box-shadow: none;
  background: var(--rag-surface-2);
  border: 1px solid var(--rag-border);
  border-radius: var(--rag-r-8);
  color: var(--rag-text-1);
  white-space: normal; word-break: break-word;
}
div.element-container:has(.qa-anchor:not(.qa-anchor--ghost)) + div.element-container [data-testid="stButton"] > button p,
div[class*="stElementContainer"]:has(.qa-anchor:not(.qa-anchor--ghost)) + div [data-testid="stButton"] > button p,
div:has(.qa-anchor:not(.qa-anchor--ghost)) + div [data-testid="stButton"] > button p {
  flex: 1; margin: 0; text-align: left; font-size: inherit; font-weight: inherit;
}
div.element-container:has(.qa-anchor:not(.qa-anchor--ghost)) + div.element-container [data-testid="stButton"] > button::before,
div[class*="stElementContainer"]:has(.qa-anchor:not(.qa-anchor--ghost)) + div [data-testid="stButton"] > button::before,
div:has(.qa-anchor:not(.qa-anchor--ghost)) + div [data-testid="stButton"] > button::before {
  content: ""; flex: none; width: 7px; height: 7px; margin-right: 10px;
  border-right: 1.6px solid var(--rag-text-3);
  border-bottom: 1.6px solid var(--rag-text-3);
  transform: rotate(-45deg);
  transition: transform 0.15s ease;
}
div:has(.qa-anchor--open) + div [data-testid="stButton"] > button::before {
  transform: rotate(45deg);
}
div.element-container:has(.qa-anchor:not(.qa-anchor--ghost)) + div.element-container [data-testid="stButton"] > button:hover:not(:disabled),
div[class*="stElementContainer"]:has(.qa-anchor:not(.qa-anchor--ghost)) + div [data-testid="stButton"] > button:hover:not(:disabled),
div:has(.qa-anchor:not(.qa-anchor--ghost)) + div [data-testid="stButton"] > button:hover:not(:disabled) {
  background: var(--rag-surface);
  border-color: var(--rag-border-strong);
}

/* 「展开全部 / 收起全部」：右侧幽灵文字按钮，不抢戏。
   折叠行选择器已用 :not(.qa-anchor--ghost) 排除本按钮（历史 bug：
   ghost 锚点也带 .qa-anchor，折叠行深底样式会以更高 specificity 压过这里，
   导致 chevron 泄漏 + 深底大按钮挡住对比卡）。
   specificity 与折叠行同构，保证任何后续规则叠加时仍是这里赢 */
div.element-container:has(.qa-anchor--ghost) + div.element-container [data-testid="stButton"] > button,
div[class*="stElementContainer"]:has(.qa-anchor--ghost) + div [data-testid="stButton"] > button,
div:has(.qa-anchor--ghost) + div [data-testid="stButton"] > button {
  width: 100%; min-height: 0; margin-top: 2px;
  padding: 2px 6px; justify-content: flex-end;
  background: transparent; border: none; box-shadow: none;
  color: var(--rag-text-3);
  font-size: var(--rag-fs-12); font-weight: 500;
}
div.element-container:has(.qa-anchor--ghost) + div.element-container [data-testid="stButton"] > button p,
div[class*="stElementContainer"]:has(.qa-anchor--ghost) + div [data-testid="stButton"] > button p,
div:has(.qa-anchor--ghost) + div [data-testid="stButton"] > button p {
  flex: none; margin: 0; text-align: right; font-size: inherit;
}
div.element-container:has(.qa-anchor--ghost) + div.element-container [data-testid="stButton"] > button::before,
div[class*="stElementContainer"]:has(.qa-anchor--ghost) + div [data-testid="stButton"] > button::before,
div:has(.qa-anchor--ghost) + div [data-testid="stButton"] > button::before {
  content: none;
}
div.element-container:has(.qa-anchor--ghost) + div.element-container [data-testid="stButton"] > button:hover:not(:disabled),
div[class*="stElementContainer"]:has(.qa-anchor--ghost) + div [data-testid="stButton"] > button:hover:not(:disabled),
div:has(.qa-anchor--ghost) + div [data-testid="stButton"] > button:hover:not(:disabled) {
  background: transparent; border: none; color: var(--rag-text-1);
}

/* 提问按钮列：按钮沉到列底，与输入框底边对齐（替代两个 st.write("") 垫片） */
div[data-testid="stColumn"]:has(.st-key-qa_ask) > div[data-testid="stVerticalBlock"] {
  height: 100%; justify-content: flex-end;
}

/* ===== 结论条 ===== */
.qa-verdict {
  display: flex; align-items: center; gap: var(--rag-sp-4);
  padding: var(--rag-sp-3) var(--rag-sp-4);
  border: 1px solid var(--rag-border); border-radius: var(--rag-r-8);
  background: var(--rag-surface-2);
}
.qa-verdict__score {
  font-size: 22px; font-weight: 650; font-variant-numeric: tabular-nums;
  line-height: 1; color: var(--rag-text-1); flex: none;
}
.qa-verdict__grade {
  font-size: var(--rag-fs-12); font-weight: 550; padding: 2px 8px;
  border-radius: var(--rag-r-4); flex: none;
  border: 1px solid var(--rag-border); color: var(--rag-text-2);
}
.qa-verdict__grade--ok { color: var(--rag-ok-fg); background: var(--rag-ok-bg); border-color: var(--rag-ok-line); }
.qa-verdict__grade--warn { color: var(--rag-warn-fg); background: var(--rag-warn-bg); border-color: var(--rag-warn-line); }
.qa-verdict__grade--bad { color: var(--rag-err-fg); background: var(--rag-err-bg); border-color: var(--rag-err-line); }
.qa-chips { display: flex; flex-wrap: wrap; gap: var(--rag-sp-2); margin-left: auto; }
.qa-chip {
  display: inline-flex; align-items: center; gap: 6px;
  font-size: var(--rag-fs-12); color: var(--rag-text-2);
  padding: 3px 9px; border-radius: var(--rag-r-4);
  border: 1px solid var(--rag-border); background: var(--rag-surface);
  cursor: help;
}
.qa-chip b { color: var(--rag-text-1); font-variant-numeric: tabular-nums; font-weight: 600; }
.qa-dot { width: 7px; height: 7px; border-radius: 999px; flex: none; background: var(--rag-text-3); }
.qa-dot--ok { background: var(--rag-ok-fg); }
.qa-dot--warn { background: var(--rag-warn-fg); }
.qa-dot--bad { background: var(--rag-err-fg); }
.qa-note {
  margin-top: var(--rag-sp-2); font-size: var(--rag-fs-12);
  padding: 6px 10px; border-radius: var(--rag-r-4);
  border: 1px solid var(--rag-border); color: var(--rag-text-2); background: var(--rag-surface-2);
}
.qa-note--warn { color: var(--rag-warn-fg); background: var(--rag-warn-bg); border-color: var(--rag-warn-line); }
.qa-note--err { color: var(--rag-err-fg); background: var(--rag-err-bg); border-color: var(--rag-err-line); }

/* ===== 表格 ===== */
.qa-table { width: 100%; border-collapse: collapse; font-size: var(--rag-fs-12); }
.qa-table th, .qa-table td {
  border: 1px solid var(--rag-border); padding: 7px 10px;
  text-align: left; vertical-align: top; color: var(--rag-text-2);
}
.qa-table th { background: var(--rag-surface-2); color: var(--rag-text-2); font-weight: 600; }
.qa-table td.qa-k { color: var(--rag-text-1); }
.qa-tag {
  display: inline-block; font-size: var(--rag-fs-12); padding: 1px 7px;
  border-radius: var(--rag-r-4); border: 1px solid var(--rag-border);
  color: var(--rag-text-2); white-space: nowrap;
}
.qa-tag--same { color: var(--rag-ok-fg); background: var(--rag-ok-bg); border-color: var(--rag-ok-line); }
.qa-tag--partial { color: var(--rag-warn-fg); background: var(--rag-warn-bg); border-color: var(--rag-warn-line); }
.qa-tag--diff { color: var(--rag-err-fg); background: var(--rag-err-bg); border-color: var(--rag-err-line); }

/* ===== 双栏 diff ===== */
.qa-diff { display: grid; grid-template-columns: 1fr 1fr; gap: var(--rag-sp-2); }
@media (max-width: 760px) { .qa-diff { grid-template-columns: 1fr; } }
.qa-dcol { border: 1px solid var(--rag-border); border-radius: var(--rag-r-8); overflow: hidden; }
.qa-dcol--std { background: var(--rag-surface-2); }   /* 左栏恒为中性基准 */
.qa-dcol__h {
  display: flex; align-items: baseline; gap: var(--rag-sp-2);
  padding: 7px 12px; font-size: var(--rag-fs-12); font-weight: 600;
  color: var(--rag-text-1); border-bottom: 1px solid var(--rag-border);
}
.qa-dcol__h span { color: var(--rag-text-3); font-weight: 400; font-variant-numeric: tabular-nums; }
.qa-seg {
  padding: 8px 12px; font-size: var(--rag-fs-12); line-height: 1.6;
  border-top: 1px solid var(--rag-border); color: var(--rag-text-2);
}
.qa-seg:first-of-type { border-top: none; }
.qa-seg__tag { display: block; font-size: var(--rag-fs-12); color: var(--rag-text-3); margin-bottom: 3px; }
.qa-seg--flat { color: var(--rag-text-3); font-style: italic; }
/* 差异只落在整栏背景：一致 = 绿，有差异 = 黄（正文不上色，保证可读） */
.qa-dcol--same {
  background: color-mix(in srgb, var(--rag-ok-fg) 10%, var(--rag-surface));
  border-color: var(--rag-ok-line);
}
.qa-dcol--diff {
  background: color-mix(in srgb, var(--rag-warn-fg) 16%, var(--rag-surface));
  border-color: var(--rag-warn-line);
}
.qa-dcol--same .qa-dcol__h { color: var(--rag-ok-fg); border-bottom-color: var(--rag-ok-line); }
.qa-dcol--diff .qa-dcol__h { color: var(--rag-warn-fg); border-bottom-color: var(--rag-warn-line); }

/* ===== chunk 行 ===== */
.qa-chunk {
  display: flex; align-items: baseline; gap: var(--rag-sp-2);
  padding: 7px 12px; border-top: 1px solid var(--rag-border); font-size: var(--rag-fs-12);
}
.qa-chunk:first-of-type { border-top: none; }
.qa-chunk__id { font-family: ui-monospace, SFMono-Regular, Menlo, monospace; color: var(--rag-text-1); flex: none; }
.qa-chunk__src { color: var(--rag-text-2); overflow: hidden; text-overflow: ellipsis; white-space: nowrap; flex: 1; }
.qa-chunk__sc { color: var(--rag-text-3); font-variant-numeric: tabular-nums; flex: none; }
.qa-chunk__pv { color: var(--rag-text-3); font-size: var(--rag-fs-12); padding: 0 12px 8px; }
.qa-flag { font-size: var(--rag-fs-12); padding: 1px 6px; border-radius: var(--rag-r-4); flex: none; border: 1px solid var(--rag-border); }
.qa-flag--rel { color: var(--rag-ok-fg); background: var(--rag-ok-bg); border-color: var(--rag-ok-line); }
.qa-flag--irrel { color: var(--rag-err-fg); background: var(--rag-err-bg); border-color: var(--rag-err-line); }
.qa-flag--unk { color: var(--rag-text-3); }

.qa-line { font-size: var(--rag-fs-12); color: var(--rag-text-2); padding: var(--rag-sp-1) 0; }
.qa-line b { color: var(--rag-text-1); }
.qa-sep { height: 1px; background: var(--rag-border); margin: var(--rag-sp-3) 0; }
.qa-mono { font-family: ui-monospace, SFMono-Regular, Menlo, monospace; }

@media (prefers-reduced-motion: reduce) {
  div.element-container:has(.qa-anchor:not(.qa-anchor--ghost)) + div.element-container [data-testid="stButton"] > button { transition: none; }
}
</style>
"""


# ---------------------------------------------------------------------------
# 折叠：状态由 session_state 维护，不用 st.expander（rerun 后会重置）
# ---------------------------------------------------------------------------
_FOLD_ORDER = ("evidence", "diag", "history")
_FOLD_META = {
    "evidence": ("01", "证据"),
    "diag": ("02", "为什么会这样，怎么修"),
    "history": ("03", "实验记录"),
}


def _fold(key: str, summary: str) -> bool:
    """渲染折叠头（全宽按钮样式），返回是否展开。

    开合箭头由 CSS ::before 画（.qa-anchor--open 控制），不放进按钮文案 ——
    ▸/▾ 这类字形在部分字体下缺字，会渲染成小圆点。
    """
    no, title = _FOLD_META[key]
    open_ = bool(st.session_state.get(f"qa_fold_{key}", False))
    anchor_cls = "qa-anchor qa-anchor--open" if open_ else "qa-anchor"
    st.markdown(f'<span class="{anchor_cls}"></span>', unsafe_allow_html=True)
    if st.button(
        f"{no}  {title}  ·  {summary}",
        key=f"qa_fold_btn_{key}",
        width="stretch",
    ):
        st.session_state[f"qa_fold_{key}"] = not open_
        st.rerun()
    return open_


def _set_all_folds(open_: bool) -> None:
    for k in _FOLD_ORDER:
        st.session_state[f"qa_fold_{k}"] = open_


# ---------------------------------------------------------------------------
# 小工具
# ---------------------------------------------------------------------------
def _module_label(config: RetrievalConfig) -> str:
    parts = []
    if config.use_vector:
        parts.append("向量")
    if config.use_bm25:
        parts.append("BM25")
    if config.use_hybrid and config.use_vector and config.use_bm25:
        parts.append("混合")
    elif config.use_vector and config.use_bm25:
        parts.append("直接拼接")
    if config.use_rerank:
        parts.append("Rerank")
    if not getattr(config, "use_context", True):
        parts.append("跳过拼接")
    return " + ".join(parts) if parts else "无检索"


def _pct(value: float) -> str:
    return f"{value * 100:.0f}%"


def _health(value: float, good: float, ok: float) -> str:
    if value >= good:
        return "ok"
    if value >= ok:
        return "warn"
    return "bad"


def _chip(name: str, value: str, health: str, tip: str) -> str:
    return (
        f'<span class="qa-chip" title="{escape(tip)}">'
        f'<i class="qa-dot qa-dot--{health}"></i>{escape(name)} <b>{escape(value)}</b></span>'
    )


def _short(text: str, n: int = 12) -> str:
    t = (text or "").strip()
    return t if len(t) <= n else t[:n] + "…"


# ---------------------------------------------------------------------------
# 要点对齐：把两篇答案拆成要点，逐条判定一致 / 部分一致 / 不一致
# 判定只在 UI 层做（difflib，确定性）；不新增模型调用、不改 core/
# ---------------------------------------------------------------------------
def _split_points(text: str, limit: int = 6) -> list[str]:
    """按句读切分，丢掉「依据：[1]」这类标注行和过短碎片。"""
    if not text:
        return []
    out: list[str] = []
    for seg in re.split(r"(?<=[。！？；;])|\n", text):
        s = seg.strip().strip("；;。 ")
        s = re.sub(r"^依据\s*[:：].*$", "", s).strip()
        if len(s) < limit:
            continue
        out.append(s)
    return out[:8]


def _coverage(point: str, whole: str) -> float:
    """要点里有多少字符能在目标文本里找到（衡量「这条要点被覆盖了多少」）。"""
    if not point:
        return 0.0
    sm = difflib.SequenceMatcher(None, point, whole, autojunk=False)
    matched = sum(b.size for b in sm.get_matching_blocks())
    return matched / len(point)


def _align(ideal: str, current: str) -> list[dict]:
    """要点级对齐：每条标准要点 -> 当前答案里最匹配的那句 + 判定。"""
    std_pts = _split_points(ideal)
    cur_pts = _split_points(current) or ([current.strip()] if current.strip() else [])
    rows: list[dict] = []
    used: set[int] = set()

    for p in std_pts:
        best_i, best_ratio = -1, 0.0
        for i, c in enumerate(cur_pts):
            if i in used:
                continue
            r = difflib.SequenceMatcher(None, p, c, autojunk=False).ratio()
            if r > best_ratio:
                best_i, best_ratio = i, r
        cover = _coverage(p, current)
        score = max(cover, best_ratio)
        if score >= 0.82:
            verdict = "same"
        elif score >= 0.45:
            verdict = "partial"
        else:
            verdict = "diff"
        if best_i >= 0 and verdict != "diff":
            used.add(best_i)
        yours = cur_pts[best_i] if best_i >= 0 and best_ratio >= 0.2 else ""
        rows.append({"std": p, "yours": yours, "verdict": verdict})

    if not rows:
        rows = [{"std": (ideal or "").strip(), "yours": (current or "").strip(), "verdict": "diff"}]
    return rows


def _cite_ids(text: str) -> list[int]:
    return sorted({int(n) for n in re.findall(r"\[(\d+)\]", text or "")})


# ---------------------------------------------------------------------------
# 结论条
# ---------------------------------------------------------------------------
def _render_verdict(report: QualityReport | None, elapsed: float, blocks: int) -> None:
    if report is None:
        chips = _chip("耗时", f"{elapsed:.2f}s", "ok", "本次检索+生成耗时") + _chip(
            "上下文", f"{blocks} 块", "ok", "喂给模型的资料块数"
        )
        st.markdown(
            f'<div class="qa-verdict"><div class="qa-verdict__score">—</div>'
            f'<div class="qa-verdict__grade">未生成对比分析</div>'
            f'<div class="qa-chips">{chips}</div></div>',
            unsafe_allow_html=True,
        )
        st.markdown(
            '<div class="qa-note">勾选「生成对比分析」后再提问，可得到综合分与差异判定。</div>',
            unsafe_allow_html=True,
        )
        return

    grade, _ = report.grade()
    score = report.overall
    gcls = "ok" if score >= 80 else ("warn" if score >= 60 else "bad")
    chips = "".join(
        [
            _chip("召回", _pct(report.recall), _health(report.recall, 0.8, 0.5), "该拿的拿到了多少"),
            _chip("纯度", _pct(report.purity), _health(report.purity, 0.8, 0.5), "上下文里有多少有用"),
            _chip("接地", _pct(report.grounded), _health(report.grounded, 0.9, 0.6), "答案有多少能在原文找到"),
            _chip("耗时", f"{elapsed:.2f}s", "ok", "本次检索+生成耗时"),
            _chip("上下文", f"{blocks} 块", "ok", "喂给模型的资料块数"),
        ]
    )
    st.markdown(
        f'<div class="qa-verdict">'
        f'<div class="qa-verdict__score">{score}</div>'
        f'<div class="qa-verdict__grade qa-verdict__grade--{gcls}">{escape(grade)}</div>'
        f'<div class="qa-chips">{chips}</div></div>',
        unsafe_allow_html=True,
    )

    if report.error:
        st.markdown(
            f'<div class="qa-note qa-note--err">{escape(report.error)}</div>',
            unsafe_allow_html=True,
        )
    if report.degraded:
        st.markdown(
            '<div class="qa-note qa-note--warn">判定降级 · 未接对话模型</div>',
            unsafe_allow_html=True,
        )
    if report.ungrounded_facts:
        facts = "、".join(f"<code>{escape(f)}</code>" for f in report.ungrounded_facts[:6])
        st.markdown(
            f'<div class="qa-note qa-note--err">疑似幻觉 · {facts}</div>',
            unsafe_allow_html=True,
        )


# ---------------------------------------------------------------------------
# 答案对比（一级页面直接展示，不折叠）
# ---------------------------------------------------------------------------
def _head(text: str) -> str:
    """要点短名：去掉开头的连接词，取前 12 字。"""
    t = re.sub(r"^(此外|另外|同时|并且|而且|其中|若|如果)[，,、]?\s*", "", (text or "").strip())
    return _short(t, 12)


def _build_rows(report: QualityReport, current_answer: str, used_refs: list[int]) -> list[dict]:
    """要点行 = 正文要点 + 依据标注（作为最后一个检查点）。"""
    ideal = report.ideal_answer
    rows = _align(ideal, current_answer)

    std_cites = _cite_ids(ideal)
    missing_cites = [i for i in std_cites if i not in (used_refs or [])]
    if std_cites:
        rows.append(
            {
                "std": "依据 " + " ".join(f"[{i}]" for i in std_cites),
                "yours": "依据 " + " ".join(f"[{i}]" for i in used_refs) if used_refs else "未标注",
                "verdict": "same" if not missing_cites else "diff",
                "cite_row": True,
            }
        )

    ungrounded = set(report.ungrounded_facts or [])
    for r in rows:
        cite = r.get("cite_row")
        if r["verdict"] == "diff":
            r["tag"] = "漏引 " + "".join(f"[{i}]" for i in missing_cites[:2]) if cite else "未提及"
        elif r["verdict"] == "partial":
            r["tag"] = "部分一致"
        else:
            r["tag"] = "一致"
        if not cite and ungrounded and any(f in r["std"] for f in ungrounded) \
                and r["verdict"] != "same":
            r["tag"] = "数字无出处"
        r["name"] = r["tag"] if "[" in r["tag"] else _head(r["std"])
    return rows


def _render_diff(report: QualityReport | None, result) -> None:
    if report is None or not report.ideal_answer:
        st.markdown(
            '<div class="qa-note">无标准答案 · 需开启对比分析</div>',
            unsafe_allow_html=True,
        )
        st.markdown(
            f'<div class="qa-line">{escape(result.answer)}</div>', unsafe_allow_html=True
        )
        return

    ideal = report.ideal_answer
    current_answer = result.answer
    rows = _build_rows(report, current_answer, result.used_refs)

    # 要点对齐表
    trs = []
    for i, r in enumerate(rows, start=1):
        v = r["verdict"]
        trs.append(
            f"<tr><td>{i}</td><td class='qa-k'>{escape(_short(r['std'], 40))}</td>"
            f"<td>{escape(_short(r['yours'], 40)) if r['yours'] else '未提及'}</td>"
            f"<td><span class='qa-tag qa-tag--{v}'>{escape(r.get('tag', v))}</span></td></tr>"
        )
    st.markdown(
        '<table class="qa-table"><thead><tr><th style="width:34px">#</th><th>标准答案</th>'
        "<th>你的答案</th><th>判定</th></tr></thead><tbody>" + "".join(trs) + "</tbody></table>",
        unsafe_allow_html=True,
    )

    # 双栏对比：差异只用「你的答案」整栏背景表达（一致绿 / 有差异黄），
    # 正文不上色 —— 红底划线式 diff 在暗色主题下基本读不清
    all_same = all(r["verdict"] == "same" for r in rows)
    left_parts, right_parts = [], []
    for i, r in enumerate(rows, start=1):
        tag = f"要点 {i}" if not r.get("cite_row") else "依据"
        left_parts.append(
            f'<div class="qa-seg"><span class="qa-seg__tag">{escape(tag)}</span>{escape(r["std"])}</div>'
        )
        body = escape(r["yours"]) if r["yours"] else "—— 未提及"
        right_parts.append(
            f'<div class="qa-seg"><span class="qa-seg__tag">{escape(tag)}</span>{body}</div>'
        )

    verdict_tag = (
        '<span class="qa-tag qa-tag--same">与标准答案一致</span>'
        if all_same
        else '<span class="qa-tag qa-tag--diff">与标准答案有差异</span>'
    )
    left = (
        '<div class="qa-dcol qa-dcol--std"><div class="qa-dcol__h">标准答案'
        f"<span>{len(report.ideal_answer)} 字</span></div>" + "".join(left_parts) + "</div>"
    )
    right = (
        f'<div class="qa-dcol {"qa-dcol--same" if all_same else "qa-dcol--diff"}">'
        f'<div class="qa-dcol__h">你的答案 {verdict_tag}'
        f"<span>{len(current_answer or '')} 字</span></div>" + "".join(right_parts) + "</div>"
    )
    st.markdown(f'<div class="qa-diff">{left}{right}</div>', unsafe_allow_html=True)

    # 事实点差异（原有数据，保持可查）
    diff = compare_answers(report.ideal_answer, current_answer)
    if diff["missing"] or diff["extra"]:
        miss = "、".join(f"<code>{escape(f)}</code>" for f in diff["missing"][:8]) or "—"
        extra = "、".join(f"<code>{escape(f)}</code>" for f in diff["extra"][:8]) or "—"
        st.markdown(
            f'<div class="qa-line" style="margin-top:var(--rag-sp-2)">缺的事实点 {miss}</div>'
            f'<div class="qa-line">多出的事实点 {extra}</div>',
            unsafe_allow_html=True,
        )


# ---------------------------------------------------------------------------
# 02 证据
# ---------------------------------------------------------------------------
def _noise_keys(report: QualityReport | None) -> set[str]:
    if report is None:
        return set()
    return {(n.get("preview") or "").strip()[:36] for n in report.noise if n.get("preview")}


def _render_evidence(trace, result, report: QualityReport | None) -> None:
    refs = result.refs or []
    noise = _noise_keys(report)
    judged = bool(report is not None and not report.degraded)

    if result.used_refs:
        st.markdown(
            '<div class="qa-line">模型依据 '
            + "".join(f"<b>[{i}]</b>" for i in result.used_refs)
            + "</div>",
            unsafe_allow_html=True,
        )
    for note in trace.notes:
        st.markdown(
            f'<div class="qa-note qa-note--warn">{escape(_short(note, 60))}</div>',
            unsafe_allow_html=True,
        )

    if not refs:
        st.markdown('<div class="qa-line">没有检索到任何资料</div>', unsafe_allow_html=True)
    else:
        rows = []
        for r in refs:
            text = (r.get("text") or "").replace("\n", " ")
            if not judged:
                flag = '<span class="qa-flag qa-flag--unk">未判定</span>'
            elif any(k and k in text for k in noise):
                flag = '<span class="qa-flag qa-flag--irrel">无关</span>'
            else:
                flag = '<span class="qa-flag qa-flag--rel">相关</span>'
            rows.append(
                f'<div class="qa-chunk"><span class="qa-chunk__id">[{r["index"]}]</span>'
                f'<span class="qa-chunk__src">{escape(r["source"])} · 第 {r["chunk_index"]} 块</span>'
                f'<span class="qa-chunk__sc">{r.get("score", "-")}</span>{flag}</div>'
                f'<div class="qa-chunk__pv">{escape(text[:110])}…</div>'
            )
        st.markdown(
            '<div class="qa-dcol">' + "".join(rows) + "</div>",
            unsafe_allow_html=True,
        )

    if report is not None and (report.missing or report.noise):
        miss = "、".join(f"[{m['index']}]" for m in report.missing[:6]) or "—"
        st.markdown(
            f'<div class="qa-line" style="margin-top:var(--rag-sp-2)">漏掉的相关块 {miss}</div>',
            unsafe_allow_html=True,
        )

    st.markdown('<div class="qa-sep"></div>', unsafe_allow_html=True)
    st.markdown('<div class="qa-line">发给模型的完整 prompt</div>', unsafe_allow_html=True)
    st.code(result.prompt, language="text")

    st.dataframe(
        pd.DataFrame(
            [
                {"阶段": s["name"], "条数": s["count"], "耗时(ms)": s["ms"], "说明": s["detail"]}
                for s in trace.stages
            ]
        ),
        width="stretch",
        hide_index=True,
    )


# ---------------------------------------------------------------------------
# 03 为什么会这样，怎么修（极简：哪里出问题 → 改哪个模块）
# ---------------------------------------------------------------------------
def _diagnose_rows(report: QualityReport | None) -> list[tuple[str, str]]:
    if report is None:
        return []
    rows: list[tuple[str, str]] = []
    if report.grounded < 0.9:
        rows.append(("生成端 · 数字无出处", "提示词：逐条标注依据"))
    if report.recall < 0.8:
        rows.append(("检索端 · 漏掉相关资料", "向量 / BM25 Top-K ↑ 或 关 Rerank"))
    if report.purity < 0.8:
        rows.append(("检索端 · 混进无关资料", "开 Rerank 或 最终块数 ↓"))
    if not rows:
        rows.append(("三项指标均达标", "无需调整"))
    return rows[:3]


def _render_diag(report: QualityReport | None) -> None:
    rows = _diagnose_rows(report)
    if not rows:
        st.markdown('<div class="qa-note">未生成对比分析</div>', unsafe_allow_html=True)
        return

    tip = escape(_short(report.diagnosis, 60)) if report and report.diagnosis else ""
    trs = "".join(
        f'<tr><td class="qa-k" style="width:44%" title="{tip}">{escape(where)}</td>'
        f'<td>→ 改 <b>{escape(what)}</b></td></tr>'
        for where, what in rows
    )
    st.markdown(
        '<table class="qa-table"><thead><tr><th>哪里出问题</th><th>改哪个模块</th></tr></thead>'
        f"<tbody>{trs}</tbody></table>",
        unsafe_allow_html=True,
    )

    if report and report.suggestions:
        items = "".join(f"<li>{escape(_short(s, 34))}</li>" for s in report.suggestions[:3])
        st.markdown(
            f'<div class="qa-line" style="margin-top:var(--rag-sp-2)">'
            f'<b>可改参数</b></div><ul style="margin:4px 0 0;padding-left:20px;'
            f'font-size:var(--rag-fs-12);color:var(--rag-text-2)">{items}</ul>',
            unsafe_allow_html=True,
        )


# ---------------------------------------------------------------------------
# 04 实验记录
# ---------------------------------------------------------------------------
def _history_deltas(history: list[dict]) -> list[str]:
    out: list[str] = []
    prev = None
    for h in history:
        cur = h.get("综合")
        if isinstance(cur, (int, float)) and isinstance(prev, (int, float)):
            d = round(cur - prev, 1)
            out.append(f"{'+' if d > 0 else ''}{d}")
        else:
            out.append("首次")
        if isinstance(cur, (int, float)):
            prev = cur
    return out


def _history_summary(history: list[dict]) -> str:
    if not history:
        return "暂无记录"
    last = history[-1]
    scored = [h for h in history if isinstance(h.get("综合"), (int, float))]
    if len(scored) >= 2:
        a, b = scored[-2]["综合"], scored[-1]["综合"]
        d = round(b - a, 1)
        arrow = "↑" if d > 0 else ("↓" if d < 0 else "→")
        return f"{len(history)} 次 · 最近 {last['时间']} 综合 {a} {arrow} {b}"
    return f"{len(history)} 次 · 最近 {last['时间']}"


def _render_history(history: list[dict]) -> None:
    if not history:
        st.markdown('<div class="qa-line">还没有记录，提问一次试试</div>', unsafe_allow_html=True)
        return

    df = pd.DataFrame(history)
    if "答案" in df.columns:
        df = df.drop(columns=["答案"])
    df.insert(len(df.columns), "较上次", _history_deltas(history))
    st.dataframe(df, width="stretch", hide_index=True, height=min(320, 60 + 35 * len(df)))

    questions = {h["问题"] for h in history}
    multi = [q for q in questions if sum(1 for h in history if h["问题"] == q) > 1]
    if multi:
        picked = st.selectbox("同一问题的不同配置", multi, key="cmp_question")
        rows = [h for h in history if h["问题"] == picked]
        cols = st.columns(len(rows))
        for col, row in zip(cols, rows):
            with col:
                st.markdown(f"**{row['检索配置']}**")
                st.caption(
                    f"{row['块数']} 块 ｜ 召回 {row['召回']} ｜ 纯度 {row['纯度']} "
                    f"｜ 接地 {row['接地']} ｜ 综合 {row['综合']}"
                )
                st.markdown(row["答案"])

    # 危险操作：二次确认
    if not st.session_state.get("_confirm_clear"):
        if st.button("清空实验记录", key="clear_history", icon=":material/delete:"):
            st.session_state["_confirm_clear"] = True
            st.rerun()
    else:
        st.warning(
            f"清空后不可恢复：这 {len(history)} 条记录会立即删除。知识库和索引不受影响。",
            icon=":material/warning:",
        )
        cc = st.columns(2)
        with cc[0]:
            if st.button(
                "确认清空", key="confirm_clear_yes", type="primary",
                icon=":material/delete_forever:",
            ):
                st.session_state["qa_history"] = []
                st.session_state["_confirm_clear"] = False
                st.rerun()
        with cc[1]:
            if st.button("取消", key="confirm_clear_no"):
                st.session_state["_confirm_clear"] = False
                st.rerun()


# ---------------------------------------------------------------------------
# 主流程
# ---------------------------------------------------------------------------
def render(settings: ModelSettings) -> None:
    st.markdown(_QA_CSS, unsafe_allow_html=True)

    kb = st.session_state.get("kb")
    if kb is None:
        theme.empty_state(
            "还没有知识库",
            "先到「流程编排」页，单击「建立索引」模块，选好文档和切片策略后建库，再回来提问。",
            "没有 API Key 也能建库；只有生成答案那一步需要 Key。",
        )
        return

    config: RetrievalConfig = st.session_state.get("retrieval_config") or RetrievalConfig()

    st.markdown(
        f'<div class="qa-line">当前配置 <b>{escape(_module_label(config))}</b> · '
        f'召回 向量{config.vector_top_k}/BM25{config.bm25_top_k} · '
        f'最终上下文 {config.rerank_top_n} 块 · 改配置去「流程编排」页</div>',
        unsafe_allow_html=True,
    )

    c1, c2 = st.columns([4, 1])
    with c1:
        question = st.text_input(
            "你的问题",
            key="qa_question",
            placeholder="例如：学校有哪些奖助学金？怎么申请？",
        )
    with c2:
        # 与输入框底边对齐的样式在 _QA_CSS（stColumn:has(.st-key-qa_ask)），不用 write 垫片
        ask = st.button(
            "提问", icon=":material/send:", key="qa_ask",
            width="stretch", type="primary",
        )

    opts = st.columns(2)
    with opts[0]:
        skip_generation = st.checkbox(
            "只检索不生成（省 token，只看找到什么）", value=False, key="qa_skip_gen"
        )
    with opts[1]:
        want_diagnosis = st.checkbox(
            "生成对比分析（多 1 次模型调用）",
            value=True,
            key="qa_diagnose",
            help="跑一次「完美检索」当参照，给出标准答案和三个质量分数。",
        )

    if ask and question.strip():
        llm = None
        if settings.llm_ready:
            try:
                llm = build_llm(settings)
            except Exception as exc:  # noqa: BLE001
                theme.error_state(
                    title="模型初始化失败",
                    reason=f"{type(exc).__name__}: {exc}",
                    scope="本次提问没有执行，检索与知识库都不受影响。",
                    kept="你输入的问题、当前检索配置和会话状态都还在。",
                    action="到左侧确认 API Key 与模型名，点「测试连接」验证后重试。",
                    code="RAG-E2002",
                    retryable=True,
                )
                return
        elif not skip_generation:
            theme.error_state(
                title="无法生成答案",
                reason="还没有配置对话模型（缺少 API Key 或模型名）。",
                scope="检索和诊断仍可使用，只是没有最终答案。",
                kept="知识库、检索配置和问题内容都还在。",
                action="要么在左侧填一个 API Key，要么勾选上面的「只检索不生成」。",
                code="RAG-E2003",
                retryable=False,
            )
            return

        t0 = time.perf_counter()
        try:
            with st.spinner("检索 + 生成中…"):
                trace = retrieve(
                    index=kb.index, nodes=kb.nodes, query=question, config=config, llm=llm
                )
                result = generate_answer(
                    question, trace, llm,
                    skip_generation=skip_generation or llm is None,
                    use_context=getattr(config, "use_context", True),
                )
            report = None
            if want_diagnosis and not skip_generation:
                with st.spinner("正在生成「标准答案」并诊断…"):
                    report = diagnose(
                        query=question, trace=trace, result=result,
                        kb=kb, llm=llm, current_config=config,
                    )
        except Exception as exc:  # noqa: BLE001
            theme.error_state(
                title="本次提问执行失败",
                reason=f"{type(exc).__name__}: {exc}",
                scope="这一问的答案和诊断都没有生成，知识库与历史记录不受影响。",
                kept="已建好的索引、之前的实验记录、当前检索配置都还在。",
                action="检查网络与 API Key 后重新点「提问」；"
                "也可以先勾选「只检索不生成」确认检索本身是否正常。",
                code="RAG-E2001",
                retryable=True,
            )
            return
        elapsed = time.perf_counter() - t0

        st.session_state["last_qa"] = {
            "question": question,
            "trace": trace,
            "result": result,
            "report": report,
            "elapsed": elapsed,
            "config": config,
        }

        history = st.session_state.setdefault("qa_history", [])
        history.append(
            {
                "时间": datetime.now().strftime("%H:%M:%S"),
                "问题": question,
                "检索配置": _module_label(config),
                "召回": _pct(report.recall) if report else "-",
                "纯度": _pct(report.purity) if report else "-",
                "接地": _pct(report.grounded) if report else "-",
                "综合": report.overall if report else "-",
                "块数": len(trace.final),
                "耗时(s)": round(elapsed, 2),
                "答案": result.answer[:600],
            }
        )

    last = st.session_state.get("last_qa")
    if not last:
        st.markdown(
            '<div class="qa-note">提一个问题试试 · 改参数后问同一个问题，看分数变化</div>',
            unsafe_allow_html=True,
        )
        history = st.session_state.get("qa_history") or []
        if history:
            st.markdown('<div class="qa-sep"></div>', unsafe_allow_html=True)
            if _fold("history", _history_summary(history)):
                _render_history(history)
        return

    trace = last["trace"]
    result = last["result"]
    report = last.get("report")

    st.markdown('<div class="qa-sep"></div>', unsafe_allow_html=True)
    _render_verdict(report, last["elapsed"], len(trace.final))

    # 答案对比：一级页面直接展示，问答后不点任何东西就能看到
    _render_diff(report, result)

    # 展开全部 / 收起全部（幽灵文字按钮，贴对比区下方）
    all_open = all(bool(st.session_state.get(f"qa_fold_{k}", False)) for k in _FOLD_ORDER)
    bar = st.columns([6, 1])
    with bar[1]:
        st.markdown('<span class="qa-anchor qa-anchor--ghost"></span>', unsafe_allow_html=True)
        if st.button("收起全部" if all_open else "展开全部", key="qa_fold_all"):
            _set_all_folds(not all_open)
            st.rerun()

    # 01 证据
    total = len(result.refs or [])
    if report is not None and not report.degraded:
        ev = f"上下文 {total} 块 · 相关 {total - len(report.noise)} · 无关 {len(report.noise)}"
    else:
        ev = f"上下文 {total} 块 · 未判定"
    if _fold("evidence", ev):
        _render_evidence(trace, result, report)

    # 02 为什么会这样，怎么修
    rows = _diagnose_rows(report)
    if not rows:
        dg = "未生成对比分析"
    elif rows[0][0] == "三项指标均达标":
        dg = "无需调整"
    else:
        dg = f"{len(rows)} 处要改 · " + " · ".join(what for _, what in rows[:2])
    if _fold("diag", dg):
        _render_diag(report)

    # 03 实验记录
    history = st.session_state.get("qa_history") or []
    if _fold("history", _history_summary(history)):
        _render_history(history)
