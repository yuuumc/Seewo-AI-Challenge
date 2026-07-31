"""V2.0 Sprint 6 (6.4): Error alerting with threshold rules.

Monitors error rates via sliding window and triggers alerts when
thresholds are exceeded. Supports Feishu webhook + optional email.

Rules:
    - 5xx rate > 1% (over 5-minute sliding window)
    - LLM timeout rate > 10%
    - Grading failure rate > 5%

Alert dedup: same rule won't fire again within 5 minutes.
Alert records are stored in a log file (and optionally DB).
"""
from __future__ import annotations

import json
import os
import smtplib
import time
import threading
from collections import deque
from dataclasses import dataclass, field
from email.mime.text import MIMEText
from typing import Deque, Dict, List, Optional

from flask import g, request


# ---------------------------------------------------------------------------
# Sliding window counter
# ---------------------------------------------------------------------------

@dataclass
class _SlidingWindow:
    """Fixed-time sliding window counter."""
    window_seconds: int = 300  # 5 minutes
    events: Deque = field(default_factory=deque)

    def add(self, success: bool, timestamp: Optional[float] = None):
        """Add an event (success=True/False)."""
        ts = timestamp or time.time()
        self.events.append((ts, success))
        self._evict(ts)

    def _evict(self, now: float):
        """Remove events older than window."""
        cutoff = now - self.window_seconds
        while self.events and self.events[0][0] < cutoff:
            self.events.popleft()

    def stats(self) -> dict:
        """Return {total, success, failure, failure_rate}."""
        now = time.time()
        self._evict(now)
        total = len(self.events)
        if total == 0:
            return {"total": 0, "success": 0, "failure": 0, "failure_rate": 0.0}
        failures = sum(1 for _, s in self.events if not s)
        return {
            "total": total,
            "success": total - failures,
            "failure": failures,
            "failure_rate": failures / total,
        }


# ---------------------------------------------------------------------------
# Alert rules
# ---------------------------------------------------------------------------

@dataclass
class AlertRule:
    """One alerting rule."""
    name: str
    description: str
    threshold: float  # e.g. 0.01 for 1%
    window: _SlidingWindow
    last_fired: float = 0.0
    dedup_seconds: int = 300  # 5 minutes
    severity: str = "warning"  # warning / critical

    def check(self) -> Optional[dict]:
        """Check if the rule should fire. Returns alert dict or None."""
        stats = self.window.stats()
        if stats["total"] < 10:  # Need at least 10 events for meaningful rate
            return None
        if stats["failure_rate"] > self.threshold:
            now = time.time()
            if now - self.last_fired < self.dedup_seconds:
                return None  # Dedup: too soon since last fire
            self.last_fired = now
            return {
                "rule": self.name,
                "severity": self.severity,
                "description": self.description,
                "failure_rate": round(stats["failure_rate"] * 100, 2),
                "threshold": round(self.threshold * 100, 2),
                "total_events": stats["total"],
                "failures": stats["failure"],
                "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S%z", time.localtime()),
            }
        return None


# ---------------------------------------------------------------------------
# Alert manager
# ---------------------------------------------------------------------------

