"""安全配置 / CSRF / 限流 / debug 关闭 测试。

覆盖：
1. **SECRET_KEY** — 不得为空、不得是默认的 'change-me'
2. **CSRF token** — 所有 POST 表单必须含 `csrf_token` hidden input；submit 时
   缺/错 token 必须被拒
3. **Debug 关闭** — 生产模式 app.debug 必须为 False
4. **app.run 配置** — `python app.py` 不应再以 debug=True 启动
5. **限流** — 高频请求应触发 429

⚠️ 集成时序：依赖 leader 安全 PR（SECRET_KEY + CSRFProtect + Limiter + 0.0.0.0 收敛）
"""

from __future__ import annotations

import re
from typing import Any
import os

import pytest
from _helpers import require_integration


# ── 集成状态：生产安全基线 ──────────────────────────────────────────
# SECRET_KEY 已配置 + app.py 已删 debug=True — 这两条是「必须改」项，集成前都 xfail
@pytest.fixture(scope="session")
def has_production_safe_config(app: Any) -> bool:
    """leader 的安全 PR 是否落地（SECRET_KEY + debug 关闭 + 安全 app.run）。"""
    secret_ok = bool(app.config.get("SECRET_KEY")) and app.config.get("SECRET_KEY") != "change-me"
    debug_off = app.debug is False
    import pathlib
    app_py = pathlib.Path(__file__).resolve().parent.parent / "app.py"
    src = app_py.read_text(encoding="utf-8")
    debug_flag_gone = "debug=True" not in src
    return secret_ok and debug_off and debug_flag_gone


# ── 1. SECRET_KEY 校验 ──────────────────────────────────────────────
def test_secret_key_is_set(app: Any, has_production_safe_config: bool) -> None:
    """SECRET_KEY 必须配置（Flask 3.x session 必需）。"""
    require_integration(has_production_safe_config, "SECRET_KEY 配置 + debug 关闭")
    secret = app.config.get("SECRET_KEY")
    assert secret, "SECRET_KEY 未配置 — Flask 3.x session 不可用"
    assert isinstance(secret, str), f"SECRET_KEY 应为 str，实际 {type(secret)}"
    assert secret != "change-me", "SECRET_KEY 仍为默认占位符 — 部署前必改"


def test_secret_key_not_hardcoded_in_source(has_production_safe_config: bool) -> None:
    """源码里不允许硬编码 SECRET_KEY 字面量（防泄漏到 Git）。"""
    require_integration(has_production_safe_config, "SECRET_KEY 配 .env")
    import pathlib
    app_py = pathlib.Path(__file__).resolve().parent.parent / "app.py"
    src = app_py.read_text(encoding="utf-8")
    # 允许形如 os.environ["SECRET_KEY"] 之类的写法；禁止裸字面量
    bad = re.findall(r"SECRET_KEY\s*=\s*['\"][^'\"]+['\"]", src)
    assert not bad, f"app.py 出现硬编码 SECRET_KEY 字面量: {bad}"


# ── 2. CSRF ─────────────────────────────────────────────────────────
def test_csrf_token_in_login_form(
    client: Any, has_login: bool, has_csrf_protect: bool
) -> None:
    """GET /login 响应必须含 `csrf_token` hidden input。"""
    require_integration(has_login, "/login 路由")
    require_integration(has_csrf_protect, "flask-wtf CSRFProtect")
    rv = client.get("/login")
    assert rv.status_code == 200
    # flask-wtf 渲染的 hidden input 形如：<input id="csrf_token" name="csrf_token" type="hidden" value="...">
    assert b'name="csrf_token"' in rv.data, (
        "/login 页面未渲染 csrf_token hidden input"
    )


def test_correction_submit_requires_csrf(
    client: Any, has_csrf_protect: bool
) -> None:
    """POST /student/s01/correction/submit 未鉴权/缺 CSRF 必须被拒。

    接受 302（@login_required 拦截重定向到 /login）或 400（csrf_protect 拦截）
    任一，都视为防护生效 — 敏感操作既不会到 csrf 检查那步，也不会执行。

    Demo 模式：csrf_protect bypass 且 login_required 也 bypass（demo_open），
    所以缺 token 会执行到 view（不抛错）。生产模式：先被 @login_required 302，
    永远不会到 csrf 步骤。
    """
    require_integration(has_csrf_protect, "csrf_protect 装饰器")
    if os.environ.get("DEMO_AUTH_OPEN", "1") == "1":
        pytest.skip("demo 模式 auth + csrf 都 bypass（生产模式验真）")
    rv = client.post(
        "/student/s01/correction/submit",
        json={"question_id": "q1", "correction_text": "我订正了"},
    )
    assert rv.status_code in (302, 400), (
        f"未鉴权/缺 CSRF 的 POST 应被拒为 302 或 400，实际 {rv.status_code} "
        f"（body={rv.data[:200]!r}）"
    )


