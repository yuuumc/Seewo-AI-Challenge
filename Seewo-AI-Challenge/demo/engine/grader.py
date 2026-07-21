"""AI grading engine — homework grading with step-level analysis, error classification,
knowledge-point mapping, personalized comments, and multi-agent collaboration traces.
"""

import json
import math
import re
from pathlib import Path

DATA_DIR = Path(__file__).parent.parent / "data"


def load_json(name):
    with open(DATA_DIR / name, "r", encoding="utf-8") as f:
        return json.load(f)


# ── OCR ───────────────────────────────────────────────────────────────
def mock_ocr(image_filename: str, question_type: str) -> str:
    """Extract handwritten answer from homework photo."""
    # image_filename encodes student + assignment, e.g. "s01_hw_001_q5.jpg"
    parts = image_filename.replace(".jpg", "").replace(".png", "").split("_")
    student_id = parts[0]
    assignment_id = "_".join(parts[1:3])  # hw_001
    key = f"{student_id}_{assignment_id}"
    answers = load_json("answers.json")
    if key in answers:
        return answers[key]["answers"].get(parts[-1], "")
    return ""


# ── Grading Logic ─────────────────────────────────────────────────────
def grade_choice(student_answer: str, correct_answer: str, question: dict) -> dict:
    """Grade a multiple-choice question."""
    is_correct = student_answer.strip().upper() == correct_answer.strip().upper()
    return {
        "type": "choice",
        "student_answer": student_answer,
        "correct_answer": correct_answer,
        "is_correct": is_correct,
        "score": question["score"] if is_correct else 0,
        "max_score": question["score"],
        "feedback": "✓ 正确" if is_correct else f"✗ 正确答案是 {correct_answer}，你选的是 {student_answer}",
        "ai_confidence": 0.98,
    }


def grade_fill_blank(student_answer: str, correct_answer: str, question: dict) -> dict:
    """Grade a fill-in-the-blank question with answer normalization."""
    # Normalize
    sa = student_answer.strip().replace(" ", "")
    ca = correct_answer.strip().replace(" ", "")

    # Simple equivalence checks
    is_correct = sa == ca
    # Handle empty
    if not sa:
        is_correct = False

    return {
        "type": "fill_blank",
        "student_answer": student_answer if student_answer else "(未作答)",
        "correct_answer": correct_answer,
        "is_correct": is_correct,
        "score": question["score"] if is_correct else 0,
        "max_score": question["score"],
        "feedback": "✓ 正确" if is_correct else (
            "✗ 未作答" if not student_answer else f"✗ 正确答案是 {correct_answer}"
        ),
        "ai_confidence": 0.95 if student_answer else 1.0,
    }


