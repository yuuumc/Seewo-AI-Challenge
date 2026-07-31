"""订正对比批改引擎 — Sprint 3 订正闭环核心.

输入：原题目 + 学生原答案 + 原批改结果 + 学生订正答案
输出：{mastery_level, is_correct, comparison, feedback, encouragement, next_steps}

Mock 优先：无 LLM key 时走规则引擎做答案比对 + 模板反馈；
prompts.correction_grading 可用时接入 LLM 增强对比分析。
"""
from __future__ import annotations

import json
import re
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Optional

DATA_DIR = Path(__file__).resolve().parent.parent / "data"


def _load_json(name: str) -> Any:
    with open(DATA_DIR / name, "r", encoding="utf-8") as f:
        return json.load(f)


# ── 掌握度判定 ────────────────────────────────────────────────────────
MASTERY_MASTERED = "mastered"
MASTERY_PARTIAL = "partial"
MASTERY_NOT_MASTERED = "not_mastered"


def _determine_mastery(
    question: dict,
    correction_text: str,
) -> tuple[str, bool]:
    """规则引擎判定掌握度.

    Returns: (mastery_level, is_correct)
    """
    q_type = question.get("type", "long_answer")
    standard = question.get("answer", "").strip()
    correction = correction_text.strip()

    if q_type == "choice":
        is_correct = correction.upper() == standard.upper()
        level = MASTERY_MASTERED if is_correct else MASTERY_NOT_MASTERED
        return level, is_correct

    if q_type == "fill_blank":
        norm = lambda s: re.sub(r"\s+", "", s)
        is_correct = norm(correction) == norm(standard)
        level = MASTERY_MASTERED if is_correct else MASTERY_NOT_MASTERED
        return level, is_correct

    # long_answer: 结构化判定
    # 完全正确：含标准答案关键步骤 + 最终结论
    # 部分正确：含部分关键步骤但缺结论
    # 未掌握：方向错误或空白
    steps = question.get("steps", [])
    key_concepts = _extract_key_concepts(question, standard)

    if not correction or len(correction) < 5:
        return MASTERY_NOT_MASTERED, False

    hit_count = sum(1 for kc in key_concepts if kc in correction)
    total = max(len(key_concepts), 1)
    ratio = hit_count / total

    has_conclusion = any(
        kw in correction
        for kw in ["所以", "因此", "故", "综上", "单调", "存在", "不存在", "递增", "递减"]
    )

    if ratio >= 0.8 and has_conclusion:
        return MASTERY_MASTERED, True
    elif ratio >= 0.4 or has_conclusion:
        return MASTERY_PARTIAL, False
    else:
        return MASTERY_NOT_MASTERED, False


def _extract_key_concepts(question: dict, standard: str) -> list[str]:
    """从题目和标准答案中提取关键概念用于匹配."""
    concepts = []
    # 从 steps 提取
    for step in question.get("steps", []):
        content = step.get("content", "")
        # 提取数学表达式片段
        for match in re.findall(r"[a-z]'?\([^)]*\)|[a-z]²|[a-z]\^[0-9]|≥|≤|=", content):
            if len(match) > 1:
                concepts.append(match)
    # 从标准答案提取
    for match in re.findall(r"[a-z]'?\([^)]*\)|[a-z]²|[a-z]\^[0-9]|≥|≤|单调|递增|递减", standard):
        concepts.append(match)
    # 去重保序
    seen = set()
    unique = []
    for c in concepts:
        if c not in seen:
            seen.add(c)
            unique.append(c)
    return unique[:8]  # 最多取 8 个


# ── 反馈生成 ──────────────────────────────────────────────────────────
def _generate_feedback(
    mastery: str,
    question: dict,
    correction_text: str,
    original_answer: str,
) -> str:
    """根据掌握度生成结构化反馈."""
    q_type = question.get("type", "long_answer")

    if mastery == MASTERY_MASTERED:
        if q_type == "choice":
            return "订正正确！你已掌握该知识点，闭环完成。"
        return "订正完全正确！关键步骤和结论都已到位，闭环完成。"

    if mastery == MASTERY_PARTIAL:
        steps = question.get("steps", [])
        missing = [
            s["content"]
            for s in steps
            if s.get("content") and s["content"] not in correction_text
        ]
        hint = f"还差一步：{missing[0]}" if missing else "注意补全最终结论"
        return f"方向正确但不够完整。{hint}，再想想。"

    return f"订正方向需要调整。标准答案的关键思路：{question.get('answer', '')[:50]}。建议回顾相关知识点后重试。"


def _generate_encouragement(
    mastery: str,
    question: dict,
    student_id: str,
) -> str:
    """生成针对性鼓励语（非空洞赞美）."""
    knowledge = question.get("knowledge", "该知识点")

    if mastery == MASTERY_MASTERED:
        return f"你在「{knowledge}」上的订正展现了清晰的推理链——从原答的卡点到现在的完整推导，进步实实在在。"

    if mastery == MASTERY_PARTIAL:
        return f"你已经找到了「{knowledge}」的正确方向，比原答案前进了一大步。补全最后一步就能闭环。"

    return f"「{knowledge}」确实有难度——原答案的困惑很正常。退一步看看定义和公式，下次订正会更有把握。"


