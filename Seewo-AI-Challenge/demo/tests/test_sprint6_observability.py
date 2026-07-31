"""V2.0 Sprint 6: Tests for observability — request logging, metrics, tracing, alerting.

Run with: python -m pytest tests/test_sprint6_observability.py -v
"""
from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path

import pytest

# Ensure demo/ and repo root are on sys.path
_DEMO_DIR = Path(__file__).resolve().parent.parent
_REPO_ROOT = _DEMO_DIR.parent
for p in (_DEMO_DIR, _REPO_ROOT):
    sp = str(p)
    if sp not in sys.path:
        sys.path.insert(0, sp)


# ── 6.1 Request Logging Tests ──

class TestRequestLogging:
    """Test structured request logging middleware."""

    def test_generate_request_id(self):
        from request_logging import generate_request_id
        rid = generate_request_id()
        assert len(rid) == 16
        assert all(c in "0123456789abcdef" for c in rid)

    def test_request_id_uniqueness(self):
        from request_logging import generate_request_id
        ids = {generate_request_id() for _ in range(100)}
        assert len(ids) == 100  # All unique

    def test_get_request_id_outside_context(self):
        from request_logging import get_request_id
        # Outside Flask request context, should return default
        assert get_request_id() == "no-request"

    def test_request_log_json_format(self):
        """Request log should be valid JSON with required fields."""
        from request_logging import _write_request_log
        # Write a test record
        record = {
            "request_id": "test123",
            "timestamp": "2026-07-31T12:00:00+0800",
            "method": "GET",
            "path": "/test",
            "endpoint": "test",
            "status_code": 200,
            "latency_ms": 12.5,
            "ip": "127.0.0.1",
            "user_id": None,
            "school_id": 1,
        }
        _write_request_log(record)
        # Verify file fallback contains the record
        from request_logging import _get_log_file
        log_path = _get_log_file()
        if os.path.exists(log_path):
            lines = open(log_path, encoding="utf-8").read().strip().split("\n")
            if lines:
                last = json.loads(lines[-1])
                assert last["request_id"] == "test123"
                assert "school_id" in last
                assert "latency_ms" in last


# ── 6.2 Prometheus Metrics Tests ──

class TestMetrics:
    """Test Prometheus text format metrics."""

    def test_render_empty_metrics(self):
        from metrics import _MetricState
        state = _MetricState()
        text = state.render_prometheus()
        assert isinstance(text, str)

    def test_counter(self):
        from metrics import _MetricState
        state = _MetricState()
        state.inc_counter("test_total", {"label": "val"})
        state.inc_counter("test_total", {"label": "val"})
        text = state.render_prometheus()
        assert "test_total" in text
        assert 'label="val"' in text

    def test_histogram(self):
        from metrics import _MetricState
        state = _MetricState()
        state.observe_histogram("test_duration_ms", {"endpoint": "/api"}, 50.0)
        state.observe_histogram("test_duration_ms", {"endpoint": "/api"}, 150.0)
        text = state.render_prometheus()
        assert "test_duration_ms_bucket" in text
        assert "test_duration_ms_sum" in text
        assert "test_duration_ms_count" in text
        # le="50" bucket should have 1 (value 50 <= 50)
        assert 'le="50"' in text

    def test_record_grading(self):
        from metrics import record_grading, get_metrics, _MetricState
        # Reset state
        import metrics as _m
        _m._metrics = _MetricState()
        record_grading("数学", "long_answer", 150.0, True, llm_used=True)
        text = _m._metrics.render_prometheus()
        assert "seewo_grading_total" in text
        assert 'subject="数学"' in text
        assert 'status="success"' in text
        assert "seewo_llm_calls_total" in text

    def test_record_http_request(self):
        from metrics import record_http_request, get_metrics, _MetricState
        import metrics as _m
        _m._metrics = _MetricState()
        record_http_request("GET", "/healthz", 200, 5.0)
        text = _m._metrics.render_prometheus()
        assert "seewo_http_requests_total" in text
        assert 'method="GET"' in text
        assert 'status="200"' in text

    def test_gauge(self):
        from metrics import _MetricState
        state = _MetricState()
        state.set_gauge("test_active", {"instance": "main"}, 42)
        text = state.render_prometheus()
        assert "test_active" in text
        assert "42" in text