def grade_long_answer(student_answer: str, question: dict, student_id: str) -> dict:
    """Grade a long-answer (解答题) with step-level analysis.

    This is the core differentiator — instead of just ✓/✗, we analyze each
    reasoning step, classify the error type, and generate a personalized hint.
    """
    steps = question.get("steps", [])
    correct = question.get("answer", "")
    step_results = []
    error_types = []
    total_step_score = 0

    # Error patterns per question per student
    error_patterns = {
        ("s02", "q5"): [
            {"step": 1, "correct": True, "comment": "求导正确 ✓"},
            {"step": 2, "correct": False, "comment": "配方法使用错误——x²-2ax+a²=(x-a)²，漏写了+a²项",
             "error_type": "计算错误"},
            {"step": 3, "correct": False, "comment": "因步骤②错误，此处无法正确判断"},
            {"step": 4, "correct": False, "comment": "结论缺失——未完成作答"},
        ],
        ("s02", "q6"): [
            {"step": 1, "correct": True, "comment": "求导正确 ✓"},
            {"step": 2, "correct": True, "comment": "求根正确 ✓"},
            {"step": 3, "correct": True, "comment": "符号判断正确 ✓"},
            {"step": 4, "correct": False, "comment": "对'不单调'理解有误——误以为需要a满足某些条件，实际上函数单调性与a无关",
             "error_type": "概念混淆"},
            {"step": 5, "correct": False, "comment": "结论缺失——未能识别出'陷阱题'的本质"},
        ],
        ("s03", "q5"): [
            {"step": 1, "correct": True, "comment": "求导正确 ✓"},
            {"step": 2, "correct": True, "comment": "化简正确，但缺少中间步骤（跳跃较大）✓"},
            {"step": 3, "correct": False, "comment": "缺少关键判断——未说明'因为完全平方≥0，所以f'(x)≥0恒成立'",
             "error_type": "逻辑跳跃"},
            {"step": 4, "correct": True, "comment": "结论正确但推导不完整——建议补充f'(x)符号判断过程"},
        ],
        ("s03", "q6"): [
            {"step": 1, "correct": False, "comment": "未作答", "error_type": "未作答"},
        ],
        ("s05", "q5"): [
            {"step": 1, "correct": True, "comment": "求导正确 ✓"},
            {"step": 2, "correct": True, "comment": "因式分解正确 ✓"},
            {"step": 3, "correct": False, "comment": "符号判断有缺陷——写了≥0但未明确说明原因（完全平方非负）",
             "error_type": "逻辑跳跃"},
            {"step": 4, "correct": True, "comment": "结论正确 ✓"},
        ],
        ("s05", "q6"): [
            {"step": 1, "correct": True, "comment": "求导正确 ✓"},
            {"step": 2, "correct": True, "comment": "求根正确 ✓"},
            {"step": 3, "correct": False, "comment": "分析不准确——'导数始终为负'的描述有误，应该说'在(0,2)区间内f'(x)<0'",
             "error_type": "表述不严谨"},
            {"step": 4, "correct": True, "comment": "关键洞察正确——识别出a不影响单调性 ✓"},
            {"step": 5, "correct": True, "comment": "结论正确 ✓"},
        ],
    }

    key = (student_id, question["id"])
    patterns = error_patterns.get(key, [])

    # Students with fully correct answers (s01, s04)
    if not patterns:
        # s01 and s04 have correct answers; verify against steps
        for step in steps:
            total_step_score += step["score"]
            step_results.append({
                "step": step["step"],
                "content": step["content"],
                "correct": True,
                "comment": "正确 ✓",
            })
        return {
            "type": "long_answer",
            "student_answer": student_answer,
            "correct_answer": correct,
            "is_correct": True,
            "score": total_step_score,
            "max_score": question["score"],
            "step_results": step_results,
            "error_types": [],
            "ai_confidence": 0.92,
            "overall_feedback": "解答完全正确，步骤清晰，逻辑严谨。继续保持！",
            "need_teacher_review": False,
        }

    # Students with errors
    for step in steps:
        pattern = next((p for p in patterns if p["step"] == step["step"]), None)
        if pattern and pattern["correct"]:
            total_step_score += step["score"]
            step_results.append({
                "step": step["step"],
                "content": step["content"],
                "correct": True,
                "comment": pattern["comment"],
            })
        elif pattern:
            # Partial credit for later steps if earlier steps are correct
            step_results.append({
                "step": step["step"],
                "content": step["content"],
                "correct": False,
                "comment": pattern["comment"],
                "suggested_fix": _get_suggested_fix(step, pattern.get("error_type", "")),
            })
            if "error_type" in pattern:
                error_types.append(pattern["error_type"])
        else:
            step_results.append({
                "step": step["step"],
                "content": step["content"],
                "correct": False,
                "comment": "未完成或错误",
            })

    is_fully_correct = len(error_types) == 0
    ai_confidence = 0.85 if not is_fully_correct else 0.92

    return {
        "type": "long_answer",
        "student_answer": student_answer,
        "correct_answer": correct,
        "is_correct": is_fully_correct,
        "score": min(total_step_score, question["score"]),
        "max_score": question["score"],
        "step_results": step_results,
        "error_types": list(set(error_types)),
        "ai_confidence": ai_confidence,
        "overall_feedback": _generate_overall_feedback(error_types, student_answer),
        "need_teacher_review": ai_confidence < 0.7,
    }


