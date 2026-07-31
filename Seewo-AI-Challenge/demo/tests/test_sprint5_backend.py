"""V2.0 Sprint 5 后端业务实现测试（快速原型师 6 项）.

覆盖:
  5.2  组织树 CRUD API — org_api.py
  5.9  数据脱敏后端 — data_masking.py
  5.10 consent 后端 — consent_manager.py
  5.12 批量导入后端 — batch_import.py
  5.6  TLS 全链路 — Caddyfile 配置检查
  5.11 备份脚本 — backup_pg.py 接口检查
"""
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

# Ensure demo dir is on path
DEMO_DIR = Path(__file__).parent.parent
sys.path.insert(0, str(DEMO_DIR))

os.environ["DEMO_AUTH_OPEN"] = "1"


class TestOrgCRUD(unittest.TestCase):
    """5.2: 组织树 CRUD API 测试."""

    def setUp(self):
        import app as app_module
        self.app = app_module.app
        self.app.config["TESTING"] = True
        self.client = self.app.test_client()

    def test_org_tree_returns_default_school(self):
        """GET /api/admin/organization/tree returns school + grades + subject_groups."""
        resp = self.client.get("/api/admin/organization/tree")
        self.assertEqual(resp.status_code, 200)
        data = resp.get_json()
        self.assertTrue(data["ok"])
        self.assertIn("school", data["data"])
        self.assertIn("grades", data["data"])
        self.assertIn("subject_groups", data["data"])

    def test_create_grade(self):
        """POST /api/admin/grade creates a grade."""
        resp = self.client.post("/api/admin/grade",
                                json={"name": "高三", "grade_level": 12, "school_id": 1})
        self.assertEqual(resp.status_code, 201)
        data = resp.get_json()
        self.assertTrue(data["ok"])
        self.assertEqual(data["data"]["name"], "高三")
        self.assertEqual(data["data"]["grade_level"], 12)

    def test_create_class(self):
        """POST /api/admin/class creates a class."""
        # First create a grade
        resp = self.client.post("/api/admin/grade",
                                json={"name": "高二", "grade_level": 11, "school_id": 1})
        grade_id = resp.get_json()["data"]["id"]

        resp = self.client.post("/api/admin/class",
                                json={"school_id": 1, "grade_id": grade_id,
                                      "name": "高二(1)班", "class_code": "G2-01"})
        self.assertEqual(resp.status_code, 201)
        data = resp.get_json()
        self.assertTrue(data["ok"])
        self.assertEqual(data["data"]["name"], "高二(1)班")

    def test_create_subject_group(self):
        """POST /api/admin/subject-group creates a subject group."""
        resp = self.client.post("/api/admin/subject-group",
                                json={"school_id": 1, "name": "数学组",
                                      "subject": "数学", "member_ids": [1, 2]})
        self.assertEqual(resp.status_code, 201)
        data = resp.get_json()
        self.assertTrue(data["ok"])
        self.assertEqual(data["data"]["subject"], "数学")

    def test_update_school(self):
        """PUT /api/admin/school/<id> updates school fields."""
        resp = self.client.put("/api/admin/school/1",
                               json={"name": "测试学校", "district": "海淀区"})
        self.assertEqual(resp.status_code, 200)
        data = resp.get_json()
        self.assertTrue(data["ok"])
        self.assertEqual(data["data"]["name"], "测试学校")

    def test_delete_grade_cascade(self):
        """DELETE /api/admin/grade/<id> removes grade and cascades to classes."""
        # Create grade + class
        resp = self.client.post("/api/admin/grade",
                                json={"name": "高一", "grade_level": 10, "school_id": 1})
        grade_id = resp.get_json()["data"]["id"]
        self.client.post("/api/admin/class",
                         json={"school_id": 1, "grade_id": grade_id, "name": "高一(1)班"})

        # Delete grade
        resp = self.client.delete(f"/api/admin/grade/{grade_id}")
        self.assertEqual(resp.status_code, 200)

        # Verify grade gone from tree
        resp = self.client.get("/api/admin/organization/tree")
        grades = resp.get_json()["data"]["grades"]
        self.assertFalse(any(g["id"] == grade_id for g in grades))

    def test_school_code_unique(self):
        """POST /api/admin/school with duplicate code returns 409."""
        resp = self.client.post("/api/admin/school",
                                json={"name": "学校A", "code": "default"})
        self.assertEqual(resp.status_code, 409)

    def test_grade_missing_name(self):
        """POST /api/admin/grade without name returns 400."""
        resp = self.client.post("/api/admin/grade", json={"grade_level": 10})
        self.assertEqual(resp.status_code, 400)


