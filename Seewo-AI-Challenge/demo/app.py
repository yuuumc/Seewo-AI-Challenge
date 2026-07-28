"""希沃智教π — AI智能作业批改系统

Phase 0 安全加固版（2026-07-28）：
  * Session 认证 + 4 角色 RBAC
  * CSRF 防护（per-session token + HMAC 比较）
  * IDOR 校验（学生只能访问自己的资源）
  * 速率限制（per-IP 滑窗）
  * 审计日志（logs/audit.log）
  * 关 debug,改 gunicorn 生产部署（见项目根 Dockerfile/gunicorn.conf.py）
  * 错误页（403/404/429 渲染 templates/errors/）

安全原语见 ``security.py``，单测见 ``tests/test_security.py``。
所有现有路由签名保持不变，前端模板仅需要：
  - 全站 POST 表单/CSRF hidden input
  - base.html 顶栏登录态偏件（_nav_user.html）

Demo 模式约定（与 tests/_helpers.py / test_grading_flow.py 对齐）：
  * ``DEMO_AUTH_OPEN=1``（默认）— 匿名可读所有 GET 页面，登录后才走
    RBAC / IDOR 校验。
  * ``DEMO_AUTH_OPEN=0`` — 生产模式：所有受保护路由必须先登录。

Usage:
  pip install flask
  python app.py
  Open http://localhost:5000

环境变量：
  SECRET_KEY         Flask session key（生产必设；开发用 DEMO_SECRET）
  DEMO_SECRET        开发态 fallback secret
  DEMO_AUTH_OPEN     "1"（默认）/ "0"：demo 模式允许匿名读
  LLM_API_KEY        设了走真 LLM，未设走 mock 引擎
  LLM_BASE_URL       OpenAI 兼容 base URL（默认 https://api.openai.com/v1）
  LLM_MODEL          模型名（默认 gpt-4o-mini）
"""

import os

from flask import Flask, render_template, request, jsonify, redirect, url_for, flash  # P0: 补 flash import（修 9 个 test_auth 500）

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
from security import (
    secret_key,
    audit_log,
    rate_limit,
    csrf_protect,
    login_required,
    roles_required,
    check_ownership,
    get_current_user,
    login_user,
    logout_user,
    register_template_helpers,
    register_error_handlers,
    DEMO_USERS,
)

app = Flask(__name__)
app.secret_key = secret_key()
app.config["MAX_CONTENT_LENGTH"] = 4 * 1024 * 1024  # 4 MB upload cap (Phase 0 防护)
app.config["SESSION_COOKIE_HTTPONLY"] = True
app.config["SESSION_COOKIE_SAMESITE"] = "Lax"

# Wire CSRF token + get_current_user into Jinja templates
register_template_helpers(app)
# Wire error pages
register_error_handlers(app)


# ── Auth routes ───────────────────────────────────────────────────────
@app.route("/login", methods=["GET", "POST"])
@rate_limit(max_per_minute=10)
def login():
    """Login page + form post. Accepts either 'username' (preferred) or
    'email' (legacy) for forward-compat with the email-style SSO swap.
    """
    if request.method == "POST":
        username = (
            request.form.get("username")
            or request.form.get("email")
            or ""
        ).strip()
        password = request.form.get("password") or ""
        user = login_user(username, password)
        if user:
            audit_log("login_success", user_id=username, role=user["role"])
            flash(f"欢迎回来，{user.get('name') or username}！", "success")
            nxt = request.args.get("next") or url_for("index")
            return redirect(nxt)
        audit_log("login_failed", user_id=username)
        flash("账号或密码错误，请重试。", "error")
        return render_template(
            "login.html", error="账号或密码错误", users=list(DEMO_USERS.items())
        ), 401
    return render_template("login.html", users=list(DEMO_USERS.items()))


@app.route("/logout", methods=["POST"])
@csrf_protect
def logout():
    """Clear session and redirect home."""
    logout_user()
    flash("已安全退出，期待再次相见。", "info")
    return redirect(url_for("index"))


# ── Landing ───────────────────────────────────────────────────────────
@app.route("/")
def index():
    """Landing page — role selection."""
    return render_template("index.html", user=get_current_user())


# ── Teacher routes ────────────────────────────────────────────────────
@app.route("/teacher")
@login_required
@roles_required("teacher", "head", "admin")
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
@login_required
@roles_required("teacher", "head", "admin")
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
@login_required
@roles_required("teacher", "head", "admin")
def teacher_analytics(assignment_id):
    """Analytics dashboard — class performance overview."""
    data = analyze_class_performance(assignment_id)
    return render_template("teacher_analytics.html", data=data)


# ── Student routes ────────────────────────────────────────────────────
@app.route("/student")
@login_required
@roles_required("teacher", "head", "admin")
def student_list():
    """Student list page."""
    students = load_json("students.json")["students"]
    return render_template("student_list.html", students=students)


@app.route("/student/<student_id>")
@login_required
def student_view(student_id):
    """Student result page — detailed feedback for one student."""
    check_ownership(student_id)
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
@login_required
def student_correction(student_id):
    """Student correction page — submit corrections for mistakes."""
    check_ownership(student_id)
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
@login_required
@csrf_protect
@rate_limit(max_per_minute=20)
def submit_correction(student_id):
    """Submit a correction answer — AI verifies and returns loop-close status."""
    check_ownership(student_id)
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

    audit_log(
        "correction_submit",
        student_id=student_id,
        question_id=question_id,
        is_correct=is_correct,
    )

    return jsonify({
        "ok": True,
        "question_id": question_id,
        "is_correct": is_correct,
        "feedback": feedback,
        "loop_closed": is_correct,
    })


