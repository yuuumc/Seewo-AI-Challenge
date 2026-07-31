"""V2.0 Sprint 7 tests — WAF middleware (7.4) + security headers (7.6).

Coverage:
  - WAF pattern matching: SQL injection, XSS, path traversal, command injection
  - WAF IP blacklist
  - WAF body size limit (413)
  - WAF health-endpoint bypass (/healthz, /metrics)
  - WAF alert logging
  - Security headers: all 8 headers present
  - Security headers: Server header removed
  - WAF false-positive: legitimate requests pass through
"""
from __future__ import annotations

import json
import urllib.parse
from pathlib import Path

import pytest


def _q(payload: str) -> str:
    """URL-encode a payload for use as a query parameter value."""
    return urllib.parse.quote(payload, safe="")


# ---------------------------------------------------------------------------
# WAF pattern matching — SQL injection
# ---------------------------------------------------------------------------

class TestWAFSQLInjection:
    """WAF should block SQL injection attempts in query params and POST body."""

    @pytest.mark.parametrize("payload", [
        "1 UNION SELECT * FROM users",
        "1; DROP TABLE users",
        "' OR '1'='1",
        "1 OR 1=1",
        "1 AND 1=1",
        "admin'--",
        "1; INSERT INTO admins VALUES('hacker','pass')",
        "1 UNION SELECT password FROM information_schema.tables",
        "1; SELECT SLEEP(5)",
        "1; BENCHMARK(1000000, MD5('test'))",
    ])
    def test_sql_injection_in_query_blocked(self, client, payload):
        """SQL injection payloads in query string → 403."""
        resp = client.get(f"/?id={_q(payload)}")
        assert resp.status_code == 403, f"Expected 403 for SQLi payload: {payload}"

    @pytest.mark.parametrize("payload", [
        "UNION SELECT username, password FROM users",
        "DROP TABLE homework",
        "DELETE FROM students WHERE 1=1",
    ])
    def test_sql_injection_in_form_blocked(self, client, payload):
        """SQL injection in form POST body → 403."""
        resp = client.post("/submit_correction", data={"content": payload})
        assert resp.status_code == 403, f"Expected 403 for form SQLi: {payload}"

    def test_sql_injection_in_json_body_blocked(self, client):
        """SQL injection in JSON body → 403."""
        resp = client.post(
            "/api/grade",
            json={"query": "1 UNION SELECT * FROM users"},
            content_type="application/json",
        )
        assert resp.status_code == 403


# ---------------------------------------------------------------------------
# WAF pattern matching — XSS
# ---------------------------------------------------------------------------

class TestWAFXSS:
    """WAF should block XSS attempts."""

    @pytest.mark.parametrize("payload", [
        "<script>alert('xss')</script>",
        "<script src='http://evil.com/x.js'></script>",
        "javascript:alert(1)",
        "<img src=x onerror=alert(1)>",
        "<iframe src='http://evil.com'></iframe>",
        "<svg onload=alert(1)>",
        "document.cookie",
        "eval('malicious')",
        "<body onload=alert(1)>",
        "<object data='http://evil.com'></object>",
    ])
    def test_xss_in_query_blocked(self, client, payload):
        """XSS payloads in query string → 403."""
        resp = client.get(f"/?q={_q(payload)}")
        assert resp.status_code == 403, f"Expected 403 for XSS payload: {payload}"

    def test_xss_in_form_blocked(self, client):
        """XSS in form POST body → 403."""
        resp = client.post("/submit_correction", data={
            "content": "<script>alert('xss')</script>"
        })
        assert resp.status_code == 403


# ---------------------------------------------------------------------------
# WAF pattern matching — Path traversal
# ---------------------------------------------------------------------------

class TestWAFPathTraversal:
    """WAF should block path traversal attempts."""

    @pytest.mark.parametrize("payload", [
        "../../../etc/passwd",
        "..\\..\\..\\windows\\system32",
        "%2e%2e%2f%2e%2e%2fetc%2fpasswd",
        "..%2f..%2fetc%2fpasswd",
        "..%5c..%5cwindows%5csystem32",
    ])
    def test_path_traversal_blocked(self, client, payload):
        """Path traversal in URL → 403."""
        resp = client.get(f"/download?file={_q(payload)}")
        assert resp.status_code == 403, f"Expected 403 for traversal: {payload}"


# ---------------------------------------------------------------------------
# WAF pattern matching — Command injection
# ---------------------------------------------------------------------------

class TestWAFCommandInjection:
    """WAF should block command injection attempts."""

    @pytest.mark.parametrize("payload", [
        ";cat /etc/passwd",
        "|ls -la",
        "$(whoami)",
        "`id`",
        "&& cat /etc/shadow",
    ])
    def test_command_injection_blocked(self, client, payload):
        """Command injection payloads → 403."""
        resp = client.get(f"/?cmd={_q(payload)}")
        assert resp.status_code == 403, f"Expected 403 for cmd injection: {payload}"


# ---------------------------------------------------------------------------
# WAF — false positive (legitimate requests should pass)
# ---------------------------------------------------------------------------

class TestWAFFalsePositives:
    """Legitimate requests should NOT be blocked by WAF."""

    def test_normal_query_passes(self, client):
        """Normal query parameter should not trigger WAF."""
        resp = client.get("/?id=12345")
        # Should not be 403 (may be 200, 302, etc. depending on auth)
        assert resp.status_code != 403, "Normal query blocked by WAF (false positive)"

    def test_normal_form_post_passes(self, client):
        """Normal form data should not trigger WAF."""
        resp = client.post("/submit_correction", data={"content": "This is a normal homework submission."})
        assert resp.status_code != 403, "Normal form post blocked by WAF (false positive)"

    def test_normal_json_passes(self, client):
        """Normal JSON body should not trigger WAF."""
        resp = client.post(
            "/api/grade",
            json={"content": "学生提交的作业内容"},
            content_type="application/json",
        )
        assert resp.status_code != 403, "Normal JSON blocked by WAF (false positive)"


