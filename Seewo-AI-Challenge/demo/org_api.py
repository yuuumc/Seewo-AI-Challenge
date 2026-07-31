"""V2.0 Sprint 5 (5.2): 组织树 CRUD API — Flask Blueprint.

Endpoints (per API_CONTRACT.md):
  GET    /api/admin/organization/tree          — 嵌套组织树
  POST   /api/admin/school                      — 创建学校
  PUT    /api/admin/school/<int:sid>            — 更新学校
  DELETE /api/admin/school/<int:sid>            — 删除/停用学校
  POST   /api/admin/grade                       — 创建年级
  PUT    /api/admin/grade/<int:gid>             — 更新年级
  DELETE /api/admin/grade/<int:gid>             — 删除年级
  POST   /api/admin/class                       — 创建班级
  PUT    /api/admin/class/<int:cid>             — 更新班级
  DELETE /api/admin/class/<int:cid>             — 删除班级
  POST   /api/admin/subject-group               — 创建学科组
  PUT    /api/admin/subject-group/<int:sgid>    — 更新学科组
  DELETE /api/admin/subject-group/<int:sgid>    — 删除学科组

数据存储：demo 模式使用 JSON 文件（data/organization.json）；
PG 模式可切换到 ORM（infra/pg/orm.py 的 School/Grade/Class/SubjectGroup）。

权限：所有端点需 @login_required + @roles_required("admin","head","teacher")
+ @data_scope() 数据范围过滤。RBAC 继承机制自动放行 super_admin/school_admin/head_teacher。
"""
from __future__ import annotations

import json
import os
from pathlib import Path

from flask import Blueprint, jsonify, request, g, session

from security import login_required, roles_required, data_scope, audit_log, get_current_user

bp = Blueprint("org_api", __name__)

_DATA_DIR = Path(__file__).parent / "data"
_ORG_FILE = _DATA_DIR / "organization.json"


# ---------------------------------------------------------------------------
# JSON storage helpers
# ---------------------------------------------------------------------------

def _load_org() -> dict:
    """Load organization data from JSON file."""
    if not _ORG_FILE.exists():
        # Seed with default school
        return {
            "schools": [
                {
                    "id": 1, "name": "默认学校", "code": "default",
                    "district": "", "school_type": "secondary",
                    "address": "", "contact_phone": "",
                    "is_active": True, "config": {},
                }
            ],
            "grades": [],
            "classes": [],
            "subject_groups": [],
            "_seq": {"school": 1, "grade": 0, "class": 0, "subject_group": 0},
        }
    with open(_ORG_FILE, "r", encoding="utf-8") as f:
        return json.load(f)