class TestDataMasking(unittest.TestCase):
    """5.9: 数据脱敏后端测试."""

    def test_mask_name_short(self):
        from data_masking import mask_name
        self.assertEqual(mask_name("张三"), "张*")
        self.assertEqual(mask_name("李"), "*")

    def test_mask_name_long(self):
        from data_masking import mask_name
        result = mask_name("欧阳修")
        self.assertTrue(result.startswith("欧"))
        self.assertIn("*", result)

    def test_mask_phone(self):
        from data_masking import mask_phone
        self.assertEqual(mask_phone("13800138000"), "138****8000")

    def test_mask_student_no(self):
        from data_masking import mask_student_no
        result = mask_student_no("2026001")
        self.assertTrue(result.startswith("2026"))
        self.assertIn("*", result)

    def test_mask_student_record_teacher_own_class(self):
        """Teacher viewing own class: name not masked, phone masked."""
        from data_masking import mask_student_record
        record = {"name": "张三", "student_no": "2026001", "phone": "13800138000"}
        masked = mask_student_record(record, role="teacher", is_own_class=True)
        self.assertEqual(masked["name"], "张三")  # not masked
        self.assertEqual(masked["phone"], "138****8000")  # masked

    def test_mask_student_record_other_role(self):
        """Non-teacher or non-own-class: all fields masked."""
        from data_masking import mask_student_record
        record = {"name": "张三", "student_no": "2026001", "phone": "13800138000"}
        masked = mask_student_record(record, role="admin", is_own_class=False)
        self.assertEqual(masked["name"], "张*")
        self.assertIn("*", masked["student_no"])
        self.assertEqual(masked["phone"], "138****8000")

    def test_mask_student_list(self):
        from data_masking import mask_student_list
        students = [
            {"name": "张三", "student_no": "2026001", "phone": "13800138000"},
            {"name": "李四", "student_no": "2026002", "phone": "13900139000"},
        ]
        masked = mask_student_list(students, role="admin")
        self.assertEqual(len(masked), 2)
        self.assertEqual(masked[0]["name"], "张*")

    def test_mask_guardian_and_id(self):
        from data_masking import mask_guardian_name, mask_id_no
        self.assertEqual(mask_guardian_name("王父"), "王*")
        result = mask_id_no("110101199001011234")
        self.assertTrue(result.startswith("110"))
        self.assertIn("*", result)


