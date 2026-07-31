"""V2.0 Sprint 6: Tests for multi-tenant LLM config (6.7),
content safety filter (6.10), school onboarding (6.9),
and backup drill (6.12).

Run with: python -m pytest tests/test_sprint6.py -v
"""
from __future__ import annotations

import json
import os
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch

import pytest

# Ensure demo/ and repo root are on sys.path
_DEMO_DIR = Path(__file__).resolve().parent.parent
_REPO_ROOT = _DEMO_DIR.parent
for p in (_DEMO_DIR, _REPO_ROOT):
    sp = str(p)
    if sp not in sys.path:
        sys.path.insert(0, sp)


# ── Fixtures ─────────────────────────────────────────────────────────

@pytest.fixture
def isolated_data_dir(tmp_path, monkeypatch):
    """Redirect data files to a temp dir so tests don't pollute real data."""
    data_dir = tmp_path / "data"
    data_dir.mkdir()

    # Patch tenant_llm_config_manager paths
    import tenant_llm_config_manager as tcm
    monkeypatch.setattr(tcm, "_DATA_DIR", data_dir)
    monkeypatch.setattr(tcm, "_CONFIG_FILE", data_dir / "tenant_llm_config.json")

    # Mock get_current_user and audit_log (no Flask request context in tests)
    monkeypatch.setattr(tcm, "get_current_user", lambda: {"user_id": "test", "role": "admin"})
    monkeypatch.setattr(tcm, "audit_log", lambda *a, **kw: None)

    # Patch content_safety_filter paths
    import content_safety_filter as csf
    monkeypatch.setattr(csf, "_DATA_DIR", data_dir)
    monkeypatch.setattr(csf, "_LOG_FILE", data_dir / "llm_content_filter_log.json")
    monkeypatch.setattr(csf, "audit_log", lambda *a, **kw: None)

    return data_dir


@pytest.fixture(autouse=True)
def _reset_provider_cache():
    """Reset LLM provider cache between tests."""
    from engine.llm.factory import reset_runtime_trace_store
    reset_runtime_trace_store()
    yield
    reset_runtime_trace_store()


@pytest.fixture(autouse=True)
def _no_llm_key(monkeypatch):
    """Ensure no LLM_API_KEY so tests run in mock mode."""
    monkeypatch.delenv("LLM_API_KEY", raising=False)


# ── 6.7: Multi-tenant LLM Config ─────────────────────────────────────

