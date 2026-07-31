"""V2.0 Sprint 5 (5.9): 数据脱敏后端 — 按角色脱敏 API 响应.

规则（对齐 API_CONTRACT.md）:
- teacher 看本班学生：姓名不脱敏，手机号脱敏
- 其他角色：姓名脱敏（张**），学号脱敏（2026***01），手机脱敏（138****5678）
- 后端已脱敏的数据前端原样渲染（masking.js 检测到 * 不会重复处理）

使用方式：
    from data_masking import mask_student_record, mask_student_list
    masked = mask_student_list(students, role="teacher", is_own_class=True)
"""
from __future__ import annotations

from typing import Any

from pii_crypto import _mask_value


def mask_name(name: str | None) -> str | None:
    """张三 → 张*, 李四 → 李*"""
    return _mask_value(name)


def mask_phone(phone: str | None) -> str | None:
    """13800138000 → 138****8000"""
    if not phone or len(phone) < 7:
        return _mask_value(phone)
    return phone[:3] + "*" * (len(phone) - 7) + phone[-4:]


def mask_student_no(student_no: str | None) -> str | None:
    """2026001 → 2026***01 (show first 4 + last 2)"""
    if not student_no or len(student_no) <= 6:
        return _mask_value(student_no)
    return student_no[:4] + "*" * (len(student_no) - 6) + student_no[-2:]


def mask_student_record(
    record: dict,
    role: str = "",
    is_own_class: bool = False,
) -> dict:
    """Mask a single student record based on caller's role.

    Args:
        record: student dict with name, student_no, phone fields
        role: caller's role (teacher/head/admin/super_admin/student/parent)
        is_own_class: True if caller is a teacher viewing their own class

    Returns:
        Masked copy of the record.
    """
    masked = dict(record)

    # teacher viewing own class: name not masked, phone still masked
    if role == "teacher" and is_own_class:
        masked["phone"] = mask_phone(record.get("phone"))
    else:
        # All other roles: mask everything
        masked["name"] = mask_name(record.get("name"))
        masked["student_no"] = mask_student_no(record.get("student_no"))
        masked["phone"] = mask_phone(record.get("phone"))

    return masked


def mask_student_list(
    students: list[dict],
    role: str = "",
    is_own_class: bool = False,
) -> list[dict]:
    """Mask a list of student records."""
    return [mask_student_record(s, role, is_own_class) for s in students]


def mask_guardian_name(name: str | None) -> str | None:
    """Mask guardian name for consent audit display."""
    return mask_name(name)


def mask_id_no(id_no: str | None) -> str | None:
    """Mask guardian ID number: show first 3 + last 2."""
    if not id_no or len(id_no) <= 5:
        return _mask_value(id_no)
    return id_no[:3] + "*" * (len(id_no) - 5) + id_no[-2:]