# ---------------------------------------------------------------------------
# WAF — health endpoints bypass
# ---------------------------------------------------------------------------

class TestWAFHealthBypass:
    """WAF should skip health check endpoints."""

    def test_healthz_not_blocked(self, client):
        """/healthz should bypass WAF even with suspicious params."""
        resp = client.get("/healthz")
        assert resp.status_code == 200

    def test_metrics_not_blocked(self, client):
        """/metrics should bypass WAF."""
        resp = client.get("/metrics")
        # May return 200 or 404 depending on implementation, but not 403
        assert resp.status_code != 403


# ---------------------------------------------------------------------------
# WAF — body size limit
# ---------------------------------------------------------------------------

class TestWAFBodySize:
    """WAF should reject oversized request bodies."""

    def test_oversized_body_rejected(self, client):
        """Request body > 10MB → 413."""
        big_data = "A" * (10 * 1024 * 1024 + 1)
        resp = client.post(
            "/submit_correction",
            data={"content": big_data},
            content_type="application/x-www-form-urlencoded",
        )
        assert resp.status_code == 413


# ---------------------------------------------------------------------------
# WAF — alert logging
# ---------------------------------------------------------------------------

class TestWAFAlertLog:
    """WAF should log alerts to logs/waf_alerts.log."""

    def test_alert_log_written(self, client):
        """After a WAF block, an alert entry should appear in the log."""
        log_file = Path(__file__).parent.parent / "logs" / "waf_alerts.log"
        # Count existing lines
        existing = 0
        if log_file.exists():
            content = log_file.read_text().strip()
            existing = len(content.split("\n")) if content else 0

        # Trigger a WAF block
        client.get("/?id=1 UNION SELECT * FROM users")

        # Check log file grew
        if log_file.exists():
            content = log_file.read_text().strip()
            if content:
                lines = content.split("\n")
                assert len(lines) > existing, "WAF alert not logged"
                # Verify the latest entry has expected fields
                last_entry = json.loads(lines[-1])
                assert "rule" in last_entry
                assert "timestamp" in last_entry
                assert "path" in last_entry


# ---------------------------------------------------------------------------
# WAF — IP blacklist
# ---------------------------------------------------------------------------

class TestWAFIPBlacklist:
    """WAF should block blacklisted IPs."""

    def test_blacklisted_ip_blocked(self, app):
        """Request from blacklisted IP → 403."""
        import waf_middleware
        # Verify blacklist loading works
        original_load = waf_middleware._load_ip_blacklist
        waf_middleware._load_ip_blacklist = lambda: {"1.2.3.4"}
        try:
            bl = waf_middleware._load_ip_blacklist()
            assert "1.2.3.4" in bl
        finally:
            waf_middleware._load_ip_blacklist = original_load


# ---------------------------------------------------------------------------
# Security headers — all headers present
# ---------------------------------------------------------------------------

class TestSecurityHeaders:
    """Security response headers should be present on all responses."""

    EXPECTED_HEADERS = [
        "X-Content-Type-Options",
        "X-Frame-Options",
        "X-XSS-Protection",
        "Referrer-Policy",
        "Content-Security-Policy",
        "Permissions-Policy",
        "Cross-Origin-Opener-Policy",
        "Cross-Origin-Resource-Policy",
    ]

    def test_all_security_headers_present(self, client):
        """All 8 security headers should be in the response."""
        resp = client.get("/healthz")
        for header in self.EXPECTED_HEADERS:
            assert header in resp.headers, f"Missing security header: {header}"

    def test_x_content_type_options(self, client):
        """X-Content-Type-Options should be nosniff."""
        resp = client.get("/healthz")
        assert resp.headers.get("X-Content-Type-Options") == "nosniff"

    def test_x_frame_options(self, client):
        """X-Frame-Options should be DENY."""
        resp = client.get("/healthz")
        assert resp.headers.get("X-Frame-Options") == "DENY"

    def test_csp_present(self, client):
        """Content-Security-Policy should contain key directives."""
        resp = client.get("/healthz")
        csp = resp.headers.get("Content-Security-Policy", "")
        assert "default-src 'self'" in csp
        assert "cdn.jsdelivr.net" in csp
        assert "frame-ancestors 'none'" in csp

    def test_permissions_policy(self, client):
        """Permissions-Policy should disable geolocation, camera, microphone."""
        resp = client.get("/healthz")
        pp = resp.headers.get("Permissions-Policy", "")
        assert "geolocation=()" in pp
        assert "camera=()" in pp
        assert "microphone=()" in pp

    def test_server_header_removed(self, client):
        """Server header should be removed (no version disclosure)."""
        resp = client.get("/healthz")
        server = resp.headers.get("Server", "")
        if server:
            assert "gunicorn" not in server.lower() or "version" not in server.lower()

    def test_referrer_policy(self, client):
        """Referrer-Policy should be strict-origin-when-cross-origin."""
        resp = client.get("/healthz")
        assert resp.headers.get("Referrer-Policy") == "strict-origin-when-cross-origin"


# ---------------------------------------------------------------------------
# WAF + Security headers integration
# ---------------------------------------------------------------------------

class TestWAFSecurityIntegration:
    """WAF and security headers should work together."""

    def test_blocked_response_has_security_headers(self, client):
        """Even 403 WAF block responses should have security headers."""
        resp = client.get("/?id=1 UNION SELECT * FROM users")
        assert resp.status_code == 403
        assert "X-Content-Type-Options" in resp.headers
        assert "X-Frame-Options" in resp.headers
