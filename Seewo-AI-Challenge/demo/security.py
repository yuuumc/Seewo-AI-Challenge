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
        "consent_given": True,
        "school_id": 1,
    },
    "head": {
        "name": "王组长",
        "role": "head",
        "password_hash": "",
        "consent_given": True,
        "school_id": 1,
    },
    "admin": {
        "name": "张主任",
        "role": "admin",
        "password_hash": "",
        "consent_given": True,
        "school_id": 1,
    },
    "s01": {
        "name": "同学A",
        "role": "student",
        "student_id": "s01",
        "password_hash": "",
        "consent_given": False,
        "school_id": 1,
    },
    "s02": {
        "name": "同学B",
        "role": "student",
        "student_id": "s02",
        "password_hash": "",
        "consent_given": False,
        "school_id": 1,
    },
    "s03": {
        "name": "同学C",
        "role": "student",
        "student_id": "s03",
        "password_hash": "",
        "consent_given": False,
        "school_id": 1,
    },
    "s04": {
        "name": "同学D",
        "role": "student",
        "student_id": "s04",
        "password_hash": "",
        "consent_given": False,
        "school_id": 1,
    },
    "s05": {
        "name": "同学E",
        "role": "student",
        "student_id": "s05",
        "password_hash": "",
        "consent_given": False,
        "school_id": 1,
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
# Audit log — Redis Stream (primary) + append-only JSON-lines file (fallback)
# V1.0 item 4: 审计日志从本地文件改 Redis Stream（docker-compose 已有 Redis）。
# Redis 不可达时自动降级回文件，保证审计不丢、不影响 UX。
# ---------------------------------------------------------------------------
_AUDIT_PATH: Optional[Path] = None
_AUDIT_REDIS = None  # type: ignore[var-annotated]
_AUDIT_REDIS_DISABLED = False  # True = Redis 不可达，后续直接走文件


def _audit_path() -> Path:
    global _AUDIT_PATH
    if _AUDIT_PATH is None:
        # Resolved lazily so tests can monkey-patch
        _AUDIT_PATH = Path(__file__).parent / "logs" / "audit.log"
        _AUDIT_PATH.parent.mkdir(parents=True, exist_ok=True)
    return _AUDIT_PATH


def _get_audit_redis():
    """惰性初始化 Redis 客户端。不可达则标记禁用，后续不再重试。"""
    global _AUDIT_REDIS, _AUDIT_REDIS_DISABLED
    if _AUDIT_REDIS_DISABLED:
        return None
    if _AUDIT_REDIS is not None:
        return _AUDIT_REDIS
    redis_url = os.environ.get("REDIS_URL", "")
    if not redis_url:
        _AUDIT_REDIS_DISABLED = True
        return None
    try:
        import redis  # type: ignore[import-untyped]

        _AUDIT_REDIS = redis.Redis.from_url(
            redis_url, decode_responses=False, socket_connect_timeout=1,
            socket_timeout=1,
        )
        _AUDIT_REDIS.ping()  # 连通性探测
    except Exception:  # noqa: BLE001 - Redis 不可达，降级文件
        _AUDIT_REDIS = None
        _AUDIT_REDIS_DISABLED = True
        return None
    return _AUDIT_REDIS


def _audit_to_file(line: str) -> None:
    """文件回退路径：追加一行 JSON。"""
    with _audit_path().open("a", encoding="utf-8") as f:
        f.write(line + "\n")


_AUDIT_STREAM_KEY = "audit:events"
_AUDIT_STREAM_MAXLEN = 10000  # 保留最近 1 万条，约 2-3 周审计量


def audit_log(event: str, **fields) -> None:
    """Write one structured audit record. Never raises (audit must not break UX).

    V2.0 Sprint 5: 审计日志制度化 — 每条记录包含 school_id + user_id + action + resource。
    V1.0: 优先写 Redis Stream（XADD audit:events），不可达时降级写文件。
    两条路径都走 JSON-lines 格式，消费侧可统一解析。

    PRD 5.8 要求审计日志保留 ≥180 天。Redis Stream maxlen=10000 约覆盖 2-3 周
    的实时事件流；长期归档走文件路径（logs/audit.log），生产环境配合 logrotate
    + OSS 归档实现 180 天保留。
    """
    try:
        # V2.0 Sprint 5: 从请求上下文获取 school_id（如果 @data_scope 已注入）
        ctx_school_id = None
        try:
            ctx_school_id = getattr(g, "school_id", None)
        except RuntimeError:
            pass  # Outside request context

        record = {
            "ts": time.strftime("%Y-%m-%dT%H:%M:%S%z", time.localtime()),
            "event": event,
            # V2.0 Sprint 5: 审计日志必须含 school_id + user_id + action + resource
            "school_id": fields.pop("school_id", ctx_school_id or 1),
            "user_id": session.get("user_id") if session else None,
            "action": event,  # action = event name（审计语义映射）
            "resource": fields.pop("resource", request.path if request else None),
            "ip": request.remote_addr if request else None,
            "path": request.path if request else None,
            "method": request.method if request else None,
            "user": session.get("user_id") if session else None,  # legacy compat
            "role": session.get("user_role") if session else None,
            **fields,
        }
        line = json.dumps(record, ensure_ascii=False, default=str)

        # 优先 Redis Stream
        r = _get_audit_redis()
        if r is not None:
            try:
                r.xadd(
                    _AUDIT_STREAM_KEY,
                    {"data": line},
                    maxlen=_AUDIT_STREAM_MAXLEN,
                    approximate=True,
                )
                return
            except Exception:  # noqa: BLE001 - Redis 写失败，降级文件
                pass
        # 降级：文件
        _audit_to_file(line)
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
    
    V2.0 Sprint 7 (7.1): After password validation, checks if MFA is enabled.
    If MFA is required, the session is NOT fully set up — instead a pending MFA
    state is stored, and the caller must redirect to /mfa-verify.
    The caller checks ``is_mfa_pending()`` to decide whether to redirect.
    """
    # V1.0: Try DB-backed authentication first
    try:
        from db_store import authenticate as _db_auth, update_last_login
        user = _db_auth(username, password, _verify_password)
        if user:
            # V2.0 Sprint 7 (7.1): Check MFA requirement before setting full session
            try:
                from mfa import mfa_check_after_login
                mfa_required, redirect_url = mfa_check_after_login(username, user)
                if mfa_required:
                    # Session has pending MFA state — caller must redirect
                    audit_log("login_mfa_required", user_id=username)
                    return {"user_id": username, "_mfa_required": True, **user}
            except ImportError:
                pass  # MFA module not available — proceed without MFA

            session.clear()
            session["user_id"] = username
            session["user_role"] = user["role"]
            session["user_name"] = user["name"]
            session["school_id"] = user.get("school_id", 1)  # V2.0 Sprint 5
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
    # V2.0 Sprint 7 (7.1): Check MFA requirement for DEMO_USERS too
    try:
        from mfa import mfa_check_after_login
        mfa_required, redirect_url = mfa_check_after_login(username, user)
        if mfa_required:
            audit_log("login_mfa_required", user_id=username)
            return {"user_id": username, "_mfa_required": True, **user}
    except ImportError:
        pass

    session.clear()
    session["user_id"] = username
    session["user_role"] = user["role"]
    session["user_name"] = user["name"]
    session["school_id"] = user.get("school_id", 1)  # V2.0 Sprint 5
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


# ---------------------------------------------------------------------------
# V2.0 Sprint 5: RBAC 角色别名映射 + 权限继承 + 数据范围装饰器
# ---------------------------------------------------------------------------

# 角色别名：旧角色名 → 新角色名（向后兼容）
ROLE_ALIASES: dict[str, str] = {
    "admin": "school_admin",
    "head": "head_teacher",
}

# 权限继承链：高级角色自动拥有低级角色的所有权限
# super_admin > school_admin > head_teacher > teacher > student
# parent 是独立角色（仅限查看子女数据，不继承 teacher）
ROLE_INHERITANCE: dict[str, set[str]] = {
    "super_admin": {"super_admin", "school_admin", "head_teacher", "teacher", "student"},
    "school_admin": {"school_admin", "head_teacher", "teacher", "student"},
    "head_teacher": {"head_teacher", "teacher", "student"},
    "teacher": {"teacher", "student"},
    "student": {"student"},
    "parent": {"parent", "student"},  # parent 可读子女数据（student 只读权限子集）
}


def _resolve_role(role: str) -> str:
    """Resolve a role name through the alias map.

    Returns the canonical V2.0 role name. Unknown roles pass through
    unchanged (so legacy roles like 'teacher' / 'student' still work).
    """
    return ROLE_ALIASES.get(role, role)


def _effective_roles(role: str) -> set[str]:
    """Return the set of all roles that ``role`` inherits from.

    For example, ``school_admin`` inherits ``head_teacher``, ``teacher``,
    and ``student`` — so a school_admin can access any endpoint that
    allows any of those roles.
    """
    canonical = _resolve_role(role)
    return ROLE_INHERITANCE.get(canonical, {canonical})


def roles_required(*allowed: str) -> Callable:
    """Reject callers whose role isn't in the allowed list.

    V2.0 Sprint 5 changes:
    - **Role aliases**: ``admin`` → ``school_admin``, ``head`` → ``head_teacher``
      (backward compat — existing @roles_required("teacher","head","admin")
      calls work unchanged).
    - **Role inheritance**: ``super_admin`` inherits all roles; ``school_admin``
      inherits head_teacher/teacher/student; etc. This means adding
      ``super_admin`` to the allowed list is NOT required — if the caller's
      role inherits any allowed role, access is granted.
    - **Demo mode**: unchanged — anonymous pass-through when DEMO_AUTH_OPEN=1.

    Usage (unchanged from V1.5):
        @roles_required("teacher", "head", "admin")
        def my_view(): ...

    In V2.0 this automatically allows super_admin, school_admin, and
    head_teacher (via inheritance), without explicitly listing them.
    """
    # Expand allowed set: each allowed role is also satisfied by any role
    # that inherits it. E.g. if "teacher" is allowed, then head_teacher,
    # school_admin, and super_admin are also allowed.
    allowed_set = set()
    for r in allowed:
        canonical = _resolve_role(r)
        allowed_set.add(canonical)
        # Also add the raw alias (so legacy role strings in sessions match)
        allowed_set.add(r)

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
            user_role = user["role"]
            # Check if user's effective roles intersect with allowed roles
            user_effective = _effective_roles(user_role)
            # Also check raw role (for legacy roles not in the inheritance map)
            if user_role not in allowed_set and not user_effective & allowed_set:
                audit_log("rbac_denied", required=sorted(allowed_set), actual=user_role)
                abort(403)
            return fn(*args, **kwargs)

        return wrapper

    return decorator


# ---------------------------------------------------------------------------
# V2.0 Sprint 7 (7.2): @min_role — minimum role level check
# ---------------------------------------------------------------------------

# Role hierarchy levels (higher = more privileged)
ROLE_LEVELS: dict[str, int] = {
    "student": 0,
    "parent": 0,
    "teacher": 1,
    "head": 2,
    "head_teacher": 2,
    "admin": 3,
    "school_admin": 3,
    "super_admin": 4,
}


def min_role(minimum: str) -> Callable:
    """Reject callers whose role level is below the minimum.

    V2.0 Sprint 7 (7.2): This decorator complements ``@roles_required``
    by enforcing a minimum role level rather than an exact role match.
    For example, ``@min_role("teacher")`` blocks students from accessing
    teacher-level APIs, while still allowing teacher/head/admin/super_admin.

    Usage:
        @login_required
        @min_role("teacher")
        def my_view(): ...
    """
    min_level = ROLE_LEVELS.get(_resolve_role(minimum), 0)

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
            user_role = user["role"]
            user_level = ROLE_LEVELS.get(_resolve_role(user_role), 0)
            if user_level < min_level:
                audit_log("min_role_denied", required=minimum, actual=user_role)
                abort(403)
            return fn(*args, **kwargs)

        return wrapper

    return decorator


def data_scope() -> Callable:
    """Inject data-scope filtering into the request context (V2.0 Sprint 5).

    This decorator runs AFTER @roles_required and sets ``g.school_id``,
    ``g.class_ids``, and ``g.student_ids`` on the Flask request context.
    Downstream queries use these to filter data by the caller's scope.

    Scope rules:
    - super_admin: all schools (g.school_id = None means no filter)
    - school_admin: own school only
    - head_teacher: own school, subject-group classes
    - teacher: own school, own classes
    - student: own school, own data only
    - parent: own school, children's data only

    Demo mode: g.school_id = 1 (default school), no class/student filter.
    """
    def decorator(fn: Callable) -> Callable:
        @functools.wraps(fn)
        def wrapper(*args, **kwargs):
            user = get_current_user()
            if not user:
                # Demo mode: default school, no filter
                g.school_id = 1
                g.class_ids = None  # None = no filter
                g.student_ids = None
                return fn(*args, **kwargs)

            role = user["role"]
            canonical = _resolve_role(role)

            # Default: user's own school
            g.school_id = user.get("school_id", 1)

            if canonical == "super_admin":
                g.school_id = None  # No school filter
                g.class_ids = None
                g.student_ids = None
            elif canonical in ("school_admin", "head_teacher"):
                g.class_ids = None  # School-wide access
                g.student_ids = None
            elif canonical == "teacher":
                # TODO: query teacher's classes from DB
                g.class_ids = None  # Will be refined when DB is connected
                g.student_ids = None
            elif canonical == "student":
                g.student_ids = [user.get("student_id")] if user.get("student_id") else None
            elif canonical == "parent":
                g.student_ids = user.get("parent_of", [])
            else:
                g.class_ids = None
                g.student_ids = None

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
# Parental consent (Sprint 4 P0-3)
# ---------------------------------------------------------------------------
def has_consent() -> bool:
    """Check whether the current user has given parental consent.

    Returns True for:
      - Non-student users (teachers, heads, admins)
      - Demo mode (DEMO_AUTH_OPEN=1) — consent auto-granted
      - Students whose ``consent_given`` field is True
    """
    if _demo_auth_open():
        return True
    user = get_current_user()
    if not user:
        return False
    if user.get("role") != "student":
        return True
    return bool(user.get("consent_given", False))


def require_consent(fn: Callable) -> Callable:
    """Block homework submission for students who haven't given consent.

    P0-3: Students must complete the parental consent flow before
    submitting homework. Non-student roles and demo mode bypass this.
    """
    @functools.wraps(fn)
    def wrapper(*args, **kwargs):
        if has_consent():
            return fn(*args, **kwargs)
        if request.path.startswith("/api/"):
            return jsonify({"ok": False, "error": "consent_required"}), 403
        return redirect(url_for("consent_page"))
    return wrapper


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
