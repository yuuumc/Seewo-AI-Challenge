# -*- coding: utf-8 -*-
"""Sprint 6 前端看板页面渲染测试。

覆盖 2 个 P1 看板模板：
  6.5 /admin/usage 教师用量看板
  6.6 /admin/health 系统健康看板

使用 Jinja2 直接渲染（不依赖 Flask app / DB），验证页面结构完整性。
"""
import os
import pytest
from jinja2 import Environment, FileSystemLoader, ChoiceLoader, DictLoader, TemplateNotFound

TEMPLATES_DIR = os.path.join(os.path.dirname(__file__), "..", "templates")
TEMPLATES_DIR = os.path.abspath(TEMPLATES_DIR)

# 测试时需要 base.html；若不存在（交付包仅含新模板），用最小桩。
BASE_STUB = """<!DOCTYPE html><html><head><title>{% block title %}{% endblock %}</title>{% block head %}{% endblock %}</head><body>{% block nav %}{% endblock %}{% block content %}{% endblock %}{% block scripts %}{% endblock %}</body></html>"""


@pytest.fixture
def env():
    # 先尝试真实文件系统；base.html 不存在时用 DictLoader 桩兜底
    loaders = [FileSystemLoader(TEMPLATES_DIR)]
    try:
        Environment(loader=FileSystemLoader(TEMPLATES_DIR)).get_template("base.html")
    except TemplateNotFound:
        loaders.append(DictLoader({"base.html": BASE_STUB}))
    e = Environment(loader=ChoiceLoader(loaders), autoescape=True)
    e.globals["csrf_token"] = lambda: "test-csrf-token"
    e.globals["get_current_user"] = lambda: None
    e.globals["get_flashed_messages"] = lambda with_categories=False: []
    return e


# ── 6.5 /admin/usage ────────────────────────────────────────────────────

def test_usage_page_renders(env):
    html = env.get_template("admin/usage.html").render()
    assert "教师用量看板" in html
    assert 'id="usage-chart"' in html
    assert 'id="ranking-body"' in html


def test_usage_period_switcher(env):
    html = env.get_template("admin/usage.html").render()
    assert 'data-period="day"' in html
    assert 'data-period="week"' in html
    assert 'data-period="month"' in html


def test_usage_kpi_cards(env):
    html = env.get_template("admin/usage.html").render()
    assert 'id="kpi-grading"' in html
    assert 'id="kpi-llm"' in html
    assert 'id="kpi-students"' in html


def test_usage_loads_echarts_and_api(env):
    html = env.get_template("admin/usage.html").render()
    assert "echarts" in html
    assert "/static/js/admin/dashboard-api.js" in html


def test_usage_ranking_table_columns(env):
    html = env.get_template("admin/usage.html").render()
    assert "批改量" in html
    assert "LLM 调用" in html
    assert "活跃学生" in html


# ── 6.6 /admin/health ───────────────────────────────────────────────────

def test_health_page_renders(env):
    html = env.get_template("admin/health.html").render()
    assert "系统健康看板" in html
    assert 'id="latency-chart"' in html
    assert 'id="success-gauge"' in html


def test_health_infra_cards(env):
    html = env.get_template("admin/health.html").render()
    for key in ("cpu", "mem", "disk", "pg"):
        assert ('id="' + key + "-value\"") in html or ('id="' + key + "-badge\"") in html


def test_health_pg_pool_display(env):
    html = env.get_template("admin/health.html").render()
    assert 'id="pg-value"' in html
    assert 'id="pg-detail"' in html


def test_health_request_log_table(env):
    html = env.get_template("admin/health.html").render()
    assert 'id="logs-body"' in html
    assert 'id="log-filter"' in html  # 过滤器
    assert "Request ID" in html


def test_health_alert_history(env):
    html = env.get_template("admin/health.html").render()
    assert 'id="alerts-body"' in html
    assert "告警历史" in html


def test_health_loads_echarts_and_api(env):
    html = env.get_template("admin/health.html").render()
    assert "echarts" in html
    assert "/static/js/admin/dashboard-api.js" in html


def test_health_refresh_button(env):
    html = env.get_template("admin/health.html").render()
    assert 'id="btn-refresh"' in html


def test_health_nav_links(env):
    html = env.get_template("admin/health.html").render()
    assert "/admin/usage" in html
    assert "/admin/organization" in html


# ── 导航一致性 ──────────────────────────────────────────────────────────

def test_usage_nav_links(env):
    html = env.get_template("admin/usage.html").render()
    assert "/admin/health" in html
    assert "/admin/organization" in html
