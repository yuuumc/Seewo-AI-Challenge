"""V2.0 Sprint 6 (6.1): Structured request logging middleware.

Generates a ``request_id`` per request and logs structured JSON to
Redis Stream (fallback: file). Integrates with TenantMiddleware.

Each log record contains:
    request_id, user_id, school_id, endpoint, method,
    status_code, latency_ms, ip, timestamp

Usage in app.py:
    from request_logging import RequestLoggingMiddleware
    RequestLoggingMiddleware(app)
"""
from __future__ import annotations

import json
import os
import time
import uuid
from typing import Optional

from flask import g, request, session


# ---------------------------------------------------------------------------
# Redis client (shared with security.py audit_log)
# ---------------------------------------------------------------------------
_LOG_REDIS = None
_LOG_REDIS_DISABLED = False
_LOG_STREAM_KEY = "req:logs"
_LOG_STREAM_MAXLEN = 10000

# File fallback
_LOG_FILE_PATH: Optional[str] = None


def _get_log_redis():
    """Lazy-init Redis client for request logging."""
    global _LOG_REDIS, _LOG_REDIS_DISABLED
    if _LOG_REDIS_DISABLED:
        return None
    if _LOG_REDIS is not None:
        return _LOG_REDIS
    redis_url = os.environ.get("REDIS_URL", "")
    if not redis_url:
        _LOG_REDIS_DISABLED = True
        return None
    try:
        import redis  # type: ignore[import-untyped]
        _LOG_REDIS = redis.Redis.from_url(
            redis_url, decode_responses=False,
            socket_connect_timeout=1, socket_timeout=1,
        )
        _LOG_REDIS.ping()
    except Exception:
        _LOG_REDIS = None
        _LOG_REDIS_DISABLED = True
        return None
    return _LOG_REDIS


def _get_log_file():
    """Return file handle for request log fallback."""
    global _LOG_FILE_PATH
    if _LOG_FILE_PATH is None:
        from pathlib import Path
        log_dir = Path(__file__).parent / "logs"
        log_dir.mkdir(parents=True, exist_ok=True)
        _LOG_FILE_PATH = str(log_dir / "requests.log")
    return _LOG_FILE_PATH


def _write_request_log(record: dict):
    """Write a request log record to Redis Stream or file."""
    line = json.dumps(record, ensure_ascii=False, default=str)

    # Try Redis first
    r = _get_log_redis()
    if r is not None:
        try:
            r.xadd(_LOG_STREAM_KEY, {"data": line}, maxlen=_LOG_STREAM_MAXLEN, approximate=True)
            return
        except Exception:
            pass  # Fall through to file

    # File fallback
    try:
        with open(_get_log_file(), "a", encoding="utf-8") as f:
            f.write(line + "\n")
    except Exception:
        pass  # Logging must never break UX


def generate_request_id() -> str:
    """Generate a unique request ID (16 hex chars)."""
    return uuid.uuid4().hex[:16]


def get_request_id() -> str:
    """Get the current request's request_id (set by middleware)."""
    try:
        return g.request_id
    except (RuntimeError, AttributeError):
        return "no-request"


class RequestLoggingMiddleware:
    """Flask before/after request hooks for structured request logging.

    Before request:
    - Generate request_id and store in g.request_id
    - Record start time

    After request:
    - Calculate latency
    - Log structured JSON with all fields
    - Add X-Request-ID response header
    """

    def __init__(self, app):
        self.app = app
        app.before_request(self._before_request)
        app.after_request(self._after_request)

    def _before_request(self):
        """Generate request_id and record start time."""
        g.request_id = request.headers.get("X-Request-ID") or generate_request_id()
        g.request_start_time = time.time()

    def _after_request(self, response):
        """Log the request after it completes."""
        try:
            latency_ms = round((time.time() - g.request_start_time) * 1000.0, 2)
        except (AttributeError, RuntimeError):
            latency_ms = 0

        # Resolve school_id from TenantMiddleware or session
        school_id = 1
        try:
            school_id = g.school_id or 1
        except (RuntimeError, AttributeError):
            pass

        record = {
            "request_id": get_request_id(),
            "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S%z", time.localtime()),
            "method": request.method,
            "path": request.path,
            "endpoint": request.endpoint or "unknown",
            "status_code": response.status_code,
            "latency_ms": latency_ms,
            "ip": request.remote_addr,
            "user_id": session.get("user_id") if session else None,
            "school_id": school_id,
            "user_agent": request.headers.get("User-Agent", "")[:200],
        }

        _write_request_log(record)

        # Add X-Request-ID to response for client-side correlation
        response.headers["X-Request-ID"] = record["request_id"]
        return response