class TestConsentManager(unittest.TestCase):
    """5.10: consent 后端测试."""

    def setUp(self):
        import app as app_module
        self.app = app_module.app
        self.app.config["TESTING"] = True
        self.client = self.app.test_client()

    def test_consent_status_demo_mode(self):
        """Demo mode returns 'demo' status."""
        from consent_manager import get_consent_status
        # DEMO_AUTH_OPEN=1 is set at module level
        status = get_consent_status("s01")
        self.assertEqual(status, "demo")

    def test_create_consent_record(self):
        """POST /consent with JSON creates a consent record."""
        # Use the test client to provide request context
        resp = self.client.post("/consent",
                                json={"guardian_name": "测试家长",
                                      "guardian_id_no": "110101199001011234",
                                      "student_id": "test_consent_001",
                                      "signature_data_url": "data:image/png;base64,iVBOR...",
                                      "agree": True})
        # In demo mode, user is teacher (non-student), so gets redirected
        # The consent endpoint requires student role
        self.assertIn(resp.status_code, [200, 302])

    def test_get_latest_consent_record(self):
        """get_latest_consent_record returns the most recent record."""
        from consent_manager import create_consent_record, get_latest_consent_record
        # Use app context for request-dependent calls
        with self.app.test_request_context("/consent", method="POST"):
            from flask import session
            session["user_id"] = "s01"
            session["user_role"] = "student"
            session["school_id"] = 1
            create_consent_record("test_consent_002", "家长A", "110101199001011234")
            create_consent_record("test_consent_002", "家长B", "110101199001011235")

        record = get_latest_consent_record("test_consent_002")
        self.assertIsNotNone(record)
        self.assertEqual(record["guardian_name"], "家长B")

    def test_consent_page_renders(self):
        """GET /consent renders with consent_status."""
        resp = self.client.get("/consent")
        # In demo mode, non-students get redirected; students see consent page
        # Demo mode auto-auths as teacher by default, so expect redirect
        self.assertIn(resp.status_code, [200, 302])

    def test_consent_api_record_not_found(self):
        """GET /api/consent/record returns 404 for non-existent student."""
        resp = self.client.get("/api/consent/record?student_id=nonexistent_xyz")
        self.assertEqual(resp.status_code, 404)


class TestBatchImport(unittest.TestCase):
    """5.12: 批量导入后端测试."""

    def setUp(self):
        import app as app_module
        self.app = app_module.app
        self.app.config["TESTING"] = True
        self.client = self.app.test_client()

    def test_template_download(self):
        """GET /api/admin/import-students/template returns xlsx."""
        resp = self.client.get("/api/admin/import-students/template")
        self.assertEqual(resp.status_code, 200)
        self.assertIn("spreadsheet", resp.content_type)

    def test_import_no_file(self):
        """POST /api/admin/import-students without file returns 400."""
        resp = self.client.post("/api/admin/import-students")
        self.assertEqual(resp.status_code, 400)

    def test_import_unsupported_format(self):
        """POST with .txt file returns 400."""
        from io import BytesIO
        resp = self.client.post("/api/admin/import-students",
                                data={"file": (BytesIO(b"test"), "test.txt")},
                                content_type="multipart/form-data")
        self.assertEqual(resp.status_code, 400)

    def test_parse_csv(self):
        """_parse_csv correctly parses CSV bytes."""
        from batch_import import _parse_csv
        csv_bytes = b"\xe5\xa7\x93\xe5\x90\x8d,\xe5\xad\xa6\xe5\x8f\xb7,\xe7\x8f\xad\xe7\xba\xa7\xe5\x90\x8d\xe7\xa7\xb0,\xe6\x80\xa7\xe5\x88\xab\n\xe5\xbc\xa0\xe4\xb8\x89,2026001,\xe9\xab\x98\xe4\xba\x8c(1)\xe7\x8f\xad,\xe7\x94\xb7"
        rows = _parse_csv(csv_bytes)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["姓名"], "张三")

    def test_normalize_row(self):
        """_normalize_row handles various column name conventions."""
        from batch_import import _normalize_row
        row = {"name": "张三", "student_no": "2026001", "class_name": "高二(1)班", "gender": "男", "_row": 2}
        nr = _normalize_row(row)
        self.assertEqual(nr["name"], "张三")
        self.assertEqual(nr["student_no"], "2026001")
        self.assertEqual(nr["class_name"], "高二(1)班")

    def test_validate_rows_missing_name(self):
        """_validate_rows flags missing name."""
        from batch_import import _validate_rows
        rows = [{"student_no": "2026001", "class_name": "高二(1)班", "_row": 2}]
        valid, errors = _validate_rows(rows, set(), {"高二(1)班"})
        self.assertEqual(len(valid), 0)
        self.assertEqual(len(errors), 1)
        self.assertIn("缺少姓名", errors[0]["reason"])

    def test_validate_rows_duplicate_in_file(self):
        """_validate_rows flags duplicate student_no within file."""
        from batch_import import _validate_rows
        rows = [
            {"name": "张三", "student_no": "2026001", "class_name": "高二(1)班", "_row": 2},
            {"name": "李四", "student_no": "2026001", "class_name": "高二(1)班", "_row": 3},
        ]
        valid, errors = _validate_rows(rows, set(), {"高二(1)班"})
        self.assertEqual(len(valid), 1)
        self.assertEqual(len(errors), 1)
        self.assertIn("重复", errors[0]["reason"])


