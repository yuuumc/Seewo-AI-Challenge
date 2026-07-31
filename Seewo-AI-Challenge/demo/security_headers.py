"""V2.0 Sprint 7 (7.6): 安全响应头加固 — Flask 层。

与 Caddy header 块形成双层保障：即使绕过 Caddy 直连 gunicorn，
Flask 层仍会注入安全头。

安全头清单：
  - X-Content-Type-Options: nosniff
  - X-Frame-Options: DENY
  - X-XSS-Protection: 1; mode=block
  - Referrer-Policy: strict-origin-when-cross-origin
  - Content-Security-Policy: self + jsdelivr CDN + inline styles
  - Permissions-Policy: 禁用不需要的浏览器 API
  - Cross-Origin-Opener-Policy: same-origin
  - Cross-Origin-Resource-Policy: same-origin
"""
from __future__ import annotations

from flask import Flask, Response

# 安全头默认值
SECURITY_HEADERS = {
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "X-XSS-Protection": "1; mode=block",
    "Referrer-Policy": "strict-origin-when-cross-origin",
    "Content-Security-Policy": (
        "default-src 'self'; "
        "script-src 'self' https://cdn.jsdelivr.net https://cdn.tailwindcss.com https://unpkg.com 'unsafe-inline'; "
        "style-src 'self' https://cdn.jsdelivr.net https://cdn.tailwindcss.com 'unsafe-inline'; "
        "img-src 'self' data: https:; "
        "font-src 'self' https://cdn.jsdelivr.net; "
        "connect-src 'self'; "
        "frame-ancestors 'none'; "
        "base-uri 'self'; "
        "form-action 'self'"
    ),
    "Permissions-Policy": (
        "geolocation=(), microphone=(), camera=(), "
        "payment=(), usb=(), magnetometer=(), gyroscope=()"
    ),
    "Cross-Origin-Opener-Policy": "same-origin",
    "Cross-Origin-Resource-Policy": "same-origin",
}


def init_security_headers(app: Flask) -> None:
    """Register after_request handler to inject security headers on every response.

    This complements the Caddy header block — if a request bypasses Caddy
    (e.g., direct access to gunicorn port), Flask still injects the headers.
    """
    @app.after_request
    def _add_security_headers(response: Response) -> Response:
        for header, value in SECURITY_HEADERS.items():
            # Don't override headers already set by Caddy or other middleware
            if header not in response.headers:
                response.headers[header] = value
        # Remove server version disclosure
        response.headers.pop("Server", None)
        return response
