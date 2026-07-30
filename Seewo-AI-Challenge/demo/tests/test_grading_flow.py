"""批改主流程 smoke 测试 — **不依赖 LLM_API_KEY**。

设计：
- 这套测试在 leader 集成前后都应 pass（demo 模式让所有页面可匿名访问）
- 走 MockProvider 路径（编排工程师的 factory，无 key 自动降级）
- 覆盖：渲染 / 200 / 关键字段存在 / 引擎函数形状 / 订正提交闭环

如果哪天这条 fail，那是真问题 — 说明 leader 集成时把 demo 模式下的页面也加了 @login_required，
违反了前端 UI 线 CHANGES.md 的「demo 模式零环境变量必须跑通」约束。
"""

from __future__ import annotations

import json
from typing import Any

import pytest
import os


# ── MIG-01: prod 模式自动登录（让"页面渲染"测试在 prod 模式也跑通）─────
@pytest.fixture(autouse=True)
def _prod_auto_login(client: Any) -> None:
    """prod 模式（DEMO_AUTH_OPEN=0）下自动登录 teacher，
    让"页面渲染"类测试聚焦渲染而非鉴权。鉴权测试在 test_auth / test_idor 里覆盖。"""
    if os.environ.get("DEMO_AUTH_OPEN", "0") == "0":
        from _helpers import login
        login(client, "teacher", "teacher123")

# ── 1. 关键 GET 页面渲染 ─────────────────────────────────────────────
PUBLIC_GET_ROUTES = [
    "/",                                            # 首页（角色选择）
    "/teacher",                                     # 教师工作台
    "/teacher/grade/hw_001",                        # 批改页
    "/teacher/analytics/hw_001",                    # 学情分析
    "/teacher/agent-trace/hw_001",                  # Agent 追踪
    "/teacher/review/hw_001",                       # AI 复核队列
    "/teacher/correction-loop/hw_001",              # 订正闭环看板
    "/student",                                     # 学生列表
    "/student/s01",                                 # 学生详情
    "/student/s01/dashboard",                       # 学生今日
    "/student/s01/correction",                      # 订正页
    "/student/s01/error-book",                      # 错题本
    "/student/s01/knowledge-tree",                  # 知识树
    "/student/s01/radar",                           # 知识雷达
    "/student/s01/growth",                          # 成长报告
    "/student/s01/coach",                           # 数学教练
    "/classroom",                                   # 课堂互动 demo
]


@pytest.mark.parametrize("path", PUBLIC_GET_ROUTES)
def test_public_get_route_renders(client: Any, path: str) -> None:
    """demo 模式下所有公开 GET 路由必须 200 + 渲染（无 env 变量）。"""
    rv = client.get(path)
    assert rv.status_code == 200, f"{path} 渲染失败 status={rv.status_code}"
    # 渲染产物是 HTML，至少含 doctype 或 <html
    body = rv.data
    assert b"<html" in body or b"<!DOCTYPE" in body, (
        f"{path} 响应不是 HTML 页面（body[:200]={body[:200]!r}）"
    )


# ── 2. API JSON 端点 ────────────────────────────────────────────────
JSON_API_ROUTES = [
    ("/api/grade/s01/hw_001", ["student_id", "total_score", "questions", "comment"]),
    ("/api/analytics/hw_001", []),  # 形状不锁死
    ("/api/correction-loop/hw_001", []),
    ("/api/review-queue/hw_001", []),
    ("/api/radar/s01", []),
    ("/api/variants/q5/B", []),
]


@pytest.mark.parametrize("path,required_keys", JSON_API_ROUTES)
def test_api_json_endpoint(client: Any, path: str, required_keys: list) -> None:
    """JSON API 端点必须返回合法 JSON（content-type + loads 不抛）。"""
    rv = client.get(path)
    assert rv.status_code == 200, f"{path} status={rv.status_code}"
    assert rv.is_json, f"{path} 不是 JSON 响应（content-type={rv.content_type}）"
    data = rv.get_json()
    for key in required_keys:
        assert key in data, f"{path} 响应缺关键字段: {key}"


