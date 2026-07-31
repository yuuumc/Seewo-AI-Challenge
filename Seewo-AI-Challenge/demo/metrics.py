"""V2.0 Sprint 6 (6.2): Prometheus metrics endpoint.

Hand-written Prometheus text format — no external library dependency.
Tracks grading latency, success rate, and LLM call count.

Metrics exposed at GET /metrics:
    # Grading
    seewo_grading_total{subject,type,status}
    seewo_grading_duration_ms{subject,type} (histogram buckets)
    seewo_grading_success_rate

    # LLM
    seewo_llm_calls_total{provider,status}
    seewo_llm_duration_ms{provider}

    # HTTP
    seewo_http_requests_total{method,endpoint,status}
    seewo_http_request_duration_ms{method,endpoint}

    # System
    seewo_active_users
"""
from __future__ import annotations

import threading
import time
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Dict, List


@dataclass
class _HistogramBucket:
    """One bucket of a histogram."""
    le: float  # upper bound (inclusive), float('inf') for +Inf
    count: int = 0


@dataclass
class _MetricState:
    """Thread-safe metric storage."""
    # Counter: name → labels_tuple → count
    counters: Dict[str, Dict[tuple, int]] = field(default_factory=lambda: defaultdict(lambda: defaultdict(int)))

    # Histogram: name → labels_tuple → {bucket_le: count, sum: float, count: int}
    histograms: Dict[str, Dict[tuple, dict]] = field(default_factory=lambda: defaultdict(lambda: defaultdict(dict)))

    # Gauge: name → labels_tuple → value
    gauges: Dict[str, Dict[tuple, float]] = field(default_factory=lambda: defaultdict(lambda: defaultdict(float)))

    _lock: threading.Lock = field(default_factory=threading.Lock)

    # Default histogram buckets (Prometheus convention, in milliseconds)
    DEFAULT_BUCKETS_MS = [5, 10, 25, 50, 100, 250, 500, 1000, 2500, 5000, 10000]

    def inc_counter(self, name: str, labels: dict, value: int = 1):
        """Increment a counter."""
        key = tuple(sorted(labels.items()))
        with self._lock:
            self.counters[name][key] += value

    def observe_histogram(self, name: str, labels: dict, value: float):
        """Record a histogram observation."""
        key = tuple(sorted(labels.items()))
        with self._lock:
            if key not in self.histograms[name]:
                self.histograms[name][key] = {
                    "buckets": {le: 0 for le in self.DEFAULT_BUCKETS_MS},
                    "sum": 0.0,
                    "count": 0,
                }
            hist = self.histograms[name][key]
            hist["sum"] += value
            hist["count"] += 1
            for le in self.DEFAULT_BUCKETS_MS:
                if value <= le:
                    hist["buckets"][le] += 1
            # +Inf bucket
            hist["buckets"][float("inf")] = hist["count"]

    def set_gauge(self, name: str, labels: dict, value: float):
        """Set a gauge value."""
        key = tuple(sorted(labels.items()))
        with self._lock:
            self.gauges[name][key] = value

    def render_prometheus(self) -> str:
        """Render all metrics in Prometheus text exposition format."""
        lines: List[str] = []
        with self._lock:
            # Counters
            for name in sorted(self.counters.keys()):
                labels_map = self.counters[name]
                lines.append(f"# TYPE {name} counter")
                for labels_tuple, count in sorted(labels_map.items()):
                    label_str = ",".join(f'{k}="{v}"' for k, v in labels_tuple)
                    lines.append(f'{name}{{{label_str}}} {count}')
                lines.append("")

            # Histograms
            for name in sorted(self.histograms.keys()):
                labels_map = self.histograms[name]
                lines.append(f"# TYPE {name} histogram")
                for labels_tuple, hist in sorted(labels_map.items()):
                    base_labels = ",".join(f'{k}="{v}"' for k, v in labels_tuple)
                    for le, count in sorted(hist["buckets"].items(), key=lambda x: (x[0] != float("inf"), x[0])):
                        le_str = "+Inf" if le == float("inf") else str(le)
                        if base_labels:
                            lines.append(f'{name}_bucket{{{base_labels},le="{le_str}"}} {count}')
                        else:
                            lines.append(f'{name}_bucket{{le="{le_str}"}} {count}')
                    lines.append(f'{name}_sum{{{base_labels}}} {hist["sum"]:.2f}')
                    lines.append(f'{name}_count{{{base_labels}}} {hist["count"]}')
                lines.append("")

            # Gauges
            for name in sorted(self.gauges.keys()):
                labels_map = self.gauges[name]
                lines.append(f"# TYPE {name} gauge")
                for labels_tuple, value in sorted(labels_map.items()):
                    label_str = ",".join(f'{k}="{v}"' for k, v in labels_tuple)
                    lines.append(f'{name}{{{label_str}}} {value}')
                lines.append("")

        return "\n".join(lines)

    def get_snapshot(self) -> dict:
        """Get a snapshot of all metrics for alerting."""
        with self._lock:
            return {
                "counters": {name: dict(labels) for name, labels in self.counters.items()},
                "histograms": {
                    name: {
                        str(labels): {"sum": h["sum"], "count": h["count"]}
                        for labels, h in labels_map.items()
                    }
                    for name, labels_map in self.histograms.items()
                },
            }


# Global singleton
_metrics = _MetricState()


def get_metrics() -> _MetricState:
    """Return the global metrics singleton."""
    return _metrics


def record_grading(subject: str, question_type: str, duration_ms: float, success: bool, llm_used: bool = False):
    """Record a grading operation metric."""
    status = "success" if success else "failure"
    get_metrics().inc_counter(
        "seewo_grading_total",
        {"subject": subject, "type": question_type, "status": status},
    )
    get_metrics().observe_histogram(
        "seewo_grading_duration_ms",
        {"subject": subject, "type": question_type},
        duration_ms,
    )
    if llm_used:
        get_metrics().inc_counter(
            "seewo_llm_calls_total",
            {"provider": "llm", "status": status},
        )
        get_metrics().observe_histogram(
            "seewo_llm_duration_ms",
            {"provider": "llm"},
            duration_ms,
        )


def record_llm_call(provider: str, duration_ms: float, success: bool, timed_out: bool = False):
    """Record an LLM provider call metric (6.3 trace_id → LLM integration).

    Called from OpenAIProvider._chat() to track actual LLM API calls
    separately from grading-level metrics.
    """
    status = "timeout" if timed_out else ("success" if success else "error")
    get_metrics().inc_counter(
        "seewo_llm_calls_total",
        {"provider": provider, "status": status},
    )
    get_metrics().observe_histogram(
        "seewo_llm_duration_ms",
        {"provider": provider},
        duration_ms,
    )


def record_http_request(method: str, endpoint: str, status: int, duration_ms: float):
    """Record an HTTP request metric."""
    get_metrics().inc_counter(
        "seewo_http_requests_total",
        {"method": method, "endpoint": endpoint, "status": str(status)},
    )
    get_metrics().observe_histogram(
        "seewo_http_request_duration_ms",
        {"method": method, "endpoint": endpoint},
        duration_ms,
    )


def render_metrics() -> str:
    """Render Prometheus text format metrics."""
    return _metrics.render_prometheus()
