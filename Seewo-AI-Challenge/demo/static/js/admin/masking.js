/* ════════════════════════════════════════════════════════════════════
 * Sprint 5 · 5.9 P1 · 数据脱敏前端渲染工具
 *
 * 设计原则：脱敏由后端完成（API 返回已脱敏数据），前端「只需正确渲染」。
 * 本工具用于两种场景：
 *   1) 后端返回未脱敏字段时的兜底（防御性，不应依赖）
 *   2) 前端本地编辑场景（如批量导入预览）需要对显示值脱敏
 *
 * 用法:
 *   Masking.maskName('张三丰')   -> '张**'
 *   Masking.maskPhone('13812345678') -> '138****5678'
 *   Masking.maskIdNo('110101199001011234') -> '110101********1234'
 *   Masking.maskStudentNo('20260001') -> '2026***01'
 *   Masking.applyToRow(row) -> 原地脱敏学生记录对象
 *
 * 角色规则（与后端 @data_scope 一致）：
 *   teacher  看本班学生：姓名不脱敏、手机仍脱敏
 *   其他角色：姓名脱敏
 *   student/parent：仅本人/子女数据不脱敏
 * ════════════════════════════════════════════════════════════════════ */
(function (global) {
  'use strict';

  function maskName(name) {
    if (!name || typeof name !== 'string') return name || '';
    // 已脱敏（含 *）则原样返回
    if (name.indexOf('*') >= 0) return name;
    if (name.length <= 1) return name;
    if (name.length === 2) return name[0] + '*';
    return name[0] + '*'.repeat(Math.min(name.length - 1, 2));
  }

  function maskPhone(phone) {
    if (!phone) return phone || '';
    var s = String(phone);
    if (s.indexOf('*') >= 0) return s;
    if (s.length === 11) return s.slice(0, 3) + '****' + s.slice(-4);
    if (s.length >= 7) return s.slice(0, 3) + '****' + s.slice(-4);
    return s.replace(/\d/g, '*');
  }

  function maskIdNo(idNo) {
    if (!idNo) return idNo || '';
    var s = String(idNo);
    if (s.indexOf('*') >= 0) return s;
    if (s.length >= 10) return s.slice(0, 6) + '*'.repeat(s.length - 10) + s.slice(-4);
    return s.replace(/.(?=.{4})/g, '*');
  }

  function maskStudentNo(no) {
    if (!no) return no || '';
    var s = String(no);
    if (s.indexOf('*') >= 0) return s;
    if (s.length <= 4) return s;
    return s.slice(0, 4) + '*'.repeat(Math.min(s.length - 8, 4)) + (s.length > 8 ? s.slice(-4) : '');
  }

  // 对学生记录行做角色感知脱敏
  // role: 'teacher'|'head_teacher'|'school_admin'|'super_admin'|'student'|'parent'
  // isOwnOrChild: 是否是本人/子女数据（student/parent 场景）
  function applyToRow(row, role, isOwnOrChild) {
    if (!row) return row;
    // 后端已脱敏（含 *）则不再处理
    var out = Object.assign({}, row);
    var maskNameNeeded = true;
    if (role === 'teacher' && !isOwnOrChild) maskNameNeeded = false; // 教师看本班不脱敏姓名
    if (isOwnOrChild) maskNameNeeded = false; // 本人/子女不脱敏
    if (maskNameNeeded && out.name) out.name = maskName(out.name);
    if (out.phone) out.phone = maskPhone(out.phone); // 手机一律脱敏
    if (out.guardian_id_no) out.guardian_id_no = maskIdNo(out.guardian_id_no);
    if (out.student_no && maskNameNeeded) out.student_no = maskStudentNo(out.student_no);
    return out;
  }

  // 批量渲染：把表格中 [data-mask="name|phone|id|studentno"] 的元素脱敏
  function renderTable(tableEl) {
    if (!tableEl) return;
    var nodes = tableEl.querySelectorAll('[data-mask]');
    nodes.forEach(function (el) {
      var t = el.getAttribute('data-mask');
      var v = el.textContent;
      if (v.indexOf('*') >= 0) return; // 已脱敏
      if (t === 'name') el.textContent = maskName(v);
      else if (t === 'phone') el.textContent = maskPhone(v);
      else if (t === 'id') el.textContent = maskIdNo(v);
      else if (t === 'studentno') el.textContent = maskStudentNo(v);
    });
  }

  global.Masking = { maskName: maskName, maskPhone: maskPhone, maskIdNo: maskIdNo, maskStudentNo: maskStudentNo, applyToRow: applyToRow, renderTable: renderTable };
})(window);