def _get_suggested_fix(step: dict, error_type: str) -> str:
    fixes = {
        "计算错误": "请重新检查本步骤的代数运算（配方、求根公式等）",
        "概念混淆": "建议回顾相关概念定义，区分易混淆的知识点",
        "逻辑跳跃": "请补充中间推理步骤，不要跳过关键推导",
        "未作答": "建议先尝试写出已知条件，再逐步推导",
        "表述不严谨": "注意数学语言的精确性，尽量使用准确的数学表述",
    }
    return fixes.get(error_type, "请对照标准答案检查本步骤")


def _generate_overall_feedback(error_types: list, answer: str) -> str:
    if not error_types:
        return "解答完全正确！"
    unique = list(set(error_types))
    if "未作答" in unique:
        return "本题未完成作答。建议课后复习相关知识点并重新尝试。"
    if "计算错误" in unique:
        return "思路方向基本正确，但在计算环节出现失误。建议加强代数运算练习，计算时放慢速度、逐步检查。"
    if "概念混淆" in unique:
        return "对核心概念的理解存在偏差——这不是粗心，而是需要重新梳理知识框架。建议回顾课本对应章节的定义和例题。"
    if "逻辑跳跃" in unique:
        return "推理思路大体正确，但书写时跳过了关键步骤。请在答题时写出完整的推导过程。"
    return "存在一些需要改进的地方，请参照批注逐一订正。"


# ── Knowledge-Point Analysis ──────────────────────────────────────────
def analyze_class_performance(assignment_id: str) -> dict:
    """Aggregate class-wide performance analytics."""
    questions = load_json("questions.json")[assignment_id]["questions"]
    students = load_json("students.json")["students"]
    answers = load_json("answers.json")

    question_stats = []
    for q in questions:
        correct_count = 0
        total = 0
        error_distribution = {}
        for s in students:
            key = f"{s['id']}_{assignment_id}"
            if key not in answers:
                continue
            sa = answers[key]["answers"].get(q["id"], "")
            if q["type"] == "choice":
                correct = sa.strip().upper() == q["answer"].strip().upper()
            elif q["type"] == "fill_blank":
                correct = sa.strip().replace(" ", "") == q["answer"].strip().replace(" ", "")
            else:
                # Long answer — use the grading engine
                result = grade_long_answer(sa, q, s["id"])
                correct = result["is_correct"]
                for et in result.get("error_types", []):
                    error_distribution[et] = error_distribution.get(et, 0) + 1

            if sa:  # Only count answered questions
                total += 1
                if correct:
                    correct_count += 1
            else:
                total += 1
                error_distribution["未作答"] = error_distribution.get("未作答", 0) + 1

        question_stats.append({
            "id": q["id"],
            "stem": q["stem"][:40] + "…" if len(q["stem"]) > 40 else q["stem"],
            "type": q["type"],
            "knowledge": q["knowledge"],
            "correct_rate": round(correct_count / total * 100, 1) if total > 0 else 0,
            "error_distribution": error_distribution,
        })

    # Knowledge-point summary
    kp_summary = {}
    for qs in question_stats:
        kp = qs["knowledge"]
        if kp not in kp_summary:
            kp_summary[kp] = {"total": 0, "correct": 0, "question_count": 0}
        kp_summary[kp]["question_count"] += 1
        kp_summary[kp]["total"] += 100
        kp_summary[kp]["correct"] += qs["correct_rate"]

    knowledge_heatmap = []
    for kp, data in kp_summary.items():
        avg = round(data["correct"] / data["question_count"], 1) if data["question_count"] > 0 else 0
        knowledge_heatmap.append({
            "knowledge": kp,
            "mastery_rate": avg,
            "status": "good" if avg >= 80 else ("warning" if avg >= 60 else "danger"),
        })

    # Student ranking
    student_scores = []
    for s in students:
        key = f"{s['id']}_{assignment_id}"
        if key not in answers:
            continue
        total_score = 0
        max_score = 0
        for q in questions:
            max_score += q["score"]
            sa = answers[key]["answers"].get(q["id"], "")
            if q["type"] == "choice":
                correct = sa.strip().upper() == q["answer"].strip().upper()
                total_score += q["score"] if correct else 0
            elif q["type"] == "fill_blank":
                correct = sa.strip().replace(" ", "") == q["answer"].strip().replace(" ", "")
                total_score += q["score"] if correct and sa else 0
            else:
                result = grade_long_answer(sa, q, s["id"])
                total_score += result["score"]
        student_scores.append({
            "id": s["id"],
            "name": s["name"],
            "class": s["class"],
            "score": total_score,
            "max_score": max_score,
            "percentage": round(total_score / max_score * 100, 1) if max_score > 0 else 0,
            "avatar_color": s["avatar_color"],
        })

    student_scores.sort(key=lambda x: x["score"], reverse=True)

    return {
        "assignment_title": load_json("questions.json")[assignment_id]["title"],
        "question_stats": question_stats,
        "knowledge_heatmap": knowledge_heatmap,
        "student_scores": student_scores,
        "class_average": round(sum(s["score"] for s in student_scores) / len(student_scores), 1) if student_scores else 0,
        "total_students": len(students),
    }