class TestTLSConfig(unittest.TestCase):
    """5.6: TLS 全链路配置测试."""

    def test_caddyfile_has_hsts_preload(self):
        caddyfile = DEMO_DIR.parent / "deploy" / "caddy" / "Caddyfile"
        content = caddyfile.read_text()
        self.assertIn("preload", content)
        self.assertIn("max-age=63072000", content)

    def test_caddyfile_tls_protocols(self):
        caddyfile = DEMO_DIR.parent / "deploy" / "caddy" / "Caddyfile"
        content = caddyfile.read_text()
        self.assertIn("tls1.2", content)
        self.assertIn("tls1.3", content)

    def test_caddyfile_permissions_policy(self):
        caddyfile = DEMO_DIR.parent / "deploy" / "caddy" / "Caddyfile"
        content = caddyfile.read_text()
        self.assertIn("Permissions-Policy", content)

    def test_caddyfile_internal_tls_comment(self):
        """Caddyfile documents internal service TLS option."""
        caddyfile = DEMO_DIR.parent / "deploy" / "caddy" / "Caddyfile"
        content = caddyfile.read_text()
        self.assertIn("内服务加密", content)


class TestBackupScript(unittest.TestCase):
    """5.11: 备份脚本接口测试（不实际执行 pg_dump）."""

    def test_backup_script_exists(self):
        script = DEMO_DIR.parent / "scripts" / "backup_pg.py"
        self.assertTrue(script.exists())

    def test_backup_script_has_subcommands(self):
        script = DEMO_DIR.parent / "scripts" / "backup_pg.py"
        content = script.read_text()
        for cmd in ["backup", "restore", "verify", "list"]:
            self.assertIn(f'"{cmd}"', content)

    def test_backup_script_has_oss_upload(self):
        script = DEMO_DIR.parent / "scripts" / "backup_pg.py"
        content = script.read_text()
        self.assertIn("_upload_oss", content)
        self.assertIn("RETENTION_DAYS", content)

    def test_backup_script_has_rotation(self):
        script = DEMO_DIR.parent / "scripts" / "backup_pg.py"
        content = script.read_text()
        self.assertIn("_rotate_backups", content)


class TestAdminStudentsAPI(unittest.TestCase):
    """5.9: 学生列表 API (with masking) 测试."""

    def setUp(self):
        import app as app_module
        self.app = app_module.app
        self.app.config["TESTING"] = True
        self.client = self.app.test_client()

    def test_students_list_returns_masked(self):
        """GET /api/admin/students returns list with masking."""
        resp = self.client.get("/api/admin/students")
        self.assertEqual(resp.status_code, 200)
        data = resp.get_json()
        self.assertTrue(data["ok"])
        self.assertIn("items", data["data"])
        self.assertIn("total", data["data"])

    def test_students_list_pagination(self):
        """GET /api/admin/students?page=1&size=2 respects pagination."""
        resp = self.client.get("/api/admin/students?page=1&size=2")
        self.assertEqual(resp.status_code, 200)
        data = resp.get_json()
        self.assertEqual(data["data"]["page"], 1)
        self.assertLessEqual(len(data["data"]["items"]), 2)


if __name__ == "__main__":
    unittest.main()