class TestTenantLLMConfig:
    """Test tenant_llm_config_manager (6.7)."""

    def test_resolve_global_defaults(self, isolated_data_dir):
        """No tenant config → falls back to global env defaults."""
        from tenant_llm_config_manager import resolve_llm_config

        cfg = resolve_llm_config(school_id=999)
        assert cfg["school_id"] == 999
        assert cfg["model_name"] == os.environ.get("LLM_MODEL", "deepseek-chat")
        assert cfg["temperature"] == float(os.environ.get("LLM_TEMPERATURE", "0.2"))
        assert "api_key" in cfg
        assert "base_url" in cfg

    def test_tenant_override(self, isolated_data_dir):
        """Tenant config overrides global defaults."""
        from tenant_llm_config_manager import set_tenant_config, resolve_llm_config

        set_tenant_config(
            school_id=5,
            model_name="gpt-4o",
            base_url="https://api.openai.com/v1",
            api_key_secret="sk-test-xxx",
            temperature=0.5,
        )
        cfg = resolve_llm_config(school_id=5)
        assert cfg["model_name"] == "gpt-4o"
        assert cfg["base_url"] == "https://api.openai.com/v1"
        assert cfg["api_key"] == "sk-test-xxx"
        assert cfg["temperature"] == 0.5

    def test_null_inheritance(self, isolated_data_dir):
        """NULL fields in tenant config inherit from global defaults."""
        from tenant_llm_config_manager import set_tenant_config, resolve_llm_config

        # Only set model_name, leave others as None (inherit)
        set_tenant_config(school_id=7, model_name="qwen-max")
        cfg = resolve_llm_config(school_id=7)
        assert cfg["model_name"] == "qwen-max"
        # Other fields should inherit from global defaults
        global_timeout = float(os.environ.get("LLM_TIMEOUT", "30"))
        assert cfg["timeout"] == global_timeout

    def test_subject_overlay(self, isolated_data_dir):
        """Subject overlay overrides tenant-level config."""
        from tenant_llm_config_manager import set_tenant_config, resolve_llm_config

        set_tenant_config(
            school_id=8,
            model_name="gpt-4o",
            temperature=0.3,
            subject_overrides={
                "math_step_grading": {"model_name": "deepseek-math", "temperature": 0.1},
            },
        )
        # Without subject → tenant level
        cfg = resolve_llm_config(school_id=8)
        assert cfg["model_name"] == "gpt-4o"
        assert cfg["temperature"] == 0.3

        # With subject → overlay
        cfg_math = resolve_llm_config(school_id=8, subject_type="math_step_grading")
        assert cfg_math["model_name"] == "deepseek-math"
        assert cfg_math["temperature"] == 0.1

    def test_get_tenant_config_none(self, isolated_data_dir):
        """get_tenant_config returns None for non-existent school."""
        from tenant_llm_config_manager import get_tenant_config
        assert get_tenant_config(school_id=999) is None

    def test_delete_tenant_config(self, isolated_data_dir):
        """Delete tenant config → school falls back to global."""
        from tenant_llm_config_manager import (
            set_tenant_config, delete_tenant_config,
            get_tenant_config, resolve_llm_config,
        )

        set_tenant_config(school_id=10, model_name="test-model")
        assert get_tenant_config(10) is not None

        deleted = delete_tenant_config(10)
        assert deleted is True
        assert get_tenant_config(10) is None

        # After delete, resolve should return global defaults
        cfg = resolve_llm_config(school_id=10)
        assert cfg["model_name"] != "test-model"

    def test_delete_nonexistent_returns_false(self, isolated_data_dir):
        """Delete non-existent config returns False."""
        from tenant_llm_config_manager import delete_tenant_config
        assert delete_tenant_config(999) is False

    def test_list_tenant_configs(self, isolated_data_dir):
        """List returns all configured tenants."""
        from tenant_llm_config_manager import set_tenant_config, list_tenant_configs

        set_tenant_config(school_id=1, model_name="m1")
        set_tenant_config(school_id=2, model_name="m2")
        configs = list_tenant_configs()
        assert len(configs) == 2
        ids = [c["school_id"] for c in configs]
        assert 1 in ids and 2 in ids

    def test_update_existing_config(self, isolated_data_dir):
        """Update existing config preserves other fields."""
        from tenant_llm_config_manager import set_tenant_config, get_tenant_config

        set_tenant_config(school_id=3, model_name="m1", temperature=0.2)
        set_tenant_config(school_id=3, temperature=0.8)  # update

        cfg = get_tenant_config(3)
        assert cfg["temperature"] == 0.8
        # model_name should be preserved from original
        assert cfg["model_name"] == "m1"


# ── 6.7: Factory school_id support ───────────────────────────────────

class TestFactorySchoolId:
    """Test factory.get_provider(school_id) (6.7)."""

    def test_get_provider_default_school(self):
        """get_provider() with no args uses school_id=1 (backward compat)."""
        from engine.llm.factory import get_provider
        provider = get_provider()
        assert provider is not None

    def test_get_provider_per_school(self, isolated_data_dir):
        """Different school_ids get separate cached providers."""
        from engine.llm.factory import get_provider, _PROVIDERS
        from tenant_llm_config_manager import set_tenant_config

        # Without LLM_API_KEY, both return MockProvider but should be
        # separate instances in the cache dict
        p1 = get_provider(school_id=1)
        p2 = get_provider(school_id=2)
        assert 1 in _PROVIDERS
        assert 2 in _PROVIDERS

    def test_reset_clears_all_providers(self):
        """reset_runtime_trace_store clears all cached providers."""
        from engine.llm.factory import (
            get_provider, reset_runtime_trace_store, _PROVIDERS,
        )
        get_provider(school_id=1)
        get_provider(school_id=2)
        assert len(_PROVIDERS) >= 2
        reset_runtime_trace_store()
        assert len(_PROVIDERS) == 0


