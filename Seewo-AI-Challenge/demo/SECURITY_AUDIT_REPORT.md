# 安全审计报告 — V2.0 Sprint 7 (7.3)

**审计日期**: 2026-07-31
**审计工具**: Bandit 1.8.6
**代码范围**: `demo/` 目录全部 Python 代码 (14,984 LOC)
**基线**: ECS main `d7bfe61`

---

## 审计摘要

| 严重度 | 发现数 | 已修复 | 剩余风险 |
|--------|--------|--------|----------|
| Critical | 0 | 0 | 0 |
| High | 1 | 1 | 0 |
| Medium | 3 | 1 | 2 (已评估，可接受) |
| Low | 710 | — | 信息性，不阻塞 |

**结论**: 所有 High/Critical 级别发现已清零。剩余 2 个 Medium 为已知设计决策，附缓解措施。

---

## 已修复发现

### 1. [HIGH] B701 — Jinja2 autoescape=False

- **文件**: `demo/tests/test_sprint6_frontend.py:26`
- **描述**: `Environment(loader=FileSystemLoader(TEMPLATES_DIR))` 未设置 `autoescape=True`，可能导致 XSS。
- **修复**: 添加 `autoescape=True` 参数。
- **状态**: ✅ 已修复

---

## 已评估剩余风险

### 2. [MEDIUM] B310 — urllib.request.urlopen 审计

- **文件**: `demo/alerting.py:217`, `demo/engine/llm/openai_provider.py:489`
- **描述**: `urllib.request.urlopen` 可能允许 `file://` 或自定义协议。
- **风险评估**: 
  - `alerting.py`: URL 来自环境变量 `ALERT_FEISHU_WEBHOOK`，仅管理员可配置，不接受用户输入。
  - `openai_provider.py`: URL 来自 `LLM_BASE_URL` 环境变量 + allowlist 校验（`engine/llm/allowlist.py`），已限制为已知 LLM API 端点。
- **缓解措施**: 已有 allowlist 校验（V1.0 item 5），环境变量仅运维可配置。
- **状态**: ⚠️ 可接受风险

### 3. [MEDIUM] B104 — 绑定所有接口

- **文件**: `demo/app.py:2098`
- **描述**: `app.run(host=...)` 可能绑定 `0.0.0.0`。
- **风险评估**: 代码已有显式拦截 — `FLASK_HOST=0.0.0.0` 时 `sys.exit(2)`，仅允许 `127.0.0.1`。生产环境使用 gunicorn。
- **缓解措施**: 已有运行时拦截逻辑。
- **状态**: ⚠️ 误报（已有防护）

---

## Low 级别发现统计

| 类别 | 数量 | 说明 |
|------|------|------|
| B404 (import subprocess) | 3 | 仅用于备份脚本，不接收用户输入 |
| B603 (subprocess without shell=True) | 5 | 使用参数列表而非 shell=True，安全 |
| B607 (subsystem partial path) | 2 | 使用 PATH 解析，可接受 |
| B105 (hardcoded password string) | 8 | demo 密码（teacher123 等），仅 demo 模式 |
| B311 (random for security) | 12 | 使用 `random` 而非 `secrets`，但仅用于非安全场景 |
| B408 (import pickle) | 1 | 已审计，不反序列化不可信数据 |
| 其他 | 679 | 信息性，不阻塞 |

---

## 人工审计补充

### SQL 注入检查

- ✅ 所有数据库操作使用 SQLAlchemy ORM 或参数化查询 (`text()` + bind parameters)
- ✅ 未发现 f-string / .format() 拼接 SQL 的代码
- ✅ `db_store.py` 中的查询均使用 ORM `select()` + `where()` 链式调用

### XSS 检查

- ✅ Jinja2 模板默认 `autoescape=True`（Flask 默认配置）
- ✅ 修复了测试文件中的 autoescape=False 问题
- ✅ `|safe` 过滤器使用已审计，仅用于已知安全内容

### 路径遍历检查

- ✅ 文件操作使用 `Path()` + 验证路径前缀
- ✅ 文件上传使用 `secure_filename` 检查
- ✅ 未发现用户输入直接拼接文件路径

### 硬编码密钥检查

- ✅ `SECRET_KEY` 从环境变量读取，有安全默认值
- ✅ `LLM_API_KEY` 从环境变量读取
- ✅ Demo 密码仅用于 demo 模式（DEMO_AUTH_OPEN=1）
- ✅ bcrypt 哈希使用 cost=12

### 不安全反序列化检查

- ✅ `pickle` 导入仅 1 处（`db_store.py`），不用于反序列化不可信数据
- ✅ JSON 反序列化使用 `json.loads()` 安全函数
- ✅ 未发现 `eval()` / `exec()` 调用

---

## 权限最小化审计 (7.2)

### 端点权限收紧清单

| 端点 | 文件 | 旧权限 | 新权限 | 原因 |
|------|------|--------|--------|------|
| DELETE /api/admin/class/<cid> | org_api.py | admin, head, **teacher** | admin, head | 删除班级不应允许 teacher |
| POST /api/admin/import-students | batch_import.py | admin, head, **teacher** | admin, head | 批量导入不应允许 teacher |
| POST /api/admin/import-students/confirm | batch_import.py | admin, head, **teacher** | admin, head | 确认导入不应允许 teacher |
| GET /api/admin/import-students/template | batch_import.py | admin, head, **teacher** | admin, head | 下载导入模板不应允许 teacher |
| DELETE /api/student/<id>/data | app.py | login_required (任何登录用户) | admin | 数据删除仅限管理员 |
| GET /api/student/<id>/export | app.py | login_required (任何登录用户) | admin, head | 数据导出限管理员和组长 |

### 新增 `@min_role("teacher")` 装饰器

- 基于 `ROLE_LEVELS` 字典的角色层级检查
- student (0) < teacher (1) < head (2) < admin (3) < super_admin (4)
- 支持 V2.0 角色别名（admin→school_admin, head→head_teacher）
- 与 `@roles_required` 互补，按最小角色级别而非精确角色匹配

---

*审计人: 全栈代码审查官*
*审计工具版本: bandit 1.8.6*
