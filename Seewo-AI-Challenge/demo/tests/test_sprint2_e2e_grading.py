"""Sprint 2 端到端批改测试（提示词工程师线）.

覆盖:
  1. Provider 多学科 prompt 分发（OpenAIProvider / DeepSeekProvider 按 subject_type 选 prompt）
  2. MockProvider 多学科结构化结果（7 学科全覆盖）
  3. 端到端流程: 学生提交 → grader 选 prompt → provider → 结构化结果
  4. 结构化结果字段完整性 (step_results / error_types / confidence / overall_feedback)
  5. 向后兼容: 无 subject_type 的题目回退到 math_step_grading

验收: ≥5 个测试，覆盖 ≥3 个学科，mock 模式全绿。

Run: cd Seewo-AI-Challenge/demo && python -m pytest tests/test_sprint2_e2e_grading.py -v
"""
from __future__ import annotations

import os
import sys
import unittest
from pathlib import Path

HERE = Path(__file__).parent
DEMO = HERE.parent
sys.path.insert(0, str(DEMO))

from prompts import get_prompt, list_subject_types
from tests._multi_subject_fixtures import MOCK_SAMPLES, ERROR_TYPES_BY_SUBJECT


def _ensure_clean_factory() -> None:
    """Reset factory singleton + trace store for test isolation."""
    for k in ("LLM_API_KEY", "LLM_BASE_URL", "LLM_MODEL", "LLM_API_MODEL"):
        os.environ.pop(k, None)
    from engine.llm import factory
    factory.reset_runtime_trace_store()


class TestProviderMultiSubjectPromptDispatch(unittest.TestCase):
    """Task 1: OpenAIProvider / DeepSeekProvider 按 subject_type 选 prompt."""

    def setUp(self) -> None:
        _ensure_clean_factory()

    def test_openai_provider_uses_subject_prompt_when_subject_type_set(self) -> None:
        """OpenAIProvider.grade_step 收到 subject_type 时应调 get_prompt 取对应 prompt。"""
        from engine.llm.openai_provider import OpenAIProvider

        provider = OpenAIProvider(
            base_url="https://invalid.example/v1",
            api_key="sk-test",
            model="gpt-test",
        )
        # 给一个 chinese_essay 题目
        question = {
            "id": "test_cn_01",
            "type": "long_answer",
            "subject_type": "chinese_essay",
            "stem": "以「坚持」为题写议论文",
            "score": 60,
            "answer": "（范文）",
        }
        # 调 _step_grading_system_prompt 验证 prompt 分发
        prompt = provider._step_grading_system_prompt(question=question)
        expected_prompt = get_prompt("chinese_essay")
        self.assertEqual(prompt, expected_prompt)
        self.assertIn("你是一位", prompt)

    def test_openai_provider_falls_back_to_math_when_no_subject_type(self) -> None:
        """无 subject_type 时回退到 math_step_grading（向后兼容 Sprint 1）。"""
        from engine.llm.openai_provider import OpenAIProvider
        from prompts import load_math_step_grading

        provider = OpenAIProvider(
            base_url="https://invalid.example/v1",
            api_key="sk-test",
            model="gpt-test",
        )
        question = {"id": "q5", "type": "long_answer", "stem": "求导", "score": 12}
        prompt = provider._step_grading_system_prompt(question=question)
        self.assertEqual(prompt, load_math_step_grading())

    def test_deepseek_provider_uses_subject_prompt_for_non_math(self) -> None:
        """DeepSeekProvider 对非 math_calculation 学科也走 get_prompt。"""
        from engine.llm.deepseek_provider import DeepSeekProvider

        provider = DeepSeekProvider(
            base_url="https://api.deepseek.com/v1",
            api_key="sk-test",
            model="deepseek-math",
        )
        question = {
            "id": "test_phys_01",
            "type": "long_answer",
            "subject_type": "physics_short",
            "stem": "求绳的拉力",
            "score": 10,
        }
        prompt = provider._step_grading_system_prompt(question=question)
        expected = get_prompt("physics_short")
        self.assertEqual(prompt, expected)

    def test_deepseek_provider_keeps_math_prompt_for_math_calculation(self) -> None:
        """DeepSeekProvider 对 math_calculation 保持 DeepSeek 专用 prompt。"""
        from engine.llm.deepseek_provider import DeepSeekProvider, _STEP_GRADING_SYSTEM_DEEPSEEK

        provider = DeepSeekProvider(
            base_url="https://api.deepseek.com/v1",
            api_key="sk-test",
            model="deepseek-math",
        )
        question = {
            "id": "q5",
            "type": "long_answer",
            "subject_type": "math_calculation",
            "stem": "求导",
            "score": 12,
        }
        prompt = provider._step_grading_system_prompt(question=question)
        self.assertEqual(prompt, _STEP_GRADING_SYSTEM_DEEPSEEK)

    def test_openai_provider_unknown_subject_type_falls_back(self) -> None:
        """未知 subject_type 应回退到 math_step_grading 而非崩溃。"""
        from engine.llm.openai_provider import OpenAIProvider

        provider = OpenAIProvider(
            base_url="https://invalid.example/v1",
            api_key="sk-test",
            model="gpt-test",
        )
        question = {"id": "x", "subject_type": "nonexistent_subject", "stem": "?", "score": 5}
        prompt = provider._step_grading_system_prompt(question=question)
        # 应回退到 math prompt（非空、含角色定义）
        self.assertIsInstance(prompt, str)
        self.assertGreater(len(prompt), 500)


