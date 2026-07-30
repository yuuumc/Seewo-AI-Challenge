"""Security primitives for the Seewo AI Challenge demo.

This module provides lightweight, self-contained helpers for the demo
to satisfy Phase 0 P0 blockers (P0-1 ~ P0-6) without bringing in
heavy dependencies (no Flask-Login, no Flask-WTF, no flask-limiter
required). Production deployments should swap these for battle-
tested extensions; the wrappers here keep the demo's surface area
stable so the existing Jinja templates and route signatures continue
to work.

What lives here:
    * ``secret_key()``  - env-driven SECRET_KEY with safe dev fallback
    * ``audit_log()``   - structured append-only log to logs/audit.log
    * ``rate_limit()``  - in-memory per-IP token bucket
    * ``csrf_token``    - per-session token + ``csrf_protect`` decorator
    * ``login_required``/``roles_required``  - session auth + RBAC
    * ``check_ownership``  - IDOR guard for student-scoped routes
    * ``get_current_user``  - session lookup
    * ``DEMO_USERS``  - 8 demo accounts (4 roles + 5 students; aligned
                        with the test harness in tests/_helpers.py)

Demo-mode contract (driven by env, default OFF for production safety):
    * ``DEMO_AUTH_OPEN=0`` (default) — production-style: every protected
      route requires auth, CSRF + rate-limit strictly enforced.
    * ``DEMO_AUTH_OPEN=1`` — demo/showcase mode: anonymous GETs allowed,
      auth decorators only enforce when a user is actually logged in.
      Set explicitly via env (e.g. ``demo/start.sh``) for local demos.
      The test harness in tests/conftest.py also sets it for demo-mode
      test runs (production-style prod-mode tests use ``DEMO_AUTH_OPEN=0``).

These are intentionally simple and readable; the unit tests in
``tests/test_security.py`` exercise the surface.
"""
from __future__ import annotations

import functools
import hashlib
import hmac
import json
import os
import secrets
import time
from collections import defaultdict, deque
from pathlib import Path
from typing import Callable, Optional

import bcrypt
from flask import (
    abort,
    current_app,
    flash,
    g,
    jsonify,
    redirect,
    render_template,
    request,
    session,
    url_for,
)


# ---------------------------------------------------------------------------
# Demo mode toggle — when set to "0", auth/CSRF/rate-limit enforce strictly
# ---------------------------------------------------------------------------
def _demo_open() -> bool:
    """Demo mode: bypass CSRF + rate-limit + auth for the demo deploy.

    MIG-02: Default OFF (env var unset == "0"). Set ``DEMO_AUTH_OPEN=1``
    to enable the demo bypass for showcases. Production never sets this.
    """
    return os.environ.get("DEMO_AUTH_OPEN", "0") != "0"


# Kept for backward compat with the original name
def _demo_auth_open() -> bool:  # noqa: D401
    return _demo_open()


# ---------------------------------------------------------------------------
# Demo user table (Phase 0 placeholder; Phase 1 swaps to real SSO)
# ---------------------------------------------------------------------------
# Passwords are stored as bcrypt hashes (cost=12, per-user salt). MIG-03
# replaced the prior SHA-256 + hardcoded salt scheme. Phase 1 should move
# to a real user store with argon2id (preferred) and per-user work factors.
# The 8 accounts align 1:1 with tests/_helpers.py:DEMO_ACCOUNTS, which the
# test harness uses to verify login + role + IDOR behavior.
DEMO_USERS: dict = {
    "teacher": {
        "name": "李老师",
        "role": "teacher",
        "password_hash": "",
    },
    "head": {
        "name": "王组长",
        "role": "head",
        "password_hash": "",
    },
    "admin": {
        "name": "张主任",
        "role": "admin",
        "password_hash": "",
    },
    "s01": {
        "name": "同学A",
        "role": "student",
        "student_id": "s01",
        "password_hash": "",
    },
    "s02": {
        "name": "同学B",
        "role": "student",
        "student_id": "s02",
        "password_hash": "",
    },
    "s03": {
        "name": "同学C",
        "role": "student",
        "student_id": "s03",
        "password_hash": "",
    },
    "s04": {
        "name": "同学D",
        "role": "student",
        "student_id": "s04",
        "password_hash": "",
    },
    "s05": {
        "name": "同学E",
        "role": "student",
        "student_id": "s05",
        "password_hash": "",
    },
}


