"""检索质量诊断：给当前配置的答案打一个"裁判分"。

教学里最难的一环是**反馈**：学生改了参数，看到答案变了，但不知道是变好还是变差。
这个模块就是补上这一环，做法是造一个"完美检索"当参照物：

    1. 宽召回：把召回范围放到最大（向量 20 + BM25 20 + RRF 融合 12，不截断）
       —— 这近似"如果检索器不犯错，本来能拿到哪些资料"
    2. 让 LLM 在宽召回结果里圈出「真正含答案的那几块」（relevant set）
    3. 拿当前配置实际用的块去和它比，得到三个可横向比较的分数：

       召回覆盖率 = 当前块 ∩ 相关块 / 相关块     → 有没有漏掉关键信息
       上下文纯度 = 当前块 ∩ 相关块 / 当前块     → 有没有混进无关噪声
       答案接地率 = 答案里的事实点能在上下文中找到的比例 → 有没有在编

    4. 顺便生成「理想答案」和一份针对性的参数建议

三个分数里，召回和纯度是纯集合运算（零成本、确定性），
接地率用"数字/型号/百分比"这类硬事实做启发式核对（同样零成本）。
只有「圈相关块 + 理想答案 + 诊断」需要一次 LLM 调用。
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field

from core.pipeline import build_context
from core.retrievers import RetrievalConfig, retrieve

DIAGNOSE_PROMPT = """你是一个 RAG 系统的质检员。请根据下面的材料做一次诊断。

【用户问题】
{query}

【候选资料】
这是把召回范围放到最大后拿到的 {n} 段资料，其中（可能）包含回答问题所需的全部信息。
{context}

【当前系统实际使用的资料编号】
{used_ids}

【当前检索配置】
{config_desc}

【当前系统生成的答案】
{answer}

请完成三件事，只输出一个 JSON 对象，不要输出多余文字：

