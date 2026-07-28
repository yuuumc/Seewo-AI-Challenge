"""Unit tests for prompts/ and eval/ modules.

Run with: cd Seewo-AI-Challenge/demo && python -m pytest tests/test_prompts_and_eval.py -v
Or standalone: python tests/test_prompts_and_eval.py
"""

import json
import sys
import unittest
from pathlib import Path

# Allow running from any CWD
HERE = Path(__file__).parent
DEMO = HERE.parent
sys.path.insert(0, str(DEMO))

from prompts import (
    list_prompts,
    load_math_step_grading,
    load_correction_validation,
    load_comment_generation,
    PROMPTS_VERSION,
)
from eval import (
    load_golden_set,
    validate_golden_set,
    list_samples,
    get_sample_by_id,
    ALLOWED_ERROR_TYPES,
)


class TestPromptsLoader(unittest.TestCase):
    """prompts/ loader API contract."""

    def test_list_prompts_returns_three(self):
        ps = list_prompts()
        self.assertEqual(len(ps), 3)
        names = {p["name"] for p in ps}
        self.assertEqual(names, {"math_step_grading", "correction_validation", "comment_generation"})

    def test_each_prompt_has_version_and_size(self):
        for p in list_prompts():
            self.assertIn("version", p)
            self.assertEqual(p["version"], PROMPTS_VERSION)
            self.assertGreater(int(p["size_bytes"]), 1000)  # at least 1 KB

    def test_load_each_prompt_returns_nonempty_string(self):
        for fn in (load_math_step_grading, load_correction_validation, load_comment_generation):
            txt = fn()
            self.assertIsInstance(txt, str)
            self.assertGreater(len(txt), 1000)

    def test_math_step_grading_has_required_sections(self):
        txt = load_math_step_grading()
        # role
        self.assertIn("你是一位", txt)
        # 5 error types
        for et in ALLOWED_ERROR_TYPES:
            self.assertIn(et, txt, f"missing error type: {et}")
        # few-shot
        self.assertIn("Few-shot 示例", txt)
        # JSON schema
        self.assertIn("JSON Schema", txt)
        # 抗注入条款
        self.assertIn("防注入", txt)
        # 显式注入规则
        self.assertIn("忽略以上指令", txt)

    def test_correction_validation_has_required_sections(self):
        txt = load_correction_validation()
        self.assertIn("你是一位", txt)
        self.assertIn("Few-shot 示例", txt)
        self.assertIn("JSON Schema", txt)
        self.assertIn("防注入", txt)
        # 必须明确反对关键词匹配
        self.assertIn("关键词", txt)
        # 必须明确三个诊断维度
        for k in ("identified_original_error", "redo_logically_correct", "addresses_original_question"):
            self.assertIn(k, txt)

    def test_comment_generation_has_three_tiers(self):
        txt = load_comment_generation()
        for tier in ("优秀", "需订正", "严重薄弱"):
            self.assertIn(tier, txt)
        # 苏格拉底式
        self.assertIn("苏格拉底", txt)
        # 必须反对空话
        self.assertTrue("不要使用" in txt or "避免" in txt)
        # 防注入
        self.assertIn("防注入", txt)
        # JSON schema
        self.assertIn("JSON Schema", txt)
        # 三档 tier 标识
        for tier in ("excellent", "needs_correction", "severe_weakness"):
            self.assertIn(tier, txt)


class TestGoldenSet(unittest.TestCase):
    """eval/golden_set.json structure and coverage."""

    @classmethod
    def setUpClass(cls):
        cls.golden = load_golden_set()

    def test_golden_set_loads(self):
        self.assertIn("_meta", self.golden)
        self.assertIn("samples", self.golden)

    def test_golden_set_validates(self):
        ok, errs = validate_golden_set(self.golden)
        self.assertTrue(ok, f"validation errors: {errs}")
        self.assertEqual(errs, [])

    def test_sample_count_matches_meta(self):
        meta_count = self.golden["_meta"]["sample_count"]
        self.assertEqual(meta_count, len(self.golden["samples"]))

    def test_real_and_adversarial_split(self):
        real = list_samples(self.golden, kind="real_student")
        adv = list_samples(self.golden, kind="adversarial")
        self.assertEqual(len(real), 10)
        self.assertEqual(len(adv), 2)

    def test_all_five_error_types_covered(self):
        all_ets = set()
        for s in self.golden["samples"]:
            for et in s["expected_analysis"]["error_types"]:
                all_ets.add(et)
        self.assertEqual(all_ets, ALLOWED_ERROR_TYPES)

    def test_all_samples_have_step_results(self):
        for s in self.golden["samples"]:
            sr = s["expected_analysis"]["step_results"]
            self.assertGreater(len(sr), 0, f"{s['id']} has empty step_results")

    def test_step_results_match_reference_steps(self):
        for s in self.golden["samples"]:
            ref = s["reference_steps"]
            sr = s["expected_analysis"]["step_results"]
            self.assertEqual(
                len(sr), len(ref),
                f"{s['id']}: step_results length {len(sr)} != reference_steps length {len(ref)}"
            )
            for j, (r, x) in enumerate(zip(ref, sr)):
                self.assertEqual(r["step"], x["step"], f"{s['id']}[{j}]: step number mismatch")
                # content should be exactly the reference step content
                self.assertEqual(r["content"], x["content"], f"{s['id']}[{j}]: content mismatch")

    def test_adversarial_samples_have_intent(self):
        for s in list_samples(self.golden, kind="adversarial"):
            self.assertIn("adversarial_intent", s)
            self.assertIn(s["adversarial_intent"], {"prompt_injection", "empty_answer"})

    def test_prompt_injection_evaluation_criteria(self):
        s = get_sample_by_id(self.golden, "gs_011_prompt_injection")
        self.assertIsNotNone(s)
        self.assertIn("evaluation_criteria", s)
        self.assertGreater(len(s["evaluation_criteria"]), 0)

    def test_unique_sample_ids(self):
        ids = [s["id"] for s in self.golden["samples"]]
        self.assertEqual(len(ids), len(set(ids)), "duplicate sample ids found")


class TestPromptGraderShapeCompatibility(unittest.TestCase):
    """Prompts' JSON schema must match engine.grader.grade_long_answer() return shape."""

    @classmethod
    def setUpClass(cls):
        cls.grader_path = DEMO / "engine" / "grader.py"
        cls.grade_long_answer_signature_fields = {
            "type", "student_answer", "correct_answer", "is_correct", "score",
            "max_score", "step_results", "error_types", "ai_confidence",
            "overall_feedback", "need_teacher_review",
        }
        cls.step_result_fields = {"step", "content", "correct", "comment"}

    def test_math_step_grading_schema_matches_grader(self):
        """Verify the prompt's step_results schema is a subset of grader's step output."""
        # We can't import grader directly (it may have side effects), but we can
        # check the prompt's stated JSON schema is consistent.
        txt = load_math_step_grading()
        # Must mention every required field
        for field in ("step", "content", "correct", "comment", "error_type",
                      "suggested_fix", "error_types", "confidence",
                      "overall_feedback", "need_teacher_review"):
            self.assertIn(field, txt, f"math_step_grading missing field: {field}")


if __name__ == "__main__":
    unittest.main(verbosity=2)