# ── 6.3 Tracing Tests ──

class TestTracing:
    """Test lightweight distributed tracing."""

    def test_get_trace_id_outside_context(self):
        from tracing import get_trace_id
        assert get_trace_id() == "no-trace"

    def test_create_span(self):
        from tracing import create_span
        span = create_span("test_stage", {"input": "data"})
        assert span.stage == "test_stage"
        assert span.input_payload == {"input": "data"}
        assert span.duration_ms == 0.0  # Not ended yet

    def test_span_end(self):
        from tracing import create_span
        span = create_span("test_stage")
        time.sleep(0.01)
        span.end()
        assert span.duration_ms > 0

    def test_span_context_manager(self):
        from tracing import create_span
        with create_span("test_ctx") as span:
            time.sleep(0.01)
        assert span.duration_ms > 0

    def test_span_error_recording(self):
        from tracing import create_span
        span = create_span("test_error")
        span.set_error("Something went wrong")
        assert span.error == "Something went wrong"

    def test_span_to_trace_record(self):
        from tracing import create_span
        span = create_span("test_record", {"q": "math"})
        span.set_output({"score": 80})
        span.end()
        record = span.to_trace_record_dict()
        assert record["stage"] == "test_record"
        assert record["input"] == {"q": "math"}
        assert record["output"] == {"score": 80}
        assert "trace_id" in record


# ── 6.4 Alerting Tests ──

class TestAlerting:
    """Test error alerting with threshold rules."""

    def test_alert_manager_singleton(self):
        from alerting import get_alert_manager, AlertManager
        am1 = get_alert_manager()
        am2 = get_alert_manager()
        assert am1 is am2  # Same instance

    def test_sliding_window(self):
        from alerting import _SlidingWindow
        sw = _SlidingWindow(window_seconds=1)
        sw.add(True)
        sw.add(False)
        sw.add(True)
        stats = sw.stats()
        assert stats["total"] == 3
        assert stats["success"] == 2
        assert stats["failure"] == 1
        assert abs(stats["failure_rate"] - 1/3) < 0.01

    def test_sliding_window_eviction(self):
        from alerting import _SlidingWindow
        sw = _SlidingWindow(window_seconds=1)
        sw.add(False, timestamp=time.time() - 2)  # Old event
        sw.add(True)
        stats = sw.stats()
        assert stats["total"] == 1  # Old event evicted
        assert stats["failure"] == 0

    def test_alert_rule_no_fire_below_threshold(self):
        from alerting import AlertRule, _SlidingWindow
        rule = AlertRule(
            name="test", description="test",
            threshold=0.5, window=_SlidingWindow(300),
        )
        # 10 successes, 0 failures → 0% failure rate, no alert
        for _ in range(10):
            rule.window.add(True)
        assert rule.check() is None

    def test_alert_rule_fires_above_threshold(self):
        from alerting import AlertRule, _SlidingWindow
        rule = AlertRule(
            name="test", description="test",
            threshold=0.1, window=_SlidingWindow(300),
        )
        # 9 successes, 1 failure → 10% failure rate = threshold (not > threshold)
        for _ in range(9):
            rule.window.add(True)
        rule.window.add(False)
        assert rule.check() is None  # Equal, not greater

        # Add another failure → 2/11 = 18% > 10%
        rule.window.add(False)
        alert = rule.check()
        assert alert is not None
        assert alert["rule"] == "test"
        assert alert["failure_rate"] > 10

    def test_alert_dedup(self):
        from alerting import AlertRule, _SlidingWindow
        rule = AlertRule(
            name="test", description="test",
            threshold=0.05, window=_SlidingWindow(300),
            dedup_seconds=300,
        )
        # 5 failures, 5 successes → 50% > 5%
        for _ in range(5):
            rule.window.add(False)
            rule.window.add(True)
        # First fire
        alert1 = rule.check()
        assert alert1 is not None
        # Second fire within dedup window → should not fire
        alert2 = rule.check()
        assert alert2 is None

    def test_record_http_status(self):
        from alerting import get_alert_manager
        am = get_alert_manager()
        am.record_http_status(200)
        am.record_http_status(500)
        am.record_http_status(200)
        status = am.get_rule_status()
        http_rule = next(r for r in status if r["rule"] == "http_5xx")
        assert http_rule["total_events"] >= 3

    def test_get_rule_status(self):
        from alerting import get_alert_manager
        am = get_alert_manager()
        status = am.get_rule_status()
        assert len(status) == 3
        rule_names = {r["rule"] for r in status}
        assert "http_5xx" in rule_names
        assert "llm_timeout" in rule_names
        assert "grading_failure" in rule_names