def _save_org(data: dict) -> None:
    """Save organization data to JSON file (atomic write)."""
    _DATA_DIR.mkdir(parents=True, exist_ok=True)
    tmp = _ORG_FILE.with_suffix(".tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    tmp.replace(_ORG_FILE)


def _next_id(data: dict, key: str) -> int:
    seq = data.setdefault("_seq", {})
    seq[key] = seq.get(key, 0) + 1
    return seq[key]


def _school_filter(items: list, school_id: int | None) -> list:
    """Filter items by school_id; None means no filter (super_admin)."""
    if school_id is None:
        return items
    return [i for i in items if i.get("school_id") == school_id]


def _ok(data=None, **extra):
    return jsonify({"ok": True, "data": data, **extra})


def _err(msg: str, code: int = 400):
    return jsonify({"ok": False, "error": msg}), code


# ---------------------------------------------------------------------------
# Organization tree (nested)
# ---------------------------------------------------------------------------

@bp.route("/api/admin/organization/tree")
@login_required
@roles_required("teacher", "head", "admin")
@data_scope()
def org_tree():
    """Return the organization tree for the current user's scope."""
    data = _load_org()
    school_id = getattr(g, "school_id", 1)

    schools = _school_filter(data["schools"], school_id)
    if not schools:
        return _ok({"school": None, "grades": [], "subject_groups": []})

    school = schools[0]
    grades = _school_filter(data.get("grades", []), school_id)
    subject_groups = _school_filter(data.get("subject_groups", []), school_id)

    # Build nested structure: school → grades → classes
    for grade in grades:
        grade["classes"] = [
            {**c, "student_count": _count_students(c.get("id"))}
            for c in _school_filter(data.get("classes", []), school_id)
            if c.get("grade_id") == grade.get("id")
        ]

    return _ok({
        "school": school,
        "grades": grades,
        "subject_groups": subject_groups,
    })


def _count_students(class_id: int | None) -> int:
    """Count students in a class (from students.json if available)."""
    if not class_id:
        return 0
    try:
        from engine.grader import load_json
        students = load_json("students.json").get("students", [])
        return sum(1 for s in students if s.get("class_id") == class_id)
    except Exception:
        return 0


# ---------------------------------------------------------------------------
# School CRUD
# ---------------------------------------------------------------------------

@bp.route("/api/admin/school", methods=["POST"])
@login_required
@roles_required("admin")
@data_scope()
def school_create():
    body = request.get_json(silent=True) or {}
    name = body.get("name", "").strip()
    code = body.get("code", "").strip()
    if not name or not code:
        return _err("name and code are required")

    data = _load_org()
    if any(s["code"] == code for s in data["schools"]):
        return _err("school code already exists", 409)

    sid = _next_id(data, "school")
    school = {
        "id": sid,
        "name": name,
        "code": code,
        "district": body.get("district", ""),
        "school_type": body.get("school_type", "secondary"),
        "address": body.get("address", ""),
        "contact_phone": body.get("contact_phone", ""),
        "is_active": True,
        "config": body.get("config", {}),
    }
    data["schools"].append(school)
    _save_org(data)
    audit_log("school_created", resource=f"school:{sid}", school_id=sid)
    return _ok(school), 201


@bp.route("/api/admin/school/<int:sid>", methods=["PUT"])
@login_required
@roles_required("admin")
@data_scope()
def school_update(sid):
    body = request.get_json(silent=True) or {}
    data = _load_org()

    school = next((s for s in data["schools"] if s["id"] == sid), None)
    if not school:
        return _err("school not found", 404)

    # school_admin can only update own school
    if getattr(g, "school_id", None) and g.school_id != sid:
        return _err("forbidden: cannot edit other school", 403)

    for field in ("name", "code", "district", "school_type", "address", "contact_phone", "config"):
        if field in body:
            school[field] = body[field]
    if "is_active" in body:
        school["is_active"] = bool(body["is_active"])

    _save_org(data)
    audit_log("school_updated", resource=f"school:{sid}", school_id=sid)
    return _ok(school)


@bp.route("/api/admin/school/<int:sid>", methods=["DELETE"])
@login_required
@roles_required("admin")
@data_scope()
def school_delete(sid):
    """Soft-delete (deactivate) by default; hard delete with ?hard=1."""
    data = _load_org()
    school = next((s for s in data["schools"] if s["id"] == sid), None)
    if not school:
        return _err("school not found", 404)

    hard = request.args.get("hard") == "1"
    if hard:
        # Only super_admin can hard-delete
        user = get_current_user()
        if user and user.get("role") != "super_admin":
            return _err("hard delete requires super_admin", 403)
        data["schools"] = [s for s in data["schools"] if s["id"] != sid]
    else:
        school["is_active"] = False

    _save_org(data)
    audit_log("school_deleted", resource=f"school:{sid}", school_id=sid, hard=hard)
    return _ok({"id": sid, "is_active": school.get("is_active", False) if not hard else None})


# ---------------------------------------------------------------------------
# Grade CRUD
# ---------------------------------------------------------------------------

@bp.route("/api/admin/grade", methods=["POST"])
@login_required
@roles_required("admin", "head")
@data_scope()
def grade_create():
    body = request.get_json(silent=True) or {}
    name = body.get("name", "").strip()
    if not name:
        return _err("name is required")

    data = _load_org()
    school_id = body.get("school_id", getattr(g, "school_id", 1))

    gid = _next_id(data, "grade")
    grade = {
        "id": gid,
        "school_id": school_id,
        "name": name,
        "grade_level": body.get("grade_level", 1),
        "academic_year": body.get("academic_year", "2026-2027"),
        "is_active": True,
    }
    data.setdefault("grades", []).append(grade)
    _save_org(data)
    audit_log("grade_created", resource=f"grade:{gid}", school_id=school_id)
    return _ok(grade), 201


@bp.route("/api/admin/grade/<int:gid>", methods=["PUT"])
@login_required
@roles_required("admin", "head")
@data_scope()
def grade_update(gid):
    body = request.get_json(silent=True) or {}
    data = _load_org()

    grade = next((g_ for g_ in data.get("grades", []) if g_["id"] == gid), None)
    if not grade:
        return _err("grade not found", 404)

    for field in ("name", "grade_level", "academic_year", "is_active"):
        if field in body:
            grade[field] = body[field]

    _save_org(data)
    audit_log("grade_updated", resource=f"grade:{gid}", school_id=grade.get("school_id"))
    return _ok(grade)


@bp.route("/api/admin/grade/<int:gid>", methods=["DELETE"])
@login_required
@roles_required("admin", "head")
@data_scope()
def grade_delete(gid):
    data = _load_org()
    grade = next((g_ for g_ in data.get("grades", []) if g_["id"] == gid), None)
    if not grade:
        return _err("grade not found", 404)

    data["grades"] = [g_ for g_ in data.get("grades", []) if g_["id"] != gid]
    # Cascade: remove classes under this grade
    data["classes"] = [c for c in data.get("classes", []) if c.get("grade_id") != gid]
    _save_org(data)
    audit_log("grade_deleted", resource=f"grade:{gid}", school_id=grade.get("school_id"))
    return _ok({"id": gid})


# ---------------------------------------------------------------------------
# Class CRUD
# ---------------------------------------------------------------------------

@bp.route("/api/admin/class", methods=["POST"])
@login_required
@roles_required("admin", "head", "teacher")
@data_scope()
def class_create():
    body = request.get_json(silent=True) or {}
    name = body.get("name", "").strip()
    if not name:
        return _err("name is required")

    data = _load_org()
    school_id = body.get("school_id", getattr(g, "school_id", 1))

    cid = _next_id(data, "class")
    cls = {
        "id": cid,
        "school_id": school_id,
        "grade_id": body.get("grade_id"),
        "name": name,
        "teacher_id": body.get("teacher_id"),
        "class_code": body.get("class_code", ""),
        "is_active": True,
    }
    data.setdefault("classes", []).append(cls)
    _save_org(data)
    audit_log("class_created", resource=f"class:{cid}", school_id=school_id)
    return _ok(cls), 201


@bp.route("/api/admin/class/<int:cid>", methods=["PUT"])
@login_required
@roles_required("admin", "head", "teacher")
@data_scope()
def class_update(cid):
    body = request.get_json(silent=True) or {}
    data = _load_org()

    cls = next((c for c in data.get("classes", []) if c["id"] == cid), None)
    if not cls:
        return _err("class not found", 404)

    for field in ("name", "grade_id", "teacher_id", "class_code", "is_active"):
        if field in body:
            cls[field] = body[field]

    _save_org(data)
    audit_log("class_updated", resource=f"class:{cid}", school_id=cls.get("school_id"))
    return _ok(cls)


@bp.route("/api/admin/class/<int:cid>", methods=["DELETE"])
@login_required
@roles_required("admin", "head", "teacher")
@data_scope()
def class_delete(cid):
    data = _load_org()
    cls = next((c for c in data.get("classes", []) if c["id"] == cid), None)
    if not cls:
        return _err("class not found", 404)

    data["classes"] = [c for c in data.get("classes", []) if c["id"] != cid]
    _save_org(data)
    audit_log("class_deleted", resource=f"class:{cid}", school_id=cls.get("school_id"))
    return _ok({"id": cid})


# ---------------------------------------------------------------------------
# Subject Group CRUD
# ---------------------------------------------------------------------------

@bp.route("/api/admin/subject-group", methods=["POST"])
@login_required
@roles_required("admin", "head")
@data_scope()
def subject_group_create():
    body = request.get_json(silent=True) or {}
    name = body.get("name", "").strip()
    subject = body.get("subject", "").strip()
    if not name or not subject:
        return _err("name and subject are required")

    data = _load_org()
    school_id = body.get("school_id", getattr(g, "school_id", 1))

    sgid = _next_id(data, "subject_group")
    sg = {
        "id": sgid,
        "school_id": school_id,
        "name": name,
        "subject": subject,
        "leader_id": body.get("leader_id"),
        "member_ids": body.get("member_ids", []),
        "is_active": True,
    }
    data.setdefault("subject_groups", []).append(sg)
    _save_org(data)
    audit_log("subject_group_created", resource=f"subject_group:{sgid}", school_id=school_id)
    return _ok(sg), 201


@bp.route("/api/admin/subject-group/<int:sgid>", methods=["PUT"])
@login_required
@roles_required("admin", "head")
@data_scope()
def subject_group_update(sgid):
    body = request.get_json(silent=True) or {}
    data = _load_org()

    sg = next((s for s in data.get("subject_groups", []) if s["id"] == sgid), None)
    if not sg:
        return _err("subject group not found", 404)

    for field in ("name", "subject", "leader_id", "member_ids", "is_active"):
        if field in body:
            sg[field] = body[field]

    _save_org(data)
    audit_log("subject_group_updated", resource=f"subject_group:{sgid}", school_id=sg.get("school_id"))
    return _ok(sg)


@bp.route("/api/admin/subject-group/<int:sgid>", methods=["DELETE"])
@login_required
@roles_required("admin", "head")
@data_scope()
def subject_group_delete(sgid):
    data = _load_org()
    sg = next((s for s in data.get("subject_groups", []) if s["id"] == sgid), None)
    if not sg:
        return _err("subject group not found", 404)

    data["subject_groups"] = [s for s in data.get("subject_groups", []) if s["id"] != sgid]
    _save_org(data)
    audit_log("subject_group_deleted", resource=f"subject_group:{sgid}", school_id=sg.get("school_id"))
    return _ok({"id": sgid})
