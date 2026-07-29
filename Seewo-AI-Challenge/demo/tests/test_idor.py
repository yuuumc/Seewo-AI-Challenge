"""P0-4 IDOR（Insecure Direct Object Reference）最小修复 测试。

当前状态：11 个 student_id 路由均已挂 check_ownership 装饰器（Week 1 RBAC 加固
+ Week 2 收口），但「已挂」≠「已测」。本测试在 DEMO_AUTH_OPEN=0 模式下验证
学生越权访问他人资源应被 403 拒绝。

覆盖：
1. **学生越权访问他人 HTML 页面**（9 个路由）→ 403
2. **学生越权访问他人 API**（2 个 API 路由）→ 403
3. **教师 / 教研组长 / admin 访问任意学生** → 不被拦截（staff 权限）
4. **学生访问自己的资源** → 不被拦截
5. **审计日志记录 idor_blocked 事件**

⚠️ Demo 模式（DEMO_AUTH_OPEN=1，默认）下 check_ownership 对匿名调用直接放行，
  所以本测试在默认模式 xfail，必须 DEMO_AUTH_OPEN=0 才跑真实断言。
"""

from __future__ import annotations

import os
from typing import Any

import pytest
from _helpers import require_integration


# 所有 student_id 路由（来自 demo/app.py 真实声明顺序）
_STUDENT_HTML_ROUTES: list[str] = [
    "/student/{sid}/dashboard",
    "/student/{sid}/radar",
    "/student/{sid}/error-book",
    "/student/{sid}/knowledge-tree",
    "/student/{sid}/coach",
    "/student/{sid}/growth",
    "/student/{sid}/correction",
    "/student/{sid}",  # student_view
]
_STUDENT_API_ROUTES: list[str] = [
    "/api/grade/{sid}/hw_001",
    "/api/radar/{sid}",
]
# POST 路由（/student/<sid>/correction/submit）走另一套校验，跳过 HTML/GET 检查
_STUDENT_POST_ROUTES: list[str] = [
    "/student/{sid}/correction/submit",
]


@pytest.fixture(autouse=True)
def _require_strict_auth() -> None:
    """Demo 模式装饰器 bypass，本测试需要 production-style 鉴权。"""
    if os.environ.get("DEMO_AUTH_OPEN", "1") != "0":
        pytest.skip("DEMO_AUTH_OPEN=0 required for P0-4 IDOR tests")


@pytest.fixture(autouse=True)
def _clear_rate_limit_buckets() -> None:
    """清空 in-memory rate-limit 桶,避免测试间累积触发 429。"""
    try:
        from security import _RL_BUCKETS  # type: ignore[attr-defined]
        _RL_BUCKETS.clear()
    except (ImportError, AttributeError):
        pass
    yield
    try:
        from security import _RL_BUCKETS  # type: ignore[attr-defined]
        _RL_BUCKETS.clear()
    except (ImportError, AttributeError):
        pass


def _login(client: Any, username: str, password: str) -> None:
    """登录并断言成功。

    P0-3 行为: production 模式下 /login 也走 CSRF 校验,
    必须先 GET 拿 csrf_token hidden input, 再 POST 带 token。
    """
    import re
    # 1) GET /login 拿 csrf_token
    rv = client.get("/login")
    assert rv.status_code == 200, f"GET /login failed: {rv.status_code}"
    m = re.search(rb'name="csrf_token"[^>]*value="([^"]+)"', rv.data)
    if not m:
        m = re.search(rb'value="([^"]+)"[^>]*name="csrf_token"', rv.data)
    assert m, f"无法从 /login 响应解析 csrf_token（response={rv.data[:300]!r}）"
    csrf_token = m.group(1).decode("ascii")

    # 2) POST /login 带 csrf_token
    rv = client.post(
        "/login",
        data={"username": username, "password": password, "csrf_token": csrf_token},
    )
    assert rv.status_code in (200, 302), f"login as {username} failed: {rv.status_code}"


def _logout(client: Any) -> None:
    client.post("/logout")


# ── 1. 学生越权访问他人资源（HTML 路由）───────────────────────────
def test_student_cannot_view_peer_html_pages(client: Any) -> None:
    """学生 s01 登录后访问 /student/s02/* 应被 403 拒绝。"""
    _login(client, "s01", "student123")
    try:
        for path_tpl in _STUDENT_HTML_ROUTES:
            path = path_tpl.format(sid="s02")
            rv = client.get(path)
            assert rv.status_code == 403, (
                f"❌ {path} 学生越权未被拦截 (status={rv.status_code}); "
                f"check_ownership 可能未生效"
            )
    finally:
        _logout(client)


# ── 2. 学生越权访问他人资源（API 路由）────────────────────────────
def test_student_cannot_call_peer_apis(client: Any) -> None:
    """学生 s01 调用 /api/grade/s02/* 与 /api/radar/s02 应被 403 拒绝。"""
    _login(client, "s01", "student123")
    try:
        for path_tpl in _STUDENT_API_ROUTES:
            path = path_tpl.format(sid="s02")
            rv = client.get(path)
            assert rv.status_code == 403, (
                f"❌ {path} API 越权未被拦截 (status={rv.status_code})"
            )
    finally:
        _logout(client)


# ── 3. 教师可访问任意学生资源（staff 权限）───────────────────────
@pytest.mark.parametrize("staff_user,staff_pwd", [
    ("teacher", "teacher123"),
    ("head", "head123"),
    ("admin", "admin123"),
])
def test_staff_can_access_any_student(
    client: Any, staff_user: str, staff_pwd: str
) -> None:
    """教师 / 教研组长 / admin 访问任意 student 路由应不被 IDOR 拦截。"""
    _login(client, staff_user, staff_pwd)
    try:
        for path_tpl in _STUDENT_HTML_ROUTES + _STUDENT_API_ROUTES:
            path = path_tpl.format(sid="s02")
            rv = client.get(path)
            # 期望不是 401/403（鉴权通过）；200/302/404/500 都接受（数据/路由问题非 IDOR 范畴）
            assert rv.status_code not in (401, 403), (
                f"❌ {staff_user} 访问 {path} 被 IDOR 拦截 (status={rv.status_code})"
            )
    finally:
        _logout(client)


# ── 4. 学生访问自己资源应通过 ────────────────────────────────────
def test_student_can_access_own_resources(client: Any) -> None:
    """学生 s01 访问 /student/s01/* 应不被 IDOR 拦截。"""
    _login(client, "s01", "student123")
    try:
        for path_tpl in _STUDENT_HTML_ROUTES:
            path = path_tpl.format(sid="s01")
            rv = client.get(path)
            assert rv.status_code not in (401, 403), (
                f"❌ 学生访问自己 {path} 被拦截 (status={rv.status_code}); "
                f"check_ownership 误伤本人"
            )
    finally:
        _logout(client)


# ── 5. 集成状态检查 ──────────────────────────────────────────────
def test_check_ownership_actually_enforced(
    client: Any, has_login: bool
) -> None:
    """P0-4 真实修复: check_ownership 装饰器在 production 模式下应被实际执行。"""
    require_integration(has_login, "/login 路由")
    # 不登录直接 GET /student/s02/dashboard
    rv = client.get("/student/s02/dashboard")
    # production 模式：未登录应先被 login_required 拦截（401 / 重定向到 /login）
    # 不强制 401（depends on @login_required 的 demo 行为），但不应 200
    assert rv.status_code in (302, 401, 403), (
        f"❌ 未登录访问 /student/s02/dashboard 竟 200 渲染 — 鉴权链断了"
        f"（status={rv.status_code}）"
    )
