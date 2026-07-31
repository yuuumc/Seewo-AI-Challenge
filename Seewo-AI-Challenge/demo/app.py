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
  * ``DEMO_AUTH_OPEN=0``（默认，生产安全）— 所有受保护路由必须先登录，
    CSRF / 限流严格启用。
  * ``DEMO_AUTH_OPEN=1`` — 演示/本地开发：匿名可读所有 GET 页面，登录后
    才走 RBAC / IDOR 校验（需显式开启）。

Usage:
  pip install flask
  python app.py
  Open http://localhost:5000

环境变量：
  SECRET_KEY         Flask session key（生产必设；开发用 DEMO_SECRET）
  DEMO_SECRET        开发态 fallback secret
  DEMO_AUTH_OPEN     "0"（默认，生产安全）/ "1"（演示模式，需显式开启）
  LLM_API_KEY        设了走真 LLM，未设走 mock 引擎
  LLM_BASE_URL       OpenAI 兼容 base URL（默认 https://api.openai.com/v1）
  LLM_MODEL          模型名（默认 gpt-4o-mini）
"""

import os
import sys
import time

from flask import Flask, render_template, request, jsonify, redirect, url_for, flash, session, g  # P0: 补 flash import（修 9 个 test_auth 500）

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
    _demo_auth_open,
    register_error_handlers,
    DEMO_USERS,
    has_consent,
    require_consent,
    data_scope,
)

# V2.0 Sprint 5: 组织树 CRUD API + 批量导入 + consent 管理
from org_api import bp as org_api_bp
from batch_import import bp as batch_import_bp
from consent_manager import build_consent_context, get_consent_status, create_consent_record, get_latest_consent_record
from data_masking import mask_student_list, mask_name, mask_phone, mask_student_no

app = Flask(__name__)
app.secret_key = secret_key()
app.config["MAX_CONTENT_LENGTH"] = 4 * 1024 * 1024  # 4 MB upload cap (Phase 0 防护)
app.config["SESSION_COOKIE_HTTPONLY"] = True
app.config["SESSION_COOKIE_SAMESITE"] = "Lax"

# Wire CSRF token + get_current_user into Jinja templates
register_template_helpers(app)
# Wire error pages
register_error_handlers(app)

# V2.0 Sprint 5: Register blueprints
app.register_blueprint(org_api_bp)
app.register_blueprint(batch_import_bp)

# V2.0 Sprint 6: Observability middleware (supersedes Sprint 5 tenant-only middleware)
from tenant_middleware import TenantMiddleware  # noqa: E402
from request_logging import RequestLoggingMiddleware  # noqa: E402
from tracing import init_tracing  # noqa: E402
from alerting import get_alert_manager  # noqa: E402
from metrics import record_http_request, render_metrics  # noqa: E402

TenantMiddleware(app)
RequestLoggingMiddleware(app)
init_tracing(app)

# V2.0 Sprint 6: After-request hook for metrics + alerting
@app.after_request
def _sprint6_after_request(response):
    """Record HTTP metrics and check alert thresholds."""
    try:
        from flask import g
        latency_ms = round((time.time() - g.request_start_time) * 1000.0, 2)
        record_http_request(request.method, request.endpoint or "unknown",
                            response.status_code, latency_ms)
        get_alert_manager().record_http_status(response.status_code)
        # Check alert rules every 10th request (lightweight)
        if hasattr(g, "request_id") and hash(g.request_id) % 10 == 0:
            get_alert_manager().check_all()
    except Exception:
        pass  # Metrics must not break UX
    return response



# ── Auth routes ───────────────────────────────────────────────────────

# V2.0 Sprint 6: Admin dashboard routes
@app.route("/admin/usage")
@roles_required("school_admin", "super_admin")
def admin_usage():
    return render_template("admin/usage.html")

@app.route("/admin/health")
@roles_required("school_admin", "super_admin")
def admin_health():
    return render_template("admin/health.html")

@app.route("/login", methods=["GET", "POST"])
@csrf_protect
@rate_limit(max_per_minute=10)
def login():
    """Login page + form post. Accepts either 'username' (preferred) or
    'email' (legacy) for forward-compat with the email-style SSO swap.

    P0-3 安全 Blocker: 登录端点也加 CSRF 防护
    - 防「登录 CSRF」: 攻击者诱骗已退出用户 POST 登录成攻击者账号,
      一旦用户后续填了真实信息(地址/支付/敏感数据)就泄露给攻击者
    - 登录页 GET 时 get_csrf_token() 已把 token 写 session, login.html
      渲染为 hidden input, POST 时 csrf_protect 校验
    - Demo 模式(DEMO_AUTH_OPEN=1)装饰器 bypass, 不影响 demo 跑通
    - MIG-02: 默认 DEMO_AUTH_OPEN=0（生产安全），demo 需显式开启
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
    """Teacher main dashboard — multi-homework overview (V1.0 Sprint 2)."""
    students = load_json("students.json")["students"]
    homeworks = _list_all_homeworks()
    # Default assignment for backward compat (first or hw_001)
    default_hw = homeworks[0] if homeworks else None
    return render_template(
        "teacher_dashboard.html",
        students=students,
        assignment=default_hw,
        homeworks=homeworks,
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


# ── V1.5 Sprint 3: 订正闭环 · 学生端页面 ─────────────────────────────
def _get_student_id_from_session() -> str | None:
    """Extract student_id from the current session user."""
    user = get_current_user()
    if not user:
        return None
    # Student usernames are like "s01", "s02" etc. — same as student_id
    if user.get("role") == "student":
        return user.get("user_id")
    return None


def _build_correction_context(submission_id: str) -> dict | None:
    """Build context for the correction submit page from a submission_id.

    submission_id format: "<student_id>_<hw_key>" e.g. "s01_hw_001"
    """
    answers = load_json("answers.json")
    sub = answers.get(submission_id)
    if not sub:
        return None

    student_id = sub.get("student_id", "")
    hw_key = sub.get("assignment_id", "hw_001")
    questions_all = load_json("questions.json")
    hw = questions_all.get(hw_key, {})
    questions = hw.get("questions", [])

    # Get corrections for this student
    corrections = load_json("corrections.json")
    corr_key = f"{hw_key}_corrections"

    # Build per-question info
    items = []
    for q in questions:
        qid = q["id"]
        student_answer = sub.get("answers", {}).get(qid, "")
        # Determine if the answer is correct
        if q["type"] == "choice":
            is_correct = student_answer.strip().upper() == q.get("answer", "").strip().upper()
        elif q["type"] == "fill_blank":
            is_correct = student_answer.strip().replace(" ", "") == q.get("answer", "").strip().replace(" ", "")
        else:
            result = grade_long_answer(student_answer, q, student_id)
            is_correct = result.get("is_correct", False)

        # Check correction status
        sub_key = f"{student_id}_{qid}"
        corr = corrections.get(corr_key, {}).get(sub_key, {})
        corr_status = corr.get("status", "pending")
        attempts = corr.get("attempts", [])

        items.append({
            "id": qid,
            "type": q["type"],
            "subject_type": q.get("subject_type", "math_calculation"),
            "stem": q.get("stem", ""),
            "options": q.get("options", []),
            "answer": q.get("answer", ""),
            "score": q.get("score", 0),
            "knowledge": q.get("knowledge", ""),
            "student_answer": student_answer,
            "is_correct": is_correct,
            "correction_status": corr_status,
            "correction_attempts": attempts,
        })

    students = load_json("students.json")["students"]
    student = next((s for s in students if s["id"] == student_id), None)

    return {
        "submission_id": submission_id,
        "student": student,
        "hw_key": hw_key,
        "hw_title": hw.get("title", hw_key),
        "items": items,
        "wrong_count": sum(1 for i in items if not i["is_correct"]),
        "corrected_count": sum(1 for i in items if i["correction_status"] == "closed"),
    }


@app.route("/student/correction/<submission_id>")
@login_required
def student_correction_submit_page(submission_id):
    """V1.5 Sprint 3: Correction submit page for a specific submission.

    Shows original questions, student answers, grading results, and
    provides a correction input area per question type.
    """
    ctx = _build_correction_context(submission_id)
    if not ctx:
        return "Submission not found", 404

    # Ownership check: student can only view their own submissions
    sid = _get_student_id_from_session()
    if sid and ctx["student"] and ctx["student"]["id"] != sid:
        return "Forbidden", 403

    return render_template("student_correction_submit.html", **ctx)


@app.route("/student/corrections")
@login_required
def student_corrections_list():
    """V1.5 Sprint 3: Correction history page for the current student."""
    sid = _get_student_id_from_session()
    if not sid:
        # Non-student users: redirect to their dashboard or show empty
        return render_template("student_corrections.html", corrections=[], student=None, pending_count=0)

    # Build correction history from corrections.json
    corrections_data = load_json("corrections.json")
    answers = load_json("answers.json")
    questions_all = load_json("questions.json")
    students = load_json("students.json")["students"]
    student = next((s for s in students if s["id"] == sid), None)

    history = []
    for hw_key, hw_data in questions_all.items():
        corr_key = f"{hw_key}_corrections"
        hw_corrections = corrections_data.get(corr_key, {})
        questions = hw_data.get("questions", [])

        for q in questions:
            qid = q["id"]
            sub_key = f"{sid}_{qid}"
            corr = hw_corrections.get(sub_key)
            if not corr:
                continue

            # Get original answer
            submission_key = f"{sid}_{hw_key}"
            orig_answer = answers.get(submission_key, {}).get("answers", {}).get(qid, "")

            attempts = corr.get("attempts", [])
            latest_attempt = attempts[-1] if attempts else {}

            history.append({
                "hw_key": hw_key,
                "hw_title": hw_data.get("title", hw_key),
                "question_id": qid,
                "question_stem": q.get("stem", "")[:80],
                "question_type": q.get("type", ""),
                "knowledge": q.get("knowledge", ""),
                "original_answer": orig_answer[:100],
                "correction_text": latest_attempt.get("content", "")[:100],
                "mastery_level": "mastered" if corr.get("status") == "closed" else "partial",
                "status": corr.get("status", "pending"),
                "attempts_count": len(attempts),
                "feedback": latest_attempt.get("feedback", ""),
            })

    # Sort by most recent first (using attempts order as proxy)
    history.reverse()

    # Count pending corrections (wrong answers without closed corrections)
    pending_count = 0
    for hw_key, hw_data in questions_all.items():
        submission_key = f"{sid}_{hw_key}"
        sub = answers.get(submission_key)
        if not sub:
            continue
        corr_key = f"{hw_key}_corrections"
        hw_corrections = corrections_data.get(corr_key, {})
        for q in hw_data.get("questions", []):
            qid = q["id"]
            sa = sub.get("answers", {}).get(qid, "")
            if q["type"] == "choice":
                is_correct = sa.strip().upper() == q.get("answer", "").strip().upper()
            elif q["type"] == "fill_blank":
                is_correct = sa.strip().replace(" ", "") == q.get("answer", "").strip().replace(" ", "")
            else:
                is_correct = sa.strip() != ""  # simplified
            if not is_correct:
                sub_key = f"{sid}_{qid}"
                corr = hw_corrections.get(sub_key, {})
                if corr.get("status") != "closed":
                    pending_count += 1

    return render_template(
        "student_corrections.html",
        corrections=history,
        student=student,
        pending_count=pending_count,
    )


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


# ── V1.0 Sprint 2: 作业创建/组卷 ─────────────────────────────────────
def _list_all_homeworks():
    """List all homeworks from PG (if available) or JSON fallback."""
    homeworks = []
    pg_ok = False
    try:
        from db_store import is_pg_available
        if is_pg_available():
            from infra.pg.orm import Homework
            from sqlalchemy import create_engine, select
            from sqlalchemy.orm import Session
            from db_store import _get_sync_db_url
            engine = create_engine(_get_sync_db_url())
            with Session(engine) as s:
                rows = s.execute(select(Homework).order_by(Homework.created_at.desc())).scalars().all()
                homeworks = [
                    {
                        "hw_key": r.hw_key,
                        "title": r.title,
                        "subject": r.subject,
                        "grade": r.grade,
                        "knowledge_points": r.knowledge_points,
                        "questions": r.questions,
                        "question_count": len(r.questions),
                        "total_score": sum(q.get("score", 0) for q in r.questions),
                    }
                    for r in rows
                ]
            pg_ok = True
    except Exception:
        pass

    if not pg_ok:
        # Fallback: load from JSON
        all_hw = load_json("questions.json")
        for hw_key, hw_data in all_hw.items():
            questions = hw_data.get("questions", [])
            homeworks.append({
                "hw_key": hw_key,
                "title": hw_data.get("title", ""),
                "subject": hw_data.get("subject", "数学"),
                "grade": hw_data.get("grade", ""),
                "knowledge_points": hw_data.get("knowledge_points", []),
                "questions": questions,
                "question_count": len(questions),
                "total_score": sum(q.get("score", 0) for q in questions),
            })

    return homeworks


@app.route("/teacher/homework/create", methods=["GET"])
@login_required
@roles_required("teacher", "head", "admin")
def teacher_create_homework_form():
    """Render the create homework page."""
    students = load_json("students.json")["students"]
    classes = sorted(set(s["class"] for s in students))
    return render_template("teacher_create_homework.html", classes=classes)


@app.route("/teacher/homework/create", methods=["POST"])
@login_required
@roles_required("teacher", "head", "admin")
@csrf_protect
@rate_limit(max_per_minute=10)
def teacher_create_homework_submit():
    """Handle homework creation form submission.

    Creates a new homework in PG (if available) or in-memory JSON.
    Supports: subject, grade, title, knowledge_points, questions (dynamic list),
    target_class, deadline.
    """
    import json as _json
    from datetime import datetime

    title = request.form.get("title", "").strip()
    subject = request.form.get("subject", "数学").strip()
    grade = request.form.get("grade", "").strip()
    knowledge_points_str = request.form.get("knowledge_points", "").strip()
    target_class = request.form.get("target_class", "").strip()
    deadline = request.form.get("deadline", "").strip()
    questions_json = request.form.get("questions_json", "[]")

    if not title:
        return jsonify({"ok": False, "feedback": "作业标题不能为空"}), 400

    try:
        questions = _json.loads(questions_json)
    except (ValueError, TypeError):
        return jsonify({"ok": False, "feedback": "题目数据格式错误"}), 400

    if not questions:
        return jsonify({"ok": False, "feedback": "至少需要一道题目"}), 400

    # Ensure each question has subject_type (default: math_calculation for backward compat)
    for q in questions:
        if not q.get("subject_type"):
            q["subject_type"] = "math_calculation"

    knowledge_points = [kp.strip() for kp in knowledge_points_str.split(",") if kp.strip()]

    # Generate hw_key: hw_<timestamp>
    hw_key = f"hw_{int(datetime.utcnow().timestamp())}"

    audit_log("homework_create", title=title, hw_key=hw_key,
              subject=subject, question_count=len(questions), target_class=target_class)

    # Try PG first
    saved_to_pg = False
    try:
        from db_store import is_pg_available
        if is_pg_available():
            from infra.pg.orm import Homework
            from sqlalchemy import create_engine
            from sqlalchemy.orm import Session
            from db_store import _get_sync_db_url
            engine = create_engine(_get_sync_db_url())
            with Session(engine) as s:
                hw = Homework(
                    hw_key=hw_key,
                    title=title,
                    subject=subject,
                    grade=grade or None,
                    knowledge_points=knowledge_points,
                    questions=questions,
                )
                s.add(hw)
                s.commit()
            saved_to_pg = True
    except Exception as e:
        audit_log("homework_create_pg_error", error=str(e))

    if saved_to_pg:
        return jsonify({
            "ok": True,
            "hw_key": hw_key,
            "redirect": f"/teacher/grade/{hw_key}",
            "message": f"作业「{title}」已创建并保存到数据库",
        })

    # Fallback: save to in-memory questions.json structure (demo mode)
    all_hw = load_json("questions.json")
    all_hw[hw_key] = {
        "id": hw_key,
        "title": title,
        "subject": subject,
        "grade": grade,
        "knowledge_points": knowledge_points,
        "questions": questions,
    }
    # Write back to JSON file (demo mode persistence)
    _data_dir = os.path.join(os.path.dirname(__file__), "data")
    with open(os.path.join(_data_dir, "questions.json"), "w", encoding="utf-8") as f:
        _json.dump(all_hw, f, ensure_ascii=False, indent=2)

    return jsonify({
        "ok": True,
        "hw_key": hw_key,
        "redirect": f"/teacher/grade/{hw_key}",
        "message": f"作业「{title}」已创建（演示模式，保存到 JSON）",
    })


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
# V1.0 item 1: /healthz + /readyz 不走鉴权（无 @login_required），
# 供负载均衡器 / caddy / k8s 探活。这两个路由在任何 before_request 之前
# 注册，确保 prod 模式下匿名可访问。
@app.route("/healthz")
def healthz():
    """Liveness probe for k8s / load balancer. 进程存活即 OK，不查依赖。"""
    return jsonify({"status": "ok"})


@app.route("/readyz")
def readyz():
    """Readiness probe: PG + Redis 都通才 200；任一失败返 503。

    V1.0 item 1: 与 FastAPI /api/v1/readyz 对齐，供 Flask 直挂场景
    （gunicorn 不经 FastAPI 时）的 LB 探活。
    """
    checks = {}
    # PG
    try:
        from db_store import is_pg_available

        checks["postgres"] = {"ok": bool(is_pg_available())}
    except Exception as exc:  # noqa: BLE001
        checks["postgres"] = {"ok": False, "error": str(exc)}
    # Redis
    try:
        from security import _get_audit_redis

        r = _get_audit_redis()
        checks["redis"] = {"ok": r is not None and bool(r.ping())}
    except Exception as exc:  # noqa: BLE001
        checks["redis"] = {"ok": False, "error": str(exc)}
    ready = all(c.get("ok") for c in checks.values())
    body = {"ready": ready, "checks": checks}
    from flask import make_response

    resp = make_response(jsonify(body), 200 if ready else 503)
    return resp


# ── V2.0 Sprint 6: Observability endpoints ────────────────────────────

@app.route("/metrics")
def metrics():
    """Prometheus text exposition format endpoint (6.2).

    No auth required (metrics don't contain PII; Prometheus scrapes
    without session cookies). Returns text/plain.
    """
    from flask import Response
    return Response(render_metrics(), mimetype="text/plain; version=0.0.4; charset=utf-8")


@app.route("/api/admin/alerts")
@login_required
@roles_required("admin", "head")
def api_admin_alerts():
    """Alert rule status + recent alerts (6.4).

    Returns current alert rule status and recent fired alerts.
    """
    am = get_alert_manager()
    return jsonify({
        "rules": am.get_rule_status(),
        "recent_alerts": am.get_recent_alerts(limit=20),
    })


# ── OCR Upload (Sprint 2) ─────────────────────────────────────────────
@app.route("/api/ocr/upload", methods=["POST"])
@login_required
def api_ocr_upload():
    """学生上传答卷图片 → OCR 识别 → 返回结构化文本.

    Accepts multipart/form-data with:
        - file: image file (jpg/png)
        - question_type: "choice" | "fill_blank" | "long_answer"
        - question_id: optional question id

    Returns JSON: {text, confidence, provider, lines, question_type, question_id}
    Falls back to mock OCR when PaddleOCR unavailable (no crash).
    """
    import base64

    from engine.ocr import extract_text

    # Get question_type (default long_answer)
    question_type = request.form.get("question_type", "long_answer")
    question_id = request.form.get("question_id", "unknown")

    # Read image file
    if "file" not in request.files:
        return jsonify({"error": "no file uploaded"}), 400

    file = request.files["file"]
    if not file.filename:
        return jsonify({"error": "empty filename"}), 400

    # Read bytes and encode to base64 for the OCR engine
    image_bytes = file.read()
    image_b64 = base64.b64encode(image_bytes).decode("ascii")

    result = extract_text(image_b64, question_type)
    result["question_id"] = question_id
    return jsonify(result)


@app.route("/api/ocr/grade", methods=["POST"])
@login_required
@require_consent
def api_ocr_grade():
    """学生上传答卷图片 → OCR 识别 → 直接走 grading 流程.

    Accepts multipart/form-data with:
        - file: image file (jpg/png)
        - question_type: "choice" | "fill_blank" | "long_answer"
        - question_id: question id
        - student_id: student id

    Returns JSON: {ocr_result, grade_result}
    """
    import base64

    from engine.ocr import extract_text

    question_type = request.form.get("question_type", "long_answer")
    question_id = request.form.get("question_id", "")
    student_id = request.form.get("student_id", "")

    if "file" not in request.files:
        return jsonify({"error": "no file uploaded"}), 400

    file = request.files["file"]
    if not file.filename:
        return jsonify({"error": "empty filename"}), 400

    image_bytes = file.read()
    image_b64 = base64.b64encode(image_bytes).decode("ascii")

    # Step 1: OCR
    ocr_result = extract_text(image_b64, question_type)
    student_answer = ocr_result.get("text", "")

    # Step 2: Grade using the recognized text
    questions = load_json("questions.json")
    # Try to find the question across all assignments
    question = None
    assignment_id = "hw_001"
    for aid, assignment in questions.items():
        for q in assignment.get("questions", []):
            if q["id"] == question_id:
                question = q
                assignment_id = aid
                break
        if question:
            break

    if not question:
        # Fallback: create a minimal question dict
        question = {"id": question_id, "type": question_type, "score": 10,
                     "answer": "", "steps": [], "knowledge": ""}

    if question_type == "choice":
        grade_result = grade_choice(student_answer, question.get("answer", ""), question)
    elif question_type == "fill_blank":
        grade_result = grade_fill_blank(student_answer, question.get("answer", ""), question)
    else:
        grade_result = grade_long_answer(student_answer, question, student_id)

    return jsonify({
        "ocr_result": ocr_result,
        "grade_result": grade_result,
    })


# ── Sprint 3: 订正闭环 API ────────────────────────────────────────────

def _resolve_submission(submission_id: str) -> tuple[dict | None, dict | None]:
    """从 submission_id（如 s02_hw_001）解析出 answer record + question.

    Returns: (answer_record, question_dict) or (None, None) if not found.
    """
    answers = load_json("answers.json")
    record = answers.get(submission_id)
    if not record:
        return None, None

    assignment_id = record.get("assignment_id", "hw_001")
    questions_data = load_json("questions.json")
    assignment = questions_data.get(assignment_id, {})
    return record, assignment


def _find_question_in_assignment(assignment: dict, question_id: str) -> dict | None:
    """在 assignment 中查找指定 question_id 的题目."""
    for q in assignment.get("questions", []):
        if q["id"] == question_id:
            return q
    return None


def _find_original_grading(student_id: str, question_id: str) -> dict:
    """查找学生原批改结果（从 grading_results.json 或 fallback 构造）."""
    try:
        results = load_json("grading_results.json")
        for r in results.get("results", []):
            if r.get("student_id") == student_id and r.get("question_id") == question_id:
                return r
    except (FileNotFoundError, KeyError):
        pass
    # Fallback: 构造一个最简 result
    return {"is_correct": False, "score": 0, "step_results": []}


def _save_correction_record(
    student_id: str,
    homework_key: str,
    question_id: str,
    original_answer: str,
    correction_text: str,
    grading_result: dict,
) -> None:
    """将订正记录写入 corrections.json（JSON fallback 模式）.

    同一 student+question 的订正追加到 attempts 列表；
    mastery_level=mastered 时 status 置为 closed。
    """
    import json as _json
    corrections_path = os.path.join(os.path.dirname(__file__), "data", "corrections.json")
    try:
        with open(corrections_path, "r", encoding="utf-8") as f:
            corrections = _json.load(f)
    except (FileNotFoundError, _json.JSONDecodeError):
        corrections = {}

    hw_key = f"{homework_key}_corrections"
    sub_key = f"{student_id}_{question_id}"

    if hw_key not in corrections:
        corrections[hw_key] = {}
    if sub_key not in corrections[hw_key]:
        corrections[hw_key][sub_key] = {
            "student_id": student_id,
            "question_id": question_id,
            "original_answer": original_answer,
            "attempts": [],
            "status": "open",
        }

    record = corrections[hw_key][sub_key]
    attempt_num = len(record["attempts"]) + 1
    record["attempts"].append({
        "attempt": attempt_num,
        "content": correction_text,
        "result": "correct" if grading_result["is_correct"] else "incorrect",
        "mastery_level": grading_result["mastery_level"],
        "feedback": grading_result["feedback"],
        "comparison": grading_result["comparison"],
        "encouragement": grading_result["encouragement"],
        "next_steps": grading_result.get("next_steps", ""),
        "graded_by": grading_result.get("graded_by", "mock"),
        "timestamp": grading_result.get("timestamp", ""),
    })

    # mastered → 闭环
    if grading_result["mastery_level"] == "mastered":
        record["status"] = "closed"

    with open(corrections_path, "w", encoding="utf-8") as f:
        _json.dump(corrections, f, ensure_ascii=False, indent=2)


@app.route("/api/correction/submit", methods=["POST"])
@login_required
@require_consent
@csrf_protect
@rate_limit(max_per_minute=20)
def api_correction_submit():
    """学生提交订正 → LLM/mock 对比批改 → 写 corrections 表 → 返回结构化结果.

    接口契约（与原型师对齐）:
        Request:  { submission_id, question_id, correction_text }
        Response: { ok, is_correct, mastery_level, feedback, encouragement, comparison }
    """
    from engine.correction_grader import grade_correction

    body = request.get_json(silent=True) or {}
    submission_id = body.get("submission_id", "")
    question_id = body.get("question_id", "")
    correction_text = body.get("correction_text", "").strip()

    if not submission_id or not question_id or not correction_text:
        return jsonify({"ok": False, "error": "缺少必填字段: submission_id, question_id, correction_text"}), 400

    # 权限校验：学生只能提交自己的订正
    user = get_current_user()
    record, assignment = _resolve_submission(submission_id)
    if not record:
        return jsonify({"ok": False, "error": "提交记录不存在"}), 404

    submission_student_id = record.get("student_id", "")
    if user and user.get("role") == "student":
        own_student_id = user.get("student_id", "")
        if own_student_id and own_student_id != submission_student_id:
            audit_log("correction_idor_blocked", target=submission_id, own=own_student_id)
            return jsonify({"ok": False, "error": "无权提交他人的订正"}), 403

    # 查找题目
    question = _find_question_in_assignment(assignment, question_id)
    if not question:
        return jsonify({"ok": False, "error": "题目不存在"}), 404

    # 获取原答案和原批改结果
    original_answer = record.get("answers", {}).get(question_id, "")
    original_result = _find_original_grading(submission_student_id, question_id)

    # 订正对比批改
    grading_result = grade_correction(
        question=question,
        original_answer=original_answer,
        original_result=original_result,
        correction_text=correction_text,
        student_id=submission_student_id,
    )

    # 持久化（JSON fallback；PG 可用时 future 迁移）
    homework_key = record.get("assignment_id", "hw_001")
    _save_correction_record(
        student_id=submission_student_id,
        homework_key=homework_key,
        question_id=question_id,
        original_answer=original_answer,
        correction_text=correction_text,
        grading_result=grading_result,
    )

    audit_log(
        "correction_submit_api",
        student_id=submission_student_id,
        question_id=question_id,
        mastery=grading_result["mastery_level"],
    )

    return jsonify({
        "ok": True,
        "is_correct": grading_result["is_correct"],
        "mastery_level": grading_result["mastery_level"],
        "feedback": grading_result["feedback"],
        "encouragement": grading_result["encouragement"],
        "comparison": grading_result["comparison"],
        "next_steps": grading_result.get("next_steps", ""),
        "emotional_feedback": grading_result.get("emotional_feedback", ""),
    })


@app.route("/api/correction/list", methods=["GET"])
@login_required
def api_correction_list():
    """返回当前学生的订正列表.

    Response: { ok, corrections: [...], pending_count: int }
    每条 correction: { question_id, homework_key, mastery_level, attempt_count,
                       latest_feedback, status, created_at }
    """
    from engine.correction_grader import get_latest_mastery

    user = get_current_user()
    if not user:
        if _demo_auth_open():
            # demo 模式默认返回 s01 的数据
            student_id = request.args.get("student_id", "s01")
        else:
            return jsonify({"ok": False, "error": "未登录"}), 401
    else:
        if user.get("role") == "student":
            student_id = user.get("student_id", "")
        else:
            # teacher/admin 可以查指定学生
            student_id = request.args.get("student_id", "")

    if not student_id:
        return jsonify({"ok": False, "error": "缺少 student_id"}), 400

    # 从 corrections.json 读取
    corrections_data = load_json("corrections.json")
    result_list = []
    for hw_key, hw_corrections in corrections_data.items():
        actual_hw_key = hw_key.replace("_corrections", "")
        for sub_key, record in hw_corrections.items():
            if record.get("student_id") != student_id:
                continue
            attempts = record.get("attempts", [])
            latest_mastery = get_latest_mastery(attempts)
            latest_attempt = max(attempts, key=lambda a: a.get("attempt", 0)) if attempts else {}
            result_list.append({
                "question_id": record.get("question_id", ""),
                "homework_key": actual_hw_key,
                "mastery_level": latest_mastery,
                "attempt_count": len(attempts),
                "latest_feedback": latest_attempt.get("feedback", ""),
                "latest_encouragement": latest_attempt.get("encouragement", ""),
                "status": record.get("status", "open"),
                "created_at": record.get("created_at", ""),
                "latest_timestamp": latest_attempt.get("timestamp", ""),
            })

    # 待订正计数：有批改结果但无订正记录的 submission 数
    pending_count = _count_pending_corrections(student_id)

    return jsonify({
        "ok": True,
        "corrections": result_list,
        "pending_count": pending_count,
    })


def _count_pending_corrections(student_id: str) -> int:
    """计算待订正数量：有批改结果但无订正记录的题目数.

    遍历学生的 submission 中每道题，检查 corrections.json 是否有对应记录。
    """
    answers = load_json("answers.json")
    corrections_data = load_json("corrections.json")

    # 收集已订正的 question_id 集合
    corrected_keys = set()
    for hw_key, hw_corrections in corrections_data.items():
        for sub_key, record in hw_corrections.items():
            if record.get("student_id") == student_id:
                corrected_keys.add(record.get("question_id", ""))

    # 遍历该学生的所有 submission，统计未订正的错题
    pending = 0
    for sub_id, record in answers.items():
        if record.get("student_id") != student_id:
            continue
        assignment_id = record.get("assignment_id", "hw_001")
        questions_data = load_json("questions.json")
        assignment = questions_data.get(assignment_id, {})
        answers_dict = record.get("answers", {})

        for q in assignment.get("questions", []):
            q_id = q["id"]
            if q_id in corrected_keys:
                continue
            # 判断是否答错（有批改结果但未订正）
            student_answer = answers_dict.get(q_id, "")
            if not student_answer:
                continue
            # 简单判断：choice/fill_blank 与标准答案比对
            if q.get("type") == "choice":
                if student_answer.strip().upper() != q.get("answer", "").strip().upper():
                    pending += 1
            elif q.get("type") == "fill_blank":
                import re as _re
                norm = lambda s: _re.sub(r"\s+", "", s)
                if norm(student_answer) != norm(q.get("answer", "")):
                    pending += 1
            else:
                # long_answer: 有答案就认为可能需要订正（简化逻辑）
                # 实际应查 grading_results 判断 is_correct
                try:
                    grading = _find_original_grading(student_id, q_id)
                    if not grading.get("is_correct", True):
                        pending += 1
                except Exception:
                    pass

    return pending


# ── Sprint 4 P0-3: 家长知情同意 ──────────────────────────────────────

@app.route("/consent")
@login_required
def consent_page():
    """Parental consent page — shown on student's first login.

    V2.0 Sprint 5 (5.10): Upgraded to formalized consent with three states
    (granted/pending/demo), guardian signature, and audit trail.
    """
    user = get_current_user()
    # Non-students don't need consent
    if user and user.get("role") != "student":
        return redirect(url_for("index"))
    # Already consented — still show the page (audit record view)
    # V2.0 Sprint 5: inject formalized consent context
    ctx = build_consent_context()
    ctx["user"] = user
    return render_template("consent.html", **ctx)


@app.route("/consent", methods=["POST"])
@login_required
@csrf_protect
def consent_submit():
    """Handle parental consent form submission.

    V2.0 Sprint 5 (5.10): Formalized consent with guardian info + signature.
    """
    user = get_current_user()
    if not user:
        return redirect(url_for("login"))
    if user.get("role") != "student":
        return redirect(url_for("index"))

    # V2.0 Sprint 5: Support both JSON (formalized) and form (legacy) submissions
    if request.is_json:
        body = request.get_json()
        guardian_name = body.get("guardian_name", "").strip()
        guardian_id_no = body.get("guardian_id_no", "").strip()
        signature_data_url = body.get("signature_data_url", "")
        agreed = body.get("agree", False)
        student_id = body.get("student_id", user.get("student_id", user.get("user_id", "")))
    else:
        # Legacy form submission (backward compat with V1.5 consent.html)
        guardian_name = request.form.get("guardian_name", "").strip()
        guardian_id_no = request.form.get("guardian_id_no", "").strip()
        signature_data_url = request.form.get("signature_data_url", "")
        agreed = request.form.get("parent_consent") == "on" or request.form.get("agree") == "on"
        student_id = user.get("student_id", user.get("user_id", ""))

    if not agreed:
        flash("需要家长/监护人勾选同意才能继续使用。", "error")
        ctx = build_consent_context()
        ctx["user"] = user
        return render_template("consent.html", **ctx), 400

    if not guardian_name:
        flash("需要填写监护人姓名。", "error")
        ctx = build_consent_context()
        ctx["user"] = user
        return render_template("consent.html", **ctx), 400

    # V2.0 Sprint 5: Create formalized consent record
    record = create_consent_record(
        student_id=student_id,
        guardian_name=guardian_name,
        guardian_id_no=guardian_id_no,
        signature_data_url=signature_data_url,
        agreed=True,
    )

    session["consent_given"] = True

    if request.is_json:
        return jsonify({"ok": True, "data": {"status": "granted", "record_id": record["record_id"]}})

    flash("感谢确认！您现在可以提交作业了。", "success")
    return redirect(url_for("index"))


# ── V2.0 Sprint 5: 组织树管理页 + 学生列表脱敏 API + consent 审计 ─────

@app.route("/admin/organization")
@login_required
@roles_required("admin", "head", "teacher")
def admin_organization_page():
    """V2.0 Sprint 5 (5.3): Organization tree management page."""
    return render_template("admin/organization.html")


@app.route("/api/admin/students")
@login_required
@roles_required("admin", "head", "teacher")
@data_scope()
def api_admin_students():
    """V2.0 Sprint 5 (5.9): Student list with role-based masking.

    Query params: class_id, page (default 1), size (default 20)
    """
    import math
    class_id = request.args.get("class_id", type=int)
    page = request.args.get("page", 1, type=int)
    size = request.args.get("size", 20, type=int)
    page = max(1, page)
    size = max(1, min(100, size))

    students = load_json("students.json").get("students", [])

    # Filter by class_id if provided
    if class_id:
        students = [s for s in students if s.get("class_id") == class_id]

    total = len(students)
    start = (page - 1) * size
    page_items = students[start:start + size]

    # V2.0 Sprint 5 (5.9): Role-based masking
    user = get_current_user()
    role = user.get("role", "") if user else ""
    # teacher viewing own class → name not masked; others → masked
    is_own_class = role == "teacher"  # simplified: assume teacher queries own class

    masked = mask_student_list(page_items, role=role, is_own_class=is_own_class)

    return jsonify({
        "ok": True,
        "data": {
            "items": [
                {
                    "id": s.get("student_id", s.get("id", "")),
                    "name": s.get("name", ""),
                    "student_no": s.get("student_no", s.get("student_id", "")),
                    "class_name": s.get("class_name", ""),
                    "phone": s.get("phone", ""),
                }
                for s in masked
            ],
            "total": total,
            "page": page,
        }
    })


@app.route("/api/consent/record")
@login_required
def api_consent_record():
    """V2.0 Sprint 5 (5.10): Get consent record for audit."""
    student_id = request.args.get("student_id", "")
    if not student_id:
        user = get_current_user()
        student_id = user.get("student_id", user.get("user_id", "")) if user else ""

    record = get_latest_consent_record(student_id)
    if not record:
        return jsonify({"ok": False, "error": "no consent record found"}), 404

    from data_masking import mask_guardian_name, mask_id_no
    return jsonify({
        "ok": True,
        "data": {
            "record_id": record.get("record_id"),
            "granted_at": record.get("granted_at"),
            "guardian_name_masked": mask_guardian_name(record.get("guardian_name")),
            "guardian_id_no_masked": mask_id_no(record.get("guardian_id_no")),
            "version": record.get("version"),
        }
    })

@app.route("/api/student/<student_id>/data", methods=["DELETE"])
@login_required
@csrf_protect
def api_delete_student_data(student_id):
    """Delete all data for a student (GDPR-style right to erasure).

    Permission: students can only delete their own data;
    teachers/admins can delete any student's data.
    """
    user = get_current_user()
    if not user:
        if _demo_auth_open():
            pass  # demo mode: allow
        else:
            return jsonify({"ok": False, "error": "auth_required"}), 401

    # Permission check: students can only operate on their own data
    if user and user.get("role") == "student":
        own = user.get("student_id", "")
        if own and own != student_id:
            audit_log("delete_data_idor_blocked", target=student_id, own=own)
            return jsonify({"ok": False, "error": "forbidden"}), 403

    from db_store import delete_student_data
    summary = delete_student_data(student_id)

    audit_log(
        "student_data_deleted",
        student_id=student_id,
        deleted_by=user.get("user_id", "demo") if user else "demo",
        **summary,
    )

    return jsonify({"ok": True, "deleted": summary})


@app.route("/api/student/<student_id>/export")
@login_required
def api_export_student_data(student_id):
    """Export all data for a student as JSON (GDPR-style data portability).

    Permission: students can only export their own data;
    teachers/admins can export any student's data.
    """
    user = get_current_user()
    if not user:
        if _demo_auth_open():
            pass
        else:
            return jsonify({"ok": False, "error": "auth_required"}), 401

    # Permission check
    if user and user.get("role") == "student":
        own = user.get("student_id", "")
        if own and own != student_id:
            audit_log("export_data_idor_blocked", target=student_id, own=own)
            return jsonify({"ok": False, "error": "forbidden"}), 403

    from db_store import export_student_data
    data = export_student_data(student_id)

    audit_log(
        "student_data_exported",
        student_id=student_id,
        exported_by=user.get("user_id", "demo") if user else "demo",
    )

    return jsonify({"ok": True, "data": data})


# ── Sprint 4: 教师端掌握度看板 ──────────────────────────────────────

@app.route("/teacher/mastery")
@login_required
@roles_required("teacher", "head", "admin")
def teacher_mastery_page():
    """Teacher class mastery dashboard — per-question + per-student mastery view."""
    # Reuse the API aggregation logic directly for server-side rendering
    from engine.grader import load_json, get_correction_status

    questions_all = load_json("questions.json")
    corrections_data = load_json("corrections.json")
    answers = load_json("answers.json")
    students = load_json("students.json")["students"]

    homeworks_result = []
    for hw_key, hw_data in questions_all.items():
        questions = hw_data.get("questions", [])
        hw_questions = []
        for q in questions:
            qid = q["id"]
            mastery_counts = {"mastered": 0, "partial": 0, "not_mastered": 0, "uncorrected": 0}
            corr_key = f"{hw_key}_corrections"
            hw_corrections = corrections_data.get(corr_key, {})
            student_details = []
            for s in students:
                sid = s["id"]
                submission_key = f"{sid}_{hw_key}"
                sub = answers.get(submission_key, {})
                sa = sub.get("answers", {}).get(qid, "")
                if q.get("type") == "choice":
                    orig_correct = sa.strip().upper() == q.get("answer", "").strip().upper()
                elif q.get("type") == "fill_blank":
                    orig_correct = sa.strip().replace(" ", "") == q.get("answer", "").strip().replace(" ", "")
                else:
                    result = grade_long_answer(sa, q, sid)
                    orig_correct = result.get("is_correct", False)
                if orig_correct:
                    mastery_counts["mastered"] += 1
                    student_details.append({"student": s, "mastery": "mastered", "original_answer": sa})
                    continue
                sub_key = f"{sid}_{qid}"
                corr = hw_corrections.get(sub_key, {})
                if corr:
                    latest_mastery = "mastered" if corr.get("status") == "closed" else "partial"
                    attempts = corr.get("attempts", [])
                    if attempts:
                        latest_mastery = attempts[-1].get("mastery_level", latest_mastery)
                    if latest_mastery == "mastered":
                        mastery_counts["mastered"] += 1
                    elif latest_mastery == "partial":
                        mastery_counts["partial"] += 1
                    else:
                        mastery_counts["not_mastered"] += 1
                    student_details.append({"student": s, "mastery": latest_mastery, "original_answer": sa,
                                           "correction_attempts": len(attempts)})
                else:
                    mastery_counts["uncorrected"] += 1
                    student_details.append({"student": s, "mastery": "uncorrected", "original_answer": sa})
            total = sum(mastery_counts.values())
            mastery_rate = round(mastery_counts["mastered"] / total * 100, 1) if total > 0 else 0
            hw_questions.append({
                "question_id": qid, "stem": q.get("stem", "")[:80],
                "full_stem": q.get("stem", ""), "knowledge": q.get("knowledge", ""),
                "type": q.get("type", ""), "mastery_distribution": mastery_counts,
                "mastery_rate": mastery_rate, "total_students": total,
                "student_details": student_details,
            })
        hw_questions.sort(key=lambda x: x["mastery_rate"])
        for i, q in enumerate(hw_questions[:3]):
            q["weakest"] = True
        homeworks_result.append({
            "hw_key": hw_key, "title": hw_data.get("title", hw_key),
            "subject": hw_data.get("subject", ""),
            "questions": hw_questions,
        })

    students_result = []
    for s in students:
        sid = s["id"]
        correction_count = 0
        closed_count = 0
        latest_time = ""
        for hw_key in questions_all:
            corr_key = f"{hw_key}_corrections"
            hw_corrections = corrections_data.get(corr_key, {})
            for sub_key, rec in hw_corrections.items():
                if rec.get("student_id") != sid:
                    continue
                correction_count += 1
                if rec.get("status") == "closed":
                    closed_count += 1
                attempts = rec.get("attempts", [])
                if attempts:
                    t = attempts[-1].get("timestamp", "")
                    if t > latest_time:
                        latest_time = t
        status = get_correction_status(sid, "hw_001")
        mastery_rate = status.get("loop_rate", 100)
        students_result.append({
            "student_id": sid, "name": s.get("name", sid),
            "avatar_color": s.get("avatar_color", "#ccc"),
            "correction_count": correction_count, "closed_count": closed_count,
            "pending_count": correction_count - closed_count,
            "latest_correction_time": latest_time, "mastery_rate": mastery_rate,
        })

    return render_template("teacher_mastery.html",
                           homeworks=homeworks_result, students=students_result,
                           total_students=len(students))


# ── Sprint 4: 教师端掌握度看板 API ───────────────────────────────────

@app.route("/api/teacher/mastery")
@login_required
@roles_required("teacher", "head", "admin")
def api_teacher_mastery():
    """Aggregate class-wide mastery data for the teacher dashboard.

    Returns per-homework → per-question mastery distribution and
    per-student correction progress. Data sourced from corrections +
    submissions (JSON fallback or PG).

    Response contract:
        {
          "homeworks": [
            {
              "hw_key": "hw_001",
              "title": "...",
              "questions": [
                {
                  "question_id": "q5",
                  "stem": "...",
                  "knowledge": "...",
                  "mastery_distribution": {
                    "mastered": 2,
                    "partial": 1,
                    "not_mastered": 1,
                    "uncorrected": 1
                  },
                  "weakest": true   // top-3 lowest mastery rate
                }
              ]
            }
          ],
          "students": [
            {
              "student_id": "s01",
              "name": "同学A",
              "avatar_color": "#...",
              "correction_count": 3,
              "closed_count": 2,
              "pending_count": 1,
              "latest_correction_time": "2026-07-30T...",
              "mastery_rate": 66.7
            }
          ]
        }
    """
    from engine.grader import load_json, get_correction_status

    questions_all = load_json("questions.json")
    corrections_data = load_json("corrections.json")
    answers = load_json("answers.json")
    students = load_json("students.json")["students"]

    homeworks_result = []

    for hw_key, hw_data in questions_all.items():
        questions = hw_data.get("questions", [])
        hw_questions = []

        for q in questions:
            qid = q["id"]
            # Count mastery levels across all students
            mastery_counts = {"mastered": 0, "partial": 0, "not_mastered": 0, "uncorrected": 0}
            corr_key = f"{hw_key}_corrections"
            hw_corrections = corrections_data.get(corr_key, {})

            for s in students:
                sid = s["id"]
                # Check if the student got this question wrong
                submission_key = f"{sid}_{hw_key}"
                sub = answers.get(submission_key, {})
                sa = sub.get("answers", {}).get(qid, "")

                # Determine if originally correct
                if q.get("type") == "choice":
                    orig_correct = sa.strip().upper() == q.get("answer", "").strip().upper()
                elif q.get("type") == "fill_blank":
                    orig_correct = sa.strip().replace(" ", "") == q.get("answer", "").strip().replace(" ", "")
                else:
                    result = grade_long_answer(sa, q, sid)
                    orig_correct = result.get("is_correct", False)

                if orig_correct:
                    mastery_counts["mastered"] += 1
                    continue

                # Check correction status
                sub_key = f"{sid}_{qid}"
                corr = hw_corrections.get(sub_key, {})
                if corr:
                    latest_mastery = "mastered" if corr.get("status") == "closed" else "partial"
                    attempts = corr.get("attempts", [])
                    if attempts:
                        latest_mastery = attempts[-1].get("mastery_level", latest_mastery)
                    if latest_mastery == "mastered":
                        mastery_counts["mastered"] += 1
                    elif latest_mastery == "partial":
                        mastery_counts["partial"] += 1
                    else:
                        mastery_counts["not_mastered"] += 1
                else:
                    mastery_counts["uncorrected"] += 1

            total = sum(mastery_counts.values())
            mastery_rate = round(mastery_counts["mastered"] / total * 100, 1) if total > 0 else 0

            hw_questions.append({
                "question_id": qid,
                "stem": q.get("stem", "")[:60],
                "knowledge": q.get("knowledge", ""),
                "type": q.get("type", ""),
                "mastery_distribution": mastery_counts,
                "mastery_rate": mastery_rate,
                "total_students": total,
            })

        # Mark top-3 weakest questions
        hw_questions.sort(key=lambda x: x["mastery_rate"])
        for i, q in enumerate(hw_questions[:3]):
            q["weakest"] = True

        homeworks_result.append({
            "hw_key": hw_key,
            "title": hw_data.get("title", hw_key),
            "questions": hw_questions,
        })

    # Per-student progress
    students_result = []
    for s in students:
        sid = s["id"]
        correction_count = 0
        closed_count = 0
        latest_time = ""

        for hw_key in questions_all:
            corr_key = f"{hw_key}_corrections"
            hw_corrections = corrections_data.get(corr_key, {})
            for sub_key, rec in hw_corrections.items():
                if rec.get("student_id") != sid:
                    continue
                correction_count += 1
                if rec.get("status") == "closed":
                    closed_count += 1
                attempts = rec.get("attempts", [])
                if attempts:
                    t = attempts[-1].get("timestamp", "")
                    if t > latest_time:
                        latest_time = t

        # Overall mastery rate from correction status
        status = get_correction_status(sid, "hw_001")
        mastery_rate = status.get("loop_rate", 100)

        students_result.append({
            "student_id": sid,
            "name": s.get("name", sid),
            "avatar_color": s.get("avatar_color", "#ccc"),
            "correction_count": correction_count,
            "closed_count": closed_count,
            "pending_count": correction_count - closed_count,
            "latest_correction_time": latest_time,
            "mastery_rate": mastery_rate,
        })

    return jsonify({
        "ok": True,
        "homeworks": homeworks_result,
        "students": students_result,
    })


# ── Sprint 6 API: 多租户配置管理 (6.7) + 内容安全过滤日志 (6.10) ──────

@app.route("/api/admin/tenant-config")
@login_required
@roles_required("admin")
def api_tenant_config_list():
    """List all tenant LLM configs (6.7)."""
    from tenant_llm_config_manager import list_tenant_configs

    configs = list_tenant_configs()
    # Mask api_key in response
    for c in configs:
        if c.get("api_key_secret"):
            c["api_key_secret"] = "***"
    return jsonify({"ok": True, "configs": configs})


@app.route("/api/admin/tenant-config/<int:school_id>")
@login_required
@roles_required("admin")
def api_tenant_config_get(school_id):
    """Get resolved LLM config for a school (6.7)."""
    from tenant_llm_config_manager import resolve_llm_config, get_tenant_config

    subject = request.args.get("subject")
    resolved = resolve_llm_config(school_id, subject_type=subject)
    # Mask api_key in response
    if resolved.get("api_key"):
        resolved["api_key"] = "***"
    tenant = get_tenant_config(school_id)
    return jsonify({
        "ok": True,
        "resolved": resolved,
        "tenant_config": tenant,
    })


@app.route("/api/admin/tenant-config/<int:school_id>", methods=["PUT"])
@login_required
@roles_required("admin")
@csrf_protect
def api_tenant_config_update(school_id):
    """Create or update tenant LLM config (6.7)."""
    from tenant_llm_config_manager import set_tenant_config

    data = request.get_json(silent=True) or {}
    config = set_tenant_config(
        school_id,
        model_name=data.get("model_name"),
        temperature=data.get("temperature"),
        max_tokens=data.get("max_tokens"),
        timeout=data.get("timeout"),
        api_key_secret=data.get("api_key_secret"),
        base_url=data.get("base_url"),
        subject_overrides=data.get("subject_overrides"),
    )
    # Mask api_key in response
    if config.get("api_key_secret"):
        config["api_key_secret"] = "***"
    return jsonify({"ok": True, "config": config})


@app.route("/api/admin/tenant-config/<int:school_id>", methods=["DELETE"])
@login_required
@roles_required("admin")
@csrf_protect
def api_tenant_config_delete(school_id):
    """Delete tenant LLM config (6.7). School falls back to global defaults."""
    from tenant_llm_config_manager import delete_tenant_config

    deleted = delete_tenant_config(school_id)
    return jsonify({"ok": deleted, "message": "已删除" if deleted else "配置不存在"})


@app.route("/api/admin/filter-logs")
@login_required
@roles_required("admin", "head")
def api_filter_logs():
    """Get content safety filter logs (6.10)."""
    from content_safety_filter import get_filter_logs

    school_id = request.args.get("school_id", type=int)
    limit = request.args.get("limit", 100, type=int)
    logs = get_filter_logs(school_id=school_id, limit=min(limit, 500))
    return jsonify({"ok": True, "logs": logs, "count": len(logs)})


@app.route("/api/admin/filter-stats")
@login_required
@roles_required("admin", "head")
def api_filter_stats():
    """Get content safety filter statistics (6.10)."""
    from content_safety_filter import get_filter_stats

    school_id = request.args.get("school_id", type=int)
    stats = get_filter_stats(school_id=school_id)
    return jsonify({"ok": True, "stats": stats})


if __name__ == "__main__":
    print("=" * 60)
    print("  希沃智教π — AI智能作业批改系统 Demo (Phase 0 安全加固版)")
    print("  开发入口（仅用于本地调试，生产请用 gunicorn）")
    print("  ────────────────────────────────────────────────────")
    print("  浏览器访问:    http://localhost:5000")
    print("  教师账号:      teacher / teacher123")
    print("  学生账号:      s01 ~ s05 / student123")
    print("  生产启动:      gunicorn -c gunicorn.conf.py 'demo.app:app'")
    print("=" * 60)
    # P0-1 安全 Blocker:
    # - debug 永远 False（即使 FLASK_DEBUG=1 也强制覆盖）
    # - host 默认 127.0.0.1（防误绑 0.0.0.0 暴露 RCE 风险）
    # - 任何 0.0.0.0 绑定请求都拒绝执行（生产请用 gunicorn）
    _host = os.environ.get("FLASK_HOST", "127.0.0.1")
    if _host == "0.0.0.0":
        print(
            "[!] 安全拦截: FLASK_HOST=0.0.0.0 不允许走 dev 入口（防 RCE）。\n"
            "    生产请用 gunicorn -c gunicorn.conf.py（默认绑 0.0.0.0:8000）\n"
            "    外层由 nginx 拦截（见 deploy/nginx.conf.example）"
        )
        sys.exit(2)
    app.run(
        debug=False,
        host=_host,
        port=int(os.environ.get("FLASK_PORT", "5000")),
    )
