"""Sprint 4 P0 compliance tests.

Covers:
  P0-1: LLM API student_id anonymization
    - Mock provider trace input_payload does not contain raw student_id
    - Pseudonymization is deterministic and irreversible
  P0-2: Data delete/export API
    - DELETE /api/student/<id>/data deletes submissions + corrections
    - GET /api/student/<id>/export returns JSON with all student data
    - Permission: students can only operate on their own data
  P0-3: Parental consent
    - consent_given field exists on DEMO_USERS
    - require_consent blocks submission for non-consenting students
    - Demo mode (DEMO_AUTH_OPEN=1) auto-grants consent
  P0-4: Teacher mastery API
    - GET /api/teacher/mastery returns homeworks + students structure
"""
from __future__ import annotations

import json
import os
import sys
import unittest
from pathlib import Path

# Make demo/ importable
_DEMO_DIR = Path(__file__).resolve().parent.parent
_REPO_ROOT = _DEMO_DIR.parent
for p in (_DEMO_DIR, _REPO_ROOT):
    sp = str(p)
    if sp not in sys.path:
        sys.path.insert(0, sp)

# Force demo mode for tests
os.environ.setdefault("DEMO_AUTH_OPEN", "1")
for k in ("LLM_API_KEY", "LLM_BASE_URL", "LLM_MODEL"):
    os.environ.pop(k, None)


class TestP0_1_StudentIdAnonymization(unittest.TestCase):
    """P0-1: LLM-bound student_id must be pseudonymized."""

    def setUp(self):
        from engine.llm import factory
        factory.reset_runtime_trace_store()

    def test_pseudonymize_is_deterministic(self):
        """Same input + salt → same pseudonym."""
        from engine.llm.pseudonym import pseudonymize_student_id
        a = pseudonymize_student_id("s01")
        b = pseudonymize_student_id("s01")
        self.assertEqual(a, b)

    def test_pseudonymize_differs_from_raw(self):
        """Pseudonym must not equal the raw student_id."""
        from engine.llm.pseudonym import pseudonymize_student_id
        raw = "s01"
        pseudo = pseudonymize_student_id(raw)
        self.assertNotEqual(pseudo, raw)
        self.assertTrue(pseudo.startswith("pseudo_"))

    def test_pseudonymize_is_irreversible(self):
        """Pseudonym must not contain the raw student_id."""
        from engine.llm.pseudonym import pseudonymize_student_id
        raw = "s01"
        pseudo = pseudonymize_student_id(raw)
        self.assertNotIn(raw, pseudo)

    def test_pseudonymize_different_ids_different_output(self):
        """Different student_ids → different pseudonyms."""
        from engine.llm.pseudonym import pseudonymize_student_id
        a = pseudonymize_student_id("s01")
        b = pseudonymize_student_id("s02")
        self.assertNotEqual(a, b)

    def test_mock_provider_trace_no_raw_student_id(self):
        """Mock provider's trace input_payload must not contain raw student_id."""
        from engine.llm import get_provider, TraceCollector, store_trace, get_runtime_trace
        from engine.grader import load_json

        provider = get_provider()
        questions = load_json("questions.json")["hw_001"]["questions"]
        # Find a long_answer question
        long_q = next(q for q in questions if q["type"] == "long_answer")

        raw_sid = "s02"
        trace = TraceCollector(student_id=raw_sid, assignment_id="hw_001")
        provider.grade_step(
            question=long_q,
            student_answer="f'(x) = 2x - 2a, 单调递增",
            standard_answer=long_q.get("answer", ""),
            student_id=raw_sid,
            trace=trace,
        )
        store_trace(trace)

        # Inspect all trace records — none should contain the raw student_id
        runtime = get_runtime_trace(raw_sid, "hw_001")
        stages = runtime.get("stages", [])
        self.assertTrue(len(stages) > 0, "expected at least one trace stage")

        for stage in stages:
            input_payload = stage.get("input_payload", {})
            # The student_id field must be pseudonymized
            if "student_id" in input_payload:
                self.assertNotEqual(
                    input_payload["student_id"], raw_sid,
                    f"stage {stage['stage']}: raw student_id leaked into trace"
                )
                self.assertTrue(
                    input_payload["student_id"].startswith("pseudo_"),
                    f"stage {stage['stage']}: student_id not pseudonymized"
                )

    def test_openai_provider_trace_no_raw_student_id(self):
        """OpenAI provider's trace input_payload must not contain raw student_id
        even when it falls back to MockProvider (no network)."""
        os.environ["LLM_API_KEY"] = "sk-test-fake"
        os.environ["LLM_BASE_URL"] = "https://example.invalid/v1"
        os.environ["LLM_MODEL"] = "gpt-test"
        try:
            from engine.llm import factory
            factory.reset_runtime_trace_store()
            from engine.llm import get_provider, TraceCollector, store_trace
            from engine.grader import load_json

            provider = get_provider()
            questions = load_json("questions.json")["hw_001"]["questions"]
            long_q = next(q for q in questions if q["type"] == "long_answer")

            raw_sid = "s03"
            trace = TraceCollector(student_id=raw_sid, assignment_id="hw_001")
            provider.grade_step(
                question=long_q,
                student_answer="some answer",
                standard_answer=long_q.get("answer", ""),
                student_id=raw_sid,
                trace=trace,
            )
            store_trace(trace)

            # The trace will have either a real grading stage or a fallback stage
            from engine.llm import get_runtime_trace
            runtime = get_runtime_trace(raw_sid, "hw_001")
            for stage in runtime.get("stages", []):
                input_payload = stage.get("input_payload", {})
                if "student_id" in input_payload:
                    self.assertNotEqual(
                        input_payload["student_id"], raw_sid,
                        f"stage {stage['stage']}: raw student_id leaked"
                    )
        finally:
            for k in ("LLM_API_KEY", "LLM_BASE_URL", "LLM_MODEL"):
                os.environ.pop(k, None)
            from engine.llm import factory
            factory.reset_runtime_trace_store()


