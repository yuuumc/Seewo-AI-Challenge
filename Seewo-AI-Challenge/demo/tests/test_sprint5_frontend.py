# -*- coding: utf-8 -*-
"""Sprint 5 前端页面渲染测试。

覆盖 4 个模块的模板渲染：
  ① /admin/organization 组织树管理页
  ② /consent 正式化同意页（granted / pending / demo 三态）
  ③ 数据脱敏展示（masking.js 为纯前端工具，此处验证模板可渲染脱敏标记）
  ④ 批量导入前端（组织树页内嵌 3 步弹窗）

说明：使用 Jinja2 直接渲染模板（不依赖 Flask app / DB），验证页面结构完整性。
集成测试需在真实 app 注册路由后补充（leader 在 ECS 上接入后运行）。
"""
import os
import pytest
from jinja2 import Environment, FileSystemLoader

TEMPLATES_DIR = os.path.join(os.path.dirname(__file__), "..", "templates")
TEMPLATES_DIR = os.path.abspath(TEMPLATES_DIR)


@pytest.fixture
def env():
    e = Environment(loader=FileSystemLoader(TEMPLATES_DIR), autoescape=True)
    e.globals["csrf_token"] = lambda: "test-csrf-token"
    return e


# ── ① 组织树管理页 ──────────────────────────────────────────────────────

def test_organization_page_renders(env):
    html = env.get_template("admin/organization.html").render(
        current_user={"role": "school_admin"}
    )
    assert "组织树管理" in html
    assert 'id="org-tree"' in html
    assert 'id="node-detail"' in html
    assert 'id="btn-add-school"' in html


def test_organization_import_dialog_3_steps(env):
    html = env.get_template("admin/organization.html").render(current_user={"role": "school_admin"})
    assert 'id="import-step-1"' in html
    assert 'id="import-step-2"' in html
    assert 'id="import-step-3"' in html
    assert 'id="drop-zone"' in html  # 拖拽上传
    assert 'id="btn-confirm-import"' in html  # 确认导入
    assert 'id="btn-download-errors"' in html  # 错误报告下载


def test_organization_loads_scripts(env):
    html = env.get_template("admin/organization.html").render(current_user={"role": "school_admin"})
    assert "/static/js/admin/org-api.js" in html
    assert "/static/js/admin/organization.js" in html


def test_organization_csrf_token_injected(env):
    html = env.get_template("admin/organization.html").render(current_user={"role": "school_admin"})
    assert "test-csrf-token" in html


# ── ② 同意页三态 ────────────────────────────────────────────────────────

def test_consent_pending_renders_signature_form(env):
    html = env.get_template("consent.html").render(
        consent_status="pending", student_name="张三", student_id=10
    )
    assert "监护人同意书" in html
    assert 'id="sig-canvas"' in html  # 手写签字画板
    assert 'name="guardian_name"' in html
    assert 'name="agree"' in html  # 同意勾选
    assert "test-csrf-token" in html


def test_consent_granted_renders_audit_record(env):
    html = env.get_template("consent.html").render(
        consent_status="granted", student_name="张三", student_id=10,
        consent_record={
            "granted_at": "2026-07-31 10:00:00",
            "guardian_name_masked": "张**",
            "guardian_id_no_masked": "110101********1234",
            "record_id": "CONSENT-2026-001",
            "version": "2.0",
        },
    )
    assert "已获得监护人同意" in html
    assert "CONSENT-2026-001" in html  # 审计记录编号
    assert "110101********1234" in html  # 证件号脱敏展示


def test_consent_granted_without_record(env):
    html = env.get_template("consent.html").render(
        consent_status="granted", student_name="李四", student_id=11
    )
    assert "已获得监护人同意" in html


def test_consent_demo_mode_banner(env):
    html = env.get_template("consent.html").render(
        consent_status="demo", student_name="王五", student_id=12
    )
    assert "演示模式" in html
    assert "DEMO_AUTH_OPEN" in html


def test_consent_degradation_notice_present(env):
    """未同意时显示功能降级提示"""
    html = env.get_template("consent.html").render(
        consent_status="pending", student_name="张三", student_id=10
    )
    assert "降级" in html or "只读" in html


# ── ③ 脱敏展示：模板可渲染脱敏标记 ─────────────────────────────────────

def test_consent_audit_record_uses_masked_fields(env):
    """同意记录的监护人信息以脱敏形式展示（后端返回已脱敏，前端原样渲染）"""
    html = env.get_template("consent.html").render(
        consent_status="granted", student_name="张三", student_id=10,
        consent_record={
            "granted_at": "2026-07-31", "guardian_name_masked": "张**",
            "guardian_id_no_masked": "110101********1234",
            "record_id": "R1", "version": "2.0",
        },
    )
    assert "张**" in html
    assert "110101********1234" in html


# ── ④ 批量导入：在组织树页内嵌 ─────────────────────────────────────────

def test_batch_import_supports_xlsx_csv(env):
    html = env.get_template("admin/organization.html").render(current_user={"role": "school_admin"})
    assert 'accept=".xlsx,.csv"' in html


def test_batch_import_editable_preview(env):
    """预览表格的错误行可编辑修正（class prev-edit 由 JS 注入，模板提供容器）"""
    html = env.get_template("admin/organization.html").render(current_user={"role": "school_admin"})
    assert 'id="prev-body"' in html  # 预览表格体
    assert 'id="show-errors-only"' in html  # 仅看错误行开关


def test_batch_import_error_report_download(env):
    html = env.get_template("admin/organization.html").render(current_user={"role": "school_admin"})
    assert 'id="btn-download-errors"' in html