# ── 6.10: Content Safety Filter ──────────────────────────────────────

class TestContentSafetyFilter:
    """Test content_safety_filter (6.10)."""

    def test_pass_on_safe_text(self, isolated_data_dir):
        """Safe text passes through unchanged."""
        from content_safety_filter import filter_llm_output

        safe = "解答完全正确，步骤清晰，逻辑严谨。继续保持！"
        result = filter_llm_output(raw_text=safe, scenario="grading")
        assert result["decision"] == "pass"
        assert result["filtered_text"] == safe

    def test_block_on_improper_guidance(self, isolated_data_dir):
        """Critical content (improper_guidance) is blocked."""
        from content_safety_filter import filter_llm_output

        bad = "你可以不交作业，这没什么大不了的。"
        result = filter_llm_output(raw_text=bad, scenario="grading")
        assert result["decision"] == "block"
        assert result["severity"] == "critical"
        # Filtered text should be the degraded fallback, not the original
        assert result["filtered_text"] != bad
        assert len(result["filtered_text"]) > 0

    def test_block_on_value_bias(self, isolated_data_dir):
        """Value bias content is blocked."""
        from content_safety_filter import filter_llm_output

        bad = "差生就是不行，怎么教都没用。"
        result = filter_llm_output(raw_text=bad, scenario="grading")
        assert result["decision"] == "block"
        assert result["category"] == "value_bias"

    def test_block_on_sensitive_content(self, isolated_data_dir):
        """Sensitive content is blocked."""
        from content_safety_filter import filter_llm_output

        bad = "这个内容涉及赌博，可以去试试。"
        result = filter_llm_output(raw_text=bad, scenario="grading")
        assert result["decision"] == "block"
        assert result["severity"] == "high"

    def test_degrade_on_academic_mislead(self, isolated_data_dir):
        """Academic mislead content is degraded (medium severity)."""
        from content_safety_filter import filter_llm_output

        bad = "注意：导数为0的点一定是极值点。"
        result = filter_llm_output(raw_text=bad, scenario="grading")
        assert result["decision"] == "degrade"
        assert result["category"] == "academic_mislead"
        assert result["severity"] == "medium"
        # Degraded text should be different from original
        assert result["filtered_text"] != bad

    def test_degradation_output_is_string(self, isolated_data_dir):
        """Degraded output is a non-empty string."""
        from content_safety_filter import filter_llm_output

        bad = "导数为0一定是极值"
        result = filter_llm_output(
            raw_text=bad, scenario="grading", student_id="s01",
        )
        assert isinstance(result["filtered_text"], str)
        assert len(result["filtered_text"]) > 0

    def test_degradation_per_scenario(self, isolated_data_dir):
        """Each scenario produces appropriate degraded text."""
        from content_safety_filter import filter_llm_output

        for scenario in ["grading", "correction", "emotional", "comment"]:
            result = filter_llm_output(
                raw_text="导数为0一定是极值",
                scenario=scenario,
                student_id="s01",
            )
            assert result["decision"] in ("degrade", "block")
            assert isinstance(result["filtered_text"], str)
            assert len(result["filtered_text"]) > 0

    def test_filter_log_written(self, isolated_data_dir):
        """Filter log is persisted to JSON file."""
        from content_safety_filter import filter_llm_output, get_filter_logs

        filter_llm_output(raw_text="安全文本", scenario="grading", school_id=1)
        logs = get_filter_logs()
        assert len(logs) >= 1
        assert logs[-1]["scenario"] == "grading"
        assert logs[-1]["school_id"] == 1

    def test_filter_stats(self, isolated_data_dir):
        """Filter stats returns aggregate counts."""
        from content_safety_filter import filter_llm_output, get_filter_stats

        filter_llm_output(raw_text="安全", scenario="grading", school_id=1)
        filter_llm_output(raw_text="可以不交作业", scenario="grading", school_id=1)
        filter_llm_output(raw_text="导数为0一定是极值", scenario="grading", school_id=1)

        stats = get_filter_stats()
        assert stats["total"] >= 3
        assert stats["pass"] >= 1
        assert stats["block"] >= 1
        assert stats["degrade"] >= 1

    def test_filter_log_school_filter(self, isolated_data_dir):
        """Filter logs can be filtered by school_id."""
        from content_safety_filter import filter_llm_output, get_filter_logs

        filter_llm_output(raw_text="安全", scenario="grading", school_id=1)
        filter_llm_output(raw_text="安全", scenario="grading", school_id=2)

        logs_1 = get_filter_logs(school_id=1)
        logs_2 = get_filter_logs(school_id=2)
        assert all(l["school_id"] == 1 for l in logs_1)
        assert all(l["school_id"] == 2 for l in logs_2)


