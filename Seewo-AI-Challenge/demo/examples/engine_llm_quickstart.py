"""Quick usage example for ``engine.llm`` (Phase 1 LLM 接入骨架入口示意).

This file is *not* part of the demo runtime - it's a documentation
artifact that the team leader can use as a reference when wiring
the new provider layer into ``app.py`` via the PATCHES.md
integration patches.

Run from ``Seewo-AI-Challenge/demo/``::

    python ../examples/engine_llm_quickstart.py
"""
from __future__ import annotations

import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
DEMO = os.path.join(HERE, "..", "Seewo-AI-Challenge", "demo")
sys.path.insert(0, DEMO)


def demo_no_key() -> None:
    """Demo without LLM_API_KEY - mock provider is auto-selected."""
    os.environ.pop("LLM_API_KEY", None)
    from engine.llm import get_provider
    provider = get_provider()
    print(f"[no-key mode] provider = {type(provider).__name__}, name = {provider.name!r}")


def demo_mock_grading() -> None:
    """End-to-end demo: mock provider grades s02's q5 with full trace."""
    from engine.llm import get_provider
    from engine.llm.base import TraceCollector
    from engine.llm.factory import store_trace, get_runtime_trace
    from engine.grader import load_json

    provider = get_provider()
    questions = load_json("questions.json")["hw_001"]["questions"]
    q5 = next(q for q in questions if q["id"] == "q5")

    # Thread the same collector through every call so the
    # multi-stage trace is preserved.
    collector = TraceCollector(student_id="s02", assignment_id="hw_001")

    # Stage 1: step-level grading
    grade_result = provider.grade_step(
        question=q5,
        student_answer="(mock student answer for s02 q5)",
        standard_answer=q5.get("answer", ""),
        student_id="s02",
        trace=collector,
    )
    print(f"[mock] q5 is_correct={grade_result['is_correct']}, score={grade_result['score']}")

    # Stage 2: correction validation
    corr_result = provider.validate_correction(
        question=q5,
        student_correction="(mock correction)",
        expected_answer=q5.get("answer", ""),
        trace=collector,
    )
    print(f"[mock] correction is_correct={corr_result['is_correct']}")

    # Stage 3: comment generation
    comment = provider.generate_comment(
        student={"id": "s02", "name": "测试学生"},
        performance={"assignment_id": "hw_001", "total": 50, "max_score": 100, "mistakes": [q5]},
        trace=collector,
    )
    print(f"[mock] comment = {comment!r}")

    # Persist + read back via the runtime store
    store_trace(collector)
    rt = get_runtime_trace("s02", "hw_001")
    print(f"[mock] runtime trace: {len(rt['stages'])} stages, "
          f"agents={rt['agents']}")
    print(f"[mock] trace string: {rt['trace']!r}")


def demo_with_key() -> None:
    """Demo with LLM_API_KEY - OpenAIProvider is selected.

    This branch is not actually called (no real key), it just
    shows what the wiring looks like.
    """
    os.environ["LLM_API_KEY"] = "sk-your-real-key"
    os.environ["LLM_BASE_URL"] = "https://api.deepseek.com/v1"
    os.environ["LLM_MODEL"] = "deepseek-chat"
    from engine.llm import get_provider
    provider = get_provider()
    print(f"[with-key mode] provider = {type(provider).__name__}, "
          f"name = {provider.name!r}")
    # NOTE: calling provider.grade_step() here would hit DeepSeek
    # for real. Don't run this in CI without a sandboxed test key.


if __name__ == "__main__":
    print("=== Phase 1 LLM 接入骨架 quickstart ===\n")
    demo_no_key()
    print()
    demo_mock_grading()
    print()
    print("--- (the following requires a real LLM_API_KEY, demo only) ---")
    print("demo_with_key()   # uncomment to actually call DeepSeek")