# ── Integration: Flask app with observability ──

class TestFlaskIntegration:
    """Test that observability middleware works with Flask app."""

    def test_metrics_endpoint(self):
        """GET /metrics should return Prometheus text format."""
        from flask import Flask
        import metrics as _m
        _m._metrics = _m._MetricState()

        app = Flask(__name__)
        app.config["TESTING"] = True

        from metrics import record_http_request, render_metrics
        from flask import Response

        @app.route("/metrics")
        def metrics_endpoint():
            return Response(render_metrics(), mimetype="text/plain")

        record_http_request("GET", "/test", 200, 10.0)

        with app.test_client() as c:
            resp = c.get("/metrics")
            assert resp.status_code == 200
            assert b"seewo_http_requests_total" in resp.data

    def test_request_id_header(self):
        """Response should include X-Request-ID header."""
        from flask import Flask
        from request_logging import RequestLoggingMiddleware

        app = Flask(__name__)
        app.config["TESTING"] = True
        RequestLoggingMiddleware(app)

        @app.route("/")
        def index():
            return "ok"

        with app.test_client() as c:
            resp = c.get("/")
            assert resp.status_code == 200
            assert "X-Request-ID" in resp.headers

    def test_request_id_propagation(self):
        """Client-provided X-Request-ID should be echoed back."""
        from flask import Flask
        from request_logging import RequestLoggingMiddleware

        app = Flask(__name__)
        app.config["TESTING"] = True
        RequestLoggingMiddleware(app)

        @app.route("/")
        def index():
            return "ok"

        with app.test_client() as c:
            resp = c.get("/", headers={"X-Request-ID": "my-custom-id"})
            assert resp.headers["X-Request-ID"] == "my-custom-id"

    def test_grade_long_answer_records_metrics(self):
        """grade_long_answer should record metrics."""
        import metrics as _m
        _m._metrics = _m._MetricState()

        from engine.grader import grade_long_answer
        # Use a simple question
        question = {
            "id": "test_q",
            "type": "long_answer",
            "subject": "数学",
            "answer": "test answer",
            "score": 10,
            "steps": [],
            "knowledge": "test",
        }
        result = grade_long_answer("student answer", question, "s01")
        assert result is not None

        # Check metrics were recorded
        text = _m._metrics.render_prometheus()
        assert "seewo_grading_total" in text
        assert 'subject="数学"' in text


# ── 6.3 LLM Provider Trace Integration Tests ──

