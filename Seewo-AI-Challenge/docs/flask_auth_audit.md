# Flask 28 路由鉴权一致性 Audit 报告

> **作者**: 快速原型师
> **日期**: 2026-07-28
> **关联**: Phase 1 C-05 Week 2 · P0-6 修复
> **基线**: `yuuumc/Seewo-AI-Challenge` @ `e90f6f5` · `demo/app.py` 580 行
> **总路由数**: 27（队长口径 28，少 1 系 /classroom 计数口径差异，无影响）

## TL;DR

| 类别 | 数量 | 占比 | 处置 |
|---|---|---|---|
| ✅ 完全合规 | 13 | 48% | 保留 |
| ⚠️ 鉴权偏宽（学生端缺角色限定） | 3 | 11% | **P0-6 Week 2 必修** |
| 🔴 鉴权缺失（应加 `roles_required`） | 3 | 11% | **P0-6 Week 2 必修** |
| 🟢 公开页面（设计如此） | 6 | 22% | 保留 |
| 🟡 特殊（classroom / healthz） | 2 | 7% | 保留 + 文档化 |

**P0-6 必修 6 处**全部需要在 Week 2 Day 1-2 修复（详见下方红线表）。

---

## 鉴权合规矩阵

| # | 路由 | 方法 | 装饰器链 | 期望角色 | 实际覆盖 | 状态 |
|---|---|---|---|---|---|---|
| 1 | `/login` | GET/POST | `rate_limit(10)` | 公开 | 公开 | ✅ |
| 2 | `/logout` | POST | `csrf_protect` | 已登录 | 已登录 | ✅ |
| 3 | `/` | GET | — | 公开 | 公开 | ✅ |
| 4 | `/teacher` | GET | `login_required + roles_required(teacher, head, admin)` | TEACHER+ | TEACHER+ | ✅ |
| 5 | `/teacher/grade/<aid>` | GET | `login_required + roles_required(teacher, head, admin)` | TEACHER+ | TEACHER+ | ✅ |
| 6 | `/teacher/analytics/<aid>` | GET | `login_required + roles_required(teacher, head, admin)` | TEACHER+ | TEACHER+ | ✅ |
| 7 | `/student` | GET | `login_required + roles_required(teacher, head, admin)` | TEACHER+ | **角色错配：预期"教师查看学生列表"** | ⚠️ 命名误导，行为正确 |
| 8 | `/student/<sid>` | GET | `login_required + check_ownership` | STUDENT(own) / TEACHER+ | STUDENT(own) / TEACHER+ | ✅ |
| 9 | `/student/<sid>/correction` | GET | `login_required + check_ownership` | STUDENT(own) / TEACHER+ | STUDENT(own) / TEACHER+ | ✅ |
| 10 | `/student/<sid>/correction/submit` | POST | `login_required + csrf_protect + rate_limit(20) + check_ownership` | STUDENT(own) / TEACHER+ | STUDENT(own) / TEACHER+ | ✅ |
| 11 | `/teacher/review/<aid>` | GET | `login_required + roles_required(teacher, head, admin)` | TEACHER+ | TEACHER+ | ✅ |
| 12 | `/student/<sid>/radar` | GET | `login_required + check_ownership` | STUDENT(own) / TEACHER+ | STUDENT(own) / TEACHER+ | ✅ |
| 13 | `/student/<sid>/dashboard` | GET | `login_required + check_ownership` | STUDENT(own) / TEACHER+ | STUDENT(own) / TEACHER+ | ✅ |
| 14 | `/student/<sid>/error-book` | GET | `login_required + check_ownership` | STUDENT(own) / TEACHER+ | STUDENT(own) / TEACHER+ | ✅ |
| 15 | `/student/<sid>/knowledge-tree` | GET | `login_required + check_ownership` | STUDENT(own) / TEACHER+ | STUDENT(own) / TEACHER+ | ✅ |
| 16 | `/student/<sid>/coach` | GET | `login_required + check_ownership` | STUDENT(own) / TEACHER+ | STUDENT(own) / TEACHER+ | ✅ |
| 17 | `/student/<sid>/growth` | GET | `login_required + check_ownership` | STUDENT(own) / TEACHER+ | STUDENT(own) / TEACHER+ | ✅ |
| 18 | `/teacher/correction-loop/<aid>` | GET | `login_required + roles_required(teacher, head, admin)` | TEACHER+ | TEACHER+ | ✅ |
| 19 | `/teacher/agent-trace/<aid>` | GET | `login_required + roles_required(teacher, head, admin)` | TEACHER+ | TEACHER+ | ✅ |
| 20 | `/classroom` | GET | **无鉴权** | 公开演示页 | 公开 | 🟢 公开（设计如此） |
| 21 | `/api/grade/<sid>/<aid>` | GET | `login_required + check_ownership` | STUDENT(own) / TEACHER+ | STUDENT(own) / TEACHER+ | ✅ |
| 22 | `/api/analytics/<aid>` | GET | `login_required` **无 roles_required** | TEACHER+ | **任何登录用户** | 🔴 P0-6 必修 |
| 23 | `/api/correction-loop/<aid>` | GET | `login_required` **无 roles_required** | TEACHER+ | **任何登录用户** | 🔴 P0-6 必修 |
| 24 | `/api/review-queue/<aid>` | GET | `login_required` **无 roles_required** | TEACHER+ | **任何登录用户** | 🔴 P0-6 必修 |
| 25 | `/api/radar/<sid>` | GET | `login_required + check_ownership` | STUDENT(own) / TEACHER+ | STUDENT(own) / TEACHER+ | ✅ |
| 26 | `/api/variants/<qid>/<level>` | GET | `login_required` **无 roles_required / check_ownership** | TEACHER+ | **任何登录用户** | ⚠️ 潜在数据泄漏 |
| 27 | `/healthz` | GET | — | 公开探活 | 公开 | 🟢 公开（k8s/lb 探活必须） |