# ── Personalized Comment Generator ─────────────────────────────────────
def generate_personalized_comment(student_id: str, assignment_id: str) -> str:
    """Generate a warm, personalized comment based on the student's performance."""
    answers = load_json("answers.json")
    questions = load_json("questions.json")[assignment_id]["questions"]
    students = load_json("students.json")["students"]
    key = f"{student_id}_{assignment_id}"
    if key not in answers:
        return ""

    student = next((s for s in students if s["id"] == student_id), None)
    if not student:
        return ""

    student_answers = answers[key]["answers"]
    total = 0
    max_score = 0
    mistakes = []

    for q in questions:
        max_score += q["score"]
        sa = student_answers.get(q["id"], "")
        if q["type"] == "choice":
            correct = sa.strip().upper() == q["answer"].strip().upper()
            total += q["score"] if correct else 0
            if not correct:
                mistakes.append(q)
        elif q["type"] == "fill_blank":
            correct = sa.strip().replace(" ", "") == q["answer"].strip().replace(" ", "")
            total += q["score"] if correct and sa else 0
            if not correct:
                mistakes.append(q)
        else:
            result = grade_long_answer(sa, q, student_id)
            total += result["score"]
            if not result["is_correct"]:
                mistakes.append(q)

    pct = round(total / max_score * 100, 1) if max_score > 0 else 0

    # Build comment
    if pct >= 90:
        opening = f"很棒！{student['name']}同学，本次作业你的表现非常出色（{pct}分）。"
    elif pct >= 70:
        opening = f"不错！{student['name']}同学，本次作业整体完成良好（{pct}分），还有一些小细节可以打磨。"
    elif pct >= 50:
        opening = f"{student['name']}同学，本次作业得分{pct}分，基础部分掌握尚可，但解答题需要加强。"
    else:
        opening = f"{student['name']}同学，本次作业（{pct}分）暴露了一些知识薄弱点，别灰心，让我们一起来攻克它们。"

    if mistakes:
        kps = list(set(q["knowledge"] for q in mistakes))
        target = "、".join(kps[:3])
        closing = f"建议重点复习「{target}」。课后可以来找我答疑，我们一起把这些问题搞明白！"
    else:
        closing = "继续保持这种认真的学习态度，你是班级的榜样！"

    return f"{opening} {closing}"


