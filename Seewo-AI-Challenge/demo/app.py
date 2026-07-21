"""希沃智教π — AI智能作业批改系统

Usage:
  pip install flask
  python app.py
  Open http://localhost:5000
"""

from flask import Flask, render_template, request, jsonify
from engine.grader import (
    grade_choice,
    grade_fill_blank,
    grade_long_answer,
    analyze_class_performance,
    generate_personalized_comment,
    load_json,
    verify_correction,
    get_correction_status,
    get_class_correction_stats,
    get_variants,
    get_agent_trace,
    get_student_knowledge_radar,
    get_teacher_review_queue,
    get_student_dashboard,
    get_knowledge_tree,
    get_growth_report,
    get_math_coach_scenario,
    list_coach_scenarios,
    get_ai_error_book,
    get_classroom_interaction_data,
)

app = Flask(__name__)


@app.route("/")
def index():
    """Landing page — role selection."""
    return render_template("index.html")


# ── Teacher routes ────────────────────────────────────────────────────
@app.route("/teacher")
def teacher_dashboard():
    """Teacher main dashboard — assignment overview."""
    students = load_json("students.json")["students"]
    questions = load_json("questions.json")["hw_001"]
    return render_template(
        "teacher_dashboard.html",
        students=students,
        assignment=questions,
    )


@app.route("/teacher/grade/<assignment_id>")
def teacher_grade(assignment_id):
    """Grading page — show AI grading results for all students."""
    students = load_json("students.json")["students"]
    questions = load_json("questions.json")[assignment_id]["questions"]
    answers = load_json("answers.json")

    results = []
    for s in students:
        key = f"{s['id']}_{assignment_id}"
        if key not in answers:
            continue
        student_result = {
            "student": s,
            "questions": [],
            "total_score": 0,
            "max_score": 0,
        }
        for q in questions:
            student_answer = answers[key]["answers"].get(q["id"], "")
            if q["type"] == "choice":
                r = grade_choice(student_answer, q["answer"], q)
            elif q["type"] == "fill_blank":
                r = grade_fill_blank(student_answer, q["answer"], q)
            else:
                r = grade_long_answer(student_answer, q, s["id"])
            r["question_stem"] = q["stem"]
            r["question_type"] = q["type"]
            r["question_id"] = q["id"]
            r["knowledge"] = q.get("knowledge", "")
            student_result["questions"].append(r)
            student_result["total_score"] += r["score"]
            student_result["max_score"] += r["max_score"]
        student_result["percentage"] = (
            round(student_result["total_score"] / student_result["max_score"] * 100, 1)
            if student_result["max_score"] > 0
            else 0
        )
        student_result["comment"] = generate_personalized_comment(s["id"], assignment_id)
        results.append(student_result)

    results.sort(key=lambda x: x["total_score"], reverse=True)
    return render_template(
        "teacher_grade.html",
        results=results,
        assignment=load_json("questions.json")[assignment_id],
    )


@app.route("/teacher/analytics/<assignment_id>")
def teacher_analytics(assignment_id):
    """Analytics dashboard — class performance overview."""
    data = analyze_class_performance(assignment_id)
    return render_template("teacher_analytics.html", data=data)


# ── Student routes ────────────────────────────────────────────────────
@app.route("/student")
def student_list():
    """Student list page."""
    students = load_json("students.json")["students"]
    return render_template("student_list.html", students=students)


@app.route("/student/<student_id>")
def student_view(student_id):
    """Student result page — detailed feedback for one student."""
    students = load_json("students.json")["students"]
    student = next((s for s in students if s["id"] == student_id), None)
    if not student:
        return "Student not found", 404

    answers = load_json("answers.json")
    assignment = load_json("questions.json")["hw_001"]
    key = f"{student_id}_hw_001"

    questions_result = []
    total_score = 0
    max_score_total = 0

    for q in assignment["questions"]:
        sa = answers.get(key, {}).get("answers", {}).get(q["id"], "")
        if q["type"] == "choice":
            r = grade_choice(sa, q["answer"], q)
        elif q["type"] == "fill_blank":
            r = grade_fill_blank(sa, q["answer"], q)
        else:
            r = grade_long_answer(sa, q, student_id)
        r["question_stem"] = q["stem"]
        r["question_type"] = q["type"]
        r["question_id"] = q["id"]
        r["knowledge"] = q.get("knowledge", "")
        r["max_score"] = q["score"]
        questions_result.append(r)
        total_score += r["score"]
        max_score_total += q["score"]

    percentage = round(total_score / max_score_total * 100, 1) if max_score_total > 0 else 0
    comment = generate_personalized_comment(student_id, "hw_001")

    return render_template(
        "student_view.html",
        student=student,
        questions=questions_result,
        total_score=total_score,
        max_score=max_score_total,
        percentage=percentage,
        comment=comment,
        assignment=assignment,
    )