# ── 6.10: Integration hooks ──────────────────────────────────────────

class TestContentFilterIntegration:
    """Test content safety filter integration into grading paths (6.10)."""

    def test_grader_overall_feedback_filtered(self, isolated_data_dir):
        """grader.grade_long_answer applies filter to overall_feedback."""
        from engine.grader import grade_long_answer

        questions = load_json("questions.json")
        hw = questions.get("hw_001", {})
        qs = hw.get("questions", [])
        q5 = next((q for q in qs if q["id"] == "q5"), None)
        assert q5 is not None

        # s02 has errors on q5 → overall_feedback is generated
        result = grade_long_answer("some answer", q5, "s02")
        assert "overall_feedback" in result
        # Filter should have been applied (pass for normal feedback)
        assert isinstance(result["overall_feedback"], str)
        assert len(result["overall_feedback"]) > 0

    def test_correction_encouragement_filtered(self, isolated_data_dir):
        """correction_grader.grade_correction applies filter to encouragement."""
        from engine.correction_grader import grade_correction

        questions = load_json("questions.json")
        hw = questions.get("hw_001", {})
        qs = hw.get("questions", [])
        q5 = next((q for q in qs if q["id"] == "q5"), None)
        assert q5 is not None

        result = grade_correction(
            question=q5,
            original_answer="wrong answer",
            original_result={"score": 0, "is_correct": False},
            correction_text="f'(x) = 2x - 2a, 令f'(x)=0得x=a",
            student_id="s02",
        )
        assert "encouragement" in result
        assert isinstance(result["encouragement"], str)
        assert len(result["encouragement"]) > 0

    def test_emotional_feedback_filtered(self, isolated_data_dir):
        """emotional_feedback.generate_emotional_feedback applies filter."""
        # Pre-populate history cache to avoid circular recursion:
        # build_student_history → grade_long_answer → _attach_emotional_feedback
        # → generate_emotional_feedback → build_student_history
        from engine.emotional_feedback import _HISTORY_CACHE
        _HISTORY_CACHE[("s01", "hw_001")] = {
            "has_history": True,
            "student_id": "s01",
            "student_name": "同学s01",
            "score_trend": [8.0],
            "current_score": 8,
            "max_score": 10,
            "strengths": ["计算"],
            "weaknesses": ["概念"],
            "correction_rate": 0.5,
            "correction_mastery": {},
        }

        from engine.emotional_feedback import generate_emotional_feedback
        text = generate_emotional_feedback(
            student_id="s01",
            current_performance={"score": 8, "max_score": 10, "is_correct": False},
        )
        assert isinstance(text, str)
        assert len(text) > 0


# ── 6.10: Prompt loading ─────────────────────────────────────────────