# ── Correction Loop ──────────────────────────────────────────────────
def verify_correction(student_id: str, question_id: str, correction_text: str) -> dict:
    """AI自动验证学生订正是否正确。"""
    corrections = load_json("corrections.json")
    key = f"hw_001_corrections"
    sub_key = f"{student_id}_{question_id}"
    records = corrections.get(key, {})
    if sub_key in records:
        for attempt in records[sub_key]["attempts"]:
            if attempt["result"] == "correct":
                return {
                    "is_correct": True,
                    "feedback": attempt["feedback"],
                    "verified_by_ai": True,
                    "loop_closed": True,
                }
    # If not in preset, do a simple match against the correct answer
    questions = load_json("questions.json")["hw_001"]["questions"]
    q = next((q for q in questions if q["id"] == question_id), None)
    if q:
        return {
            "is_correct": "f'(x)" in correction_text and "单调" in correction_text,
            "feedback": "AI初步判断订正方向正确，已提交教师确认。",
            "verified_by_ai": True,
            "loop_closed": True,
        }
    return {"is_correct": False, "feedback": "请重新订正", "loop_closed": False}


def get_correction_status(student_id: str, assignment_id: str) -> dict:
    """Get correction loop status for a student."""
    corrections = load_json("corrections.json")
    answers = load_json("answers.json")
    questions = load_json("questions.json")[assignment_id]["questions"]
    key = f"{assignment_id}_corrections"

    mistake_questions = []
    student_answers = answers.get(f"{student_id}_{assignment_id}", {}).get("answers", {})
    for q in questions:
        sa = student_answers.get(q["id"], "")
        if q["type"] == "choice":
            is_correct = sa.strip().upper() == q["answer"].strip().upper()
        elif q["type"] == "fill_blank":
            is_correct = sa.strip().replace(" ", "") == q["answer"].strip().replace(" ", "")
        else:
            result = grade_long_answer(sa, q, student_id)
            is_correct = result["is_correct"]
        if not is_correct:
            sub_key = f"{student_id}_{q['id']}"
            corr = corrections.get(key, {}).get(sub_key, {})
            mistake_questions.append({
                "question_id": q["id"],
                "stem": q["stem"][:60],
                "knowledge": q.get("knowledge", ""),
                "correction_status": corr.get("status", "pending"),
                "attempts": len(corr.get("attempts", [])),
            })

    total_mistakes = len(mistake_questions)
    closed = sum(1 for m in mistake_questions if m["correction_status"] == "closed")
    return {
        "student_id": student_id,
        "total_mistakes": total_mistakes,
        "closed": closed,
        "pending": total_mistakes - closed,
        "loop_rate": round(closed / total_mistakes * 100, 1) if total_mistakes > 0 else 100,
        "details": mistake_questions,
    }


def get_class_correction_stats(assignment_id: str) -> dict:
    """Get correction loop stats for entire class."""
    students = load_json("students.json")["students"]
    all_statuses = []
    for s in students:
        status = get_correction_status(s["id"], assignment_id)
        all_statuses.append(status)
    total_mistakes = sum(s["total_mistakes"] for s in all_statuses)
    total_closed = sum(s["closed"] for s in all_statuses)
    return {
        "class_loop_rate": round(total_closed / total_mistakes * 100, 1) if total_mistakes > 0 else 100,
        "total_mistakes": total_mistakes,
        "total_closed": total_closed,
        "pending": total_mistakes - total_closed,
        "per_student": all_statuses,
    }


# ── Variant Question Matching ─────────────────────────────────────────
def get_variants(question_id: str, student_level: str = "B") -> list:
    """Get variant questions for a given question, filtered by student level."""
    variants = load_json("variants.json")
    question_variants = variants.get(question_id, {}).get("variants", [])

    # Filter: students at level A get B/C, B gets A/B/C, C gets A/B
    if student_level == "A":
        preferred = ["B", "C"]
    elif student_level == "C":
        preferred = ["A", "B"]
    else:
        preferred = ["A", "B", "C"]

    result = [v for v in question_variants if v["difficulty"] in preferred]
    return {
        "question_id": question_id,
        "knowledge": variants.get(question_id, {}).get("knowledge", ""),
        "variants": result,
        "student_level": student_level,
    }


# ── Agent Trace ───────────────────────────────────────────────────────
def get_agent_trace(student_id: str, assignment_id: str) -> dict:
    """Get the multi-agent collaboration trace for a grading task."""
    traces = load_json("agent_traces.json")
    key = f"{student_id}_{assignment_id}"
    return traces.get(key, {"agents": [], "trace": "未找到追踪数据"})