class TestMockProviderMultiSubject(unittest.TestCase):
    """Task 3: MockProvider 多学科结构化结果（7 学科全覆盖）。"""

    def setUp(self) -> None:
        _ensure_clean_factory()

    def _build_question(self, sample: dict) -> dict:
        """从 MOCK_SAMPLE 构造一个 question dict。"""
        return {
            "id": sample["id"],
            "type": "long_answer",
            "subject_type": sample["subject_type"],
            "stem": sample["question_stem"],
            "score": sample["max_score"],
            "answer": "(reference)",
            "steps": sample["reference_steps"],
        }

    def test_mock_provider_returns_structured_result_for_each_subject(self) -> None:
        """7 学科（math_calculation + 6 fixture）全覆盖：mock provider 返回结构化结果。"""
        from engine.llm.mock_provider import MockProvider

        provider = MockProvider()

        # 1. math_calculation — 走 rule engine（用现有 questions.json q5）
        from engine.grader import load_json
        math_q = load_json("questions.json")["hw_001"]["questions"][4]  # q5
        math_result = provider.grade_step(
            question=math_q,
            student_answer="f(x)=x^2, f'(x)=2x",
            standard_answer=math_q.get("answer", ""),
            student_id="s02",
        )
        self.assertIn("step_results", math_result)
        self.assertIn("error_types", math_result)
        self.assertIn("ai_confidence", math_result)

        # 2-7. 6 non-math subjects via fixtures
        for sample in MOCK_SAMPLES:
            q = self._build_question(sample)
            result = provider.grade_step(
                question=q,
                student_answer=sample["student_answer"],
                standard_answer="(reference)",
                student_id="s02",
            )
            # 结构化字段完整性
            for field in ("type", "is_correct", "score", "max_score",
                          "step_results", "error_types", "ai_confidence",
                          "overall_feedback", "need_teacher_review"):
                self.assertIn(field, result, f"{sample['id']}: missing {field}")

            # step_results 非空
            self.assertGreater(len(result["step_results"]), 0,
                               f"{sample['id']}: empty step_results")

            # error_types 在该学科词表内
            vocab = ERROR_TYPES_BY_SUBJECT[sample["subject_type"]]
            for et in result["error_types"]:
                self.assertIn(et, vocab,
                              f"{sample['id']}: error_type {et!r} not in {sample['subject_type']} vocab")

            # confidence 在 (0, 1]
            self.assertGreater(result["ai_confidence"], 0.0)
            self.assertLessEqual(result["ai_confidence"], 1.0)

            # overall_feedback 非空
            self.assertGreater(len(result["overall_feedback"]), 10)

    def test_mock_provider_math_calculation_uses_rule_engine(self) -> None:
        """math_calculation 学科走 rule engine（不使用 fixture）。"""
        from engine.llm.mock_provider import MockProvider
        from engine.grader import load_json

        provider = MockProvider()
        questions = load_json("questions.json")["hw_001"]["questions"]
        q5 = next(q for q in questions if q["id"] == "q5")
        result = provider.grade_step(
            question=q5,
            student_answer="f(x)=x^2, f'(x)=2x",
            standard_answer=q5.get("answer", ""),
            student_id="s02",
        )
        # rule engine 对 s02/q5 的已知 pattern：步骤 2 错误
        self.assertFalse(result["is_correct"])
        self.assertIn("计算错误", result.get("error_types", []))


