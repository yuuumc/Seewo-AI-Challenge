"""V2.0 Sprint 5 (5.10): Consent 后端 — 正式化同意记录管理.

功能:
- 三态 consent_status: granted / pending / demo
- 同意记录持久化（JSON 文件 + PG 可选）
- 审计查询：获取学生最近一条同意记录
- 未同意降级：require_consent 装饰器已有，这里补充正式化逻辑

数据结构 (data/consent_records.json):
[
  {
    "record_id": "cr_001",
    "student_id": "s01",
    "student_name": "同学A",
    "guardian_name": "张父",
    "guardian_id_no": "110101199001011234",
    "signature_data_url": "data:image/png;base64,...",
    "agreed": true,
    "granted_at": "2026-07-31T10:30:00+0800",
    "granted_by": "s01",
    "version": "v2.0",
    "school_id": 1
  }
]
"""
from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import Optional

from flask import session

from security import get_current_user, audit_log

_DATA_DIR = Path(__file__).parent / "data"
_CONSENT_FILE = _DATA_DIR / "consent_records.json"
_CONSENT_VERSION = "v2.0"


def _load_records() -> list[dict]:
    if not _CONSENT_FILE.exists():
        return []
    with open(_CONSENT_FILE, "r", encoding="utf-8") as f:
        return json.load(f)


def _save_records(records: list[dict]) -> None:
    _DATA_DIR.mkdir(parents=True, exist_ok=True)
    tmp = _CONSENT_FILE.with_suffix(".tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(records, f, ensure_ascii=False, indent=2)
    tmp.replace(_CONSENT_FILE)


def _next_record_id(records: list[dict]) -> str:
    max_num = 0
    for r in records:
        rid = r.get("record_id", "")
        if rid.startswith("cr_"):
            try:
                num = int(rid[3:])
                max_num = max(max_num, num)
            except ValueError:
                pass
    return f"cr_{max_num + 1:03d}"


def get_consent_status(student_id: str = None) -> str:
    """Determine consent status for a student.

    Returns: "granted", "pending", or "demo"
    - demo: DEMO_AUTH_OPEN=1 (auto-granted in demo mode)
    - granted: consent record exists or consent_given=True in session/DEMO_USERS
    - pending: no consent record
    """
    # Demo mode: auto-granted
    if os.environ.get("DEMO_AUTH_OPEN", "0") == "1":
        return "demo"

    user = get_current_user()
    if not user:
        return "pending"

    # Non-students don't need consent
    if user.get("role") != "student":
        return "granted"

    # Check session
    if session.get("consent_given"):
        return "granted"

    # Check consent records
    sid = student_id or user.get("student_id") or user.get("user_id", "")
    records = _load_records()
    if any(r.get("student_id") == sid and r.get("agreed") for r in records):
        return "granted"

    # Check DEMO_USERS
    from security import DEMO_USERS
    du = DEMO_USERS.get(user.get("user_id", ""))
    if du and du.get("consent_given"):
        return "granted"

    return "pending"


def get_student_name(student_id: str = None) -> str:
    """Get student display name for consent page."""
    user = get_current_user()
    if not user:
        return ""
    sid = student_id or user.get("student_id") or user.get("user_id", "")
    from security import DEMO_USERS
    du = DEMO_USERS.get(sid)
    if du:
        return du.get("name", sid)
    return user.get("name", sid)


def create_consent_record(
    student_id: str,
    guardian_name: str,
    guardian_id_no: str,
    signature_data_url: str = "",
    agreed: bool = True,
) -> dict:
    """Create a new consent record and persist it.

    Returns the created record dict.
    """
    records = _load_records()
    record_id = _next_record_id(records)
    user = get_current_user()
    school_id = 1
    if user:
        school_id = user.get("school_id", 1)

    student_name = get_student_name(student_id)

    record = {
        "record_id": record_id,
        "student_id": student_id,
        "student_name": student_name,
        "guardian_name": guardian_name,
        "guardian_id_no": guardian_id_no,
        "signature_data_url": signature_data_url[:200] if signature_data_url else "",
        "agreed": agreed,
        "granted_at": time.strftime("%Y-%m-%dT%H:%M:%S%z", time.localtime()),
        "granted_by": user.get("user_id", "") if user else "",
        "version": _CONSENT_VERSION,
        "school_id": school_id,
    }

    records.append(record)
    _save_records(records)

    # Update session
    session["consent_given"] = True

    # Update DEMO_USERS in-memory
    from security import DEMO_USERS
    uid = user.get("user_id", "") if user else ""
    if uid in DEMO_USERS:
        DEMO_USERS[uid]["consent_given"] = True

    # Try PG update
    try:
        from db_store import set_consent as _db_set_consent
        _db_set_consent(uid)
    except Exception:
        pass

    audit_log("consent_recorded", resource=f"consent:{record_id}",
              student_id=student_id, school_id=school_id)
    return record


def get_latest_consent_record(student_id: str) -> Optional[dict]:
    """Get the most recent consent record for a student (for audit display)."""
    records = _load_records()
    matching = [r for r in records if r.get("student_id") == student_id and r.get("agreed")]
    if not matching:
        return None
    return matching[-1]


def build_consent_context() -> dict:
    """Build template context for the consent page.

    Returns dict with: consent_status, student_name, student_id, consent_record
    """
    user = get_current_user()
    if not user:
        return {"consent_status": "demo", "student_name": "", "student_id": ""}

    sid = user.get("student_id") or user.get("user_id", "")
    status = get_consent_status(sid)
    name = get_student_name(sid)

    ctx = {
        "consent_status": status,
        "student_name": name,
        "student_id": sid,
    }

    if status == "granted":
        record = get_latest_consent_record(sid)
        if record:
            from data_masking import mask_guardian_name, mask_id_no
            ctx["consent_record"] = {
                "record_id": record.get("record_id"),
                "granted_at": record.get("granted_at"),
                "guardian_name_masked": mask_guardian_name(record.get("guardian_name")),
                "guardian_id_no_masked": mask_id_no(record.get("guardian_id_no")),
                "version": record.get("version"),
            }
        else:
            ctx["consent_record"] = None
    else:
        ctx["consent_record"] = None

    return ctx
