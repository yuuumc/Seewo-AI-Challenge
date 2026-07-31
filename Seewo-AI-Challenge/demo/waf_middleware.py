"""V2.0 Sprint 7 (7.4): WAF 中间件 — Flask 层 Web Application Firewall.

作为 Caddy WAF 的第二层防线（纵深防御），在 Flask 应用层对每个请求做：
  - SQL 注入检测（URL 参数 + POST body 正则匹配）
  - XSS 检测（<script> / javascript: / onerror= 等）
  - 路径遍历检测（../ / ..\\）
  - 请求体大小限制（10MB）
  - IP 黑名单（可选，从 data/ip_blacklist.json 加载）

命中规则时返回 403 + 记录到 alert 日志（logs/waf_alerts.log）。

与 Caddy WAF 的关系：
  Caddy 层做第一道拦截（高性能，规则简单）；
  Flask 层做第二道（精细，可访问 request 上下文）。
  双层确保即使一层被绕过，另一层仍能拦截。
"""
from __future__ import annotations

import json
import os
import re
import time
from pathlib import Path
from typing import Any

from flask import Flask, Request, abort

_DATA_DIR = Path(__file__).parent / "data"
_ALERT_LOG = Path(__file__).parent.parent / "logs" / "waf_alerts.log"

# 请求体大小限制 10MB
MAX_BODY_SIZE = 10 * 1024 * 1024

# ---------------------------------------------------------------------------
# WAF 规则定义
# ---------------------------------------------------------------------------

# SQL 注入模式
SQL_INJECTION_PATTERNS = [
    r"(?i)union\s+select",
    r"(?i)drop\s+table",
    r"(?i)insert\s+into\s+.*values",
    r"(?i)delete\s+from\s+\w+",
    r"(?i)update\s+\w+\s+set\s+.*=",
    r"(?i)select\s+.*\s+from\s+\w+",
    r"(?i)--\s*$",  # SQL 注释
    r"(?i)/\*.*\*/",  # SQL 块注释
    r"(?i);\s*(drop|delete|update|insert|alter|create)\s+",
    r"(?i)or\s+1\s*=\s*1",
    r"(?i)and\s+1\s*=\s*1",
    r"(?i)'\s*or\s*'",
    r"(?i)benchmark\s*\(",
    r"(?i)sleep\s*\(",
    r"(?i)waitfor\s+delay",
    r"(?i)xp_cmdshell",
    r"(?i)information_schema",
    r"(?i)load_file\s*\(",
    r"(?i)into\s+outfile",
    r"(?i)concat\s*\(",
]

# XSS 模式
XSS_PATTERNS = [
    r"(?i)<script[^>]*>",
    r"(?i)</script>",
    r"(?i)javascript:",
    r"(?i)on(error|load|click|mouseover|focus|blur|submit|change)\s*=",
    r"(?i)<iframe[^>]*",
    r"(?i)<object[^>]*",
    r"(?i)<embed[^>]*",
    r"(?i)<svg[^>]*on",
    r"(?i)<img[^>]+onerror",
    r"(?i)<body[^>]+onload",
    r"(?i)document\.cookie",
    r"(?i)document\.write",
    r"(?i)window\.location",
    r"(?i)eval\s*\(",
    r"(?i)alert\s*\(",
    r"(?i)prompt\s*\(",
    r"(?i)String\.fromCharCode",
    r"(?i)expression\s*\(",
    r"(?i)<meta[^>]+http-equiv",
]

# 路径遍历模式
PATH_TRAVERSAL_PATTERNS = [
    r"\.\./",
    r"\.\.\\",
    r"%2e%2e%2f",
    r"%2e%2e/",
    r"..%2f",
    r"..%5c",
    r"%2e%2e%5c",
    r"\.\.%00",
]

# 命令注入模式
COMMAND_INJECTION_PATTERNS = [
    r"(?i);\s*(cat|ls|id|whoami|wget|curl|bash|sh|nc|python|perl)\s",
    r"(?i)\|\s*(cat|ls|id|whoami|wget|curl|bash|sh|nc|python|perl)\s",
    r"(?i)`[^`]*(cat|ls|id|whoami|wget|curl|bash|sh|nc|python|perl)",
    r"(?i)\$\([^)]*(cat|ls|id|whoami|wget|curl|bash|sh|nc|python|perl)",
    r"(?i)&&\s*(cat|ls|id|whoami|wget|curl|bash|sh|nc|python|perl)\s",
]

# 编译正则
_COMPILED_PATTERNS: list[tuple[str, re.Pattern]] = []