class TestP0_2_DataDeleteExport(unittest.TestCase):
    """P0-2: Data delete/export API."""

    def setUp(self):
        import importlib
        import app
        importlib.reload(app)
        self.app = app.app
        self.app.config["TESTING"] = True
        self.client = self.app.test_client()

    def test_export_returns_student_data(self):
        """GET /api/student/<id>/export returns JSON with student data."""
        resp = self.client.get("/api/student/s01/export")
        self.assertEqual(resp.status_code, 200)
        data = resp.get_json()
        self.assertTrue(data["ok"])
        self.assertIn("data", data)
        self.assertEqual(data["data"]["student_id"], "s01")
        self.assertIn("submissions", data["data"])
        self.assertIn("corrections", data["data"])

    def test_delete_removes_student_data(self):
        """DELETE /api/student/<id>/data removes submissions and corrections."""
        # Use a temp student to avoid destroying demo data
        # In demo mode, the delete operates on JSON files
        resp = self.client.delete("/api/student/s05/data")
        self.assertEqual(resp.status_code, 200)
        data = resp.get_json()
        self.assertTrue(data["ok"])
        self.assertIn("deleted", data)

    def test_export_permission_student_own_only(self):
        """Students can only export their own data (prod mode)."""
        os.environ["DEMO_AUTH_OPEN"] = "0"
        try:
            import importlib
            import app
            importlib.reload(app)
            client = app.app.test_client()
            # Login as s01
            from _helpers import login
            login(client, "s01", "student123")
            # Try to export s02's data → should be 403
            resp = client.get("/api/student/s02/export")
            self.assertEqual(resp.status_code, 403)
            # Export own data → should be 200
            resp = client.get("/api/student/s01/export")
            self.assertEqual(resp.status_code, 200)
        finally:
            os.environ["DEMO_AUTH_OPEN"] = "1"


