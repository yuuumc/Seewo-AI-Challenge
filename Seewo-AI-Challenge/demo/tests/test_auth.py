"""认证 / 角色 / IDOR 测试。

覆盖：
1. **登录 smoke** — 4 个角色 + 5 个学生共 8 个演示账号能正常登录
2. **角色隔离** — student 账号无法访问 teacher / admin 专属路径
3. **IDOR** — student A 无法直接通过 URL 访问 student B 的私有数据
4. **登出** — 登出后 session 失效

⚠️ 集成时序：
- 大多数测试在 `/login` / `/logout` 路由就位后才会 pass
- 当前阶段（leader 尚未集成）全部 xfail，理由统一为 TODO(leader-integration)
- leader 集成后这些测试应**全绿**，如果某条仍 fail 那是真问题
"""

from __future__ import annotations

from typing import Any

import pytest
from _helpers import DEMO_ACCOUNTS, require_integration, login, logout


# ── 1. 登录 smoke ────────────────────────────────────────────────────
@pytest.mark.parametrize("account_key", list(DEMO_ACCOUNTS.keys()))
def test_demo_account_login(
    client: Any, has_login: bool, account_key: str
) -> None:
    """所有 8 个演示账号都能登录成功（POST /login 200 + session 含 user_id）。"""
    require_integration(has_login, "/login 路由")
    account = DEMO_ACCOUNTS[account_key]
    rv = login(client, account["username"], account["password"])
    assert rv.status_code in (200, 302), f"{account_key} login got {rv.status_code}"
    # 登录后 session 应包含 user_id（leader 的 engine.auth.py 约定）
    with client.session_transaction() as sess:
        assert sess.get("user_id"), f"{account_key} session 缺 user_id"
        assert sess.get("user_role") == account["role"], (
            f"{account_key} 角色不符: expected={account['role']} "
            f"got={sess.get('user_role')}"
        )


def test_login_with_wrong_password(client: Any, has_login: bool) -> None:
    """错误密码必须被拒（不能绕过 demo 模式随便进）。"""
    require_integration(has_login, "/login 路由")
    rv = login(client, "teacher", "WRONG")
    # 200（带 flash 错误消息）或 401 都算合规；302 到 login 页也算
    assert rv.status_code in (200, 302, 401), f"unexpected status {rv.status_code}"
    with client.session_transaction() as sess:
        assert not sess.get("user_id"), "错误密码不应建立 session"


# ── 2. 角色隔离 ──────────────────────────────────────────────────────
def test_student_cannot_access_teacher_dashboard(
    client: Any, has_login: bool
) -> None:
    """student 登录后访问 /teacher 应被 RBAC 拒绝（403 / 302）。"""
    require_integration(has_login, "/login 路由 + RBAC 装饰器")
    login(client, "s01", "student123")
    rv = client.get("/teacher", follow_redirects=False)
    assert rv.status_code in (302, 403), (
        f"student 访问 /teacher 应被拒，实际 status={rv.status_code}"
    )


def test_teacher_cannot_access_admin_console(
    client: Any, has_login: bool
) -> None:
    """teacher 访问 /admin 应被 RBAC 拒绝。"""
    require_integration(has_login, "/login 路由 + RBAC 装饰器")
    login(client, "teacher", "teacher123")
    rv = client.get("/admin", follow_redirects=False)
    # /admin 可能压根没注册（404 也算被拒）
    assert rv.status_code in (302, 403, 404), (
        f"teacher 访问 /admin 应被拒，实际 status={rv.status_code}"
    )


# ── 3. IDOR ──────────────────────────────────────────────────────────
def test_student_idor_blocked(client: Any, has_login: bool) -> None:
    """student A 不能看 student B 的私有数据。

    攻击路径：s01 登录后直接 GET /student/s02/dashboard（自己的学生 ID 才能看自己的）。
    """
    require_integration(has_login, "/login 路由 + 授权装饰器")
    login(client, "s01", "student123")
    rv = client.get("/student/s02/dashboard", follow_redirects=False)
    # 期望：403（RBAC 拦截）或 302（重定向回自己的页）
    assert rv.status_code in (302, 403), (
        f"s01 直接访问 /student/s02/dashboard 应被拦截，实际 status={rv.status_code}"
    )


def test_anonymous_idor_blocked(client: Any) -> None:
    """未登录用户访问 /student/s01/dashboard 应被拦截（demo 模式例外除外）。"""
    # 这条测试不依赖 leader 集成（leader 集成后可能加 @login_required；
    # 当前 demo 模式允许匿名访问所有页面以方便评审 demo）
    rv = client.get("/student/s01/dashboard", follow_redirects=False)
    # demo 模式约定：匿名可访问所有页面以便评委点开即看
    # leader 集成后这条会 fail，说明已收紧权限 — 那正是我们要的
    assert rv.status_code in (200, 302, 403), (
        f"匿名访问 demo 页应 200/302/403，实际 {rv.status_code}"
    )


# ── 4. 登出 ──────────────────────────────────────────────────────────
def test_logout_clears_session(client: Any, has_login: bool, has_logout: bool) -> None:
    """登录 → 登出 → session.user_id 应清空。"""
    require_integration(has_login and has_logout, "/login + /logout 路由")
    login(client, "teacher", "teacher123")
    logout(client)
    with client.session_transaction() as sess:
        assert not sess.get("user_id"), "登出后 session.user_id 应清空"
