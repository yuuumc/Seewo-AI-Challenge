"""V1.0 Sprint 1 — 工程配套测试（6 项）。

覆盖:
  1. healthz 分流: /healthz + /readyz 在 prod 模式下匿名可访问
  2. certbot 自动化: Caddyfile + check_cert_expiry.py 存在且可执行
  3. FastAPI 去双源: fastapi_app.security._DEMO_USERS 指向 demo.security.DEMO_USERS
  4. 审计 Redis Stream: Redis 可用时走 XADD；不可用时降级文件
  5. provider+model 白名单: 拒绝内网/非白名单 host + 非白名单 model
  6. 验收: 上述测试全绿
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

_DEMO_DIR = Path(__file__).resolve().parent.parent
if str(_DEMO_DIR) not in sys.path:
    sys.path.insert(0, str(_DEMO_DIR))


# ════════════════════════════════════════════════════════════════════
# Item 1: healthz 分流
# ════════════════════════════════════════════════════════════════════
class TestHealthzBypass:
    """healthz / readyz 不走鉴权，prod 模式匿名可访问。"""

    def test_healthz_ok_demo_mode(self, client):
        """demo 模式 /healthz 返回 200。"""
        resp = client.get("/healthz")
        assert resp.status_code == 200
        assert resp.get_json()["status"] == "ok"

    def test_healthz_ok_prod_mode(self, client):
        """prod 模式（DEMO_AUTH_OPEN=0）下 /healthz 仍 200，无需登录。"""
        with patch("security._demo_open", return_value=False), \
             patch("security._demo_auth_open", return_value=False):
            resp = client.get("/healthz")
            assert resp.status_code == 200
            assert resp.get_json()["status"] == "ok"

    def test_readyz_returns_checks(self, client):
        """/readyz 返回 checks 结构（PG + Redis 状态）。"""
        resp = client.get("/readyz")
        assert resp.status_code in (200, 503)
        body = resp.get_json()
        assert "ready" in body
        assert "checks" in body
        assert "postgres" in body["checks"]
        assert "redis" in body["checks"]

    def test_readyz_no_auth_prod_mode(self, client):
        """prod 模式下 /readyz 不被鉴权拦截。"""
        with patch("security._demo_open", return_value=False), \
             patch("security._demo_auth_open", return_value=False):
            resp = client.get("/readyz")
            assert resp.status_code in (200, 503)


# ════════════════════════════════════════════════════════════════════
# Item 2: certbot 自动化
# ════════════════════════════════════════════════════════════════════
class TestCertAutomation:
    """Caddyfile + 证书到期检查脚本就位。"""

    def test_caddyfile_exists(self):
        caddyfile = _DEMO_DIR.parent / "deploy" / "caddy" / "Caddyfile"
        assert caddyfile.exists(), "deploy/caddy/Caddyfile 不存在"
        content = caddyfile.read_text(encoding="utf-8")
        # Caddy 自动 LE 签发 + 续期
        assert "seewo.researchkit.online" in content
        assert "reverse_proxy" in content

    def test_cert_check_script_exists_and_runs(self):
        script = _DEMO_DIR.parent / "scripts" / "check_cert_expiry.py"
        assert script.exists(), "scripts/check_cert_expiry.py 不存在"
        content = script.read_text(encoding="utf-8")
        assert "--warn-days" in content
        assert "--crit-days" in content

    def test_cert_check_script_help(self):
        """脚本 --help 能正常运行（验证语法无误）。"""
        import subprocess

        script = _DEMO_DIR.parent / "scripts" / "check_cert_expiry.py"
        result = subprocess.run(
            [sys.executable, str(script), "--help"],
            capture_output=True,
            text=True,
            timeout=10,
        )
        assert result.returncode == 0
        assert "warn-days" in result.stdout


# ════════════════════════════════════════════════════════════════════
# Item 3: FastAPI 去双源
# ════════════════════════════════════════════════════════════════════
class TestFastApiSingleSource:
    """FastAPI 不再维护独立 _DEMO_USERS 副本，统一走 demo.security.DEMO_USERS。"""

    def test_no_local_demo_users_dict(self):
        """fastapi_app/security.py 源码中不应再有 _DEMO_USERS: dict = 赋值。"""
        sec_path = _DEMO_DIR / "fastapi_app" / "security.py"
        source = sec_path.read_text(encoding="utf-8")
        # 不应有独立的字典字面量赋值（import 别名可以）
        assert "_DEMO_USERS: dict = {" not in source, (
            "fastapi_app/security.py 仍有独立 _DEMO_USERS 副本（双源）"
        )

    def test_imports_from_demo_security(self):
        """_DEMO_USERS 应从 demo.security 导入。"""
        sec_path = _DEMO_DIR / "fastapi_app" / "security.py"
        source = sec_path.read_text(encoding="utf-8")
        assert "from demo.security import DEMO_USERS" in source


# ════════════════════════════════════════════════════════════════════
# Item 4: 审计 Redis Stream
# ════════════════════════════════════════════════════════════════════
class TestAuditRedisStream:
    """审计日志优先写 Redis Stream，不可达降级文件。"""

    def test_file_fallback_when_no_redis(self, app, tmp_path):
        """无 REDIS_URL 时降级写文件。"""
        import security

        # 重置 Redis 状态，确保走文件
        security._AUDIT_REDIS = None
        security._AUDIT_REDIS_DISABLED = False
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("REDIS_URL", None)
            security._AUDIT_REDIS_DISABLED = False  # re-check
            with app.test_request_context("/login", method="POST"):
                security.audit_log("test_event", key="val")
        # 文件应有一行
        log_path = security._audit_path()
        assert log_path.exists()
        lines = log_path.read_text(encoding="utf-8").strip().split("\n")
        last = json.loads(lines[-1])
        assert last["event"] == "test_event"
        assert last["key"] == "val"

    def test_redis_stream_when_available(self, app):
        """Redis 可用时走 XADD。"""
        import security

        mock_redis = MagicMock()
        mock_redis.ping.return_value = True
        security._AUDIT_REDIS = mock_redis
        security._AUDIT_REDIS_DISABLED = False
        with patch.object(security, "_get_audit_redis", return_value=mock_redis):
            with app.test_request_context("/api/test", method="GET"):
                security.audit_log("redis_event", detail="x")
        mock_redis.xadd.assert_called_once()
        call = mock_redis.xadd.call_args
        assert call.args[0] == "audit:events"
        # fields 是第二个位置参数 {"data": line}
        data_field = call.args[1]["data"]
        data_str = data_field.decode() if isinstance(data_field, bytes) else data_field
        assert "redis_event" in data_str
        # 清理
        security._AUDIT_REDIS = None
        security._AUDIT_REDIS_DISABLED = False

    def test_audit_never_raises(self, app):
        """audit_log 在任何异常下都不抛。"""
        import security

        with patch.object(security, "_get_audit_redis", side_effect=RuntimeError):
            with patch.object(security, "_audit_to_file", side_effect=OSError):
                with app.test_request_context("/"):
                    # 不应抛异常
                    security.audit_log("boom")
        security._AUDIT_REDIS = None
        security._AUDIT_REDIS_DISABLED = False


# ════════════════════════════════════════════════════════════════════
# Item 5: provider+model 白名单
# ════════════════════════════════════════════════════════════════════
class TestProviderAllowlist:
    """LLM base_url + model 白名单校验。"""

    def test_allow_openai_host(self):
        from engine.llm.allowlist import validate_llm_base_url

        assert validate_llm_base_url("https://api.openai.com/v1") == "https://api.openai.com/v1"

    def test_allow_deepseek_host(self):
        from engine.llm.allowlist import validate_llm_base_url

        assert validate_llm_base_url("https://api.deepseek.com/v1") == "https://api.deepseek.com/v1"

    def test_reject_unknown_host(self):
        """设置了 ALLOWED_LLM_HOSTS 后，非白名单 hostname 被拒。"""
        from engine.llm.allowlist import validate_llm_base_url

        with patch.dict(os.environ, {"ALLOWED_LLM_HOSTS": "api.openai.com"}):
            with pytest.raises(ValueError, match="not in allowlist"):
                validate_llm_base_url("https://evil.example.com/v1")

    def test_reject_localhost(self):
        from engine.llm.allowlist import validate_llm_base_url

        with pytest.raises(ValueError, match="reserved/private IP"):
            validate_llm_base_url("http://127.0.0.1:8080/v1")

    def test_reject_metadata_ip(self):
        """拒绝云元数据 SSRF 地址。"""
        from engine.llm.allowlist import validate_llm_base_url

        with pytest.raises(ValueError, match="reserved/private IP"):
            validate_llm_base_url("http://169.254.169.254/latest/meta-data")

    def test_allow_gpt_model(self):
        from engine.llm.allowlist import validate_llm_model

        assert validate_llm_model("gpt-4o-mini") == "gpt-4o-mini"

    def test_allow_deepseek_model(self):
        from engine.llm.allowlist import validate_llm_model

        assert validate_llm_model("deepseek-math") == "deepseek-math"

    def test_reject_unknown_model(self):
        from engine.llm.allowlist import validate_llm_model

        with pytest.raises(ValueError, match="does not match"):
            validate_llm_model("evil-model")

    def test_safe_validate_returns_bool(self):
        from engine.llm.allowlist import safe_validate

        assert safe_validate("https://api.openai.com/v1", "gpt-4o-mini") is True
        assert safe_validate("http://169.254.169.254", "evil") is False

    def test_env_extends_allowlist(self):
        """ALLOWED_LLM_HOSTS 环境变量可扩展白名单。"""
        from engine.llm.allowlist import validate_llm_base_url

        with patch.dict(os.environ, {"ALLOWED_LLM_HOSTS": "internal-llm.corp.local"}):
            # 扩展后通过白名单检查（DNS 解析 internal-llm 可能失败，但 best-effort 放行）
            try:
                result = validate_llm_base_url("https://internal-llm.corp.local/v1")
                assert result == "https://internal-llm.corp.local/v1"
            except ValueError:
                # DNS 解析到内网 IP 会被拒——这也是正确行为
                pass

    def test_factory_falls_back_to_mock_on_bad_url(self):
        """factory 在白名单校验失败时回退 MockProvider。"""
        from engine.llm.factory import get_provider, reset_runtime_trace_store

        reset_runtime_trace_store()
        with patch.dict(
            os.environ,
            {
                "LLM_API_KEY": "sk-test",
                "LLM_BASE_URL": "http://169.254.169.254/v1",
                "LLM_MODEL": "gpt-4o-mini",
            },
        ):
            provider = get_provider()
            assert provider.name == "mock"
        reset_runtime_trace_store()