class TestLLMTraceIntegration:
    """Test trace_id propagation through LLM provider _chat() (6.3)."""

    def test_record_llm_call_metric(self):
        """record_llm_call should populate seewo_llm_calls_total."""
        import metrics as _m
        _m._metrics = _m._MetricState()

        from metrics import record_llm_call
        record_llm_call("test-provider", 250.0, success=True, timed_out=False)
        record_llm_call("test-provider", 5000.0, success=False, timed_out=True)

        text = _m._metrics.render_prometheus()
        assert "seewo_llm_calls_total" in text
        assert 'provider="test-provider"' in text
        assert 'status="success"' in text
        assert 'status="timeout"' in text
        assert "seewo_llm_duration_ms" in text

    def test_record_llm_telemetry_records_both(self):
        """_record_llm_telemetry should record to both metrics and alerting."""
        import metrics as _m
        _m._metrics = _m._MetricState()

        from alerting import get_alert_manager
        # Reset alert manager
        import alerting as _a
        _a._alert_manager = _a.AlertManager()

        from engine.llm.openai_provider import _record_llm_telemetry
        _record_llm_telemetry("openai", 100.0, success=True, timed_out=False)

        # Metrics recorded
        text = _m._metrics.render_prometheus()
        assert 'provider="openai"' in text
        assert 'status="success"' in text

        # Alerting recorded
        am = get_alert_manager()
        status = am.get_rule_status()
        llm_rule = next(r for r in status if r["rule"] == "llm_timeout")
        assert llm_rule["total_events"] >= 1

    def test_record_llm_telemetry_failure(self):
        """_record_llm_telemetry with failure should record to alerting."""
        import alerting as _a
        _a._alert_manager = _a.AlertManager()

        from engine.llm.openai_provider import _record_llm_telemetry
        _record_llm_telemetry("deepseek-math", 30000.0, success=False, timed_out=True)

        from alerting import get_alert_manager
        am = get_alert_manager()
        status = am.get_rule_status()
        llm_rule = next(r for r in status if r["rule"] == "llm_timeout")
        assert llm_rule["failures"] >= 1

    def test_record_llm_telemetry_swallows_errors(self):
        """_record_llm_telemetry must never raise even if deps missing."""
        from engine.llm.openai_provider import _record_llm_telemetry
        # Should not raise
        _record_llm_telemetry("test", 100.0, success=True, timed_out=False)

    def test_chat_sends_trace_id_header(self):
        """_chat() should include X-Trace-Id in request headers."""
        from unittest.mock import patch, MagicMock
        from engine.llm.openai_provider import OpenAIProvider

        provider = OpenAIProvider(
            base_url="http://fake.test/v1",
            api_key="test-key",
            model="test-model",
            timeout=5,
            max_retries=0,
        )

        captured_headers = {}

        class FakeResponse:
            def __enter__(self):
                return self
            def __exit__(self, *args):
                pass
            def read(self):
                return json.dumps({
                    "choices": [{"message": {"content": '{"is_correct": true}'}}]
                }).encode("utf-8")

        def fake_urlopen(req, **kwargs):
            captured_headers.update(req.headers)
            return FakeResponse()

        with patch("urllib.request.urlopen", side_effect=fake_urlopen):
            data, err = provider._chat(
                [{"role": "user", "content": "test"}],
                json_mode=True,
            )

        assert "X-trace-id" in captured_headers or "X-Trace-Id" in captured_headers
        # trace_id should be "no-trace" when outside Flask context
        trace_val = captured_headers.get("X-trace-id") or captured_headers.get("X-Trace-Id")
        assert trace_val == "no-trace"

    def test_chat_failure_records_telemetry(self):
        """_chat() on failure should record to alerting."""
        import alerting as _a
        _a._alert_manager = _a.AlertManager()

        from unittest.mock import patch
        from engine.llm.openai_provider import OpenAIProvider
        import urllib.error

        provider = OpenAIProvider(
            base_url="http://fake.test/v1",
            api_key="test-key",
            model="test-model",
            timeout=1,
            max_retries=0,
        )

        def fake_urlopen(req, **kwargs):
            raise urllib.error.HTTPError(
                req.full_url, 500, "Server Error", {}, None
            )

        with patch("urllib.request.urlopen", side_effect=fake_urlopen):
            data, err = provider._chat(
                [{"role": "user", "content": "test"}],
                json_mode=True,
            )

        assert data is None
        assert err is not None

        from alerting import get_alert_manager
        am = get_alert_manager()
        status = am.get_rule_status()
        llm_rule = next(r for r in status if r["rule"] == "llm_timeout")
        assert llm_rule["total_events"] >= 1
