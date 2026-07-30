"""多学科/多题型 prompt 测试（Sprint 1 · 提示词工程师线）。

验证：
1. 7 个学科/题型 prompt 都能加载且非空；
2. 每个 prompt 含必要结构（角色、JSON schema、error_types 枚举、防注入）；
3. 每个 mock fixture 的 expected_analysis 与该学科的 error_types 词表一致；
4. mock fixture 的 step_results 与 reference_steps 一一对应；
5. 向后兼容：原 list_prompts() 仍返回 3 个，原 3 个 load 函数仍可用。

Run: cd Seewo-AI-Challenge/demo && python -m pytest tests/test_multi_subject_prompts.py -v
"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

HERE = Path(__file__).parent
DEMO = HERE.parent
sys.path.insert(0, str(DEMO))

from prompts import (
    PROMPTS_VERSION,
    list_prompts,
    list_multi_subject_prompts,
    list_subject_types,
    get_prompt,
    load_prompt_by_name,
    load_math_step_grading,
    load_correction_validation,
    load_comment_generation,
)
from tests._multi_subject_fixtures import MOCK_SAMPLES, ERROR_TYPES_BY_SUBJECT


class TestMultiSubjectPromptsLoader(unittest.TestCase):
    """多学科 prompt 加载与注册表 API。"""

    def test_list_multi_subject_prompts_returns_six(self):
        ps = list_multi_subject_prompts()
        self.assertEqual(len(ps), 6)
        names = {p["name"] for p in ps}
        expected = {
            "math_application_grading", "chinese_essay_grading",
            "english_cloze_grading", "english_essay_grading",
            "physics_short_grading", "chemistry_short_grading",
        }
        self.assertEqual(names, expected)

    def test_each_multi_prompt_nonempty_and_has_version(self):
        for p in list_multi_subject_prompts():
            self.assertEqual(p["version"], PROMPTS_VERSION)
            self.assertGreater(int(p["size_bytes"]), 800)

    def test_list_subject_types_returns_seven(self):
        st = list_subject_types()
        self.assertEqual(len(st), 7)
        for s in ("math_calculation", "math_application", "chinese_essay",
                   "english_cloze", "english_essay", "physics_short", "chemistry_short"):
            self.assertIn(s, st)

    def test_get_prompt_returns_nonempty_string_for_each(self):
        for st in list_subject_types():
            txt = get_prompt(st)
            self.assertIsInstance(txt, str)
            self.assertGreater(len(txt), 800, f"{st} prompt too short")

    def test_get_prompt_unknown_raises_keyerror(self):
        with self.assertRaises(KeyError):
            get_prompt("nonexistent_subject")

    def test_load_prompt_by_name_works_for_all_nine(self):
        for name in ("math_step_grading", "correction_validation", "comment_generation",
                      "math_application_grading", "chinese_essay_grading",
                      "english_cloze_grading", "english_essay_grading",
                      "physics_short_grading", "chemistry_short_grading"):
            txt = load_prompt_by_name(name)
            self.assertIsInstance(txt, str)
            self.assertGreater(len(txt), 800)


class TestBackwardCompat(unittest.TestCase):
    """向后兼容：原 3-prompt API 不受影响。"""

    def test_list_prompts_still_returns_three(self):
        ps = list_prompts()
        self.assertEqual(len(ps), 3)
        names = {p["name"] for p in ps}
        self.assertEqual(names, {"math_step_grading", "correction_validation", "comment_generation"})

    def test_original_load_functions_work(self):
        for fn in (load_math_step_grading, load_correction_validation, load_comment_generation):
            txt = fn()
            self.assertIsInstance(txt, str)
            self.assertGreater(len(txt), 1000)


class TestPromptStructure(unittest.TestCase):
    """每个多学科 prompt 的结构完整性。"""

    def test_each_prompt_has_required_sections(self):
        for st in list_subject_types():
            txt = get_prompt(st)
            # 角色定义
            self.assertIn("你是一位", txt, f"{st}: missing role definition")
            # JSON schema
            self.assertIn("JSON", txt, f"{st}: missing JSON schema")
            # error_types 枚举（至少含"未作答"）
            self.assertIn("未作答", txt, f"{st}: missing 未作答 in error_types")
            # 防注入条款
            self.assertIn("防注入", txt, f"{st}: missing anti-injection clause")
            # step_results 字段
            self.assertIn("step_results", txt, f"{st}: missing step_results in schema")

    def test_each_prompt_error_types_match_fixture_vocab(self):
        """prompt 中出现的 error_types 与 fixture 词表一致。"""
        for st in list_subject_types():
            if st == "math_calculation":
                continue  # 复用 eval/golden_set，不在这批 fixture 里
            txt = get_prompt(st)
            vocab = ERROR_TYPES_BY_SUBJECT[st]
            # prompt 应至少提到该学科 3 个以上 error_types
            mentioned = [et for et in vocab if et in txt]
            self.assertGreater(len(mentioned), 2,
                               f"{st}: prompt only mentions {mentioned} from vocab {vocab}")


class TestMockFixtures(unittest.TestCase):
    """mock fixture 的 schema 一致性。"""

    def test_six_mock_samples_exist(self):
        self.assertEqual(len(MOCK_SAMPLES), 6)

    def test_each_sample_has_required_keys(self):
        required = {"id", "subject_type", "question_stem", "max_score",
                    "reference_steps", "student_answer", "expected_analysis"}
        for s in MOCK_SAMPLES:
            missing = required - set(s.keys())
            self.assertFalse(missing, f"{s.get('id')}: missing keys {missing}")

    def test_step_results_match_reference_steps(self):
        for s in MOCK_SAMPLES:
            ref = s["reference_steps"]
            sr = s["expected_analysis"]["step_results"]
            self.assertEqual(len(sr), len(ref),
                             f"{s['id']}: step_results {len(sr)} != reference {len(ref)}")
            for j, (r, x) in enumerate(zip(ref, sr)):
                self.assertEqual(r["step"], x["step"],
                                 f"{s['id']}[{j}]: step number mismatch")
                self.assertIn("content", r)
                self.assertIn("correct", x)
                self.assertIn("comment", x)

    def test_error_types_within_subject_vocab(self):
        for s in MOCK_SAMPLES:
            st = s["subject_type"]
            vocab = ERROR_TYPES_BY_SUBJECT[st]
            for et in s["expected_analysis"]["error_types"]:
                self.assertIn(et, vocab,
                              f"{s['id']}: error_type {et!r} not in {st} vocab")

    def test_confidence_in_valid_range(self):
        for s in MOCK_SAMPLES:
            c = s["expected_analysis"]["confidence"]
            self.assertGreater(c, 0.0)
            self.assertLessEqual(c, 1.0)

    def test_overall_feedback_nonempty(self):
        for s in MOCK_SAMPLES:
            fb = s["expected_analysis"]["overall_feedback"]
            self.assertIsInstance(fb, str)
            self.assertGreater(len(fb), 20, f"{s['id']}: overall_feedback too short")


class TestSchemaFieldCompatibility(unittest.TestCase):
    """mock fixture 的 expected_analysis 字段与 grader.py 返回 shape 兼容。"""

    def test_expected_analysis_has_grader_compatible_fields(self):
        required = {"step_results", "error_types", "confidence",
                    "overall_feedback", "need_teacher_review"}
        for s in MOCK_SAMPLES:
            ea = s["expected_analysis"]
            missing = required - set(ea.keys())
            self.assertFalse(missing, f"{s['id']}: missing analysis fields {missing}")

    def test_step_result_fields(self):
        for s in MOCK_SAMPLES:
            for sr in s["expected_analysis"]["step_results"]:
                self.assertIn("step", sr)
                self.assertIn("content", sr)
                self.assertIn("correct", sr)
                self.assertIn("comment", sr)
                self.assertIsInstance(sr["correct"], bool)


if __name__ == "__main__":
    unittest.main(verbosity=2)