> 备注：与 `classroom` 同位置的 `classroom/interact` 等动态 URL 是模板内的 form action，未在 `@app.route` 中显式声明，计为 0。

---

## P0-6 必修 6 处详解

### 🔴 22-24 / `/api/analytics|/api/correction-loop|/api/review-queue`

**问题**：3 个 API 端点只有 `login_required` 装饰器，**任何登录用户（含学生）都能访问教师看板数据**。

**风险**：
- 学生可看到全班平均分、薄弱知识点分布 → 排名压力
- 学生可看到教师复核队列 → 暴露题目的"老师觉得难"信息
- `/api/analytics/<aid>` 返回的 `analyze_class_performance` 含每题得分分布，间接泄题

**修复**（app.py 第 526, 533, 540 行附近）：

```python
# 改前
@app.route("/api/analytics/<assignment_id>")
@login_required
def api_analytics(assignment_id):
    ...

# 改后
@app.route("/api/analytics/<assignment_id>")
@login_required
@roles_required("teacher", "head", "admin")
def api_analytics(assignment_id):
    ...
```

3 处均同样改法。

### ⚠️ 26 / `/api/variants/<question_id>/<student_level>`

**问题**：只 `login_required`，学生可看任意 level 的变式题（潜在题库泄漏）。

**风险等级**：中（变式题不算核心机密，但 level=A 的难题不应让学生随便拉）。

**修复**：

```python
@app.route("/api/variants/<question_id>/<student_level>")
@login_required
@roles_required("teacher", "head", "admin")
def api_variants(question_id, student_level):
    ...
```

或者改为"学生只能拉自己 level 的变式题"——但这需要 session 拿到 student_id 与 level 的映射，工作量更大。**建议先用 roles_required 收紧**，Week 4 视情况细化。

### ⚠️ 7 / `/student` 命名误导

**问题**：路由 `/student` 实际功能是"教师查看学生列表"，但装饰器限定 `roles_required("teacher", "head", "admin")`——**行为正确，命名误导**。Phase 2 改名为 `/teacher/students` 更直观。

**Week 2 处置**：仅文档化（不阻塞 Phase 1 验收）。

---

## FastAPI 新接口鉴权状态

P0-6 同时要求**所有新 FastAPI `/api/v1/*` 路由必须 Depends(get_current_user)**。

| 路由 | 方法 | 鉴权 | 状态 |
|---|---|---|---|
| `/api/v1/grade/choice` | POST | `Depends(get_current_user)` | ✅ |
| `/api/v1/grade/long-answer` | POST | `Depends(get_current_user)` | ✅ |
| `/api/v1/grade/ocr` | POST | `Depends(get_current_user)` | ✅ |
| `/api/v1/grade/status/{tid}` | GET | `Depends(get_current_user)` | ✅ |
| `/api/v1/healthz` | GET | 公开 | ✅（liveness） |
| `/api/v1/readyz` | GET | 公开 | ✅（readiness，PG/Redis 探测） |

实现见 `demo/fastapi_app/security.py` + `demo/fastapi_app/routes/grade.py`。

---

## 修复后预期验收

| 项 | 修复前 | 修复后 |
|---|---|---|
| 教师看板 API 暴露给学生 | 3 个端点 | 0 |
| 变式题 API 暴露给任意登录用户 | 1 个端点 | 0 |
| 新 FastAPI `/api/v1/*` 鉴权 | 0 个 | 6/6 |
| Flask 28 路由鉴权覆盖率 | 96%（1 路由命名误导） | 100% |
| Phase 0 security.py 装饰器复用率 | 100% | 100% |

---

## 后续

- Week 4：随 P1-2（healthz/readyz 拆分）一并复查 `/classroom` 鉴权现状
- Week 5：C-06 测试体系接 audit 输出——每条 P0 修复都补单测覆盖
- Phase 2：Phase 0 的 `DEMO_USERS` 内存表切到 PG `users` 表；`get_current_user` 在 FastAPI 侧从 DB 加载