# ── 订正闭环 ──────────────────────────────────────────────────────────
@app.route("/student/<student_id>/correction")
def student_correction(student_id):
    """Student correction page — submit corrections for mistakes."""
    students = load_json("students.json")["students"]
    student = next((s for s in students if s["id"] == student_id), None)
    if not student:
        return "Student not found", 404

    # Find wrong questions
    answers = load_json("answers.json")
    questions = load_json("questions.json")["hw_001"]["questions"]
    key = f"{student_id}_hw_001"
    wrong_qs = []
    for q in questions:
        sa = answers.get(key, {}).get("answers", {}).get(q["id"], "")
        if q["type"] == "choice":
            correct = sa.strip().upper() == q["answer"].strip().upper()
        elif q["type"] == "fill_blank":
            correct = sa.strip().replace(" ", "") == q["answer"].strip().replace(" ", "")
        else:
            result = grade_long_answer(sa, q, student_id)
            correct = result["is_correct"]
        if not correct:
            wrong_qs.append({
                "id": q["id"],
                "stem": q["stem"],
                "type": q["type"],
                "knowledge": q.get("knowledge", ""),
                "your_answer": sa,
                "correct_answer": q.get("answer", ""),
            })

    # Get correction statuses and variants
    corr_status = get_correction_status(student_id, "hw_001")
    variants_data = {}
    for wq in wrong_qs:
        variants_data[wq["id"]] = get_variants(wq["id"], student.get("level", "B"))

    return render_template(
        "student_correction.html",
        student=student,
        wrong_questions=wrong_qs,
        corr_status=corr_status,
        variants=variants_data,
    )


@app.route("/student/<student_id>/correction/submit", methods=["POST"])
def submit_correction(student_id):
    """Submit a correction answer — AI verifies and returns loop-close status."""
    students = load_json("students.json")["students"]
    student = next((s for s in students if s["id"] == student_id), None)
    if not student:
        return jsonify({"ok": False, "feedback": "学生不存在"}), 404

    body = request.get_json(silent=True) or {}
    question_id = body.get("question_id", "")
    correction_text = body.get("correction_text", "").strip()

    if not correction_text:
        return jsonify({"ok": False, "feedback": "请输入订正内容"})

    questions = load_json("questions.json")["hw_001"]["questions"]
    q = next((q for q in questions if q["id"] == question_id), None)
    if not q:
        return jsonify({"ok": False, "feedback": "题目不存在"}), 404

    # Objective questions: direct answer comparison
    if q["type"] == "choice":
        is_correct = correction_text.strip().upper() == q["answer"].strip().upper()
        feedback = "订正正确！已自动闭环。" if is_correct else f"答案不正确，正确答案是 {q['answer']}。"
    elif q["type"] == "fill_blank":
        norm = lambda s: s.strip().replace(" ", "")
        is_correct = norm(correction_text) == norm(q["answer"])
        feedback = "订正正确！已自动闭环。" if is_correct else f"答案不正确，正确答案是 {q['answer']}。"
    else:
        # Long answer: delegate to AI verification
        result = verify_correction(student_id, question_id, correction_text)
        is_correct = result.get("is_correct", False)
        feedback = result.get("feedback", "请重新订正")

    return jsonify({
        "ok": True,
        "question_id": question_id,
        "is_correct": is_correct,
        "feedback": feedback,
        "loop_closed": is_correct,
    })


# ── AI 复核队列 ───────────────────────────────────────────────────────
@app.route("/teacher/review/<assignment_id>")
def teacher_review_queue(assignment_id):
    """Teacher review queue — low-confidence items sorted by urgency."""
    queue = get_teacher_review_queue(assignment_id)
    return render_template("teacher_review.html", queue=queue, assignment_id=assignment_id)


# ── 学生知识雷达 ──────────────────────────────────────────────────────
@app.route("/student/<student_id>/radar")
def student_radar(student_id):
    """Student knowledge radar chart page."""
    radar_data = get_student_knowledge_radar(student_id)
    if not radar_data:
        return "Student not found", 404
    return render_template("student_radar.html", data=radar_data)


@app.route("/student/<student_id>/dashboard")
def student_dashboard(student_id):
    """Student Today Dashboard — tasks, AI suggestions, reminders."""
    data = get_student_dashboard(student_id)
    if not data or not data.get("student"):
        return "Student not found", 404
    return render_template("student_dashboard.html", data=data)


@app.route("/student/<student_id>/error-book")
def student_error_book(student_id):
    """AI Error Book — reconstructed error analysis with knowledge chains."""
    data = get_ai_error_book(student_id)
    if not data.get("student"):
        return "Student not found", 404
    return render_template("student_error_book.html", data=data)