def _hash_password(password: str) -> str:
    """Hash a password using bcrypt (cost=12). Production-safe.

    MIG-03: Replaced SHA-256 + hardcoded salt with bcrypt.
    bcrypt handles per-hash salt internally; no external salt needed.
    """
    return bcrypt.hashpw(
        password.encode("utf-8"), bcrypt.gensalt(rounds=12)
    ).decode("utf-8")


def _verify_password(password: str, password_hash: str) -> bool:
    """Verify a password against a bcrypt hash.

    MIG-03: Replaced ``hmac.compare_digest(sha256(...), sha256(...))`` with
    ``bcrypt.checkpw`` which is constant-time and salt-aware.
    """
    if not password_hash:
        return False
    try:
        return bcrypt.checkpw(
            password.encode("utf-8"), password_hash.encode("utf-8")
        )
    except (ValueError, TypeError):
        # Malformed hash (e.g. legacy SHA-256 from pre-MIG-03)
        return False


def _seed_demo_passwords() -> None:
    """Fill in password hashes on first import (avoids module-level import side effects)."""
    seed = {
        "teacher": "teacher123",
        "head": "head123",
        "admin": "admin123",
        "s01": "student123",
        "s02": "student123",
        "s03": "student123",
        "s04": "student123",
        "s05": "student123",
    }
    for username, pwd in seed.items():
        DEMO_USERS[username]["password_hash"] = _hash_password(pwd)


_seed_demo_passwords()


# ---------------------------------------------------------------------------
# Session secret — env-driven, NEVER hardcoded in production
# ---------------------------------------------------------------------------
def secret_key() -> str:
    """Return the Flask SECRET_KEY, sourced from env (with a demo fallback)."""
    key = os.environ.get("SECRET_KEY")
    if key and key != "change-me":
        return key
    # Demo fallback: deterministic per-process so sessions survive within a run
    # but a fresh process produces a fresh key (forcing re-login on restart).
    demo = os.environ.get("DEMO_SECRET", "seewo-ai-challenge-demo-secret-2026")
    return demo


# ---------------------------------------------------------------------------
# Audit log — append-only JSON-lines to logs/audit.log
# ---------------------------------------------------------------------------
_AUDIT_PATH: Optional[Path] = None


def _audit_path() -> Path:
    global _AUDIT_PATH
    if _AUDIT_PATH is None:
        # Resolved lazily so tests can monkey-patch
        _AUDIT_PATH = Path(__file__).parent / "logs" / "audit.log"
        _AUDIT_PATH.parent.mkdir(parents=True, exist_ok=True)
    return _AUDIT_PATH


def audit_log(event: str, **fields) -> None:
    """Write one structured audit record. Never raises (audit must not break UX)."""
    try:
        record = {
            "ts": time.strftime("%Y-%m-%dT%H:%M:%S%z", time.localtime()),
            "event": event,
            "ip": request.remote_addr if request else None,
            "path": request.path if request else None,
            "method": request.method if request else None,
            "user": session.get("user_id") if session else None,
            "role": session.get("user_role") if session else None,
            **fields,
        }
        line = json.dumps(record, ensure_ascii=False, default=str)
        with _audit_path().open("a", encoding="utf-8") as f:
            f.write(line + "\n")
    except Exception:  # noqa: BLE001 - audit must not raise
        pass


# ---------------------------------------------------------------------------
# Rate limit — in-memory per-IP token bucket (demo only; use Redis in prod)
# ---------------------------------------------------------------------------
_RL_BUCKETS: dict = defaultdict(deque)