for name, patterns in [
    ("sql_injection", SQL_INJECTION_PATTERNS),
    ("xss", XSS_PATTERNS),
    ("path_traversal", PATH_TRAVERSAL_PATTERNS),
    ("command_injection", COMMAND_INJECTION_PATTERNS),
]:
    for p in patterns:
        _COMPILED_PATTERNS.append((name, re.compile(p)))


def _load_ip_blacklist() -> set[str]:
    """Load IP blacklist from data/ip_blacklist.json."""
    f = _DATA_DIR / "ip_blacklist.json"
    if not f.exists():
        return set()
    try:
        with open(f, "r", encoding="utf-8") as fh:
            return set(json.load(fh).get("ips", []))
    except Exception:
        return set()


def _log_alert(
    rule_type: str,
    client_ip: str,
    method: str,
    path: str,
    matched_pattern: str,
    payload_sample: str = "",
) -> None:
    """Log WAF alert to logs/waf_alerts.log."""
    _ALERT_LOG.parent.mkdir(parents=True, exist_ok=True)
    record = {
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S%z", time.localtime()),
        "rule": rule_type,
        "client_ip": client_ip,
        "method": method,
        "path": path,
        "matched_pattern": matched_pattern,
        "payload_sample": payload_sample[:200],
    }
    try:
        from security import audit_log
        audit_log(
            "waf_alert",
            rule=rule_type,
            client_ip=client_ip,
            path=path,
            matched_pattern=matched_pattern,
        )
    except Exception:
        pass
    with open(_ALERT_LOG, "a", encoding="utf-8") as f:
        f.write(json.dumps(record, ensure_ascii=False) + "\n")


def _check_value(value: str) -> tuple[str, str] | None:
    """Check a single string value against all WAF patterns.

    Returns (rule_type, matched_pattern) if a match is found, None otherwise.
    """
    if not value or len(value) > 10000:
        return None
    for rule_type, pattern in _COMPILED_PATTERNS:
        m = pattern.search(value)
        if m:
            return rule_type, m.group(0)
    return None


def _check_request(req: Request) -> tuple[str, str, str] | None:
    """Check a Flask request for WAF violations.

    Returns (rule_type, matched_pattern, payload_sample) if violation found.
    """
    # Check URL path
    result = _check_value(req.path)
    if result:
        return result[0], result[1], f"path={req.path}"

    # Check query parameters
    for key, value in req.args.items():
        result = _check_value(value)
        if result:
            return result[0], result[1], f"{key}={value}"

    # Check form data
    if req.form:
        for key, value in req.form.items():
            result = _check_value(value)
            if result:
                return result[0], result[1], f"{key}={value}"

    # Check JSON body (if Content-Type is JSON)
    if req.content_type and "application/json" in req.content_type:
        try:
            data = req.get_json(silent=True)
            if data and isinstance(data, dict):
                for key, value in data.items():
                    if isinstance(value, str):
                        result = _check_value(value)
                        if result:
                            return result[0], result[1], f"{key}={value}"
        except Exception:
            pass

    # Check raw body for non-JSON content types
    if req.data and len(req.data) < 100000:
        try:
            body_str = req.data.decode("utf-8", errors="replace")
            result = _check_value(body_str)
            if result:
                return result[0], result[1], "body"
        except Exception:
            pass

    return None


class WAFMiddleware:
    """Flask WAF middleware — checks every request for attack patterns."""

    def __init__(self, app: Flask) -> None:
        self.app = app
        self.ip_blacklist: set[str] = _load_ip_blacklist()
        app.before_request(self._before_request)

    def _before_request(self) -> Any:
        """Check request before processing. Aborts with 403 if WAF rule matches."""
        from flask import request

        # Skip health check endpoints
        if request.path in ("/healthz", "/metrics"):
            return None

        client_ip = request.remote_addr or ""

        # IP blacklist check
        if client_ip and client_ip in self.ip_blacklist:
            _log_alert("ip_blacklist", client_ip, request.method, request.path, client_ip)
            abort(403)

        # Request body size check
        content_length = request.content_length or 0
        if content_length > MAX_BODY_SIZE:
            _log_alert(
                "oversized_body",
                client_ip,
                request.method,
                request.path,
                f"size={content_length}",
            )
            abort(413)

        # Pattern-based checks
        violation = _check_request(request)
        if violation:
            rule_type, matched, sample = violation
            _log_alert(rule_type, client_ip, request.method, request.path, matched, sample)
            abort(403)

        return None

    def reload_blacklist(self) -> None:
        """Reload IP blacklist from file (for runtime updates)."""
        self.ip_blacklist = _load_ip_blacklist()


def init_waf(app: Flask) -> WAFMiddleware | None:
    """Initialize WAF middleware on the Flask app.

    Returns the middleware instance, or None if initialization fails.
    """
    try:
        return WAFMiddleware(app)
    except Exception:
        return None
