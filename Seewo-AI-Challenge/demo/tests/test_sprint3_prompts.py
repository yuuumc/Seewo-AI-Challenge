"""Sprint 3 订正批改 + 情感化评语 prompt 测试（提示词工程师线）.

覆盖:
  1. 两个新 prompt 能加载且非空（correction_grading / emotional_feedback）
  2. prompt 含必要结构（角色、JSON schema、few-shot、防注入）
  3. 订正批改 fixture 覆盖 mastered/partial/not_mastered 各 ≥2 条
  4. 掌握度判定逻辑校验（fixture 的 expected_mastery_level 正确）
  5. 情感化评语质量评测对比（≥3 组，有/无历史数据差异化）
  6. 评语长度/禁忌词/必需元素校验
  7. 向后兼容：原 list_prompts() 仍返回 3 个，多学科仍 6 个

Run: cd Seewo-AI-Challenge/demo && python -m pytest tests/test_sprint3_prompts.py -v
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
    list_sprint3_prompts,
    load_correction_grading,
    load_emotional_feedback,
    load_prompt_by_name,
)
from tests._sprint3_fixtures import (
    CORRECTION_FIXTURES,
    EMOTIONAL_FEEDBACK_FIXTURES,
    FEEDBACK_QUALITY_RULES,
)


class TestSprint3PromptLoading(unittest.TestCase):
    """两个新 prompt 能加载、非空、有版本。"""

    def test_list_sprint3_prompts_returns_two(self):
        ps = list_sprint3_prompts()
        self.assertEqual(len(ps), 2)
        names = {p["name"] for p in ps}
        self.assertEqual(names, {"correction_grading", "emotional_feedback"})

    def test_each_sprint3_prompt_has_version_and_size(self):
        for p in list_sprint3_prompts():
            self.assertEqual(p["version"], PROMPTS_VERSION)
            self.assertGreater(int(p["size_bytes"]), 1000)

    def test_load_correction_grading_returns_nonempty(self):
        txt = load_correction_grading()
        self.assertIsInstance(txt, str)
        self.assertGreater(len(txt), 1000)

    def test_load_emotional_feedback_returns_nonempty(self):
        txt = load_emotional_feedback()
        self.assertIsInstance(txt, str)
        self.assertGreater(len(txt), 1000)

    def test_load_prompt_by_name_works_for_sprint3(self):
        for name in ("correction_grading", "emotional_feedback"):
            txt = load_prompt_by_name(name)
            self.assertIsInstance(txt, str)
            self.assertGreater(len(txt), 1000)


class TestCorrectionGradingPromptStructure(unittest.TestCase):
    """订正对比批改 prompt 结构完整性。"""

    def setUp(self):
        self.prompt = load_correction_grading()

    def test_has_role_definition(self):
        self.assertIn("你是一位", self.prompt)

    def test_has_mastery_level_schema(self):
        self.assertIn("mastery_level", self.prompt)
        self.assertIn("mastered", self.prompt)
        self.assertIn("partial", self.prompt)
        self.assertIn("not_mastered", self.prompt)

    def test_has_required_output_fields(self):
        for field in ("mastery_level", "comparison", "encouragement",
                       "next_steps", "confidence"):
            self.assertIn(field, self.prompt, f"missing {field}")

    def test_has_few_shot_examples(self):
        # 至少 3 个 few-shot（mastered/partial/not_mastered 各一）
        self.assertIn("Few-shot 示例 1", self.prompt)
        self.assertIn("Few-shot 示例 2", self.prompt)
        self.assertIn("Few-shot 示例 3", self.prompt)

    def test_has_mastery_criteria(self):
        self.assertIn("mastered", self.prompt)
        self.assertIn("partial", self.prompt)
        self.assertIn("not_mastered", self.prompt)
        # 判定标准要有关键词
        self.assertIn("明确回应", self.prompt)

    def test_has_anti_injection(self):
        self.assertIn("防注入", self.prompt)

    def test_has_json_schema(self):
        self.assertIn("JSON", self.prompt)


class TestEmotionalFeedbackPromptStructure(unittest.TestCase):
    """情感化评语 prompt 结构完整性。"""

    def setUp(self):
        self.prompt = load_emotional_feedback()

    def test_has_role_definition(self):
        self.assertIn("你是一位", self.prompt)

    def test_has_quality_standards(self):
        self.assertIn("具体性", self.prompt)
        self.assertIn("温暖性", self.prompt)
        self.assertIn("指导性", self.prompt)

    def test_has_length_requirement(self):
        self.assertIn("100-200", self.prompt)

    def test_has_forbidden_phrases(self):
        self.assertIn("你真棒", self.prompt)
        self.assertIn("继续努力", self.prompt)

    def test_has_few_shot_examples(self):
        self.assertIn("Few-shot 示例 1", self.prompt)
        self.assertIn("Few-shot 示例 2", self.prompt)
        self.assertIn("Few-shot 示例 3", self.prompt)

    def test_has_history_vs_no_history_distinction(self):
        # prompt 应体现有/无历史数据的差异处理
        self.assertIn("历史", self.prompt)
        self.assertIn("缺失", self.prompt)

    def test_has_anti_injection(self):
        self.assertIn("防注入", self.prompt)

    def test_output_is_plain_text_not_json(self):
        self.assertIn("直接输出评语文本", self.prompt)
        self.assertIn("不要", self.prompt)
        self.assertIn("JSON", self.prompt)


class TestCorrectionFixtures(unittest.TestCase):
    """订正批改 fixture 完整性与掌握度覆盖。"""

    def test_at_least_six_fixtures(self):
        self.assertGreaterEqual(len(CORRECTION_FIXTURES), 6)

    def test_mastery_level_coverage(self):
        """mastered/partial/not_mastered 各 ≥2 条。"""
        counts = {"mastered": 0, "partial": 0, "not_mastered": 0}
        for f in CORRECTION_FIXTURES:
            level = f["expected_mastery_level"]
            self.assertIn(level, counts, f"unknown level: {level}")
            counts[level] += 1
        for level, count in counts.items():
            self.assertGreaterEqual(count, 2, f"{level}: only {count} fixtures, need ≥2")

    def test_each_fixture_has_required_keys(self):
        required = {"id", "question_stem", "original_answer", "original_grading",
                    "correction_text", "expected_mastery_level", "expected_analysis"}
        for f in CORRECTION_FIXTURES:
            missing = required - set(f.keys())
            self.assertFalse(missing, f"{f.get('id')}: missing {missing}")

    def test_each_fixture_analysis_has_required_fields(self):
        required = {"mastery_level", "comparison", "encouragement",
                    "next_steps", "confidence"}
        for f in CORRECTION_FIXTURES:
            ea = f["expected_analysis"]
            missing = required - set(ea.keys())
            self.assertFalse(missing, f"{f['id']}: missing {missing}")

    def test_mastery_level_consistency(self):
        """fixture 的 expected_mastery_level 与 expected_analysis.mastery_level 一致。"""
        for f in CORRECTION_FIXTURES:
            self.assertEqual(
                f["expected_mastery_level"],
                f["expected_analysis"]["mastery_level"],
                f"{f['id']}: mismatch",
            )

    def test_confidence_in_valid_range(self):
        for f in CORRECTION_FIXTURES:
            c = f["expected_analysis"]["confidence"]
            self.assertGreater(c, 0.0)
            self.assertLessEqual(c, 1.0)

    def test_encouragement_nonempty(self):
        for f in CORRECTION_FIXTURES:
            fb = f["expected_analysis"]["encouragement"]
            self.assertIsInstance(fb, str)
            self.assertGreater(len(fb), 10, f"{f['id']}: encouragement too short")

    def test_original_grading_has_step_results(self):
        for f in CORRECTION_FIXTURES:
            sr = f["original_grading"].get("step_results", [])
            self.assertGreater(len(sr), 0, f"{f['id']}: no step_results")

    def test_fixtures_cover_multiple_subjects(self):
        """fixture 覆盖 ≥2 个学科。"""
        subjects = {f["subject"] for f in CORRECTION_FIXTURES}
        self.assertGreaterEqual(len(subjects), 2, f"only {subjects}")


class TestEmotionalFeedbackFixtures(unittest.TestCase):
    """情感化评语质量评测对比样本。"""

    def test_at_least_three_comparison_groups(self):
        self.assertGreaterEqual(len(EMOTIONAL_FEEDBACK_FIXTURES), 3)

    def test_each_group_has_with_and_without_history(self):
        for g in EMOTIONAL_FEEDBACK_FIXTURES:
            self.assertIn("with_history", g)
            self.assertIn("without_history", g)
            self.assertIn("student_name", g["with_history"])
            self.assertIn("student_name", g["without_history"])

    def test_with_history_has_trend_data(self):
        for g in EMOTIONAL_FEEDBACK_FIXTURES:
            wh = g["with_history"]
            self.assertIn("score_trend", wh, f"{g['id']}: no score_trend")
            self.assertIsInstance(wh["score_trend"], list)
            self.assertGreater(len(wh["score_trend"]), 1)

    def test_without_history_lacks_trend(self):
        """无历史数据组不应有 score_trend。"""
        for g in EMOTIONAL_FEEDBACK_FIXTURES:
            wh = g["without_history"]
            self.assertNotIn("score_trend", wh, f"{g['id']}: should not have trend")

    def test_with_history_has_correction_data(self):
        for g in EMOTIONAL_FEEDBACK_FIXTURES:
            wh = g["with_history"]
            self.assertIn("correction_rate", wh, f"{g['id']}: no correction_rate")
            self.assertIn("correction_mastery", wh, f"{g['id']}: no correction_mastery")

    def test_without_history_has_note(self):
        for g in EMOTIONAL_FEEDBACK_FIXTURES:
            wh = g["without_history"]
            self.assertIn("note", wh)

    def test_expected_features_defined(self):
        for g in EMOTIONAL_FEEDBACK_FIXTURES:
            self.assertIn("with_history_expected_features", g)
            self.assertIn("without_history_expected_features", g)
            self.assertGreater(len(g["with_history_expected_features"]), 1)
            self.assertGreater(len(g["without_history_expected_features"]), 1)

    def test_groups_cover_different_score_levels(self):
        """对比组覆盖不同分数段（高/中/低）。"""
        scores = [g["with_history"]["current_score"] for g in EMOTIONAL_FEEDBACK_FIXTURES]
        self.assertGreater(max(scores), 90)  # 高分段
        self.assertLess(min(scores), 70)    # 低分段


class TestFeedbackQualityRules(unittest.TestCase):
    """评语质量规则校验常量。"""

    def test_min_max_length_defined(self):
        self.assertGreater(FEEDBACK_QUALITY_RULES["min_length"], 0)
        self.assertGreater(FEEDBACK_QUALITY_RULES["max_length"],
                           FEEDBACK_QUALITY_RULES["min_length"])

    def test_forbidden_phrases_not_empty(self):
        self.assertGreater(len(FEEDBACK_QUALITY_RULES["forbidden_phrases"]), 0)

    def test_required_elements_defined(self):
        self.assertGreater(len(FEEDBACK_QUALITY_RULES["required_elements"]), 0)

    def test_forbidden_phrases_in_prompt(self):
        """prompt 中应提及禁忌词。"""
        txt = load_emotional_feedback()
        for phrase in FEEDBACK_QUALITY_RULES["forbidden_phrases"]:
            self.assertIn(phrase, txt, f"prompt should mention forbidden: {phrase}")


class TestBackwardCompat(unittest.TestCase):
    """向后兼容：原 API 不受 Sprint 3 影响。"""

    def test_list_prompts_still_returns_three(self):
        ps = list_prompts()
        self.assertEqual(len(ps), 3)

    def test_list_multi_subject_prompts_still_returns_six(self):
        ps = list_multi_subject_prompts()
        self.assertEqual(len(ps), 6)

    def test_original_load_functions_work(self):
        from prompts import (
            load_math_step_grading,
            load_correction_validation,
            load_comment_generation,
        )
        for fn in (load_math_step_grading, load_correction_validation, load_comment_generation):
            txt = fn()
            self.assertIsInstance(txt, str)
            self.assertGreater(len(txt), 500)

    def test_sprint3_prompts_separate_from_multi_subject(self):
        """Sprint 3 prompt 不出现在 list_multi_subject_prompts 中。"""
        ms_names = {p["name"] for p in list_multi_subject_prompts()}
        s3_names = {p["name"] for p in list_sprint3_prompts()}
        self.assertEqual(ms_names & s3_names, set())


if __name__ == "__main__":
    unittest.main(verbosity=2)