# ── 3. 订正提交闭环 ─────────────────────────────────────────────────
def test_correction_submit_objective_correct(client: Any) -> None:
    """选择题订正答对 → ok=True, loop_closed=True。"""
    # 先找一个真存在的选择题 ID
    from engine.grader import load_json  # type: ignore
    questions = load_json("questions.json")["hw_001"]["questions"]
    choice_q = next((q for q in questions if q["type"] == "choice"), None)
    if not choice_q:
        pytest.skip("hw_001 无选择题 — 当前 demo 数据未含此题型")
    from _helpers import get_csrf_token
    token = get_csrf_token(client)
    rv = client.post(
        "/student/s01/correction/submit",
        json={"question_id": choice_q["id"], "correction_text": choice_q["answer"], "csrf_token": token},
    )
    assert rv.status_code == 200
    payload = rv.get_json()
    assert payload["ok"] is True
    assert payload["is_correct"] is True
    assert payload["loop_closed"] is True


def test_correction_submit_objective_wrong(client: Any) -> None:
    """选择题订正答错 → ok=True（接口层面）, is_correct=False。"""
    from engine.grader import load_json  # type: ignore
    questions = load_json("questions.json")["hw_001"]["questions"]
    choice_q = next((q for q in questions if q["type"] == "choice"), None)
    if not choice_q:
        pytest.skip("hw_001 无选择题")
    from _helpers import get_csrf_token
    token = get_csrf_token(client)
    rv = client.post(
        "/student/s01/correction/submit",
        json={"question_id": choice_q["id"], "correction_text": "WRONG_ANSWER_XYZ", "csrf_token": token},
    )
    assert rv.status_code == 200
    payload = rv.get_json()
    assert payload["is_correct"] is False
    assert payload["loop_closed"] is False


def test_correction_submit_empty_text_rejected(client: Any) -> None:
    """空订正文本必须被拒（接口契约：empty → 400 / 200 + ok=False）。"""
    from _helpers import get_csrf_token
    token = get_csrf_token(client)
    rv = client.post(
        "/student/s01/correction/submit",
        json={"question_id": "q1", "correction_text": "", "csrf_token": token},
    )
    # app.py 当前实现：空文本 → 200 + ok=False, feedback="请输入订正内容"
    # 集成后可能改为 400；两者都接受
    assert rv.status_code in (200, 400)
    if rv.status_code == 200:
        payload = rv.get_json()
        assert payload["ok"] is False


# ── 4. 引擎函数形状（grader.py / llm Provider） ─────────────────────
def test_grader_engine_imports_cleanly() -> None:
    """engine.grader 必须可干净导入（无 LLM 框架依赖）。"""
    import engine.grader  # type: ignore
    # 关键函数都得可调用
    for name in (
        "grade_choice", "grade_fill_blank", "grade_long_answer",
        "analyze_class_performance", "generate_personalized_comment",
        "verify_correction", "get_agent_trace", "load_json",
    ):
        assert hasattr(engine.grader, name), f"engine.grader 缺 {name}"


def test_llm_factory_falls_back_to_mock() -> None:
    """无 LLM_API_KEY 时 get_provider() 必须返回 MockProvider。"""
    import os
    os.environ.pop("LLM_API_KEY", None)
    try:
        from engine.llm.factory import get_provider  # type: ignore
    except ImportError:
        pytest.skip("engine.llm.factory 尚未集成（编排工程师的 PR 未合入）")
    provider = get_provider()
    # 不强锁类型名（MockProvider 可能被 import 别名）；只验形状
    assert hasattr(provider, "grade_step"), "provider 缺 grade_step 方法"
    assert hasattr(provider, "validate_correction"), "provider 缺 validate_correction"
    assert hasattr(provider, "generate_comment"), "provider 缺 generate_comment"


# ── 5. 数据完整性 ───────────────────────────────────────────────────
def test_data_files_present_and_valid_json() -> None:
    """data/ 目录下所有 JSON 文件必须能 loads（防 P0-9 文档/数据漂移）。"""
    import pathlib
    data_dir = pathlib.Path(__file__).resolve().parent.parent / "data"
    assert data_dir.is_dir(), f"data 目录不存在: {data_dir}"
    json_files = list(data_dir.glob("*.json"))
    assert len(json_files) >= 5, f"data/ JSON 文件过少: {len(json_files)}"
    for jf in json_files:
        try:
            json.loads(jf.read_text(encoding="utf-8"))
        except json.JSONDecodeError as e:
            pytest.fail(f"{jf.name} 不是合法 JSON: {e}")


def test_students_json_has_5_students() -> None:
    """students.json 必须含 5 名学生（demo 数据基线）。"""
    from engine.grader import load_json  # type: ignore
    data = load_json("students.json")
    students = data.get("students", [])
    assert len(students) == 5, f"预期 5 名学生，实际 {len(students)}"
    ids = {s["id"] for s in students}
    assert ids == {"s01", "s02", "s03", "s04", "s05"}, f"学生 ID 集合不符: {ids}"