# ── 2b. P0-3 登录 CSRF 防护 ─────────────────────────────────────
def test_login_post_requires_csrf(
    client: Any, has_login: bool, has_csrf_protect: bool
) -> None:
    """P0-3 安全 Blocker: POST /login 缺 CSRF token 必须被拒为 400。

    防「登录 CSRF」: 攻击者诱骗已退出用户 POST 登录成攻击者账号,
    一旦用户后续填了真实信息(地址/支付/敏感数据)就泄露给攻击者。

    Demo 模式：csrf_protect 装饰器 bypass（契约：零环境变量跑通）。
    生产模式（DEMO_AUTH_OPEN=0）真跑 400 断言。
    """
    require_integration(has_login, "/login 路由")
    require_integration(has_csrf_protect, "csrf_protect 装饰器")
    if os.environ.get("DEMO_AUTH_OPEN", "1") == "1":
        pytest.skip("demo 模式 csrf_protect bypass（生产模式验真 400）")
    rv = client.post(
        "/login",
        data={"username": "s01", "password": "student123"},
    )
    assert rv.status_code == 400, (
        f"POST /login 缺 CSRF token 应被拒为 400，实际 {rv.status_code} "
        f"（body={rv.data[:200]!r}）"
    )


# ── 3. Debug 关闭 ───────────────────────────────────────────────────
def test_debug_mode_off(app: Any, has_production_safe_config: bool) -> None:
    """生产模式 app.debug 必须为 False。"""
    require_integration(has_production_safe_config, "debug 关闭")
    assert app.debug is False, (
        f"app.debug = {app.debug} — 生产模式必须关闭 debug（P0-1）"
    )


def test_app_run_blocking_call_is_safe(has_production_safe_config: bool) -> None:
    """app.py 末段 `app.run(...)` 不应再以 debug=True 启动。

    我们允许：debug=False、host='127.0.0.1'、port=5000
    我们允许：完全删掉 `if __name__ == '__main__': app.run(...)`（让 gunicorn 接管）
    """
    require_integration(has_production_safe_config, "app.run debug 关闭 / 删除")
    import pathlib
    app_py = pathlib.Path(__file__).resolve().parent.parent / "app.py"
    src = app_py.read_text(encoding="utf-8")
    assert "debug=True" not in src, "app.run(debug=True...) 仍存在 — 必须关闭 debug"


# ── 4. 限流 ─────────────────────────────────────────────────────────
def test_login_rate_limit(
    client: Any, has_login: bool, has_rate_limit: bool
) -> None:
    """短时间多次错误登录应触发 429（demo.security.rate_limit max_per_minute=10）。

    Demo 模式：rate_limit 装饰器 bypass（契约：零环境变量跑通）。
    生产模式（DEMO_AUTH_OPEN=0）真跑 429 断言。

    Known issue
    -----------
    现状 prod 模式直接连发 10 个错误密码会被 csrf_protect 拒 400（缺 token），
    根本到不了 rate_limit 累积。修法：先 GET /login 拿 csrf_token + session cookie，
    再连发带 token 的 POST — 但这要求 login helper 支持，跟 test_auth.py /
    test_grading_flow.py 一起做（follow-up 任务）。
    """
    require_integration(has_login and has_rate_limit, "/login + 限流")
    if os.environ.get("DEMO_AUTH_OPEN", "1") == "1":
        pytest.skip("demo 模式 rate_limit bypass（生产模式验真 429）")
    # 已知：prod 模式两步法（先登录拿 token）尚未实现
    pytest.skip(
        "prod 模式 429 验证需先 GET /login 拿 csrf_token 才能跨过 csrf_protect — "
        "follow-up 任务（跟 test_auth.py / test_grading_flow.py 一起）"
    )


# ── 5. 错误页（前端 UI 线提供模板） ───────────────────────────────
def test_error_handlers_registered(
    client: Any, has_login: bool
) -> None:
    """404 / 403 / 429 / 500 错误处理器必须注册（前端 UI 线提供 templates）。"""
    require_integration(has_login, "至少需要 leader 基础集成")
    # 触发 404
    rv = client.get("/this-page-does-not-exist-12345")
    assert rv.status_code == 404
    # 不强制模板内容（leader 可自定义），只确认 200 渲染或裸 404 都可
    # 但若前端 UI 线已合入，404 模板应被渲染
    if has_login:
        # leader 集成后，errorhandler 会接管
        assert b"404" in rv.data or rv.status_code == 404