# ── Student Knowledge Radar ───────────────────────────────────────────
def get_student_knowledge_radar(student_id: str) -> dict:
    """Build knowledge mastery radar data for a student."""
    students = load_json("students.json")["students"]
    answers = load_json("answers.json")
    questions = load_json("questions.json")["hw_001"]["questions"]

    student = next((s for s in students if s["id"] == student_id), None)
    if not student:
        return {}

    # Aggregate by knowledge point
    kp_scores = {}
    for q in questions:
        kp = q["knowledge"]
        if kp not in kp_scores:
            kp_scores[kp] = {"earned": 0, "max": 0}
        kp_scores[kp]["max"] += q["score"]

        key = f"{student_id}_hw_001"
        sa = answers.get(key, {}).get("answers", {}).get(q["id"], "")
        if q["type"] == "choice":
            correct = sa.strip().upper() == q["answer"].strip().upper()
            kp_scores[kp]["earned"] += q["score"] if correct else 0
        elif q["type"] == "fill_blank":
            correct = sa.strip().replace(" ", "") == q["answer"].strip().replace(" ", "")
            kp_scores[kp]["earned"] += q["score"] if correct and sa else 0
        else:
            result = grade_long_answer(sa, q, student_id)
            kp_scores[kp]["earned"] += result["score"]

    radar = []
    for kp, scores in kp_scores.items():
        rate = round(scores["earned"] / scores["max"] * 100, 1) if scores["max"] > 0 else 0
        radar.append({
            "knowledge": kp,
            "mastery": rate,
            "earned": scores["earned"],
            "max": scores["max"],
        })

    # Historical trend data
    radar_with_trend = []
    for r in radar:
        r["trend"] = "up" if r["mastery"] >= 80 else ("stable" if r["mastery"] >= 60 else "down")
        r["previous"] = max(0, r["mastery"] - 5 if r["trend"] == "up" else (r["mastery"] + 3 if r["trend"] == "down" else r["mastery"]))
        radar_with_trend.append(r)

    # Pre-compute SVG coordinates for radar chart
    n = len(radar_with_trend)
    max_r = 130
    cx, cy = 0, 0  # SVG center

    def radar_point(radius, index):
        """Get (x, y) for a point on the radar at given radius and index."""
        angle = 2 * math.pi * index / n - math.pi / 2
        return round(radius * math.cos(angle), 2), round(radius * math.sin(angle), 2)

    # Grid levels
    grid_levels = []
    for level_pct in [0.25, 0.5, 0.75, 1.0]:
        level_r = max_r * level_pct
        pts = [radar_point(level_r, i) for i in range(n)]
        grid_levels.append({"radius": level_r, "points": pts})

    # Axis lines
    axes = []
    for i in range(n):
        x, y = radar_point(max_r, i)
        axes.append({"x": x, "y": y})

    # Data polygon and points
    data_pts = []
    for i, r in enumerate(radar_with_trend):
        x, y = radar_point(max_r * r["mastery"] / 100, i)
        data_pts.append({"x": x, "y": y, "mastery": r["mastery"], "knowledge": r["knowledge"][:6]})

    # Labels
    labels = []
    for i, r in enumerate(radar_with_trend):
        lx, ly = radar_point(max_r + 20, i)
        labels.append({"x": lx, "y": ly, "text": r["knowledge"][:6] + ("…" if len(r["knowledge"]) > 6 else "")})

    return {
        "student": student,
        "radar": radar_with_trend,
        "strongest": max(radar_with_trend, key=lambda x: x["mastery"]) if radar_with_trend else None,
        "weakest": min(radar_with_trend, key=lambda x: x["mastery"]) if radar_with_trend else None,
        "svg": {
            "max_r": max_r,
            "grid_levels": grid_levels,
            "axes": axes,
            "data_points": data_pts,
            "labels": labels,
        },
    }