class TestEndToEndGradingFlow(unittest.TestCase):
    """Task 2: 端到端批改流程（grade_long_answer_with_trace）。"""

    def setUp(self) -> None:
        _ensure_clean_factory()

    def test_e2e_math_calculation_via_trace(self) -> None:
        """端到端: math_calculation → grade_long_answer_with_trace → 结构化结果。"""
        from engine.grader import grade_long_answer_with_trace, load_json

        q = load_json("questions.json")["hw_001"]["questions"][4]  # q5
        result = grade_long_answer_with_trace(
            "f(x)=x^2, f'(x)=2x", q, "s02", "hw_001"
        )
        self.assertIn("step_results", result)
        self.assertIn("error_types", result)
        self.assertIn("ai_confidence", result)
        self.assertIn("overall_feedback", result)
        # trace 已存储
        from engine.llm import get_runtime_trace
        trace = get_runtime_trace("s02", "hw_001")
        self.assertIn("math_grading", trace.get("agents", []))

    def test_e2e_physics_short_via_trace(self) -> None:
        """端到端: physics_short → grade_long_answer_with_trace → 结构化结果。"""
        from engine.grader import grade_long_answer_with_trace

        question = {
            "id": "ms_physics_01",
            "type": "long_answer",
            "subject_type": "physics_short",
            "stem": "质量 m=2kg 加速上升 a=2m/s²，求拉力 T",
            "score": 10,
            "answer": "T=24N",
            "steps": [
                {"step": 1, "content": "受力分析"},
                {"step": 2, "content": "牛顿第二定律 T-mg=ma"},
                {"step": 3, "content": "T=2×(10+2)=24N"},
                {"step": 4, "content": "结论 T=24N"},
            ],
        }
        result = grade_long_answer_with_trace(
            "T-mg=ma, T=m(g+a)=2×(10-2)=16N", question, "s03", "hw_001"
        )
        self.assertFalse(result["is_correct"])
        self.assertGreater(len(result["step_results"]), 0)
        self.assertIn("计算错误", result["error_types"])
        self.assertGreater(len(result["overall_feedback"]), 10)

        # trace 验证
        from engine.llm import get_runtime_trace
        trace = get_runtime_trace("s03", "hw_001")
        self.assertIn("math_grading", trace.get("agents", []))

    def test_e2e_chinese_essay_via_trace(self) -> None:
        """端到端: chinese_essay → grade_long_answer_with_trace → 结构化结果。"""
        from engine.grader import grade_long_answer_with_trace

        question = {
            "id": "ms_cn_essay_01",
            "type": "long_answer",
            "subject_type": "chinese_essay",
            "stem": "以「坚持」为题写议论文",
            "score": 60,
            "answer": "(范文)",
            "steps": [
                {"step": 1, "content": "内容（20分）"},
                {"step": 2, "content": "结构（15分）"},
                {"step": 3, "content": "语言（20分）"},
                {"step": 4, "content": "文面（5分）"},
            ],
        }
        result = grade_long_answer_with_trace(
            "坚持是成功的基石。爱迪生发明电灯...", question, "s01", "hw_001"
        )
        self.assertIn("step_results", result)
        self.assertIn("error_types", result)
        self.assertIn("overall_feedback", result)
        # 结构混乱应出现在 error_types
        self.assertIn("结构混乱", result["error_types"])

    def test_e2e_chemistry_short_via_trace(self) -> None:
        """端到端: chemistry_short → grade_long_answer_with_trace → 结构化结果。"""
        from engine.grader import grade_long_answer_with_trace

        question = {
            "id": "ms_chem_01",
            "type": "long_answer",
            "subject_type": "chemistry_short",
            "stem": "氢气还原氧化铜，写方程式并计算",
            "score": 10,
            "answer": "H₂+CuO=Cu+H₂O（加热）, 0.1mol",
            "steps": [
                {"step": 1, "content": "方程式"},
                {"step": 2, "content": "原理"},
                {"step": 3, "content": "计算"},
                {"step": 4, "content": "结论"},
            ],
        }
        result = grade_long_answer_with_trace(
            "H₂+CuO=Cu+H₂O, n(CuO)=0.1mol, 需要 0.1mol H₂",
            question, "s04", "hw_001",
        )
        self.assertFalse(result["is_correct"])
        self.assertIn("条件遗漏", result["error_types"])
        self.assertGreater(result["ai_confidence"], 0.0)

    def test_e2e_backward_compat_no_subject_type(self) -> None:
        """无 subject_type 的题目仍走 rule engine（向后兼容）。"""
        from engine.grader import grade_long_answer_with_trace, load_json

        q = load_json("questions.json")["hw_001"]["questions"][4]
        # 确保没有 subject_type
        q_copy = {k: v for k, v in q.items() if k != "subject_type"}
        result = grade_long_answer_with_trace(
            "f(x)=x^2, f'(x)=2x", q_copy, "s02", "hw_001"
        )
        self.assertIn("step_results", result)
        self.assertIn("is_correct", result)