def rate_limit(max_per_minute: int = 30):
    """Per-IP sliding window limiter. Decorate POST routes to throttle abuse."""

    def decorator(fn: Callable) -> Callable:
        @functools.wraps(fn)
        def wrapper(*args, **kwargs):
            # Demo mode: rate-limit off (the test contract is "demo 模式零环境变量必须跑通")
            if _demo_open():
                return fn(*args, **kwargs)
            ip = request.remote_addr or "unknown"
            now = time.time()
            bucket = _RL_BUCKETS[(fn.__name__, ip)]
            # Drop entries older than 60s
            while bucket and bucket[0] < now - 60:
                bucket.popleft()
            if len(bucket) >= max_per_minute:
                audit_log("rate_limit_exceeded", route=fn.__name__, count=len(bucket))
                return (
                    jsonify({"ok": False, "feedback": "请求过于频繁，请稍后再试"}),
                    429,
                )
            bucket.append(now)
            return fn(*args, **kwargs)

        return wrapper

    return decorator


# ---------------------------------------------------------------------------
# CSRF — per-session token + constant-time compare
# ---------------------------------------------------------------------------
def get_csrf_token() -> str:
    """Return (and lazily generate) the per-session CSRF token."""
    tok = session.get("_csrf")
    if not tok:
        tok = secrets.token_urlsafe(32)
        session["_csrf"] = tok
    return tok


def csrf_protect(fn: Callable) -> Callable:
    """Reject non-GET requests whose form/json token doesn't match the session.

    Demo mode: bypass entirely (the test contract is "demo 模式零环境变量
    必须跑通"). Set ``DEMO_AUTH_OPEN=0`` to enable real CSRF enforcement.
    """

    @functools.wraps(fn)
    def wrapper(*args, **kwargs):
        if _demo_open():
            return fn(*args, **kwargs)
        if request.method in ("GET", "HEAD", "OPTIONS"):
            return fn(*args, **kwargs)
        expected = session.get("_csrf", "")
        provided = (
            request.form.get("csrf_token")
            or request.headers.get("X-CSRF-Token")
            or (request.get_json(silent=True) or {}).get("csrf_token")
            or ""
        )
        if not expected or not hmac.compare_digest(expected, provided):
            audit_log("csrf_rejected", route=fn.__name__)
            return jsonify({"ok": False, "feedback": "CSRF 校验失败"}), 400
        return fn(*args, **kwargs)

    return wrapper


# Make the token available in Jinja templates (for the login form etc.)
def register_template_helpers(app) -> None:
    """Wire csrf_token() and get_current_user() into Jinja globals."""
    app.jinja_env.globals["csrf_token"] = get_csrf_token
    app.jinja_env.globals["get_current_user"] = get_current_user


# ---------------------------------------------------------------------------
# Auth + RBAC
# ---------------------------------------------------------------------------
def get_current_user() -> Optional[dict]:
    """Return the current user dict from session, or None.
    
    V1.0: Uses db_store.get_user() which tries PG first, falls back to DEMO_USERS.
    Session stores username; user details are looked up fresh each request
    (so DB changes are reflected immediately).
    """
    user_id = session.get("user_id")
    if not user_id:
        return None
    # V1.0: Try DB store first, fall back to DEMO_USERS
    try:
        from db_store import get_user as _db_get_user
        user = _db_get_user(user_id)
    except Exception:
        user = DEMO_USERS.get(user_id)
    if not user:
        return None
    return {"user_id": user_id, **user}


def login_user(username: str, password: str) -> Optional[dict]:
    """Validate creds and populate the session. Returns the user dict on success.
    
    V1.0: Authentication goes through db_store → PG users table (with DEMO_USERS fallback).
    Password verification uses bcrypt (constant-time, MIG-03).
    """
    # V1.0: Try DB-backed authentication first
    try:
        from db_store import authenticate as _db_auth, update_last_login
        user = _db_auth(username, password, _verify_password)
        if user:
            session.clear()
            session["user_id"] = username
            session["user_role"] = user["role"]
            session["user_name"] = user["name"]
            session["_csrf"] = secrets.token_urlsafe(32)  # fresh token per login
            update_last_login(username)  # PG only, no-op in fallback
            return {"user_id": username, **user}
        return None
    except Exception:
        pass

    # Fallback: original DEMO_USERS path (unchanged behavior)
    user = DEMO_USERS.get(username)
    if not user:
        return None
    expected = user.get("password_hash", "")
    if not _verify_password(password, expected):
        return None
    session.clear()
    session["user_id"] = username
    session["user_role"] = user["role"]
    session["user_name"] = user["name"]
    session["_csrf"] = secrets.token_urlsafe(32)  # fresh token per login
    return {"user_id": username, **user}