def _generate_comparison(
    question: dict,
    original_answer: str,
    correction_text: str,
    mastery: str,
) -> str:
    """生成原答案 vs 订正答案的差异分析."""
    q_type = question.get("type", "long_answer")

    if q_type in ("choice", "fill_blank"):
        standard = question.get("answer", "")
        orig_status = "正确" if original_answer.strip().upper() == standard.upper() else "错误"
        corr_status = "正确" if correction_text.strip().upper() == standard.upper() else "错误"
        return f"原答案「{original_answer.strip()}」（{orig_status}）→ 订正「{correction_text.strip()}」（{corr_status}）"

    # long_answer
    orig_len = len(original_answer)
    corr_len = len(correction_text)
    length_change = f"字数 {orig_len}→{corr_len}（{'扩展了推理' if corr_len > orig_len else '精简了'}）"

    if mastery == MASTERY_MASTERED:
        return f"原答案缺少完整推理链，订正补全了关键步骤。{length_change}，闭环成功。"
    elif mastery == MASTERY_PARTIAL:
        return f"原答案方向偏差，订正已修正方向但仍有缺漏。{length_change}，接近闭环。"
    else:
        return f"原答案与订正均存在方向性偏差。{length_change}，建议重新审题。"


# ── LLM prompt 集成（可选）────────────────────────────────────────────
def _try_llm_correction_grading(
    question: dict,
    original_answer: str,
    original_result: dict,
    correction_text: str,
) -> Optional[dict]:
    """尝试用 LLM 做订正对比批改.

    prompts.load_correction_grading() 可用时走 LLM；否则返回 None 走 mock。
    """
    try:
        from prompts import load_correction_grading

        # 检查 correction_grading prompt 是否可加载
        try:
            prompt_text = load_correction_grading()
        except (KeyError, FileNotFoundError):
            return None

        # 如果有 LLM provider 配置，尝试调用
        import os
        api_key = os.environ.get("LLM_API_KEY", "")
        if not api_key:
            return None  # 无 key 走 mock

        # 构造 LLM 调用（此处仅占位，实际由 provider 层接入）
        # TODO: 当提示词工程师的 prompt 就绪 + LLM key 配置后，这里接入 provider
        return None
    except Exception:
        return None


# ── 公共入口 ──────────────────────────────────────────────────────────
def grade_correction(
    question: dict,
    original_answer: str,
    original_result: dict,
    correction_text: str,
    student_id: str = "",
) -> dict:
    """订正对比批改 — 公共入口.

    Parameters
    ----------
    question : dict
        原题目 dict（含 type/answer/steps/knowledge）
    original_answer : str
        学生原始答案
    original_result : dict
        原批改结果（含 score/is_correct/step_results）
    correction_text : str
        学生订正答案
    student_id : str
        学生 ID（用于个性化反馈）

    Returns
    -------
    dict with keys:
        mastery_level, is_correct, comparison, feedback,
        encouragement, next_steps, graded_by, timestamp
    """
    # 1. 尝试 LLM
    llm_result = _try_llm_correction_grading(
        question, original_answer, original_result, correction_text
    )
    if llm_result is not None:
        llm_result.setdefault("graded_by", "llm")
        llm_result.setdefault("timestamp", datetime.utcnow().isoformat())
        if "emotional_feedback" not in llm_result:
            llm_result["emotional_feedback"] = _attach_correction_emotional_feedback(
                student_id, question, original_result, llm_result
            )
        return llm_result

    # 2. Mock 规则引擎
    mastery, is_correct = _determine_mastery(question, correction_text)
    feedback = _generate_feedback(mastery, question, correction_text, original_answer)
    encouragement = _generate_encouragement(mastery, question, student_id)
    comparison = _generate_comparison(question, original_answer, correction_text, mastery)

    next_steps_map = {
        MASTERY_MASTERED: "已掌握，可以进入下一个知识点。",
        MASTERY_PARTIAL: "补全缺失步骤后重新提交订正。",
        MASTERY_NOT_MASTERED: "回顾课本相关定义和例题，再尝试订正。",
    }

    result = {
        "mastery_level": mastery,
        "is_correct": is_correct,
        "comparison": comparison,
        "feedback": feedback,
        "encouragement": encouragement,
        "next_steps": next_steps_map[mastery],
        "graded_by": "mock",
        "timestamp": datetime.utcnow().isoformat(),
    }
    # Sprint 4: 订正批改后更新情感化评语
    result["emotional_feedback"] = _attach_correction_emotional_feedback(
        student_id, question, original_result, result
    )
    return result


def _attach_correction_emotional_feedback(
    student_id: str,
    question: dict,
    original_result: dict,
    correction_result: dict,
) -> str:
    """订正批改后更新情感化评语（Sprint 4）.

    输入 = 学生历史 + 本次订正表现（掌握度 + 原批改得分）。
    """
    try:
        from engine.emotional_feedback import generate_emotional_feedback

        current_performance = {
            "score": original_result.get("score", 0),
            "max_score": original_result.get("max_score", question.get("score", 0)),
            "is_correct": correction_result.get("is_correct", False),
            "error_types": original_result.get("error_types", []),
            "knowledge": question.get("knowledge", ""),
            "mastery_level": correction_result.get("mastery_level", ""),
        }
        return generate_emotional_feedback(
            student_id=student_id,
            current_performance=current_performance,
        )
    except Exception:
        return ""


def get_latest_mastery(attempts: list) -> str:
    """从 attempts 列表取最新一次的 mastery_level.

    attempts 按 attempt 序号排序，取最后一条。
    """
    if not attempts:
        return MASTERY_NOT_MASTERED
    latest = max(attempts, key=lambda a: a.get("attempt", 0))
    return latest.get("mastery_level", MASTERY_NOT_MASTERED)
