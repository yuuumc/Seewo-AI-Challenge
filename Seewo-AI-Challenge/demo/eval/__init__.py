"""eval package — golden set loader + evaluator skeleton for Seewo-AI-Challenge.

Public API:
    load_golden_set(path=None) -> dict   # load JSON
    validate_golden_set(golden) -> tuple[bool, list[str]]   # schema validation
    list_samples(golden, kind=None) -> list[dict]   # filter
    get_sample_by_id(golden, sample_id) -> dict | None
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import List, Optional, Tuple

EVAL_DIR = Path(__file__).parent
DEFAULT_GOLDEN_PATH = EVAL_DIR / "golden_set.json"

# Required top-level keys for each sample
_REQUIRED_SAMPLE_KEYS = {
    "id",
    "kind",
    "question_stem",
    "question_type",
    "knowledge",
    "max_score",
    "reference_steps",
    "student_answer",
    "expected_analysis",
}

# Required keys in expected_analysis (must match grader.py return shape)
_REQUIRED_ANALYSIS_KEYS = {
    "step_results",
    "error_types",
    "confidence",
    "overall_feedback",
    "need_teacher_review",
}

# Allowed error_types (must match grader.py _get_suggested_fix() keys)
ALLOWED_ERROR_TYPES = frozenset({
    "计算错误",
    "概念混淆",
    "逻辑跳跃",
    "未作答",
    "表述不严谨",
})


def load_golden_set(path: Optional[Path] = None) -> dict:
    """Load the golden set JSON.

    Args:
        path: optional path to a custom JSON; defaults to eval/golden_set.json.

    Returns:
        Parsed dict with keys: _meta, samples.

    Raises:
        FileNotFoundError: if the JSON file does not exist.
        json.JSONDecodeError: if the file is not valid JSON.
    """
    target = Path(path) if path else DEFAULT_GOLDEN_PATH
    if not target.exists():
        raise FileNotFoundError(f"Golden set not found: {target}")
    with open(target, "r", encoding="utf-8") as f:
        return json.load(f)


def validate_golden_set(golden: dict) -> Tuple[bool, List[str]]:
    """Validate the golden set against the expected schema.

    Args:
        golden: parsed golden set dict (from load_golden_set).

    Returns:
        (is_valid, errors) — is_valid is True iff errors is empty.
    """
    errors: List[str] = []

    if "_meta" not in golden:
        errors.append("Missing _meta section")
    if "samples" not in golden:
        errors.append("Missing samples section")
        return False, errors

    sample_ids_seen = set()
    for idx, sample in enumerate(golden["samples"]):
        prefix = f"samples[{idx}] (id={sample.get('id', '?')})"

        # Required top-level keys
        missing = _REQUIRED_SAMPLE_KEYS - set(sample.keys())
        if missing:
            errors.append(f"{prefix}: missing keys: {sorted(missing)}")

        # Unique sample id
        sid = sample.get("id")
        if sid in sample_ids_seen:
            errors.append(f"{prefix}: duplicate sample id {sid!r}")
        sample_ids_seen.add(sid)

        # expected_analysis keys
        analysis = sample.get("expected_analysis", {})
        missing_a = _REQUIRED_ANALYSIS_KEYS - set(analysis.keys())
        if missing_a:
            errors.append(f"{prefix}.expected_analysis: missing keys: {sorted(missing_a)}")

        # error_types must be subset of allowed
        for et in analysis.get("error_types", []):
            if et not in ALLOWED_ERROR_TYPES:
                errors.append(
                    f"{prefix}.expected_analysis.error_types: "
                    f"unknown error type {et!r}; allowed: {sorted(ALLOWED_ERROR_TYPES)}"
                )

        # step_results shape sanity
        for j, sr in enumerate(analysis.get("step_results", [])):
            if "step" not in sr or "content" not in sr or "correct" not in sr:
                errors.append(
                    f"{prefix}.step_results[{j}]: missing required keys (step, content, correct)"
                )
            if sr.get("correct") is False and "error_type" not in sr:
                errors.append(
                    f"{prefix}.step_results[{j}]: correct=False but no error_type"
                )

    return len(errors) == 0, errors


def list_samples(golden: dict, kind: Optional[str] = None) -> List[dict]:
    """List samples, optionally filtered by kind.

    Args:
        golden: parsed golden set.
        kind: optional filter — "real_student" / "adversarial" / None for all.

    Returns:
        List of sample dicts.
    """
    samples = golden.get("samples", [])
    if kind is None:
        return samples
    return [s for s in samples if s.get("kind") == kind]


def get_sample_by_id(golden: dict, sample_id: str) -> Optional[dict]:
    """Get a single sample by its id, or None if not found."""
    for s in golden.get("samples", []):
        if s.get("id") == sample_id:
            return s
    return None


__all__ = [
    "EVAL_DIR",
    "DEFAULT_GOLDEN_PATH",
    "ALLOWED_ERROR_TYPES",
    "load_golden_set",
    "validate_golden_set",
    "list_samples",
    "get_sample_by_id",
]
