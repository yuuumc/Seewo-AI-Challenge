#!/usr/bin/env python3
"""V2.0 Sprint 6 (6.9): 新学校一键接入脚本.

功能:
  - 创建 school 记录
  - 创建默认年级（高一/高二/高三）
  - 创建默认班级（每年级 1 班）
  - 创建 admin 账号
  - 初始化租户 LLM 配置（继承全局默认）
  - --dry-run 模式预览不执行

用法:
  python scripts/onboard_school.py --name "海淀实验中学" --code hd-sy --admin-name "王管理员" --admin-password "Admin@123"
  python scripts/onboard_school.py --name "测试学校" --code test --dry-run

环境变量:
  DEMO_AUTH_OPEN=1 时使用 JSON 存储（默认）
  PG 可用时走 ORM
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path

# Add demo dir to path
DEMO_DIR = Path(__file__).parent.parent / "demo"
sys.path.insert(0, str(DEMO_DIR))


def _load_org_data() -> dict:
    org_file = DEMO_DIR / "data" / "organization.json"
    if not org_file.exists():
        return {
            "schools": [],
            "grades": [],
            "classes": [],
            "subject_groups": [],
            "_seq": {"school": 0, "grade": 0, "class": 0, "subject_group": 0},
        }
    with open(org_file, "r", encoding="utf-8") as f:
        return json.load(f)


def _save_org_data(data: dict) -> None:
    org_file = DEMO_DIR / "data" / "organization.json"
    org_file.parent.mkdir(parents=True, exist_ok=True)
    tmp = org_file.with_suffix(".tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    tmp.replace(org_file)


def _load_users() -> dict:
    users_file = DEMO_DIR / "data" / "users.json"
    if not users_file.exists():
        return {"users": []}
    with open(users_file, "r", encoding="utf-8") as f:
        return json.load(f)


def _save_users(data: dict) -> None:
    users_file = DEMO_DIR / "data" / "users.json"
    tmp = users_file.with_suffix(".tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    tmp.replace(users_file)


def _load_tenant_config() -> list:
    cfg_file = DEMO_DIR / "data" / "tenant_llm_config.json"
    if not cfg_file.exists():
        return []
    with open(cfg_file, "r", encoding="utf-8") as f:
        return json.load(f)


def _save_tenant_config(configs: list) -> None:
    cfg_file = DEMO_DIR / "data" / "tenant_llm_config.json"
    cfg_file.parent.mkdir(parents=True, exist_ok=True)
    tmp = cfg_file.with_suffix(".tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(configs, f, ensure_ascii=False, indent=2)
    tmp.replace(cfg_file)


DEFAULT_GRADES = [
    {"name": "高一", "grade_level": 10},
    {"name": "高二", "grade_level": 11},
    {"name": "高三", "grade_level": 12},
]


def onboard_school(
    name: str,
    code: str,
    admin_name: str = "管理员",
    admin_password: str = "Admin@123",
    district: str = "",
    school_type: str = "secondary",
    dry_run: bool = False,
) -> dict:
    """Onboard a new school with default structure.

    Returns dict with created resources.
    """
    org_data = _load_org_data()

    # Check code uniqueness
    if any(s["code"] == code for s in org_data["schools"]):
        print(f"[ERROR] School code '{code}' already exists", file=sys.stderr)
        sys.exit(1)

    # Generate IDs
    seq = org_data.get("_seq", {})
    school_id = seq.get("school", 0) + 1
    grade_start = seq.get("grade", 0)
    class_start = seq.get("class", 0)

    # Build school record
    school = {
        "id": school_id,
        "name": name,
        "code": code,
        "district": district,
        "school_type": school_type,
        "address": "",
        "contact_phone": "",
        "is_active": True,
        "config": {},
    }

    # Build default grades
    grades = []
    classes = []
    for i, g_def in enumerate(DEFAULT_GRADES):
        grade_id = grade_start + i + 1
        grade = {
            "id": grade_id,
            "school_id": school_id,
            "name": g_def["name"],
            "grade_level": g_def["grade_level"],
            "academic_year": "2026-2027",
            "is_active": True,
        }
        grades.append(grade)

        # One class per grade
        class_id = class_start + i + 1
        cls = {
            "id": class_id,
            "school_id": school_id,
            "grade_id": grade_id,
            "name": f"{g_def['name']}(1)班",
            "teacher_id": None,
            "class_code": f"{code.upper()}-G{g_def['grade_level']}-01",
            "is_active": True,
        }
        classes.append(cls)

    # Build admin user
    admin_user_id = f"{code}_admin"
    admin_user = {
        "user_id": admin_user_id,
        "username": admin_user_id,
        "name": admin_name,
        "role": "admin",
        "password_hash": "",  # In production: bcrypt hash
        "consent_given": True,
        "school_id": school_id,
    }

    # Build tenant LLM config (inherit global defaults = all NULL)
    tenant_config = {
        "school_id": school_id,
        "model_name": None,  # inherit global
        "temperature": None,
        "max_tokens": None,
        "timeout": None,
        "api_key_secret": None,
        "base_url": None,
        "subject_overrides": {},
        "updated_by": "system",
        "updated_at": time.strftime("%Y-%m-%dT%H:%M:%S%z", time.localtime()),
    }

    # Print plan
    print("=" * 60)
    print("  新学校接入计划" + (" (DRY RUN)" if dry_run else ""))
    print("=" * 60)
    print(f"\n  学校: {name} (code={code}, id={school_id})")
    print(f"  区域: {district or '(未指定)'}")
    print(f"  类型: {school_type}")
    print(f"\n  年级/班级:")
    for g, c in zip(grades, classes):
        print(f"    {g['name']} → {c['name']} (code={c['class_code']})")
    print(f"\n  管理员: {admin_name} (user_id={admin_user_id})")
    print(f"  密码: {'***' if not dry_run else admin_password}")
    print(f"\n  租户LLM配置: 继承全局默认 (所有字段 NULL)")
    print("=" * 60)

    if dry_run:
        print("\n[DRY RUN] 未实际写入数据。移除 --dry-run 执行。")
        return {
            "school": school,
            "grades": grades,
            "classes": classes,
            "admin": admin_user,
            "tenant_config": tenant_config,
            "dry_run": True,
        }

    # Execute: write data
    org_data["schools"].append(school)
    org_data.setdefault("grades", []).extend(grades)
    org_data.setdefault("classes", []).extend(classes)
    seq["school"] = school_id
    seq["grade"] = grade_start + len(DEFAULT_GRADES)
    seq["class"] = class_start + len(DEFAULT_GRADES)
    org_data["_seq"] = seq
    _save_org_data(org_data)
    print(f"\n[OK] 组织树数据写入: data/organization.json")

    # Write admin user
    users_data = _load_users()
    users_data.setdefault("users", []).append(admin_user)
    _save_users(users_data)
    print(f"[OK] 管理员账号写入: data/users.json")

    # Write tenant config
    configs = _load_tenant_config()
    configs.append(tenant_config)
    _save_tenant_config(configs)
    print(f"[OK] 租户LLM配置写入: data/tenant_llm_config.json")

    print(f"\n✓ 学校 '{name}' 接入完成！")
    print(f"  school_id={school_id}")
    print(f"  admin 登录: username={admin_user_id}")
    print(f"\n  下一步:")
    print(f"  1. 登录管理后台配置 LLM 参数（或保持继承全局默认）")
    print(f"  2. 通过批量导入添加学生")
    print(f"  3. 配置学科组")

    return {
        "school": school,
        "grades": grades,
        "classes": classes,
        "admin": admin_user,
        "tenant_config": tenant_config,
        "dry_run": False,
    }


def main():
    parser = argparse.ArgumentParser(description="Onboard a new school")
    parser.add_argument("--name", required=True, help="School name")
    parser.add_argument("--code", required=True, help="School code (unique)")
    parser.add_argument("--admin-name", default="管理员", help="Admin display name")
    parser.add_argument("--admin-password", default="Admin@123", help="Admin password")
    parser.add_argument("--district", default="", help="District/region")
    parser.add_argument("--school-type", default="secondary", help="School type")
    parser.add_argument("--dry-run", action="store_true", help="Preview without writing")

    args = parser.parse_args()
    onboard_school(
        name=args.name,
        code=args.code,
        admin_name=args.admin_name,
        admin_password=args.admin_password,
        district=args.district,
        school_type=args.school_type,
        dry_run=args.dry_run,
    )


if __name__ == "__main__":
    main()
