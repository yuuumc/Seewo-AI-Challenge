/* ════════════════════════════════════════════════════════════════════
 * Sprint 5 · 组织树 API 客户端 + Mock 层
 * 契约见 API_CONTRACT.md。后端 /api/admin/organization/* 就绪后自动走真实接口；
 * 未就绪（404/网络错误）时回退 mock，保证页面可演示。
 * ════════════════════════════════════════════════════════════════════ */
(function (global) {
  'use strict';

  function csrfToken() {
    var m = document.cookie.match(/(?:^|;\s*)csrf_token=([^;]+)/);
    if (m) return decodeURIComponent(m[1]);
    var el = document.querySelector('input[name="csrf_token"]');
    return el ? el.value : '';
  }

  async function request(method, url, body, isForm) {
    var opts = { method: method, headers: {}, credentials: 'same-origin' };
    if (body !== undefined && !isForm) {
      opts.headers['Content-Type'] = 'application/json';
      opts.headers['X-CSRF-Token'] = csrfToken();
      opts.body = JSON.stringify(body);
    } else if (isForm) {
      opts.headers['X-CSRF-Token'] = csrfToken();
      opts.body = body; // FormData
    }
    var res = await fetch(url, opts);
    if (res.status === 404) {
      var err = new Error('NOT_FOUND ' + url);
      err.notFound = true;
      throw err;
    }
    var data = await res.json().catch(function () { return {}; });
    if (!res.ok || data.ok === false) {
      var e = new Error(data.error || ('HTTP ' + res.status));
      e.payload = data;
      throw e;
    }
    return data.data !== undefined ? data.data : data;
  }

  // ── Mock 数据 ───────────────────────────────────────────────────────
  var MOCK = {
    school: { id: 1, name: '默认学校', code: 'default', district: '海淀区', school_type: 'senior', address: '北京市海淀区中关村南大街', contact_phone: '010-62510000', is_active: true, config: { semester: '2026-2027-1' } },
    grades: [
      { id: 1, school_id: 1, name: '高一', grade_level: 10, academic_year: '2026-2027', is_active: true,
        classes: [
          { id: 1, school_id: 1, grade_id: 1, name: '高一(1)班', teacher_id: 3, class_code: 'G1-01', is_active: true, student_count: 42 },
          { id: 2, school_id: 1, grade_id: 1, name: '高一(2)班', teacher_id: 4, class_code: 'G1-02', is_active: true, student_count: 40 }
        ] },
      { id: 2, school_id: 1, name: '高二', grade_level: 11, academic_year: '2026-2027', is_active: true,
        classes: [
          { id: 3, school_id: 1, grade_id: 2, name: '高二(1)班', teacher_id: 5, class_code: 'G2-01', is_active: true, student_count: 38 }
        ] }
    ],
    subject_groups: [
      { id: 1, school_id: 1, name: '数学组', subject: '数学', leader_id: 3, member_ids: [3, 4, 5], is_active: true },
      { id: 2, school_id: 1, name: '语文组', subject: '语文', leader_id: 6, member_ids: [6], is_active: true }
    ]
  };
  var _seq = 100;

  function mockDelay(v) { return new Promise(function (r) { setTimeout(function () { r(v); }, 120); }); }

  function mockTree() { return mockDelay(JSON.parse(JSON.stringify(MOCK))); }
  function mockCreate(kind, body) {
    _seq++;
    var node = Object.assign({ id: _seq, is_active: true }, body);
    if (kind === 'grade') { node.classes = []; MOCK.grades.push(node); }
    if (kind === 'class') { node.student_count = 0; MOCK.grades.forEach(function (g) { if (g.id === node.grade_id) g.classes.push(node); }); }
    if (kind === 'subject-group') { MOCK.subject_groups.push(node); }
    return mockDelay(node);
  }
  function mockUpdate(kind, id, body) {
    var coll = kind === 'school' ? [MOCK.school] : kind === 'grade' ? MOCK.grades : kind === 'class' ? MOCK.grades.flatMap(function (g) { return g.classes; }) : MOCK.subject_groups;
    var n = coll.find(function (x) { return x.id === id; });
    if (n) Object.assign(n, body);
    return mockDelay(n || {});
  }
  function mockDelete(kind, id) {
    if (kind === 'grade') MOCK.grades = MOCK.grades.filter(function (g) { return g.id !== id; });
    if (kind === 'class') MOCK.grades.forEach(function (g) { g.classes = g.classes.filter(function (c) { return c.id !== id; }); });
    if (kind === 'subject-group') MOCK.subject_groups = MOCK.subject_groups.filter(function (s) { return s.id !== id; });
    return mockDelay({ id: id });
  }

  // ── 公开 API ────────────────────────────────────────────────────────
  var OrgAPI = {
    USE_MOCK: false, // 真实接口 404 时自动置 true

    async getTree() {
      try { return await request('GET', '/api/admin/organization/tree'); }
      catch (e) { if (e.notFound) { this.USE_MOCK = true; return mockTree(); } throw e; }
    },
    async create(kind, body) {
      if (this.USE_MOCK) return mockCreate(kind, body);
      return request('POST', '/api/admin/' + (kind === 'subject-group' ? 'subject-group' : kind), body);
    },
    async update(kind, id, body) {
      if (this.USE_MOCK) return mockUpdate(kind, id, body);
      return request('PUT', '/api/admin/' + (kind === 'subject-group' ? 'subject-group' : kind) + '/' + id, body);
    },
    async remove(kind, id) {
      if (this.USE_MOCK) return mockDelete(kind, id);
      return request('DELETE', '/api/admin/' + (kind === 'subject-group' ? 'subject-group' : kind) + '/' + id);
    },
    async uploadStudents(file, classId) {
      if (this.USE_MOCK) return mockUpload(file, classId);
      var fd = new FormData(); fd.append('file', file); if (classId) fd.append('class_id', classId);
      return request('POST', '/api/admin/import-students', fd, true);
    },
    async confirmImport(classId, rows) {
      if (this.USE_MOCK) return mockDelay({ imported: rows.length });
      return request('POST', '/api/admin/import-students/confirm', { class_id: classId, rows: rows });
    },
    async getStudents(classId) {
      if (this.USE_MOCK) return mockStudents(classId);
      return request('GET', '/api/admin/students?class_id=' + classId);
    }
  };

  // mock 上传校验
  function mockUpload(file, classId) {
    var rows = [];
    var n = 8 + Math.floor(Math.random() * 6);
    for (var i = 1; i <= n; i++) {
      var valid = i % 5 !== 0;
      rows.push({ row: i, name: valid ? '学生' + i : (i === 10 ? '' : '重复' + i), student_no: '2026' + String(100 + i), class_name: '高一(1)班', valid: valid, reason: valid ? '' : (i === 10 ? '缺少姓名' : '学号重复') });
    }
    var errors = rows.filter(function (r) { return !r.valid; });
    return mockDelay({ total: rows.length, valid: rows.length - errors.length, invalid: errors.length, preview: rows, errors: errors });
  }
  function mockStudents(classId) {
    return mockDelay({ items: [{ id: 10, name: '张**', student_no: '2026***01', class_name: '高一(1)班', phone: '138****5678' }], total: 1, page: 1 });
  }

  global.OrgAPI = OrgAPI;
})(window);
