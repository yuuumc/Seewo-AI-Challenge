"""V2.0 Sprint 6 (6.10): AI 内容安全过滤层.

作为 provider 层的 post-processing hook，对所有经 LLM 生成的文本输出统一过滤。

三级判定: pass / degrade / block
- pass: 原文返回
- degrade: 仅 academic_mislead → 替换该字段为规则引擎结果
- block: critical/high 命中 → 整条丢弃，走降级文案

三路径接入:
  1. grade_long_answer → 过滤 overall_feedback
  2. correction_grader → 过滤 encouragement
  3. emotional_feedback → 过滤整条文本

使用方式:
    from content_safety_filter import filter_llm_output
    result = filter_llm_output(raw_text, scenario="grading", school_id=1, student_id="s01")
    if result["decision"] == "pass":
        use raw_text
    elif result["decision"] == "degrade":
        use result["degraded_to"]
    else:  # block
        use result["degraded_to"]
"""
from __future__ import annotations

import json
import os
import re
import time
from pathlib import Path
from typing import Any, Optional

from security import audit_log

_DATA_DIR = Path(__file__).parent / "data"
_LOG_FILE = _DATA_DIR / "llm_content_filter_log.json"


# ---------------------------------------------------------------------------
# Log persistence
# ---------------------------------------------------------------------------

def _load_logs() -> list[dict]:
    if not _LOG_FILE.exists():
        return []
    with open(_LOG_FILE, "r", encoding="utf-8") as f:
        return json.load(f)


def _save_logs(logs: list[dict]) -> None:
    _DATA_DIR.mkdir(parents=True, exist_ok=True)
    tmp = _LOG_FILE.with_suffix(".tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(logs, f, ensure_ascii=False, indent=2)
    tmp.replace(_LOG_FILE)


def _write_log(record: dict) -> None:
    logs = _load_logs()
    logs.append(record)
    # Keep last 10000 records
    if len(logs) > 10000:
        logs = logs[-10000:]
    _save_logs(logs)


# ---------------------------------------------------------------------------
# Mock content safety filter (rule-based, no LLM required)
# ---------------------------------------------------------------------------

# Pattern-based detection for mock mode
_MOCK_PATTERNS = {
    "improper_guidance": [
        r"不交作业", r"可以不交", r"放弃.*课", r"找陌生人", r"不用学",
        r"作弊", r"抄袭.*可以", r"逃课",
    ],
    "value_bias": [
        r"女生.*已经.*棒", r"男生.*不会", r"农村.*学生", r"差生",
        r"成绩好.*看得起", r"有钱.*家庭", r"穷.*不配",
        r"歧视", r"拜金", r"享乐",
    ],
    "sensitive_content": [
        r"政治.*敏感", r"宗教.*优越", r"暴力.*血腥", r"色情",
        r"赌博", r"毒品",
    ],
    "privacy_leak": [
        # Match patterns like "你比张伟做得好" or "李四的成绩"
        r"你比.{1,4}做得好", r".{1,4}的成绩.{0,5}比你",
        r"排名.*第.{1,3}", r"其他同学.*姓名",
    ],
    "academic_mislead": [
        r"导数为.*0.*一定是极值", r"负数.*开平方.*为正",
        r"sin.*大于.*1.*正常", r"概率.*大于.*1",
        r"速度.*等于.*位移", r"加速度.*等于.*速度",
    ],
}

# Severity mapping
_SEVERITY_MAP = {
    "improper_guidance": "critical",
    "value_bias": "critical",
    "sensitive_content": "high",
    "privacy_leak": "high",
    "academic_mislead": "medium",
}

_DECISION_MAP = {
    "critical": "block",
    "high": "block",
    "medium": "degrade",
}


def _mock_filter(text: str) -> dict:
    """Rule-based mock content safety filter (no LLM required).

    Returns dict with: decision, category, severity, confidence, reason
    """
    if not text:
        return {"decision": "pass", "category": "none", "severity": "none",
                "confidence": 1.0, "reason": "无安全问题"}

    best_category = "none"
    best_severity = "none"
    best_confidence = 0.0
    best_reason = "无安全问题"

    for category, patterns in _MOCK_PATTERNS.items():
        for pattern in patterns:
            if re.search(pattern, text, re.IGNORECASE):
                severity = _SEVERITY_MAP[category]
                # Higher severity wins
                if best_severity == "none" or (
                    severity == "critical" or
                    (severity == "high" and best_severity != "critical") or
                    (severity == "medium" and best_severity == "none")
                ):
                    best_category = category
                    best_severity = severity
                    best_confidence = 0.85
                    best_reason = f"命中{category}规则"
                break

    decision = _DECISION_MAP.get(best_severity, "pass")

    return {
        "decision": decision,
        "category": best_category,
        "severity": best_severity,
        "confidence": best_confidence,
        "reason": best_reason,
    }


# ---------------------------------------------------------------------------
# LLM-based filter (uses provider when available)
# ---------------------------------------------------------------------------

def _llm_filter(text: str) -> dict | None:
    """LLM-based content safety filter. Returns None if LLM unavailable."""
    api_key = os.environ.get("LLM_API_KEY", "")
    if not api_key:
        return None

    try:
        from engine.llm.factory import get_provider
        from prompts import load_content_safety_filter

        provider = get_provider()
        if provider.__class__.__name__ == "MockProvider":
            return None

        system_prompt = load_content_safety_filter()
        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": f"请审核以下文本：\n\n{text}"},
        ]
        data, err = provider._chat(messages, json_mode=True)

        if isinstance(data, dict):
            return {
                "decision": data.get("decision", "pass"),
                "category": data.get("category", "none"),
                "severity": data.get("severity", "none"),
                "confidence": float(data.get("confidence", 0.0)),
                "reason": data.get("reason", ""),
            }
    except Exception:
        pass

    return None


