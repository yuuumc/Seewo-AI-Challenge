"""Pytest configuration & shared fixtures for the Seewo AI Challenge demo.

设计目标：
1. **强制 demo 模式** — 任何测试运行前清空 LLM_API_KEY，确保走 MockProvider
2. **容错** — leader 集成（/login 路由、CSRF、auth 模块）尚未完成时，依赖这些的
   测试自动 xfail，**不会**让 CI 红；其他可以今天就 pass 的 smoke 测试正常跑
3. **Flask test client** — 通过 `import app; app.app` 拿到 Flask 实例，模拟真实请求
4. **demo 零环境变量基线** — 不依赖任何 .env 文件，CI / 本地 / Docker 行为一致

约定：
- 所有 fixture 都 docstring 一句话说明用途
- 共享常量 / 工具放 `_helpers.py`（pytest 不允许 `from conftest import ...`）
- 集成检测用布尔值返回（`has_*`），调用方决定 xfail / skip
"""

from __future__ import annotations

import importlib
import importlib.util
import os
import sys
from pathlib import Path
from typing import Any

import pytest

# ── 路径注入（必须在 pytest 收集 test module 之前）────────────────────
# demo/ 是 Flask 根目录，测试运行时 cwd 不一定是 demo/，所以把 demo/ 加进 sys.path
_DEMO_DIR = Path(__file__).resolve().parent.parent
if str(_DEMO_DIR) not in sys.path:
    sys.path.insert(0, str(_DEMO_DIR))

# tests/ 也要进 sys.path，让 `from _helpers import ...` 能找到 _helpers.py
# （pytest 看到 __init__.py 后会把它当 package，但相对导入 `from ._helpers` 在
# collect-only 阶段需要先 package init 完成；绝对导入更稳）
_TESTS_DIR = Path(__file__).resolve().parent
if str(_TESTS_DIR) not in sys.path:
    sys.path.insert(0, str(_TESTS_DIR))


# ── 强制 demo 模式（必须在 import app 之前）─────────────────────────
# 清空 LLM 相关 env，确保 get_provider()（P1 阶段由编排工程师接入）返回 MockProvider
@pytest.fixture(autouse=True, scope="session")
def _force_demo_mode() -> None:
    """全局 autouse session fixture：清空 LLM_* env，强制走 mock 降级路径。

    MIG-02: DEMO_AUTH_OPEN 默认值已从 "1" 改为 "0"（生产安全默认）。
    测试默认在 demo 模式跑（79 passed 基线），prod 模式测试用
    DEMO_AUTH_OPEN=0 环境变量显式触发。
    """
    for key in ("LLM_API_KEY", "LLM_BASE_URL", "LLM_MODEL"):
        os.environ.pop(key, None)
    os.environ["FLASK_ENV"] = "production"
    # MIG-02: 测试默认 demo 模式（除非外部显式设 DEMO_AUTH_OPEN=0）
    if "DEMO_AUTH_OPEN" not in os.environ:
        os.environ["DEMO_AUTH_OPEN"] = "1"


# ── Flask app / test client ─────────────────────────────────────────
@pytest.fixture(scope="session")
def app() -> Any:
    """导入 demo.app 并返回 Flask 实例。

    注：当前 app.py 没有 app.config['SECRET_KEY']，leader 的安全 PR 会补上；
    我们的测试在它没补之前只对 GET 接口做 smoke，POST / CSRF 相关测试靠 has_csrf
    检测自动 xfail。
    """
    if "app" in sys.modules:
        importlib.reload(sys.modules["app"])
        return sys.modules["app"].app
    spec = importlib.util.spec_from_file_location("app", _DEMO_DIR / "app.py")
    assert spec and spec.loader, "cannot load demo/app.py"
    module = importlib.util.module_from_spec(spec)
    sys.modules["app"] = module
    spec.loader.exec_module(module)
    return module.app


@pytest.fixture()
def client(app: Any) -> Any:
    """Flask test client — 每次测试 fresh 一个，无状态共享。"""
    return app.test_client()


