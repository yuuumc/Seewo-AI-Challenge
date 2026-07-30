"""Tests 包的共享辅助 — 纯函数 / 数据，不放 fixture。

⚠️ pytest 约定：`conftest.py` 里的 fixture 会被自动发现，但 `from conftest import ...`
是被禁止的（pytest 不会把 conftest 视为普通模块）。所有需要跨文件共享的**常量 / 工具**
放这里，conftest.py 只放 fixture。
"""

from __future__ import annotations

import pytest

# ── 演示账号表（与前端 UI 线 CHANGES.md §2 完全对齐） ───────────────
DEMO_ACCOUNTS: dict[str, dict[str, str]] = {
    "teacher": {"username": "teacher", "password": "teacher123", "role": "teacher"},
    "head": {"username": "head", "password": "head123", "role": "head"},
    "admin": {"username": "admin", "password": "admin123", "role": "admin"},
    "s01": {"username": "s01", "password": "student123", "role": "student"},
    "s02": {"username": "s02", "password": "student123", "role": "student"},
    "s03": {"username": "s03", "password": "student123", "role": "student"},
    "s04": {"username": "s04", "password": "student123", "role": "student"},
    "s05": {"username": "s05", "password": "student123", "role": "student"},
}


def require_integration(condition: bool, item: str) -> None:
    """统一 xfail 文案 — leader 集成后 grep `TODO(leader-integration)` 即可看清单。"""
    if not condition:
        pytest.xfail(f"TODO(leader-integration): {item} 尚未集成")


# ── 登录 / 登出 / CSRF helper（MIG-01: prod 模式 36 fail 收口）─────────
# 根因：prod 模式（DEMO_AUTH_OPEN=0）下 @csrf_protect 拦截无 token 的 POST，
# 导致 test_auth / test_grading_flow / test_teacher_api_rbac 全部 fail。
# 修复：login() 先 GET /login 触发 CSRF token 生成，再 POST 带 token。


def get_csrf_token(client) -> str:
    """从 Flask test client 的 session 中读取当前 CSRF token。"""
    with client.session_transaction() as sess:
        return sess.get("_csrf", "")


def login(client, username: str, password: str):
    """带 CSRF token 的登录 helper。

    流程：GET /login → Jinja csrf_token() 生成 session["_csrf"] →
    读取 token → POST /login 带 csrf_token 字段。

    在 demo 模式（DEMO_AUTH_OPEN=1）和 prod 模式（DEMO_AUTH_OPEN=0）下都能用。
    返回 Flask response 对象。
    """
    client.get("/login")  # 触发 CSRF token 生成
    token = get_csrf_token(client)
    return client.post(
        "/login",
        data={
            "username": username,
            "password": password,
            "csrf_token": token,
        },
        follow_redirects=False,
    )


def logout(client):
    """带 CSRF token 的登出 helper。"""
    token = get_csrf_token(client)
    return client.post(
        "/logout",
        data={"csrf_token": token},
        follow_redirects=False,
    )