# ---------------------------------------------------------------------------
# Degradation fallbacks
# ---------------------------------------------------------------------------

def _degrade_grading_feedback(student_answer: str, question: dict, student_id: str) -> str:
    """Rule-engine fallback for grading overall_feedback."""
    return "思路方向基本正确，但在计算环节出现失误。建议加强相关知识点练习。"


def _degrade_correction_encouragement(student_id: str) -> str:
    """Rule-engine fallback for correction encouragement."""
    return f"你在本次订正中展现了进步，继续保持。"


def _degrade_emotional_feedback(student_id: str, score: float = 0) -> str:
    """Rule-engine fallback for emotional feedback text."""
    return f"{student_id}同学，本次表现有进步，继续加油。"


def _degrade_personalized_comment(student_id: str) -> str:
    """Rule-engine fallback for personalized comment."""
    return f"{student_id}同学，本次作业整体完成良好，继续保持。"


# ---------------------------------------------------------------------------
# Main filter function
# ---------------------------------------------------------------------------

def filter_llm_output(
    raw_text: str,
    scenario: str = "grading",
    school_id: int = 1,
    student_id: str = "",
    prompt_name: str = "",
    request_id: str = "",
    question: dict | None = None,
    student_answer: str = "",
) -> dict:
    """Filter LLM output through content safety check.

    Args:
        raw_text: LLM-generated text to filter
        scenario: "grading" | "correction" | "emotional" | "comment"
        school_id: school ID for multi-tenant logging
        student_id: associated student
        prompt_name: prompt that generated the text
        request_id: trace ID (from Sprint 6.1 structured logging)
        question: question dict (for degrade fallback)
        student_answer: student's answer (for degrade fallback)

    Returns:
        dict with keys:
            decision: "pass" | "degrade" | "block"
            filtered_text: the text to use (original if pass, degraded if degrade/block)
            category, severity, confidence, reason
            degraded_to: degraded text (None if pass)
    """
    start_time = time.time()

    # Try LLM filter first, fall back to mock
    result = _llm_filter(raw_text)
    if result is None:
        result = _mock_filter(raw_text)

    decision = result["decision"]
    latency_ms = int((time.time() - start_time) * 1000)

    # Determine filtered text
    filtered_text = raw_text
    degraded_to = None

    if decision == "degrade":
        # Replace only the problematic field with rule-engine output
        degraded_to = _generate_degraded_text(scenario, student_id, question or {}, student_answer)
        filtered_text = degraded_to
    elif decision == "block":
        # Discard entire output, use rule-engine fallback
        degraded_to = _generate_degraded_text(scenario, student_id, question or {}, student_answer)
        filtered_text = degraded_to

    # Write filter log
    log_record = {
        "school_id": school_id,
        "student_id": student_id,
        "request_id": request_id,
        "scenario": scenario,
        "prompt_name": prompt_name,
        "raw_output": (raw_text or "")[:2000],
        "decision": decision,
        "category": result["category"],
        "severity": result["severity"],
        "confidence": result["confidence"],
        "reason": result["reason"],
        "degraded_to": degraded_to,
        "llm_model": os.environ.get("LLM_MODEL", "mock"),
        "latency_ms": latency_ms,
        "created_at": time.strftime("%Y-%m-%dT%H:%M:%S%z", time.localtime()),
    }
    _write_log(log_record)

    # Audit log for non-pass results
    if decision != "pass":
        audit_log(
            "content_filter_hit",
            school_id=school_id,
            student_id=student_id,
            scenario=scenario,
            decision=decision,
            category=result["category"],
            severity=result["severity"],
            prompt_name=prompt_name,
            resource=f"filter_log:{scenario}",
        )

    return {
        "decision": decision,
        "filtered_text": filtered_text,
        "category": result["category"],
        "severity": result["severity"],
        "confidence": result["confidence"],
        "reason": result["reason"],
        "degraded_to": degraded_to,
    }


def _generate_degraded_text(
    scenario: str,
    student_id: str,
    question: dict,
    student_answer: str,
) -> str:
    """Generate degraded text based on scenario."""
    if scenario == "grading":
        return _degrade_grading_feedback(student_answer, question, student_id)
    elif scenario == "correction":
        return _degrade_correction_encouragement(student_id)
    elif scenario == "emotional":
        return _degrade_emotional_feedback(student_id)
    elif scenario == "comment":
        return _degrade_personalized_comment(student_id)
    else:
        return "系统生成内容正在审核中，请稍后查看。"


def get_filter_logs(school_id: int = None, limit: int = 100) -> list[dict]:
    """Get content filter logs for admin display."""
    logs = _load_logs()
    if school_id is not None:
        logs = [l for l in logs if l.get("school_id") == school_id]
    return logs[-limit:]


def get_filter_stats(school_id: int = None) -> dict:
    """Get aggregate filter statistics."""
    logs = _load_logs()
    if school_id is not None:
        logs = [l for l in logs if l.get("school_id") == school_id]

    total = len(logs)
    passed = sum(1 for l in logs if l.get("decision") == "pass")
    degraded = sum(1 for l in logs if l.get("decision") == "degrade")
    blocked = sum(1 for l in logs if l.get("decision") == "block")

    return {
        "total": total,
        "pass": passed,
        "degrade": degraded,
        "block": blocked,
        "block_rate": (blocked / total * 100) if total > 0 else 0,
        "degrade_rate": (degraded / total * 100) if total > 0 else 0,
    }