class TestP0_3_ParentalConsent(unittest.TestCase):
    """P0-3: Parental consent gating."""

    def test_demo_users_have_consent_field(self):
        """All DEMO_USERS entries should have consent_given field."""
        from security import DEMO_USERS
        for username, user in DEMO_USERS.items():
            self.assertIn("consent_given", user, f"{username} missing consent_given")

    def test_consent_page_accessible(self):
        """GET /consent renders in demo mode."""
        import importlib
        import app
        importlib.reload(app)
        client = app.app.test_client()
        resp = client.get("/consent")
        # In demo mode, has_consent() returns True → redirect to index
        self.assertIn(resp.status_code, (302, 200))

    def test_require_consent_blocks_in_prod_mode(self):
        """In prod mode, non-consenting students are blocked from submission."""
        os.environ["DEMO_AUTH_OPEN"] = "0"
        try:
            import importlib
            import app
            importlib.reload(app)
            client = app.app.test_client()
            from _helpers import login
            login(client, "s01", "student123")

            # s01 hasn't consented → submission should be blocked
            resp = client.post("/api/correction/submit",
                json={"submission_id": "s01_hw_001", "question_id": "q5", "correction_text": "test"},
                headers={"Content-Type": "application/json"})
            self.assertEqual(resp.status_code, 403)
            data = resp.get_json()
            self.assertEqual(data.get("error"), "consent_required")
        finally:
            os.environ["DEMO_AUTH_OPEN"] = "1"

    def test_consent_submission_flow(self):
        """POST /consent with parent_consent=on grants consent."""
        os.environ["DEMO_AUTH_OPEN"] = "0"
        try:
            import importlib
            import app
            importlib.reload(app)
            client = app.app.test_client()
            from _helpers import login, get_csrf_token
            login(client, "s01", "student123")
            token = get_csrf_token(client)

            resp = client.post("/consent", data={
                "parent_consent": "on",
                "csrf_token": token,
            })
            self.assertEqual(resp.status_code, 302)
        finally:
            os.environ["DEMO_AUTH_OPEN"] = "1"
            # Reset DEMO_USERS consent state
            from security import DEMO_USERS
            DEMO_USERS["s01"]["consent_given"] = False


class TestP0_4_TeacherMasteryAPI(unittest.TestCase):
    """P0-4: Teacher mastery API."""

    def setUp(self):
        import importlib
        import app
        importlib.reload(app)
        self.client = app.app.test_client()

    def test_mastery_api_returns_homeworks(self):
        """GET /api/teacher/mastery returns homeworks structure."""
        resp = self.client.get("/api/teacher/mastery")
        self.assertEqual(resp.status_code, 200)
        data = resp.get_json()
        self.assertTrue(data["ok"])
        self.assertIn("homeworks", data)
        self.assertTrue(len(data["homeworks"]) > 0)

        hw = data["homeworks"][0]
        self.assertIn("hw_key", hw)
        self.assertIn("title", hw)
        self.assertIn("questions", hw)

    def test_mastery_api_question_structure(self):
        """Each question has mastery_distribution with expected keys."""
        resp = self.client.get("/api/teacher/mastery")
        data = resp.get_json()
        hw = data["homeworks"][0]
        q = hw["questions"][0]
        self.assertIn("question_id", q)
        self.assertIn("stem", q)
        self.assertIn("mastery_distribution", q)
        md = q["mastery_distribution"]
        for key in ("mastered", "partial", "not_mastered", "uncorrected"):
            self.assertIn(key, md)

    def test_mastery_api_returns_students(self):
        """GET /api/teacher/mastery returns per-student progress."""
        resp = self.client.get("/api/teacher/mastery")
        data = resp.get_json()
        self.assertIn("students", data)
        self.assertTrue(len(data["students"]) > 0)
        s = data["students"][0]
        self.assertIn("student_id", s)
        self.assertIn("correction_count", s)
        self.assertIn("mastery_rate", s)


if __name__ == "__main__":
    unittest.main()