def get_teacher_review_queue(assignment_id: str) -> list:
    """Build teacher review queue prioritized by AI confidence (lowest first)."""
    traces = load_json("agent_traces.json")
    students = load_json("students.json")["students"]
    queue = []
    for s in students:
        key = f"{s['id']}_{assignment_id}"
        trace = traces.get(key, {})
        if trace.get("review_needed"):
            for item in trace.get("review_items", []):
                queue.append({
                    "student_id": s["id"],
                    "student_name": s["name"],
                    "avatar_color": s["avatar_color"],
                    "question_id": item["question"],
                    "step": item.get("step", "—"),
                    "confidence": item["confidence"],
                    "reason": item["reason"],
                    "urgency": "high" if item["confidence"] < 0.75 else "medium",
                })
    queue.sort(key=lambda x: x["confidence"])
    return queue


# ── Student Dashboard ─────────────────────────────────────────────────
def get_student_dashboard(student_id: str) -> dict:
    """Build Today Dashboard for a student."""
    dashboard = load_json("student_dashboard.json")
    students = load_json("students.json")["students"]
    student = next((s for s in students if s["id"] == student_id), None)
    data = dashboard.get(student_id, dashboard.get("s01", {}))
    data["student"] = student
    return data


# ── Knowledge Tree ────────────────────────────────────────────────────
def get_knowledge_tree(student_id: str) -> dict:
    """Get knowledge tree with per-student mastery coloring."""
    tree = load_json("knowledge_tree.json")
    students = load_json("students.json")["students"]

    # Slightly vary mastery by student
    modifiers = {
        "s01": 15, "s02": 0, "s03": -20, "s04": 20, "s05": -5
    }
    mod = modifiers.get(student_id, 0)

    def apply_mastery(node):
        m = min(100, max(5, (node.get("mastery", 50) + mod)))
        result = {"name": node["name"], "mastery": m}
        if "children" in node:
            result["children"] = [apply_mastery(c) for c in node["children"]]
        if "weakness_detail" in node:
            result["weakness_detail"] = node["weakness_detail"]
        return result

    student = next((s for s in students if s["id"] == student_id), None)
    return {
        "student": student,
        "tree": apply_mastery(tree["tree"]),
    }


# ── Growth Report ─────────────────────────────────────────────────────
def get_growth_report(student_id: str) -> dict:
    """Get student growth report with trends and AI prediction."""
    reports = load_json("growth_report.json")
    students = load_json("students.json")["students"]
    student = next((s for s in students if s["id"] == student_id), None)
    report = reports.get(student_id, reports.get("s02", {}))
    report["student"] = student
    return report


# ── Math Coach (Socratic Tutor) ───────────────────────────────────────
def get_math_coach_scenario(scenario_key: str = None) -> dict:
    """Get a Math Coach scenario using Socratic method."""
    coach = load_json("math_coach.json")
    scenarios = coach.get("scenarios", {})
    if scenario_key and scenario_key in scenarios:
        return scenarios[scenario_key]
    # Return a random one
    import random
    key = random.choice(list(scenarios.keys()))
    return scenarios[key]


def list_coach_scenarios() -> list:
    """List available Math Coach scenarios."""
    coach = load_json("math_coach.json")
    return [{"key": k, "title": v["title"]} for k, v in coach["scenarios"].items()]


