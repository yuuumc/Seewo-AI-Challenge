"""Sprint 4 情感化评语接入批改流程测试（提示词工程师线）.

覆盖:
  1. grade_long_answer 结果含 emotional_feedback 字段
  2. grade_correction 结果含 emotional_feedback 字段
  3. mock 模式评语非固定文案（不同学生历史产出不同评语）
  4. 评语长度/禁忌词校验
  5. LLM hook 无 key 时返回 None（走 mock）
  6. 评测脚本 mock 模式可跑通并输出报告

Run: cd Seewo-AI-Challenge/demo && python -m pytest tests/test_emotional_feedback_sprint4.py -v
"""
from __future__ import annotations

import os
import sys
import unittest
from pathlib import Path

HERE = Path(__file__).parent
DEMO = HERE.parent
sys.path.insert(0, str(DEMO))

# 确保无 LLM key → 全程 mock
os.environ.pop("LLM_API_KEY", None)

from engine.emotional_feedback import (
    generate_emotional_feedback,
    build_student_history,
    _try_llm_emotional_feedback,
    _mock_emotional_feedback,
    feature_hits,
    clear_history_cache,
)
from engine.grader import grade_long_answer, load_json
from engine.correction_grader import grade_correction
from tests._sprint3_fixtures import (
    EMOTIONAL_FEEDBACK_FIXTURES,
    FEEDBACK_QUALITY_RULES,
)


class TestEmotionalFeedbackFieldInGrading(unittest.TestCase):
    """批改结果含 emotional_feedback 字段。"""

    def setUp(self):
        clear_history_cache()
        self.questions = load_json("questions.json")["hw_001"]["questions"]

    def test_grade_long_answer_has_emotional_feedback(self):
        q = next(q for q in self.questions if q["type"] == "long_answer")
        answers = load_json("answers.json")
        sa = answers["s02_hw_001"]["answers"].get(q["id"], "")
        result = grade_long_answer(sa, q, "s02")
        self.assertIn("emotional_feedback", result)
        self.assertIsInstance(result["emotional_feedback"], str)
        self.assertGreater(len(result["emotional_feedback"]), 0)

    def test_grade_long_answer_correct_path_has_emotional_feedback(self):
        """全对学生（s01）的批改结果也含字段。"""
        q = next(q for q in self.questions if q["type"] == "long_answer")
        answers = load_json("answers.json")
        sa = answers["s01_hw_001"]["answers"].get(q["id"], "")
        result = grade_long_answer(sa, q, "s01")
        self.assertIn("emotional_feedback", result)
        self.assertGreater(len(result["emotional_feedback"]), 10)

    def test_grade_correction_has_emotional_feedback(self):
        q = {
            "id": "q5", "type": "long_answer", "score": 12,
            "answer": "f'(x)=3(x-a)², (x-a)²≥0, 单调递增",
            "knowledge": "利用导数判断函数单调性",
            "steps": [
                {"step": 1, "content": "f'(x)=3x²-6ax+3a²", "score": 3},
                {"step": 2, "content": "=3(x-a)²", "score": 3},
                {"step": 3, "content": "≥0 单调递增", "score": 6},
            ],
        }
        correction = "f'(x)=3x²-6ax+3a²=3(x-a)² 因为(x-a)²≥0 所以f'(x)≥0 单调递增"
        result = grade_correction(q, "不会做", {"is_correct": False}, correction, "s02")
        self.assertIn("emotional_feedback", result)
        self.assertIsInstance(result["emotional_feedback"], str)
        self.assertGreater(len(result["emotional_feedback"]), 0)


class TestMockFeedbackVariesByHistory(unittest.TestCase):
    """mock 模式评语非固定文案——不同学生历史产出不同评语。"""

    def setUp(self):
        clear_history_cache()

    def test_different_students_produce_different_feedback(self):
        """s01（全对）vs s02（有错）历史不同 → 评语不同。"""
        q = next(q for q in load_json("questions.json")["hw_001"]["questions"]
                 if q["type"] == "long_answer")
        answers = load_json("answers.json")
        fb_s01 = grade_long_answer(
            answers["s01_hw_001"]["answers"][q["id"]], q, "s01"
        )["emotional_feedback"]
        fb_s02 = grade_long_answer(
            answers["s02_hw_001"]["answers"][q["id"]], q, "s02"
        )["emotional_feedback"]
        self.assertNotEqual(fb_s01, fb_s02,
                            "不同学生历史应产出不同评语")

    def test_with_vs_without_history_produce_different_feedback(self):
        """同一学生，有历史 vs 无历史 → 评语不同。"""
        wh = EMOTIONAL_FEEDBACK_FIXTURES[0]["with_history"]
        fb_with = generate_emotional_feedback(
            "李明",
            {"score": 80, "max_score": 100, "is_correct": False, "error_types": [], "knowledge": ""},
            student_history=wh,
        )
        fb_without = generate_emotional_feedback(
            "李明",
            {"score": 80, "max_score": 100, "is_correct": False, "error_types": [], "knowledge": ""},
            student_history={"has_history": False, "student_name": "李明"},
        )
        self.assertNotEqual(fb_with, fb_without,
                            "有历史 vs 无历史应产出不同评语")

    def test_feedback_not_equal_to_constant(self):
        """评语不是固定文案：多组输入产出 ≥3 种不同评语。"""
        outputs = set()
        for g in EMOTIONAL_FEEDBACK_FIXTURES:
            wh = g["with_history"]
            fb = generate_emotional_feedback(
                g["student_name"],
                {"score": wh["current_score"], "max_score": wh["max_score"],
                 "is_correct": False, "error_types": [], "knowledge": ""},
                student_history=wh,
            )
            outputs.add(fb)
        self.assertGreaterEqual(len(outputs), 2,
                                "至少 2 种不同评语，证明非固定文案")


