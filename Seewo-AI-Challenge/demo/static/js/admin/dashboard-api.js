/* ════════════════════════════════════════════════════════════════════
 * Sprint 6 · 看板 API 客户端 + Mock 层
 * 契约见 API_CONTRACT_S6.md。后端 /api/admin/health/* 与 /api/admin/usage
 * 就绪后自动走真实接口；404/网络错误回退 Mock，页面可演示。
 * ════════════════════════════════════════════════════════════════════ */
(function (global) {
  'use strict';

  function csrfToken() {
    var m = document.cookie.match(/(?:^|;\s*)csrf_token=([^;]+)/);
    if (m) return decodeURIComponent(m[1]);
    var el = document.querySelector('input[name="csrf_token"]');
    return el ? el.value : '';
  }
  async function getJSON(url) {
    var res = await fetch(url, { headers: { 'X-CSRF-Token': csrfToken() }, credentials: 'same-origin' });
    if (res.status === 404) { var e = new Error('NOT_FOUND ' + url); e.notFound = true; throw e; }
    var j = await res.json().catch(function () { return {}; });
    if (!res.ok || j.ok === false) throw new Error(j.error || 'HTTP ' + res.status);
    return j.data;
  }
  function delay(v) { return new Promise(function (r) { setTimeout(function () { r(JSON.parse(JSON.stringify(v))); }, 140); }); }

  // ── Mock 生成器 ──────────────────────────────────────────────────────
  function mockUsage(period) {
    var N = period === 'day' ? 24 : period === 'week' ? 7 : 30;
    var chart = [];
    for (var i = N - 1; i >= 0; i--) {
      var gc = 30 + Math.floor(Math.random() * 120);
      chart.push({ label: period === 'day' ? (String(i).padStart(2, '0') + ':00') : ('D-' + i), grading_count: gc, llm_calls: Math.floor(gc * 3.1), active_students: Math.floor(gc * 0.65) });
    }
    var ranking = [
      { school: '默认学校', teacher: '王老师', teacher_id: 3, grading_count: 312, llm_calls: 980, active_students: 86 },
      { school: '默认学校', teacher: '李老师', teacher_id: 4, grading_count: 287, llm_calls: 910, active_students: 79 },
      { school: '默认学校', teacher: '赵老师', teacher_id: 5, grading_count: 203, llm_calls: 640, active_students: 62 },
      { school: '默认学校', teacher: '陈老师', teacher_id: 6, grading_count: 156, llm_calls: 490, active_students: 51 },
      { school: '默认学校', teacher: '刘老师', teacher_id: 7, grading_count: 98, llm_calls: 310, active_students: 38 }
    ];
    var totals = chart.reduce(function (a, c) { a.grading_count += c.grading_count; a.llm_calls += c.llm_calls; a.active_students = Math.max(a.active_students, c.active_students); return a; }, { grading_count: 0, llm_calls: 0, active_students: 0 });
    return delay({ period: period, chart: chart, ranking: ranking, totals: totals });
  }

  function mockSummary() {
    return delay({ cpu: 38 + Math.random() * 30, memory: 55 + Math.random() * 25, disk: 68 + Math.random() * 12, pg_pool: { active: 4 + Math.floor(Math.random() * 8), idle: 8 + Math.floor(Math.random() * 8), max: 50 }, uptime_s: 86400 + Math.floor(Math.random() * 86400), checked_at: new Date().toISOString().slice(0, 19).replace('T', ' ') });
  }
  function mockTrend() {
    var pts = []; for (var i = 23; i >= 0; i--) { var c = 20 + Math.floor(Math.random() * 40); pts.push({ ts: String(i).padStart(2, '0') + ':00', avg_latency_ms: 2200 + Math.floor(Math.random() * 2000), p95_latency_ms: 4200 + Math.floor(Math.random() * 3000), count: c, fail_count: Math.random() < 0.2 ? 1 : 0 }); }
    return delay({ points: pts });
  }
  function mockSuccess() { var t = 1100 + Math.floor(Math.random() * 200), f = 10 + Math.floor(Math.random() * 20); return delay({ rate: (t - f) / t, total: t, failed: f, window: '24h' }); }
  function mockLogs() {
    var its = []; var eps = ['/api/grade/10/5', '/api/ocr/grade', '/api/correction/submit', '/teacher/grade/3']; var roles = ['teacher', 'head_teacher', 'school_admin'];
    for (var i = 0; i < 18; i++) { var s = Math.random() < 0.85 ? 200 : (Math.random() < 0.5 ? 500 : 429); its.push({ ts: '2026-08-01 ' + String(9 + Math.floor(i / 2)).padStart(2, '0') + ':' + String((i * 7) % 60).padStart(2, '0') + ':' + String((i * 3) % 60).padStart(2, '0'), request_id: 'req-' + Math.random().toString(36).slice(2, 10), method: 'POST', endpoint: eps[i % eps.length], status: s, latency_ms: 800 + Math.floor(Math.random() * 5000), user_role: roles[i % roles.length], school_id: 1 }); }
    return delay({ items: its, total: 532, page: 1, size: 20 });
  }
  function mockAlerts() {
    return delay({ items: [
      { ts: '2026-08-01 09:30:00', rule: 'grading_fail_rate', severity: 'warning', message: '批改失败率 6.2% 超阈值 5%', status: 'resolved', resolved_at: '2026-08-01 10:05:00' },
      { ts: '2026-08-01 08:15:00', rule: 'llm_timeout', severity: 'critical', message: 'LLM 超时率 12% 超阈值 10%', status: 'resolved', resolved_at: '2026-08-01 08:42:00' },
      { ts: '2026-07-31 22:10:00', rule: 'http_5xx', severity: 'warning', message: '5xx 错误率 1.3% 超阈值 1%', status: 'resolved', resolved_at: '2026-07-31 22:30:00' }
    ], total: 12, page: 1, size: 20 });
  }

  var DAPI = {
    USE_MOCK: false,
    async usage(period) { try { return await getJSON('/api/admin/usage?period=' + period); } catch (e) { if (e.notFound) { this.USE_MOCK = true; return mockUsage(period); } throw e; } },
    async summary() { try { return await getJSON('/api/admin/health/summary'); } catch (e) { if (e.notFound) { this.USE_MOCK = true; return mockSummary(); } throw e; } },
    async gradingTrend(h) { if (this.USE_MOCK) return mockTrend(); try { return await getJSON('/api/admin/health/grading-trend?hours=' + (h || 24)); } catch (e) { if (e.notFound) { this.USE_MOCK = true; return mockTrend(); } throw e; } },
    async successRate() { if (this.USE_MOCK) return mockSuccess(); try { return await getJSON('/api/admin/health/success-rate'); } catch (e) { if (e.notFound) { this.USE_MOCK = true; return mockSuccess(); } throw e; } },
    async logs(q) { if (this.USE_MOCK) return mockLogs(); try { return await getJSON('/api/admin/health/logs?' + (q || '')); } catch (e) { if (e.notFound) { this.USE_MOCK = true; return mockLogs(); } throw e; } },
    async alerts(q) { if (this.USE_MOCK) return mockAlerts(); try { return await getJSON('/api/admin/health/alerts?' + (q || '')); } catch (e) { if (e.notFound) { this.USE_MOCK = true; return mockAlerts(); } throw e; } }
  };
  global.DashboardAPI = DAPI;
})(window);