class TestStructuredResultFields(unittest.TestCase):
    """Task 4: 结构化结果字段完整性验证。"""

    def setUp(self) -> None:
        _ensure_clean_factory()

    def test_all_subjects_return_required_fields(self) -> None:
        """所有 7 学科返回的 result 都含 5 个必需结构化字段。"""
        from engine.llm.mock_provider import MockProvider
        from engine.grader import load_json

        provider = MockProvider()
        required = {"step_results", "error_types", "ai_confidence",
                    "overall_feedback", "need_teacher_review"}

        # math_calculation
        q = load_json("questions.json")["hw_001"]["questions"][4]
        r = provider.grade_step(
            question=q, student_answer="test", standard_answer="", student_id="s01"
        )
        self.assertTrue(required.issubset(set(r.keys())),
                        f"math_calculation missing: {required - set(r.keys())}")

        # 6 non-math
        for sample in MOCK_SAMPLES:
            q2 = {
                "id": sample["id"],
                "type": "long_answer",
                "subject_type": sample["subject_type"],
                "stem": sample["question_stem"],
                "score": sample["max_score"],
                "steps": sample["reference_steps"],
            }
            r = provider.grade_step(
                question=q2,
                student_answer=sample["student_answer"],
                standard_answer="(ref)",
                student_id="s01",
            )
            missing = required - set(r.keys())
            self.assertFalse(missing, f"{sample['subject_type']}: missing {missing}")

    def test_step_results_have_correct_schema(self) -> None:
        """step_results 中每个元素含 step / correct / comment。"""
        from engine.llm.mock_provider import MockProvider

        provider = MockProvider()
        for sample in MOCK_SAMPLES:
            q = {
                "id": sample["id"],
                "type": "long_answer",
                "subject_type": sample["subject_type"],
                "stem": sample["question_stem"],
                "score": sample["max_score"],
                "steps": sample["reference_steps"],
            }
            r = provider.grade_step(
                question=q,
                student_answer=sample["student_answer"],
                standard_answer="(ref)",
                student_id="s01",
            )
            for sr in r["step_results"]:
                self.assertIn("step", sr)
                self.assertIn("correct", sr)
                self.assertIn("comment", sr)
                self.assertIsInstance(sr["correct"], bool)


class TestPromptLoadingForAllSubjects(unittest.TestCase):
    """Task 3: 验证 7 学科 prompt 都能加载（mock 全链路前置条件）。"""

    def test_all_seven_subject_prompts_load_and_are_substantial(self) -> None:
        """7 学科 prompt 全部可加载、非空、含必要结构。"""
        for st in list_subject_types():
            txt = get_prompt(st)
            self.assertIsInstance(txt, str)
            self.assertGreater(len(txt), 800, f"{st} prompt too short")
            # 结构检查
            self.assertIn("JSON", txt, f"{st}: missing JSON schema")
            self.assertIn("防注入", txt, f"{st}: missing anti-injection")
            self.assertIn("step_results", txt, f"{st}: missing step_results")
            self.assertIn("error_types", txt, f"{st}: missing error_types")
            self.assertIn("overall_feedback", txt, f"{st}: missing overall_feedback")
            self.assertIn("confidence", txt, f"{st}: missing confidence field")


if __name__ == "__main__":
    unittest.main(verbosity=2)