@app.route("/student/<student_id>/knowledge-tree")
def student_knowledge_tree(student_id):
    """Knowledge Tree — mastery-colored tree visualization."""
    data = get_knowledge_tree(student_id)
    if not data.get("student"):
        return "Student not found", 404
    return render_template("student_knowledge_tree.html", data=data)


@app.route("/student/<student_id>/coach")
def student_coach(student_id):
    """Math Coach — Socratic tutoring (don't give answers directly)."""
    scenario_key = request.args.get("scenario")
    scenario = get_math_coach_scenario(scenario_key)
    scenarios = list_coach_scenarios()
    students = load_json("students.json")["students"]
    student = next((s for s in students if s["id"] == student_id), None)
    if not student:
        return "Student not found", 404
    return render_template("student_coach.html",
                         student=student, scenario=scenario, scenarios=scenarios)


@app.route("/student/<student_id>/growth")
def student_growth(student_id):
    """Growth Report — trajectory, strengths, AI prediction."""
    data = get_growth_report(student_id)
    if not data.get("student"):
        return "Student not found", 404
    return render_template("student_growth.html", data=data)


# ── 订正闭环看板 ───────────────────────────────────────────────────────
@app.route("/teacher/correction-loop/<assignment_id>")
def teacher_correction_loop(assignment_id):
    """Teacher view of class-wide correction loop status."""
    stats = get_class_correction_stats(assignment_id)
    students = load_json("students.json")["students"]
    return render_template("teacher_correction.html", stats=stats, students=students)


# ── Agent 追踪可视化 ─────────────────────────────────────────────────
@app.route("/teacher/agent-trace/<assignment_id>")
def teacher_agent_trace(assignment_id):
    """Visualize multi-agent collaboration traces."""
    students = load_json("students.json")["students"]
    traces = []
    for s in students:
        trace = get_agent_trace(s["id"], assignment_id)
        trace["student"] = s
        traces.append(trace)
    return render_template("teacher_agent_trace.html", traces=traces)


@app.route("/classroom")
def classroom_interaction():
    """Classroom interaction demo — teacher-student real-time interaction."""
    data = get_classroom_interaction_data()
    return render_template("classroom.html", data=data)


# ── API routes (JSON) ──────────────────────────────────────────────────
@app.route("/api/grade/<student_id>/<assignment_id>")
def api_grade_student(student_id, assignment_id):
    """API: grade a single student's homework, return JSON."""
    answers = load_json("answers.json")
    questions = load_json("questions.json")[assignment_id]["questions"]
    key = f"{student_id}_{assignment_id}"

    results = []
    total = 0
    max_s = 0
    for q in questions:
        sa = answers.get(key, {}).get("answers", {}).get(q["id"], "")
        if q["type"] == "choice":
            r = grade_choice(sa, q["answer"], q)
        elif q["type"] == "fill_blank":
            r = grade_fill_blank(sa, q["answer"], q)
        else:
            r = grade_long_answer(sa, q, student_id)
        r["question_id"] = q["id"]
        r["knowledge"] = q.get("knowledge", "")
        results.append(r)
        total += r["score"]
        max_s += q["score"]

    return jsonify({
        "student_id": student_id,
        "total_score": total,
        "max_score": max_s,
        "percentage": round(total / max_s * 100, 1) if max_s > 0 else 0,
        "questions": results,
        "comment": generate_personalized_comment(student_id, assignment_id),
        "agent_trace": get_agent_trace(student_id, assignment_id),
    })


@app.route("/api/analytics/<assignment_id>")
def api_analytics(assignment_id):
    """API: class analytics as JSON."""
    return jsonify(analyze_class_performance(assignment_id))


@app.route("/api/correction-loop/<assignment_id>")
def api_correction_loop(assignment_id):
    """API: class correction loop stats as JSON."""
    return jsonify(get_class_correction_stats(assignment_id))


@app.route("/api/review-queue/<assignment_id>")
def api_review_queue(assignment_id):
    """API: teacher review queue as JSON."""
    return jsonify(get_teacher_review_queue(assignment_id))


@app.route("/api/radar/<student_id>")
def api_radar(student_id):
    """API: student knowledge radar as JSON."""
    return jsonify(get_student_knowledge_radar(student_id))


@app.route("/api/variants/<question_id>/<student_level>")
def api_variants(question_id, student_level):
    """API: variant questions as JSON."""
    return jsonify(get_variants(question_id, student_level))


if __name__ == "__main__":
    print("=" * 60)
    print("  希沃智教π — AI智能作业批改系统 Demo")
    print("  打开浏览器访问: http://localhost:5000")
    print("=" * 60)
    app.run(debug=True, host="0.0.0.0", port=5000)
