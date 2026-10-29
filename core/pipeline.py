"""问答流水线：把检索结果拼成上下文，交给 LLM 生成答案。

刻意不用 query engine 的封装，而是自己拼 prompt —— 因为教学里最重要的一件事
是让学习者**看到喂给模型的原文**：检索错 → 上下文错 → 答案错，这条因果链
只有把 prompt 摊开才能讲明白。
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from llama_index.core.schema import MetadataMode, NodeWithScore

from core.retrievers import RetrievalTrace

ANSWER_PROMPT = """你是一个严格依据给定资料回答问题的助手。

规则：
1. 只使用下面【资料】中的内容回答，不要使用你自己的先验知识。
2. 如果资料中确实没有答案，就直接回答「资料中没有提到这个问题」，不要猜测或补充。
3. **回答要短：控制在 3 句话、120 字以内。** 只给结论和关键数字，
   不要复述资料原文，不要罗列不相关的条款。
4. 资料里有数字、型号、时间、比例，就写在结论里；没有的不要编。
5. 最后单独一行注明依据了哪几段资料，格式为：依据：[1][3]

【资料】
{context}

【问题】
{question}"""

# 上下文拼接被跳过时用的模板：资料没有编号、没有来源标注，
# 所以第 5 条「依据：[1][3]」没有意义，去掉 —— 让学习者观察
# 答案的「依据」会变成什么样，正是这个模式的教学点。
RAW_ANSWER_PROMPT = """你是一个严格依据给定资料回答问题的助手。

规则：
1. 只使用下面【资料】中的内容回答，不要使用你自己的先验知识。
2. 如果资料中确实没有答案，就直接回答「资料中没有提到这个问题」，不要猜测或补充。
3. **回答要短：控制在 3 句话、120 字以内。** 只给结论和关键数字，
   不要复述资料原文，不要罗列不相关的条款。
4. 资料里有数字、型号、时间、比例，就写在结论里；没有的不要编。

【资料】
{context}

【问题】
{question}"""


@dataclass
class AnswerResult:
    answer: str
    prompt: str
    context: str
    refs: list[dict]
    used_refs: list[int]


def _clean(node: NodeWithScore) -> str:
    text = node.node.get_content(metadata_mode=MetadataMode.NONE) or ""
    return re.sub(r"\n{3,}", "\n\n", text.strip())


def build_context(hits: list[NodeWithScore]) -> tuple[str, list[dict]]:
    """把最终命中的块拼成带编号的上下文。"""
    blocks: list[str] = []
    refs: list[dict] = []
    for i, hit in enumerate(hits, start=1):
        text = _clean(hit)
        source = hit.node.metadata.get("file_name") or hit.node.metadata.get("chunk_source") or "未知来源"
        chunk_index = hit.node.metadata.get("chunk_index", "-")
        blocks.append(f"[{i}] 来源：{source} 第 {chunk_index} 块\n{text}")
        refs.append(
            {
                "index": i,
                "source": source,
                "chunk_index": chunk_index,
                "score": round(float(hit.score or 0.0), 4),
                "text": text,
            }
        )
    return "\n\n".join(blocks), refs


def generate_answer(
    question: str,
    trace: RetrievalTrace,
    llm,
    skip_generation: bool = False,
    use_context: bool = True,
) -> AnswerResult:
    """use_context=False 时跳过「上下文拼接」：原始块直接进 prompt，
    不编号、不标来源 —— 用于教学对比「拼接 vs 不拼接」的答案差异。"""
    context, refs = build_context(trace.final)
    if use_context:
        prompt = ANSWER_PROMPT.format(context=context or "（没有检索到任何资料）", question=question)
    else:
        raw = "\n\n".join(r["text"] for r in refs) if refs else ""
        prompt = RAW_ANSWER_PROMPT.format(context=raw or "（没有检索到任何资料）", question=question)

    if skip_generation:
        return AnswerResult(
            answer="（已跳过生成阶段，仅展示检索结果）",
            prompt=prompt,
            context=context,
            refs=refs,
            used_refs=[],
        )

    if llm is None:
        raise ValueError("生成答案需要 LLM，请先配置 API Key。")

    answer = str(llm.complete(prompt)).strip()
    used = [int(n) for n in re.findall(r"\[(\d+)\]", answer.split("依据")[-1])]
    return AnswerResult(
        answer=answer,
        prompt=prompt,
        context=context,
        refs=refs,
        used_refs=sorted(set(used)),
    )