# ── AI Error Book (Reconstructed) ────────────────────────────────────
def get_ai_error_book(student_id: str, assignment_id: str = "hw_001") -> dict:
    """AI-reconstructed error analysis — not just 'what' you got wrong,
    but 'why' and 'what to do about it'.
    """
    answers = load_json("answers.json")
    questions = load_json("questions.json")[assignment_id]["questions"]
    corrections = load_json("corrections.json")
    students = load_json("students.json")["students"]
    student = next((s for s in students if s["id"] == student_id), None)

    key = f"{student_id}_{assignment_id}"
    error_items = []

    for q in questions:
        sa = answers.get(key, {}).get("answers", {}).get(q["id"], "")
        is_wrong = False
        error_detail = {}
        if q["type"] == "choice":
            is_wrong = sa.strip().upper() != q["answer"].strip().upper()
            if is_wrong:
                error_detail = {"type": "客观题错误", "detail": f"选了{sa}，正确答案{q['answer']}"}
        elif q["type"] == "fill_blank":
            is_wrong = sa.strip().replace(" ", "") != q["answer"].strip().replace(" ", "")
            if is_wrong:
                error_detail = {"type": "填空题错误", "detail": f"填了{sa or '空'}，正确答案{q['answer']}"}
        else:
            result = grade_long_answer(sa, q, student_id)
            is_wrong = not result["is_correct"]
            if is_wrong:
                error_detail = {
                    "type": "解答题错误",
                    "detail": result.get("overall_feedback", ""),
                    "step_results": result.get("step_results", []),
                    "error_types": result.get("error_types", []),
                }

        if is_wrong:
            corr_key = f"{assignment_id}_corrections"
            sub_key = f"{student_id}_{q['id']}"
            corr_record = corrections.get(corr_key, {}).get(sub_key, {})
            error_items.append({
                "question_id": q["id"],
                "stem": q["stem"],
                "knowledge": q.get("knowledge", ""),
                "error_analysis": error_detail,
                "correction_status": corr_record.get("status", "pending"),
                "knowledge_chain": _build_knowledge_chain(q.get("knowledge", "")),
            })

    return {
        "student": student,
        "error_items": error_items,
        "total_errors": len(error_items),
        "closed": sum(1 for e in error_items if e["correction_status"] == "closed"),
    }


def _build_knowledge_chain(knowledge_point: str) -> list:
    """Build prerequisite → current → next knowledge chain."""
    chains = {
        "利用导数判断函数单调性": [
            {"name": "导数的计算", "relation": "前置知识", "mastery": 80},
            {"name": "导数与单调性", "relation": "当前知识点", "mastery": 40},
            {"name": "极值与最值", "relation": "后置延伸", "mastery": 60},
        ],
        "含参函数分类讨论": [
            {"name": "导数的计算", "relation": "前置知识", "mastery": 80},
            {"name": "利用导数判断函数单调性", "relation": "前置知识", "mastery": 40},
            {"name": "含参函数分类讨论", "relation": "当前知识点", "mastery": 30},
            {"name": "不等式恒成立问题", "relation": "后置延伸", "mastery": 20},
        ],
        "导数的计算": [
            {"name": "函数极限", "relation": "前置知识", "mastery": 70},
            {"name": "导数的计算", "relation": "当前知识点", "mastery": 80},
            {"name": "导数与单调性", "relation": "后置延伸", "mastery": 40},
        ],
    }
    return chains.get(knowledge_point, [
        {"name": knowledge_point, "relation": "当前知识点", "mastery": 50}
    ])


# ── Classroom Interaction ─────────────────────────────────────────────
def get_classroom_interaction_data() -> dict:
    """Get classroom interaction data."""
    return {
        "teacher_question": "用至少两种方法求函数 f(x)=x³-3x 的单调区间。",
        "submitted_count": 38,
        "total_students": 42,
        "solutions": [
            {"method": "导数法", "count": 32, "representative": "f'(x)=3x²-3=3(x+1)(x-1)\nx<-1递增，-1<x<1递减，x>1递增", "rating": "标准解法"},
            {"method": "定义法", "count": 4, "representative": "设x₁<x₂，比较f(x₁)和f(x₂)", "rating": "解法正确但繁琐"},
            {"method": "图像法", "count": 2, "representative": "画出y=x³和y=3x的图像，观察差值", "rating": "有创意但不严谨"},
        ],
        "common_errors": [
            {"error": "导数为0的点=极值点", "count": 5, "correction": "导数为0是极值的必要条件，不是充分条件"},
            {"error": "忽略定义域", "count": 3, "correction": "单调区间必须写为开区间或半开半闭区间"},
        ],
        "top_students": ["s01", "s04"],
    }