class AlertManager:
    """Manages alert rules, notifications, and dedup."""

    def __init__(self):
        self._lock = threading.Lock()
        self.rules: Dict[str, AlertRule] = {}
        self._alert_log_path: Optional[str] = None
        self._feishu_webhook: Optional[str] = None
        self._smtp_config: Optional[dict] = None
        self._init_rules()
        self._init_channels()

    def _init_rules(self):
        """Initialize default alert rules."""
        self.rules["http_5xx"] = AlertRule(
            name="http_5xx",
            description="HTTP 5xx error rate exceeds 1%",
            threshold=0.01,
            window=_SlidingWindow(300),
            severity="critical",
        )
        self.rules["llm_timeout"] = AlertRule(
            name="llm_timeout",
            description="LLM timeout rate exceeds 10%",
            threshold=0.10,
            window=_SlidingWindow(300),
            severity="warning",
        )
        self.rules["grading_failure"] = AlertRule(
            name="grading_failure",
            description="Grading failure rate exceeds 5%",
            threshold=0.05,
            window=_SlidingWindow(300),
            severity="warning",
        )

    def _init_channels(self):
        """Initialize notification channels from env."""
        self._feishu_webhook = os.environ.get("ALERT_FEISHU_WEBHOOK", "")
        smtp_host = os.environ.get("ALERT_SMTP_HOST", "")
        if smtp_host:
            self._smtp_config = {
                "host": smtp_host,
                "port": int(os.environ.get("ALERT_SMTP_PORT", "587")),
                "user": os.environ.get("ALERT_SMTP_USER", ""),
                "password": os.environ.get("ALERT_SMTP_PASSWORD", ""),
                "from": os.environ.get("ALERT_SMTP_FROM", ""),
                "to": os.environ.get("ALERT_SMTP_TO", ""),
            }

    def record_http_status(self, status_code: int):
        """Record an HTTP response status."""
        success = status_code < 500
        with self._lock:
            self.rules["http_5xx"].window.add(success)

    def record_llm_call(self, success: bool, timed_out: bool = False):
        """Record an LLM API call result."""
        with self._lock:
            # LLM timeout rule
            self.rules["llm_timeout"].window.add(not timed_out)
            # Grading failure also tracks LLM failures
            if not success:
                self.rules["grading_failure"].window.add(False)
            else:
                self.rules["grading_failure"].window.add(True)

    def record_grading(self, success: bool):
        """Record a grading operation result."""
        with self._lock:
            self.rules["grading_failure"].window.add(success)

    def check_all(self) -> List[dict]:
        """Check all rules and fire alerts if needed."""
        alerts = []
        with self._lock:
            for rule in self.rules.values():
                alert = rule.check()
                if alert:
                    alerts.append(alert)
        for alert in alerts:
            self._notify(alert)
            self._log_alert(alert)
        return alerts

    def _notify(self, alert: dict):
        """Send alert notification via configured channels."""
        # Feishu webhook
        if self._feishu_webhook:
            try:
                import urllib.request
                payload = json.dumps({
                    "msg_type": "text",
                    "content": {
                        "text": (
                            f"🚨 [{alert['severity'].upper()}] {alert['rule']}\n"
                            f"{alert['description']}\n"
                            f"失败率: {alert['failure_rate']}% (阈值: {alert['threshold']}%)\n"
                            f"事件数: {alert['total_events']}, 失败: {alert['failures']}\n"
                            f"时间: {alert['timestamp']}"
                        ),
                    },
                }).encode("utf-8")
                req = urllib.request.Request(
                    self._feishu_webhook,
                    data=payload,
                    headers={"Content-Type": "application/json"},
                )
                urllib.request.urlopen(req, timeout=5)
            except Exception:
                pass  # Notification failure must not break UX

        # Email (SMTP)
        if self._smtp_config:
            try:
                self._send_email(alert)
            except Exception:
                pass

    def _send_email(self, alert: dict):
        """Send alert email via SMTP."""
        cfg = self._smtp_config
        subject = f"[{alert['severity'].upper()}] {alert['rule']} - {alert['description']}"
        body = (
            f"Alert: {alert['rule']}\n"
            f"Severity: {alert['severity']}\n"
            f"Description: {alert['description']}\n"
            f"Failure Rate: {alert['failure_rate']}% (threshold: {alert['threshold']}%)\n"
            f"Total Events: {alert['total_events']}\n"
            f"Failures: {alert['failures']}\n"
            f"Timestamp: {alert['timestamp']}\n"
        )
        msg = MIMEText(body, "plain", "utf-8")
        msg["Subject"] = subject
        msg["From"] = cfg["from"]
        msg["To"] = cfg["to"]

        with smtplib.SMTP(cfg["host"], cfg["port"], timeout=10) as server:
            if cfg["user"]:
                server.starttls()
                server.login(cfg["user"], cfg["password"])
            server.sendmail(cfg["from"], cfg["to"].split(","), msg.as_string())

    def _log_alert(self, alert: dict):
        """Write alert to log file."""
        if self._alert_log_path is None:
            from pathlib import Path
            log_dir = Path(__file__).parent / "logs"
            log_dir.mkdir(parents=True, exist_ok=True)
            self._alert_log_path = str(log_dir / "alerts.log")
        try:
            with open(self._alert_log_path, "a", encoding="utf-8") as f:
                f.write(json.dumps(alert, ensure_ascii=False) + "\n")
        except Exception:
            pass

    def get_recent_alerts(self, limit: int = 20) -> List[dict]:
        """Read recent alerts from log file."""
        if self._alert_log_path is None:
            return []
        try:
            with open(self._alert_log_path, "r", encoding="utf-8") as f:
                lines = f.readlines()
            return [json.loads(line) for line in lines[-limit:]]
        except Exception:
            return []

    def get_rule_status(self) -> List[dict]:
        """Get current status of all alert rules."""
        result = []
        with self._lock:
            for name, rule in self.rules.items():
                stats = rule.window.stats()
                result.append({
                    "rule": name,
                    "description": rule.description,
                    "severity": rule.severity,
                    "threshold_pct": round(rule.threshold * 100, 2),
                    "current_failure_rate_pct": round(stats["failure_rate"] * 100, 2),
                    "total_events": stats["total"],
                    "failures": stats["failure"],
                    "last_fired": rule.last_fired,
                })
        return result


# Global singleton
_alert_manager: Optional[AlertManager] = None


def get_alert_manager() -> AlertManager:
    """Return the global AlertManager singleton."""
    global _alert_manager
    if _alert_manager is None:
        _alert_manager = AlertManager()
    return _alert_manager