# ── Rate limit 重置（MIG-01: prod 模式测试隔离）───────────────────────
@pytest.fixture(autouse=True)
def _reset_rate_limit_buckets() -> None:
    """每个测试前/后重置 _RL_BUCKETS，避免 9 个登录测试串联撞限流（10/min）。

    根因：prod 模式（DEMO_AUTH_OPEN=0）下 @rate_limit 装饰器激活，且
    security._RL_BUCKETS 是 module-level dict，跨测试共享。

    ⚠️ 模块身份陷阱：app.py 用 ``from security import rate_limit``（无包前缀），
    ``demo/tests/_helpers.py`` 既有 ``import security`` 也有 ``from demo import security``。
    两套 import 会得到不同 module 对象，dict 也不一样。fixture 必须清两个：
      1. 顶层 ``security._RL_BUCKETS``（app.py 路由装饰器实际用的）
      2. ``demo.security._RL_BUCKETS``（helpers / 其他代码可能 import 的）

    生产环境不走这条路径（autouse 仅 pytest 收集时触发）。
    """
    for mod_name in ("security", "demo.security"):
        try:
            mod = __import__(mod_name, fromlist=["_RL_BUCKETS"])
            if hasattr(mod, "_RL_BUCKETS"):
                mod._RL_BUCKETS.clear()
        except ImportError:
            pass
    yield
    for mod_name in ("security", "demo.security"):
        try:
            mod = __import__(mod_name, fromlist=["_RL_BUCKETS"])
            if hasattr(mod, "_RL_BUCKETS"):
                mod._RL_BUCKETS.clear()
        except ImportError:
            pass


# ── 集成状态检测（leader PR 是否落地）────────────────────────────────
def _has_url_rule(app: Any, rule: str, methods: list[str] | None = None) -> bool:
    """检查 Flask url_map 是否包含给定 rule（可选方法过滤）。"""
    for r in app.url_map.iter_rules():
        if r.rule == rule and (methods is None or any(m in r.methods for m in methods)):
            return True
    return False


@pytest.fixture(scope="session")
def has_login(app: Any) -> bool:
    """/login 路由是否存在（leader 集成后才有）。"""
    return _has_url_rule(app, "/login", methods=["GET", "POST"])


@pytest.fixture(scope="session")
def has_logout(app: Any) -> bool:
    """/logout 路由是否存在。"""
    return _has_url_rule(app, "/logout", methods=["GET", "POST"])


@pytest.fixture(scope="session")
def has_csrf_protect(app: Any) -> bool:
    """CSRF 防护能力是否已集成。认两种实现：

    1. flask-wtf CSRFProtect（检测 ``app.extensions["csrf"]``）
    2. 自实现 ``demo.security.csrf_protect`` 装饰器挂载到 POST 路由
       （用 functools.wraps 留下 __wrapped__，fixture 只检测「有装饰」，
       不区分装饰器来源 — 误判成本低，因为 demo 模式下 csrf 装饰器 bypass
       由测试本身的 demo skip 处理）
    """
    # 1) flask-wtf
    try:
        from flask_wtf.csrf import CSRFProtect  # noqa: F401
        if "csrf" in app.extensions:
            return True
    except ImportError:
        pass
    # 2) 自实现 security.csrf_protect：检查 POST 路由 view 被装饰
    try:
        from demo import security  # noqa: F401
        if not hasattr(security, "csrf_protect"):
            return False
    except ImportError:
        return False
    for endpoint in ("logout", "submit_correction", "login"):
        vf = app.view_functions.get(endpoint)
        if vf is not None and hasattr(vf, "__wrapped__"):
            return True
    return False


@pytest.fixture(scope="session")
def has_rate_limit(app: Any) -> bool:
    """限流能力是否已集成。认两种实现：

    1. flask-limiter Limiter（检测 ``app.extensions["limiter"]``）
    2. 自实现 ``demo.security.rate_limit`` 装饰器挂载到 POST 路由
    """
    # 1) flask-limiter
    try:
        from flask_limiter import Limiter  # noqa: F401
        if "limiter" in app.extensions or any(
            getattr(ext, "__class__", type("_", (), {})).__name__ == "Limiter"
            for ext in app.extensions.values()
        ):
            return True
    except ImportError:
        pass
    # 2) 自实现 security.rate_limit
    try:
        from demo import security  # noqa: F401
        if not hasattr(security, "rate_limit"):
            return False
    except ImportError:
        return False
    for endpoint in ("login", "submit_correction"):
        vf = app.view_functions.get(endpoint)
        if vf is not None and hasattr(vf, "__wrapped__"):
            return True
    return False


@pytest.fixture(scope="session")
def has_auth_module() -> bool:
    """engine.auth 模块是否已被 leader 补上（sso / RBAC / session helpers）。"""
    try:
        importlib.import_module("engine.auth")
        return True
    except ImportError:
        return False


# ── 演示账号 fixture（与前端 UI 线约定一致）────────────────────────
# 8 个账号名/密码在 tests/_helpers.py 的 DEMO_ACCOUNTS 里 —
# 拆出 _helpers.py 是因为 pytest 不允许 `from conftest import ...`


@pytest.fixture()
def demo_accounts() -> dict[str, dict[str, str]]:
    """返回 8 个演示账号（4 角色 + 5 学生）的明文清单。

    测试代码用其做登录 / IDOR 校验；**不要**在 fixture 内部做登录，
    留给具体测试自己跑 client.post('/login', ...)。
    """
    # 延迟 import 避开循环
    from _helpers import DEMO_ACCOUNTS
    return DEMO_ACCOUNTS
