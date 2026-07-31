/* ════════════════════════════════════════════════════════════════════
 * Sprint 5 · 5.3 / 5.12 · 组织树管理页交互
 * 依赖: OrgAPI (org-api.js), base.html (Tailwind + Lucide)
 * ════════════════════════════════════════════════════════════════════ */
(function () {
  'use strict';
  var $ = function (s, r) { return (r || document).querySelector(s); };
  var $$ = function (s, r) { return Array.prototype.slice.call((r || document).querySelectorAll(s)); };

  var state = { tree: null, selected: null, importData: null };

  var FIELD_DEFS = {
    school: [
      { k: 'name', label: '学校名称', type: 'text', req: true },
      { k: 'code', label: '学校编码', type: 'text', req: true },
      { k: 'district', label: '所属区县', type: 'text' },
      { k: 'school_type', label: '学段', type: 'select', opts: [['primary', '小学'], ['junior', '初中'], ['senior', '高中'], ['mixed', '一贯制']] },
      { k: 'address', label: '学校地址', type: 'text' },
      { k: 'contact_phone', label: '联系电话', type: 'text' }
    ],
    grade: [
      { k: 'school_id', label: '所属学校', type: 'hidden' },
      { k: 'name', label: '年级名称', type: 'text', req: true, ph: '如 高二' },
      { k: 'grade_level', label: '年级数字(1-12)', type: 'number', req: true },
      { k: 'academic_year', label: '学年', type: 'text', ph: '2026-2027' }
    ],
    class: [
      { k: 'school_id', label: '所属学校', type: 'hidden' },
      { k: 'grade_id', label: '所属年级', type: 'hidden' },
      { k: 'name', label: '班级名称', type: 'text', req: true, ph: '如 高二(1)班' },
      { k: 'class_code', label: '班级编码', type: 'text' },
      { k: 'teacher_id', label: '班主任ID', type: 'number' }
    ],
    'subject-group': [
      { k: 'school_id', label: '所属学校', type: 'hidden' },
      { k: 'name', label: '学科组名称', type: 'text', req: true },
      { k: 'subject', label: '学科', type: 'select', opts: [['数学', '数学'], ['语文', '语文'], ['英语', '英语'], ['物理', '物理'], ['化学', '化学'], ['生物', '生物'], ['历史', '历史'], ['地理', '地理'], ['政治', '政治']] },
      { k: 'leader_id', label: '组长ID', type: 'number' }
    ]
  };
  var KIND_LABEL = { school: '学校', grade: '年级', class: '班级', 'subject-group': '学科组' };

  // ── 启动 ────────────────────────────────────────────────────────────
  document.addEventListener('DOMContentLoaded', init);

  async function init() {
    bindGlobal();
    try {
      state.tree = await OrgAPI.getTree();
      if (OrgAPI.USE_MOCK) showNotice('info', '后端 /api/admin/organization/* 未就绪，当前为 mock 演示数据。联调时自动切换真实接口。');
      renderTree();
      populateClassSelect();
    } catch (e) {
      showNotice('danger', '加载组织树失败：' + e.message);
      $('#org-tree').innerHTML = '<div class="text-center text-danger-600 text-xs py-8">加载失败</div>';
    }
    lucide.createIcons();
  }

  function bindGlobal() {
    $('#btn-add-school').addEventListener('click', function () { openModal('school', null, 'create'); });
    $('#btn-import').addEventListener('click', openImport);
    $('#btn-expand-all').addEventListener('click', function () { $$('.org-children').forEach(function (c) { c.style.display = ''; var t = c.previousElementSibling.querySelector('.twisty'); if (t) t.classList.add('open'); }); });
    $('#btn-collapse-all').addEventListener('click', function () { $$('.org-children').forEach(function (c) { c.style.display = 'none'; var t = c.previousElementSibling.querySelector('.twisty'); if (t) t.classList.remove('open'); }); });
    $('#org-search').addEventListener('input', function (e) { filterTree(e.target.value.trim().toLowerCase()); });

    $$('.import-step').forEach(function () {});
    // modal close
    $$('[data-modal-close]').forEach(function (el) { el.addEventListener('click', closeModal); });
    $('#node-form').addEventListener('submit', submitNodeForm);

    // import steps
    $('#import-file').addEventListener('change', onFileChange);
    $('#drop-zone').addEventListener('dragover', function (e) { e.preventDefault(); this.classList.add('border-primary-400', 'bg-primary-50/60'); });
    $('#drop-zone').addEventListener('dragleave', function () { this.classList.remove('border-primary-400', 'bg-primary-50/60'); });
    $('#drop-zone').addEventListener('drop', function (e) { e.preventDefault(); this.classList.remove('border-primary-400', 'bg-primary-50/60'); if (e.dataTransfer.files[0]) { $('#import-file').files = e.dataTransfer.files; onFileChange({ target: { files: e.dataTransfer.files } }); } });
    $('#btn-upload').addEventListener('click', doUpload);
    $('#btn-back-1').addEventListener('click', function () { goStep(1); });
    $('#show-errors-only').addEventListener('change', renderPreview);
    $('#btn-download-errors').addEventListener('click', downloadErrorExcel);
    $('#btn-confirm-import').addEventListener('click', doConfirmImport);
    $('#btn-import-done').addEventListener('click', function () { closeImport(); loadTree(); });
  }

  // ── 树渲染 ──────────────────────────────────────────────────────────
  function renderTree() {
    var root = $('#org-tree');
    root.innerHTML = '';
    var t = state.tree;
    if (!t || !t.school) { root.innerHTML = '<div class="text-xs text-gray-400 py-6 text-center">暂无学校，请新建</div>'; return; }
    var schoolEl = nodeEl('school', t.school, t.school.name, 'building-2', true);
    root.appendChild(schoolEl);
    var gc = document.createElement('div'); gc.className = 'org-children';
    // grades
    (t.grades || []).forEach(function (g) {
      var ge = nodeEl('grade', g, g.name, 'layers', true);
      var gcc = document.createElement('div'); gcc.className = 'org-children';
      (g.classes || []).forEach(function (c) {
        var ce = nodeEl('class', c, c.name + ' <span class="text-gray-400">(' + (c.student_count || 0) + '人)</span>', 'users', false);
        gcc.appendChild(ce);
      });
      ge.appendChild(gcc);
      gc.appendChild(ge);
    });
    // subject groups
    if (t.subject_groups && t.subject_groups.length) {
      var sgWrap = document.createElement('div'); sgWrap.className = 'mt-1';
      var sgTitle = document.createElement('div'); sgTitle.className = 'text-[11px] text-gray-400 px-2 pt-1'; sgTitle.textContent = '学科组';
      sgWrap.appendChild(sgTitle);
      (t.subject_groups).forEach(function (s) {
        sgWrap.appendChild(nodeEl('subject-group', s, s.name + ' · ' + s.subject, 'book-open', false));
      });
      gc.appendChild(sgWrap);
    }
    schoolEl.appendChild(gc);
    lucide.createIcons();
  }

  function nodeEl(kind, data, label, icon, hasToggle) {
    var row = document.createElement('div');
    row.className = 'org-node';
    row.dataset.kind = kind; row.dataset.id = data.id;
    var toggle = hasToggle ? '<i data-lucide="chevron-right" class="w-3.5 h-3.5 text-gray-400 twisty"></i>' : '<span class="w-3.5"></span>';
    var addBtn = kind === 'school' ? '<button class="ml-auto add-child p-1 rounded text-gray-300 hover:text-primary-500 hover:bg-primary-50" title="添加年级"><i data-lucide="plus" class="w-3.5 h-3.5"></i></button>'
              : kind === 'grade' ? '<button class="ml-auto add-child p-1 rounded text-gray-300 hover:text-primary-500 hover:bg-primary-50" title="添加班级"><i data-lucide="plus" class="w-3.5 h-3.5"></i></button>' : '';
    row.innerHTML = toggle + '<i data-lucide="' + icon + '" class="w-4 h-4 text-primary-400"></i><span class="flex-1 truncate">' + label + '</span>' + addBtn;
    row.addEventListener('click', function (e) {
      if (e.target.closest('.add-child')) { e.stopPropagation(); openAddChild(kind, data); return; }
      if (hasToggle && e.target.closest('.twisty')) { toggleNode(row); return; }
      selectNode(kind, data, row);
    });
    return row;
  }
  function toggleNode(row) {
    var kids = row.querySelector(':scope > .org-children');
    if (!kids) return;
    var open = kids.style.display !== 'none';
    kids.style.display = open ? 'none' : '';
    var tw = row.querySelector(':scope > .twisty');
    if (tw) tw.classList.toggle('open', !open);
  }
  function selectNode(kind, data, row) {
    $$('.org-node').forEach(function (n) { n.classList.remove('selected'); });
    row.classList.add('selected');
    state.selected = { kind: kind, data: data };
    renderDetail(kind, data);
  }
  function filterTree(q) {
    $$('.org-node').forEach(function (n) {
      var txt = n.textContent.toLowerCase();
      n.style.display = !q || txt.indexOf(q) >= 0 ? '' : 'none';
    });
  }

  // ── 详情面板 ────────────────────────────────────────────────────────
  function renderDetail(kind, data) {
    var defs = FIELD_DEFS[kind];
    var rows = defs.filter(function (f) { return f.type !== 'hidden'; }).map(function (f) {
      var v = data[f.k];
      if (f.type === 'select') { var o = (f.opts || []).find(function (x) { return x[0] === v; }); v = o ? o[1] : v; }
      return '<dt class="text-xs text-gray-400">' + f.label + '</dt><dd class="text-sm text-gray-800 font-medium">' + escapeHtml(v == null ? '—' : String(v)) + '</dd>';
    }).join('');
    var canDelete = kind !== 'school' || (data.is_active !== false);
    var panel = '\
      <div class="flex items-center justify-between mb-4">\
        <h3 class="text-base font-bold text-gray-900">' + KIND_LABEL[kind] + '详情</h3>\
        <div class="flex gap-2">\
          <button id="btn-edit" class="px-3 py-1.5 rounded-lg text-xs font-medium text-primary-600 border border-primary-200 hover:bg-primary-50">编辑</button>\
          <button id="btn-del" class="px-3 py-1.5 rounded-lg text-xs font-medium text-danger-700 border border-danger-200 hover:bg-danger-50">删除</button>\
        </div>\
      </div>\
      <dl class="grid grid-cols-2 gap-x-4 gap-y-2.5">' + rows + '</dl>';
    $('#node-detail').innerHTML = panel;
    $('#btn-edit').addEventListener('click', function () { openModal(kind, data, 'edit'); });
    $('#btn-del').addEventListener('click', function () { delNode(kind, data); });
  }

  function openAddChild(parentKind, parentData) {
    if (parentKind === 'school') openModal('grade', { school_id: parentData.id }, 'create');
    else if (parentKind === 'grade') openModal('class', { school_id: parentData.school_id, grade_id: parentData.id }, 'create');
  }

  // ── 弹窗 ────────────────────────────────────────────────────────────
  function openModal(kind, data, mode) {
    var defs = FIELD_DEFS[kind];
    $('#modal-title').textContent = (mode === 'edit' ? '编辑' : '新建') + KIND_LABEL[kind];
    var html = defs.map(function (f) {
      if (f.type === 'hidden') return '<input type="hidden" name="' + f.k + '" value="' + (data ? data[f.k] || '' : '') + '">';
      var val = data && data[f.k] != null ? data[f.k] : '';
      if (f.type === 'select') {
        var opts = (f.opts || []).map(function (o) { return '<option value="' + o[0] + '"' + (o[0] === val ? ' selected' : '') + '>' + o[1] + '</option>'; }).join('');
        return fieldWrap(f, '<select name="' + f.k + '" class="' + inpCls() + '">' + opts + '</select>');
      }
      return fieldWrap(f, '<input name="' + f.k + '" type="' + f.type + '" value="' + escapeAttr(val) + '" placeholder="' + (f.ph || '') + '" class="' + inpCls() + '"' + (f.req ? ' required' : '') + '>');
    }).join('');
    $('#modal-fields').innerHTML = html;
    $('#node-modal').dataset.kind = kind; $('#node-modal').dataset.mode = mode;
    $('#node-modal').dataset.id = (data && data.id) || '';
    $('#node-modal').classList.remove('hidden');
    lucide.createIcons();
  }
  function fieldWrap(f, inner) {
    return '<div><label class="block text-xs text-gray-500 mb-1">' + (f.req ? '<span class="text-danger-500">*</span> ' : '') + f.label + '</label>' + inner + '</div>';
  }
  function inpCls() { return 'w-full text-sm px-3 py-2 rounded-lg border border-gray-200 focus:border-primary-400 focus:ring-2 focus:ring-primary-100 outline-none'; }

  function closeModal() { $('#node-modal').classList.add('hidden'); }

  async function submitNodeForm(e) {
    e.preventDefault();
    var modal = $('#node-modal');
    var kind = modal.dataset.kind, mode = modal.dataset.mode, id = modal.dataset.id;
    var fd = new FormData(e.target);
    var body = {};
    fd.forEach(function (v, k) { body[k] = v; });
    // 类型修正
    (FIELD_DEFS[kind] || []).forEach(function (f) { if (f.type === 'number' && body[f.k] !== '') body[f.k] = Number(body[f.k]); if (f.type === 'number' && body[f.k] === '') delete body[f.k]; });
    try {
      if (mode === 'create') await OrgAPI.create(kind, body);
      else await OrgAPI.update(kind, Number(id), body);
      showNotice('success', KIND_LABEL[kind] + (mode === 'create' ? '已创建' : '已更新'));
      closeModal(); await loadTree();
    } catch (err) { showNotice('danger', '保存失败：' + err.message); }
  }

  async function delNode(kind, data) {
    if (!confirm('确认删除' + KIND_LABEL[kind] + '「' + (data.name) + '」？\n停用可保留数据；硬删将级联清除子节点，且不可恢复。')) return;
    try {
      await OrgAPI.remove(kind, data.id);
      showNotice('success', KIND_LABEL[kind] + '已删除');
      $('#node-detail').innerHTML = '<div class="text-center py-12 text-gray-400 text-sm">点击左侧节点查看详情</div>';
      await loadTree();
    } catch (err) { showNotice('danger', '删除失败：' + err.message); }
  }

  async function loadTree() {
    state.tree = await OrgAPI.getTree();
    renderTree();
    populateClassSelect();
    lucide.createIcons();
  }

  function populateClassSelect() {
    var sel = $('#import-class'); if (!sel) return;
    var opts = '<option value="">（不指定，按文件班级列）</option>';
    (state.tree.grades || []).forEach(function (g) {
      (g.classes || []).forEach(function (c) { opts += '<option value="' + c.id + '">' + g.name + ' · ' + c.name + '</option>'; });
    });
    sel.innerHTML = opts;
  }

  // ── 批量导入 3 步 ───────────────────────────────────────────────────
  function openImport() { resetImport(); $('#import-modal').classList.remove('hidden'); goStep(1); lucide.createIcons(); }
  function closeImport() { $('#import-modal').classList.add('hidden'); }
  function resetImport() { state.importData = null; $('#import-file').value = ''; $('#file-info').classList.add('hidden'); $('#btn-upload').disabled = true; $('#show-errors-only').checked = false; $('#btn-download-errors').classList.add('hidden'); }
  function goStep(n) {
    $$('.import-step').forEach(function (el) { el.classList.add('hidden'); });
    $('#import-step-' + n).classList.remove('hidden');
    $$('.step-dot').forEach(function (d) { var s = +d.dataset.step; d.classList.toggle('active', s === n); d.classList.toggle('done', s < n); });
  }

  function onFileChange(e) {
    var f = e.target.files && e.target.files[0];
    if (!f) return;
    var ok = /\.(xlsx|csv)$/i.test(f.name) && f.size < 5 * 1024 * 1024;
    $('#file-name').textContent = f.name + ' (' + (f.size / 1024).toFixed(1) + ' KB)';
    $('#file-info').classList.remove('hidden');
    $('#btn-upload').disabled = !ok;
    if (!ok) showNotice('warning', '仅支持 .xlsx/.csv 且 < 5MB');
  }

  async function doUpload() {
    var f = $('#import-file').files[0]; if (!f) return;
    $('#btn-upload').disabled = true; $('#btn-upload').textContent = '校验中…';
    try {
      var data = await OrgAPI.uploadStudents(f, $('#import-class').value);
      state.importData = data;
      $('#prev-total').textContent = data.total;
      $('#prev-valid').textContent = data.valid;
      $('#prev-invalid').textContent = data.invalid;
      $('#confirm-count').textContent = data.valid;
      $('#btn-download-errors').classList.toggle('hidden', data.invalid === 0);
      renderPreview();
      goStep(2);
    } catch (err) { showNotice('danger', '上传校验失败：' + err.message); }
    finally { $('#btn-upload').disabled = false; $('#btn-upload').textContent = '上传并校验'; }
  }

  function renderPreview() {
    var data = state.importData; if (!data) return;
    var errsOnly = $('#show-errors-only').checked;
    var body = data.preview.filter(function (r) { return !errsOnly || !r.valid; }).map(function (r) {
      var status = r.valid ? '<span class="text-accent-700">✓ 有效</span>' : '<span class="text-danger-700">✗ ' + escapeHtml(r.reason) + '</span>';
      var nameInput = r.valid
        ? '<span>' + escapeHtml(r.name || '') + '</span>'
        : '<input class="prev-edit text-xs px-2 py-0.5 rounded border border-gray-200 w-20" data-row="' + r.row + '" value="' + escapeAttr(r.name || '') + '" placeholder="修正姓名">';
      var noInput = r.valid
        ? '<span>' + escapeHtml(r.student_no || '') + '</span>'
        : '<input class="prev-edit text-xs px-2 py-0.5 rounded border border-gray-200 w-24" data-row="' + r.row + '" value="' + escapeAttr(r.student_no || '') + '" placeholder="修正学号">';
      return '<tr class="' + (r.valid ? '' : 'bg-danger-50/40') + '"><td class="px-3 py-1.5">' + r.row + '</td><td class="px-3 py-1.5">' + nameInput + '</td><td class="px-3 py-1.5">' + noInput + '</td><td class="px-3 py-1.5">' + escapeHtml(r.class_name || '') + '</td><td class="px-3 py-1.5">' + status + '</td><td class="px-3 py-1.5">' + (r.valid ? '—' : '可编辑') + '</td></tr>';
    }).join('');
    $('#prev-body').innerHTML = body || '<tr><td colspan="6" class="px-3 py-6 text-center text-gray-400">无数据</td></tr>';
  }

  async function doConfirmImport() {
    // 收集用户对错误行的修正
    var data = state.importData;
    $$('.prev-edit').forEach(function (inp) {
      var row = +inp.dataset.row;
      var r = data.preview.find(function (x) { return x.row === row; });
      if (r) { if (inp.placeholder.indexOf('姓名') >= 0) r.name = inp.value; else r.student_no = inp.value; }
    });
    var validRows = data.preview.filter(function (r) { return r.name && r.student_no; });
    try {
      var res = await OrgAPI.confirmImport($('#import-class').value, validRows);
      showResult(true, '导入完成', '成功导入 ' + (res.imported || validRows.length) + ' 名学生。');
      goStep(3);
    } catch (err) { showResult(false, '导入失败', err.message); goStep(3); }
  }

  function showResult(ok, title, desc) {
    $('#result-icon').className = 'w-14 h-14 rounded-full mx-auto flex items-center justify-center mb-3 ' + (ok ? 'bg-accent-50 text-accent-500' : 'bg-danger-50 text-danger-500');
    $('#result-icon').innerHTML = '<i data-lucide="' + (ok ? 'check-circle' : 'x-circle') + '" class="w-8 h-8"></i>';
    $('#result-title').textContent = title;
    $('#result-desc').textContent = desc;
    var data = state.importData;
    $('#result-detail').innerHTML = '共 ' + data.total + ' 行 · 有效 ' + data.valid + ' · 错误 ' + data.invalid + (data.invalid ? '（已跳过）' : '');
    lucide.createIcons();
  }

  function downloadErrorExcel() {
    var data = state.importData; if (!data || !data.errors.length) return;
    // 生成简易错误 Excel（CSV，可被 Excel 打开）
    var csv = '\uFEFF行号,姓名,学号,错误原因\n';
    data.errors.forEach(function (e) { csv += [e.row, '"' + (e.name || '').replace(/"/g, '""') + '"', '"' + (e.student_no || '').replace(/"/g, '""') + '"', '"' + e.reason.replace(/"/g, '""') + '"'].join(',') + '\n'; });
    var blob = new Blob([csv], { type: 'text/csv;charset=utf-8' });
    var a = document.createElement('a'); a.href = URL.createObjectURL(blob); a.download = 'import-errors.csv'; a.click();
    URL.revokeObjectURL(a.href);
  }

  // ── 工具 ────────────────────────────────────────────────────────────
  function showNotice(type, msg) {
    var n = $('#org-notice');
    var cls = { success: 'bg-accent-50 text-accent-700', info: 'bg-primary-50 text-primary-700', warning: 'bg-warm-50 text-warm-700', danger: 'bg-danger-50 text-danger-700' };
    n.className = 'rounded-xl px-4 py-3 text-sm ' + (cls[type] || cls.info);
    n.textContent = msg; n.classList.remove('hidden');
    clearTimeout(n._t); n._t = setTimeout(function () { n.classList.add('hidden'); }, 5000);
  }
  function escapeHtml(s) { return String(s).replace(/[&<>]/g, function (c) { return { '&': '&amp;', '<': '&lt;', '>': '&gt;' }[c]; }); }
  function escapeAttr(s) { return String(s).replace(/"/g, '&quot;'); }
})();