class TestFeedbackQuality(unittest.TestCase):
    """评语长度与禁忌词校验。"""

    def test_mock_feedback_within_length_range(self):
        for g in EMOTIONAL_FEEDBACK_FIXTURES:
            wh = g["with_history"]
            fb = generate_emotional_feedback(
                g["student_name"],
                {"score": wh["current_score"], "max_score": wh["max_score"],
                 "is_correct": False, "error_types": [], "knowledge": ""},
                student_history=wh,
            )
            self.assertGreaterEqual(len(fb), FEEDBACK_QUALITY_RULES["min_length"],
                                    f"{g['id']}: too short ({len(fb)})")
            self.assertLessEqual(len(fb), FEEDBACK_QUALITY_RULES["max_length"],
                                 f"{g['id']}: too long ({len(fb)})")

    def test_no_forbidden_phrases(self):
        for g in EMOTIONAL_FEEDBACK_FIXTURES:
            wh = g["with_history"]
            fb = generate_emotional_feedback(
                g["student_name"],
                {"score": wh["current_score"], "max_score": wh["max_score"],
                 "is_correct": False, "error_types": [], "knowledge": ""},
                student_history=wh,
            )
            for phrase in FEEDBACK_QUALITY_RULES["forbidden_phrases"]:
                self.assertNotIn(phrase, fb, f"{g['id']}: contains forbidden「{phrase}」")


class TestLLMHookFallback(unittest.TestCase):
    """无 LLM key 时 hook 返回 None，走 mock。"""

    def test_try_llm_returns_none_without_key(self):
        os.environ.pop("LLM_API_KEY", None)
        result = _try_llm_emotional_feedback(
            {"student_name": "测试", "has_history": True, "score_trend": [80]},
            {"score": 80, "max_score": 100, "is_correct": False, "error_types": []},
            "test",
        )
        self.assertIsNone(result)

    def test_mock_feedback_is_string(self):
        fb = _mock_emotional_feedback(
            {"student_name": "测试", "has_history": True, "score_trend": [80, 72],
             "strengths": ["导数"], "weaknesses": ["符号"], "correction_rate": 0.5},
            {"score": 80, "max_score": 100, "is_correct": False, "error_types": ["计算错误"], "knowledge": "导数"},
            "test",
        )
        self.assertIsInstance(fb, str)
        self.assertGreater(len(fb), 50)


class TestFeatureHits(unittest.TestCase):
    """特征命中校验函数。"""

    def test_feature_hits_matching(self):
        feedback = "李明同学，本次80分，比上次72分有进步，你在导数上表现稳定"
        hits = feature_hits(feedback, [
            "引用得分趋势(72→80进步)",
            "引用具体强项(导数)",
            "引用订正数据(未命中)",
        ])
        self.assertTrue(hits["引用得分趋势(72→80进步)"])
        self.assertTrue(hits["引用具体强项(导数)"])
        self.assertFalse(hits["引用订正数据(未命中)"])


class TestBuildStudentHistory(unittest.TestCase):
    """学生历史画像构建。"""

    def setUp(self):
        clear_history_cache()

    def test_build_history_for_known_student(self):
        h = build_student_history("s02", "hw_001")
        self.assertTrue(h.get("has_history"))
        self.assertIn("score_trend", h)
        self.assertIn("strengths", h)
        self.assertIn("weaknesses", h)

    def test_build_history_for_unknown_student(self):
        h = build_student_history("nonexistent", "hw_001")
        self.assertFalse(h.get("has_history", True))

    def test_history_cached(self):
        h1 = build_student_history("s01", "hw_001")
        h2 = build_student_history("s01", "hw_001")
        self.assertIs(h1, h2, "应返回缓存对象")


class TestEvalScript(unittest.TestCase):
    """评测脚本 mock 模式可跑通。"""

    def test_eval_script_runs_in_mock_mode(self):
        import importlib.util
        script_path = DEMO.parent / "scripts" / "eval_llm_quality.py"
        spec = importlib.util.spec_from_file_location("eval_llm_quality", script_path)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        report = mod.run("mock")
        self.assertIn("correction_grading", report)
        self.assertIn("emotional_feedback", report)
        self.assertIn("accuracy_pct", report["correction_grading"])
        self.assertIn("hit_rate_pct", report["emotional_feedback"])
        self.assertGreater(report["correction_grading"]["total"], 0)
        self.assertGreater(report["emotional_feedback"]["total_features"], 0)


if __name__ == "__main__":
    unittest.main(verbosity=2)
