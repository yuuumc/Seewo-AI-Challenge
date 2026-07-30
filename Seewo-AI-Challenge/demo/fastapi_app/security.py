"""Phase 1 FastAPI 鉴权依赖.

把 demo/security.py 的 Flask 装饰器移植为 FastAPI Depends。
复用 Flask 的 session 签名机制（itsdangerous），不需要重复登录。

P0-6 修复要点：
  - 新增 Depends(get_current_user) 替代 Flask 装饰器链
  - 复用 Flask 签名的 session cookie，零登录切换
  - 角色 / IDOR 检查一并移植
"""
from __future__ import annotations

import functools
from typing import Callable, Optional

from fastapi import Depends, HTTPException, Request, status
from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer

from demo.fastapi_app.config import get_settings

settings = get_settings()
_session_serializer = URLSafeTimedSerializer(
    settings.flask_secret_key,
    salt="cookie-session",
    signer_kwargs={"key_derivation": "hmac", "digest_method": "sha1"},
)


# —————— Demo user 表（与 demo.security.DEMO_USERS 对齐） ——————
# Week 2 用 Phase 0 内存表，Week 3 切 PG users 表。
_DEMO_USERS: dict = {
    "teacher": {"name": "李老师", "role": "teacher"},
    "head":    {"name": "王组长", "role": "head"},
    "admin":   {"name": "张主任", "role": "admin"},
    "s01":     {"name": "同学A", "role": "student", "student_id": "s01"},
    "s02":     {"name": "同学B", "role": "student", "student_id": "s02"},
    "s03":     {"name": "同学C", "role": "student", "student_id": "s03"},
    "s04":     {"name": "同学D", "role": "student", "student_id": "s04"},
    "s05":     {"name": "同学E", "role": "student", "student_id": "s05"},
}


def _decode_flask_session(request: Request) -> Optional[dict]:
    """从 Flask 签名的 cookie 解码 session."""
    cookie = request.cookies.get("session")
    if not cookie:
        return None
    try:
        return _session_serializer.loads(cookie, max_age=86400 * 7)
    except (BadSignature, SignatureExpired):
        return None


def get_current_user(request: Request) -> dict:
    """FastAPI 依赖：返回当前登录用户；未登录或 session 失效抛 401.
    
    V1.0: Uses db_store.get_user() → PG users table (with DEMO_USERS fallback).
    Both Flask and FastAPI now share the same user source via PG.
    """
    sess = _decode_flask_session(request)
    if not sess:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Not authenticated",
            headers={"WWW-Authenticate": "Cookie"},
        )
    user_id = sess.get("user_id")
    if not user_id:
        raise HTTPException(status_code=401, detail="Invalid session: no user_id")

    # V1.0: Try PG-backed user store first, fall back to _DEMO_USERS
    user = None
    try:
        from db_store import get_user as _db_get_user
        user = _db_get_user(user_id)
    except Exception:
        pass
    if not user:
        user = _DEMO_USERS.get(user_id)
    if not user:
        raise HTTPException(status_code=401, detail=f"Unknown user: {user_id}")
    return {"user_id": user_id, **user}


def require_roles(*allowed_roles: str) -> Callable:
    """FastAPI 依赖工厂：限定角色。allowed_roles 是允许的角色集合."""
    def _checker(current_user: dict = Depends(get_current_user)) -> dict:
        if current_user.get("role") not in allowed_roles:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Role '{current_user.get('role')}' not in {list(allowed_roles)}",
            )
        return current_user
    return _checker


def require_ownership(student_id: str) -> Callable:
    """FastAPI 依赖工厂：学生只能访问自己的资源，老师/组长/管理员可访问所有."""
    def _checker(current_user: dict = Depends(get_current_user)) -> dict:
        role = current_user.get("role")
        if role in {"teacher", "head", "admin"}:
            return current_user
        if current_user.get("user_id") == student_id or current_user.get("student_id") == student_id:
            return current_user
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="IDOR: cannot access another student's resource",
        )
    return _checker


__all__ = ["get_current_user", "require_roles", "require_ownership"]