{{
  "relevant_ids": [真正含有回答问题所需信息的资料编号；从 1 到 {n} 里选，可以只选一小部分],
  "ideal_answer": "如果检索完美、相关资料都拿到了，应该给出的答案。只依据上面的候选资料，不要编造",
  "diagnosis": "对比当前答案和理想答案，具体指出差在哪里，并判断主因：是检索漏召、上下文噪声、分块切断，还是模型没用好上下文",
  "suggestions": ["一条具体的参数调整建议（必须指明调哪个开关或哪个数字，例如「把 Rerank 后保留数从 4 调到 6」）", "另一条建议"]
}}"""


@dataclass
class QualityReport:
    recall: float = 0.0          # 召回覆盖率
    purity: float = 0.0          # 上下文纯度
    grounded: float = 1.0        # 答案接地率
    ideal_answer: str = ""
    diagnosis: str = ""
    suggestions: list[str] = field(default_factory=list)
    missing: list[dict] = field(default_factory=list)   # 漏掉的相关块
    noise: list[dict] = field(default_factory=list)     # 混进来的无关块
    ungrounded_facts: list[str] = field(default_factory=list)
    wide_count: int = 0
    relevant_count: int = 0
    error: str = ""
    degraded: bool = False      # LLM 没给出可用判定时，指标是按「宽召回全集」估算的

    @property
    def overall(self) -> float:
        return round((self.recall + self.purity + self.grounded) / 3 * 100, 1)

    def grade(self) -> tuple[str, str]:
        """给一个粗档位，方便一眼看结论。"""
        score = self.overall
        if score >= 80:
            return "优秀", "🟢"
        if score >= 60:
            return "及格", "🟡"
        return "偏差较大", "🔴"


# ---------------------------------------------------------------------------
# 零成本指标
# ---------------------------------------------------------------------------
_FACT_PATTERN = re.compile(
    r"\d+(?:\.\d+)?\s*(?:%|％|元|块|天|个月|年|次|万|亿|字|句|GB|MB|mAh|W)?"
    r"|[A-Za-z]{2,}[A-Za-z0-9\-_.]*",
)


def _is_meaningful(fact: str) -> bool:
    """过滤掉太泛的碎片，只留下值得核对的事实点。"""
    fact = fact.strip()
    if not fact:
        return False
    if re.fullmatch(r"[\d]{1,2}", fact):     # 1、2、3 这种小数字多半是序号
        return False
    if len(fact) == 1:
        return False
    return True


def answer_groundedness(answer: str, context: str) -> tuple[float, list[str]]:
    """答案接地率：答案里提到的数字/型号/百分比，有多少能在上下文里找到。

    这是个启发式，但抓的正是幻觉最容易露馅的地方 ——
    编造出来的数字和型号，上下文里一定找不到。
    """
    facts = []
    for raw in _FACT_PATTERN.findall(answer or ""):
        fact = raw.strip()
        if _is_meaningful(fact) and fact not in facts:
            facts.append(fact)
    if not facts:
        return 1.0, []
    missing = [f for f in facts if f not in (context or "")]
    return round(1 - len(missing) / len(facts), 3), missing


def compare_answers(ideal: str, current: str) -> dict:
    """对比两个答案的「事实点」差异。

    教学用途：读两段四百字的答案去人眼找差别太累，而且容易漏。
    把数字、型号、百分比这些硬事实抽出来做集合运算，「缺了什么」一眼就能看见。
    """

    def facts(text: str) -> list[str]:
        out: list[str] = []
        for raw in _FACT_PATTERN.findall(text or ""):
            f = raw.strip()
            if _is_meaningful(f) and f not in out:
                out.append(f)
        return out

    ideal_text = ideal or ""
    current_text = current or ""
    ideal_facts = facts(ideal_text)
    current_facts = facts(current_text)
    return {
        "ideal_facts": ideal_facts,
        "current_facts": current_facts,
        # 理想答案里提到、但在当前答案原文里根本找不到 -> 当前答案缺的料
        "missing": [f for f in ideal_facts if f not in current_text][:12],
        # 当前答案里有、理想答案里没有 -> 可能编的，也可能是理想答案没覆盖到
        "extra": [f for f in current_facts if f not in ideal_text][:12],
        "ideal_len": len(ideal_text),
        "current_len": len(current_text),
    }


def _parse_json(raw: str) -> dict:
    """从模型回答里抠出 JSON。模型经常在前后加解释或 ```json 围栏。"""
    text = (raw or "").strip()
    fence = re.search(r"```(?:json)?\s*(.+?)```", text, re.S)
    if fence:
        text = fence.group(1).strip()
    start, end = text.find("{"), text.rfind("}")
    if start == -1 or end <= start:
        return {}
    try:
        return json.loads(text[start : end + 1])
    except json.JSONDecodeError:
        return {}


# ---------------------------------------------------------------------------
# 主入口
# ---------------------------------------------------------------------------
def diagnose(
    *,
    query: str,
    trace,
    result,
    kb,
    llm,
    current_config: RetrievalConfig,
) -> QualityReport:
    """跑一次"完美检索"参照，并诊断当前配置的表现。"""
    report = QualityReport()

    # ---- 1. 宽召回：近似"理想检索" ----
    wide_config = RetrievalConfig(
        use_vector=True,
        use_bm25=True,
        use_hybrid=True,
        use_rerank=False,       # 不重排，避免再把范围缩小
        vector_top_k=20,
        bm25_top_k=20,
        fusion_top_k=12,
        rerank_top_n=12,
    )
    try:
        wide = retrieve(index=kb.index, nodes=kb.nodes, query=query, config=wide_config, llm=None)
    except Exception as exc:  # noqa: BLE001
        report.error = f"宽召回失败：{type(exc).__name__}: {exc}"
        return report

    report.wide_count = len(wide.final)
    if not wide.final:
        report.error = "宽召回也没有拿到任何资料，无法评估。"
        return report

    wide_context, wide_refs = build_context(wide.final)
    cur_context, cur_refs = build_context(trace.final)
    used_ids = "、".join(str(r["index"]) for r in cur_refs) or "（无）"

    config_desc = (
        f"向量检索={'开' if current_config.use_vector else '关'}，"
        f"BM25={'开' if current_config.use_bm25 else '关'}，"
        f"混合检索={'开' if current_config.use_hybrid else '关'}，"
        f"Rerank={'开' if current_config.use_rerank else '关'}；"
        f"向量召回 {current_config.vector_top_k} 块、BM25 召回 {current_config.bm25_top_k} 块、"
        f"融合后 {current_config.fusion_top_k} 块、最终上下文 {current_config.rerank_top_n} 块"
    )

    # ---- 2. 一次 LLM 调用：圈相关块 + 理想答案 + 诊断 ----
    if llm is not None:
        prompt = DIAGNOSE_PROMPT.format(
            query=query, n=len(wide.final), context=wide_context,
            used_ids=used_ids, config_desc=config_desc, answer=result.answer,
        )
        try:
            payload = _parse_json(str(llm.complete(prompt)))
        except Exception as exc:  # noqa: BLE001
            payload = {}
            report.error = f"诊断调用失败：{type(exc).__name__}: {exc}"
        report.ideal_answer = str(payload.get("ideal_answer", "")).strip()
        report.diagnosis = str(payload.get("diagnosis", "")).strip()
        raw_sug = payload.get("suggestions") or []
        report.suggestions = [str(s).strip() for s in raw_sug if str(s).strip()][:4]

        relevant_ids = payload.get("relevant_ids") or []
        index_to_node = {i + 1: n.node.node_id for i, n in enumerate(wide.final)}
        index_to_ref = {r["index"]: r for r in wide_refs}
        relevant_node_ids = set()
        for rid in relevant_ids:
            try:
                key = int(rid)
            except (TypeError, ValueError):
                continue
            if key in index_to_node:
                relevant_node_ids.add(index_to_node[key])
        report.relevant_count = len(relevant_node_ids)
    else:
        relevant_node_ids = set()

    # 模型没给出可用的相关块判定（比如没配对话模型，或返回的不是合法 JSON）时，
    # 退化成「宽召回全集 = 相关集合」，保证两个集合指标仍然有参考价值。
    if not relevant_node_ids:
        report.degraded = True
        relevant_node_ids = {h.node.node_id for h in wide.final}
        report.relevant_count = len(relevant_node_ids)

    # ---- 3. 集合类指标（零成本、确定性）----
    cur_node_ids = {h.node.node_id for h in trace.final}
    report.recall = round(len(cur_node_ids & relevant_node_ids) / len(relevant_node_ids), 3)
    report.purity = round(len(cur_node_ids & relevant_node_ids) / len(cur_node_ids), 3) if cur_node_ids else 0.0

    # 漏了什么 / 混进了什么（用于界面点名）
    if not report.degraded:
        index_to_ref = {r["index"]: r for r in wide_refs}
        for i, node_wrap in enumerate(wide.final, start=1):
            nid = node_wrap.node.node_id
            if nid in relevant_node_ids and nid not in cur_node_ids:
                report.missing.append(
                    {
                        "index": i,
                        "preview": (index_to_ref.get(i, {}).get("text") or "").replace("\n", " ")[:110],
                    }
                )
        for hit in trace.final:
            if hit.node.node_id not in relevant_node_ids:
                report.noise.append(
                    {"preview": (hit.node.get_content() or "").replace("\n", " ")[:110]}
                )

    # ---- 4. 接地率 ----
    report.grounded, report.ungrounded_facts = answer_groundedness(result.answer, cur_context)
    return report