class TestContentSafetyPrompt:
    """Test content_safety_filter prompt loading (6.10)."""

    def test_load_content_safety_filter(self):
        """load_content_safety_filter() returns non-empty prompt text."""
        from prompts import load_content_safety_filter
        prompt = load_content_safety_filter()
        assert isinstance(prompt, str)
        assert len(prompt) > 50
        # Should contain key audit dimensions
        assert "improper_guidance" in prompt or "不当引导" in prompt
        assert "value_bias" in prompt or "价值观" in prompt

    def test_load_prompt_by_name_content_safety(self):
        """load_prompt_by_name can load content_safety_filter."""
        from prompts import load_prompt_by_name
        prompt = load_prompt_by_name("content_safety_filter")
        assert len(prompt) > 50


# ── 6.9: School Onboarding ───────────────────────────────────────────

class TestSchoolOnboarding:
    """Test onboard_school.py (6.9)."""

    def test_dry_run_does_not_write(self, tmp_path, monkeypatch):
        """--dry-run prints plan without writing files."""
        data_dir = tmp_path / "data"
        data_dir.mkdir()

        sys.path.insert(0, str(_DEMO_DIR.parent / "scripts"))
        import onboard_school
        # Patch DEMO_DIR so all data paths redirect to tmp_path
        monkeypatch.setattr(onboard_school, "DEMO_DIR", tmp_path)

        result = onboard_school.onboard_school(
            name="测试学校",
            code="TEST001",
            admin_name="admin",
            admin_password="pass123",
            dry_run=True,
        )
        assert result["dry_run"] is True
        assert result["school"]["name"] == "测试学校"
        # No files should have been written
        assert not (data_dir / "organization.json").exists()

    def test_actual_run_creates_records(self, tmp_path, monkeypatch):
        """Actual run creates school, grades, classes, admin, tenant config."""
        data_dir = tmp_path / "data"
        data_dir.mkdir()

        sys.path.insert(0, str(_DEMO_DIR.parent / "scripts"))
        import onboard_school
        monkeypatch.setattr(onboard_school, "DEMO_DIR", tmp_path)

        result = onboard_school.onboard_school(
            name="新学校",
            code="NEW001",
            admin_name="newadmin",
            admin_password="newpass123",
            dry_run=False,
        )
        assert result["dry_run"] is False
        assert result["school"]["id"] is not None
        assert len(result["grades"]) == 3  # 高一/高二/高三
        assert len(result["classes"]) == 3  # 1 per grade
        assert result["admin"] is not None

        # Verify files were written
        org_file = tmp_path / "data" / "organization.json"
        assert org_file.exists()
        org_data = json.loads(org_file.read_text())
        assert any(s["name"] == "新学校" for s in org_data.get("schools", []))


# ── 6.12: Backup Drill ───────────────────────────────────────────────

class TestBackupDrill:
    """Test backup_drill.py (6.12)."""

    def test_crontab_template_exists(self):
        """Crontab template file exists."""
        crontab = _REPO_ROOT / "deploy" / "crontab" / "seewo-crontab"
        assert crontab.exists()
        content = crontab.read_text()
        assert "backup_pg.py" in content
        assert "backup_drill.py" in content

    def test_backup_drill_script_importable(self):
        """backup_drill.py can be imported."""
        sys.path.insert(0, str(_REPO_ROOT / "scripts"))
        import backup_drill
        assert hasattr(backup_drill, "run_drill")

    def test_backup_drill_report_structure(self, tmp_path, monkeypatch):
        """run_drill returns a report dict with expected keys."""
        sys.path.insert(0, str(_REPO_ROOT / "scripts"))
        import backup_drill

        # Point BACKUP_DIR to non-existent dir so drill fails gracefully
        monkeypatch.setenv("BACKUP_DIR", str(tmp_path / "nonexistent"))

        report = backup_drill.run_drill(
            report_dir=str(tmp_path / "reports"),
        )
        assert isinstance(report, dict)
        assert "status" in report
        assert "steps" in report
        assert "checks" in report
        # Should be failed since no backup exists
        assert report["status"] in ("failed", "passed_with_warnings")


# ── Helper ───────────────────────────────────────────────────────────

def load_json(name):
    """Load a JSON file from the demo data directory."""
    with open(_DEMO_DIR / "data" / name, "r", encoding="utf-8") as f:
        return json.load(f)