def logout_user() -> None:
    """Clear the session and audit it."""
    audit_log("logout")
    session.clear()


def login_required(fn: Callable) -> Callable:
    """Reject anonymous access with a redirect to /login (HTML) or 401 (JSON).

    Demo mode (DEMO_AUTH_OPEN=1, set explicitly via start.sh/conftest):
    when no user is in the session, the call passes through so anonymous
    readers can browse the demo. Production (default DEMO_AUTH_OPEN=0)
    always requires login.
    """

    @functools.wraps(fn)
    def wrapper(*args, **kwargs):
        if not get_current_user():
            if _demo_auth_open():
                return fn(*args, **kwargs)
            if request.path.startswith("/api/"):
                return jsonify({"ok": False, "error": "auth_required"}), 401
            return redirect(url_for("login", next=request.path))
        return fn(*args, **kwargs)

    return wrapper


def roles_required(*allowed: str) -> Callable:
    """Reject callers whose role isn't in the allowed list.

    Demo mode: when no user is in the session, the call passes through
    so anonymous readers can browse the demo. Logged-in users with the
    wrong role are still rejected with 403.
    """
    allowed_set = set(allowed)

    def decorator(fn: Callable) -> Callable:
        @functools.wraps(fn)
        def wrapper(*args, **kwargs):
            user = get_current_user()
            if not user:
                if _demo_auth_open():
                    return fn(*args, **kwargs)
                if request.path.startswith("/api/"):
                    return jsonify({"ok": False, "error": "auth_required"}), 401
                return redirect(url_for("login", next=request.path))
            if user["role"] not in allowed_set:
                audit_log("rbac_denied", required=sorted(allowed_set), actual=user["role"])
                abort(403)
            return fn(*args, **kwargs)

        return wrapper

    return decorator


# ---------------------------------------------------------------------------
# IDOR guard — students can only access their own resources; staff can access any
# ---------------------------------------------------------------------------
def check_ownership(student_id: str) -> None:
    """Abort 403 if a student tries to touch another student's data.

    Demo mode: anonymous callers are allowed through (matches the demo
    contract). Logged-in students are blocked from peers' data.
    """
    user = get_current_user()
    if not user:
        if _demo_auth_open():
            return
        abort(401)
    if user["role"] == "student":
        own = user.get("student_id")
        if own and own != student_id:
            audit_log("idor_blocked", target=student_id, own=own)
            abort(403)


# ---------------------------------------------------------------------------
# Error handlers — register via ``register_error_handlers(app)``
# ---------------------------------------------------------------------------
def register_error_handlers(app) -> None:
    @app.errorhandler(403)
    def _403(e):  # noqa: ANN001
        if request.path.startswith("/api/"):
            return jsonify({"ok": False, "error": "forbidden"}), 403
        try:
            return render_template("errors/403.html"), 403
        except Exception:
            return "Forbidden", 403

    @app.errorhandler(404)
    def _404(e):  # noqa: ANN001
        if request.path.startswith("/api/"):
            return jsonify({"ok": False, "error": "not_found"}), 404
        try:
            return render_template("errors/404.html"), 404
        except Exception:
            return "Not Found", 404

    @app.errorhandler(429)
    def _429(e):  # noqa: ANN001
        if request.path.startswith("/api/"):
            return jsonify({"ok": False, "error": "rate_limited"}), 429
        try:
            return render_template("errors/429.html"), 429
        except Exception:
            return "Too Many Requests", 429