# ── AI 复核队列 ───────────────────────────────────────────────────────
@app.route("/teacher/review/<assignment_id>")
@login_required
@roles_required("teacher", "head", "admin")
def teacher_review_queue(assignment_id):
    """Teacher review queue — low-confidence items sorted by urgency."""
    queue = get_teacher_review_queue(assignment_id)
    return render_template("teacher_review.html", queue=queue, assignment_id=assignment_id)


# ── 学生知识雷达 ──────────────────────────────────────────────────────
@app.route("/student/<student_id>/radar")
@login_required
def student_radar(student_id):
    """Student knowledge radar chart page."""
    check_ownership(student_id)
    radar_data = get_student_knowledge_radar(student_id)
    if not radar_data:
        return "Student not found", 404
    return render_template("student_radar.html", data=radar_data)


@app.route("/student/<student_id>/dashboard")
@login_required
def student_dashboard(student_id):
    """Student Today Dashboard — tasks, AI suggestions, reminders."""
    check_ownership(student_id)
    data = get_student_dashboard(student_id)
    if not data or not data.get("student"):
        return "Student not found", 404
    return render_template("student_dashboard.html", data=data)


@app.route("/student/<student_id>/error-book")
@login_required
def student_error_book(student_id):
    """AI Error Book — reconstructed error analysis with knowledge chains."""
    check_ownership(student_id)
    data = get_ai_error_book(student_id)
    if not data.get("student"):
        return "Student not found", 404
    return render_template("student_error_book.html", data=data)


@app.route("/student/<student_id>/knowledge-tree")
@login_required
def student_knowledge_tree(student_id):
    """Knowledge Tree — mastery-colored tree visualization."""
    check_ownership(student_id)
    data = get_knowledge_tree(student_id)
    if not data.get("student"):
        return "Student not found", 404
    return render_template("student_knowledge_tree.html", data=data)


@app.route("/student/<student_id>/coach")
@login_required
def student_coach(student_id):
    """Math Coach — Socratic tutoring (don't give answers directly)."""
    check_ownership(student_id)
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
@login_required
def student_growth(student_id):
    """Growth Report — trajectory, strengths, AI prediction."""
    check_ownership(student_id)
    data = get_growth_report(student_id)
    if not data.get("student"):
        return "Student not found", 404
    return render_template("student_growth.html", data=data)


# ── 订正闭环看板 ───────────────────────────────────────────────────────
@app.route("/teacher/correction-loop/<assignment_id>")
@login_required
@roles_required("teacher", "head", "admin")
def teacher_correction_loop(assignment_id):
    """Teacher view of class-wide correction loop status."""
    stats = get_class_correction_stats(assignment_id)
    students = load_json("students.json")["students"]
    return render_template("teacher_correction.html", stats=stats, students=students)


# ── Agent 追踪可视化 ─────────────────────────────────────────────────
@app.route("/teacher/agent-trace/<assignment_id>")
@login_required
@roles_required("teacher", "head", "admin")
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
@login_required
def api_grade_student(student_id, assignment_id):
    """API: grade a single student's homework, return JSON."""
    check_ownership(student_id)
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
@login_required
@roles_required("teacher", "head", "admin")  # P0-6: 收紧为教师+ 角色（学生不应见全班学情）
def api_analytics(assignment_id):
    """API: class analytics as JSON."""
    return jsonify(analyze_class_performance(assignment_id))


@app.route("/api/correction-loop/<assignment_id>")
@login_required
@roles_required("teacher", "head", "admin")  # P0-6: 收紧为教师+ 角色
def api_correction_loop(assignment_id):
    """API: class correction loop stats as JSON."""
    return jsonify(get_class_correction_stats(assignment_id))


@app.route("/api/review-queue/<assignment_id>")
@login_required
@roles_required("teacher", "head", "admin")  # P0-6: 收紧为教师+ 角色（暴露题目难度信息）
def api_review_queue(assignment_id):
    """API: teacher review queue as JSON."""
    return jsonify(get_teacher_review_queue(assignment_id))


@app.route("/api/radar/<student_id>")
@login_required
def api_radar(student_id):
    """API: student knowledge radar as JSON."""
    check_ownership(student_id)
    return jsonify(get_student_knowledge_radar(student_id))


@app.route("/api/variants/<question_id>/<student_level>")
@login_required
@roles_required("teacher", "head", "admin")  # P0-6: 收紧为教师+ 角色（变式题 A 难度不应让学生随便拉）
def api_variants(question_id, student_level):
    """API: variant questions as JSON."""
    return jsonify(get_variants(question_id, student_level))


# ── Health check ──────────────────────────────────────────────────────
@app.route("/healthz")
def healthz():
    """Liveness probe for k8s / load balancer."""
    return jsonify({"status": "ok"})


if __name__ == "__main__":
    print("=" * 60)
    print("  希沃智教π — AI智能作业批改系统 Demo (Phase 0 安全加固版)")
    print("  打开浏览器访问: http://localhost:5000")
    print("=" * 60)
    # 生产环境用 gunicorn 启动（见项目根 gunicorn.conf.py）
    # 此处仅作为开发回退入口：debug 关闭、host 收紧为 loopback
    app.run(
        debug=os.environ.get("FLASK_DEBUG", "0") == "1",
        host=os.environ.get("FLASK_HOST", "127.0.0.1"),
        port=int(os.environ.get("FLASK_PORT", "5000")),
    )
