# 未成年人学情数据合规清单 · M 级

> 适用范围：希沃智教π AI 智能作业批改系统（V1.0–V1.5）
> 法律依据：《个人信息保护法》《未成年人保护法》《数据安全法》《未成年人网络保护条例》
> 更新时间：2026-07-30 · 责任人：全栈代码审查官

---

## 1. 数据存储位置

| 检查项 | 状态 | 说明 |
|--------|------|------|
| 学情数据存储在境内服务器 | ✅ | ECS 部署于阿里云国内区域，PG 数据库同区域 |
| 无跨境数据传输 | ✅ | 无海外 API 调用；DeepSeek/OpenAI 调用仅传输脱敏文本（题目+答案），不传输学生身份信息 |
| LLM API 调用数据最小化 | ✅ | Sprint 4: student_id 经 HMAC-SHA256 匿名化后进入 LLM payload/trace；日志同步脱敏 |
| 数据库加密 | ⚠️ | PG 使用 postgres:16-alpine，未配置 TDE；建议启用 pgcrypto 或磁盘级加密 |
| 备份策略 | ❌ | 未配置定期备份；建议 pg_dump 定时备份 + 异地存储 |

## 2. 访问控制

| 检查项 | 状态 | 说明 |
|--------|------|------|
| 学生只能访问自己的数据 | ✅ | `check_ownership()` + API 层 student_id 校验，IDOR 防护到位 |
| 教师只能查看本班学生 | ⚠️ | 当前教师可查看所有学生；建议按 class_id 过滤 |
| 管理员权限最小化 | ✅ | admin 角色仅限系统配置，不直接操作学情数据 |
| API 端点均有 @login_required | ✅ | Sprint 3 新增的 /api/correction/* 端点已加 @login_required + @csrf_protect |
| 订正提交权限边界 | ✅ | 学生 A 不能提交学生 B 的订正（POST /api/correction/submit 校验 submission.student_id == current_user.student_id） |
| Rate limiting | ✅ | 订正接口 @rate_limit(max_per_minute=20)，防刷 |

## 3. 日志脱敏

| 检查项 | 状态 | 说明 |
|--------|------|------|
| audit_log 不记录学生答案明文 | ✅ | 日志仅记录 student_id + question_id + 操作类型，不含答案内容 |
| 错误日志不泄露敏感信息 | ✅ | exception 日志记录 traceback，不含 password_hash / session token |
| 访问日志 IP 脱敏 | ⚠️ | Caddy/Nginx 访问日志记录完整 IP；建议对未成年用户 IP 做截断存储（如 192.168.x.0/24） |
| LLM 请求日志 | ✅ | Sprint 4: trace 中 student_id 已匿名化，日志只记录 pseudo_ 前缀的哈希值 |

## 4. 数据出境风险

| 检查项 | 状态 | 说明 |
|--------|------|------|
| OpenAI API 调用（境外） | ⚠️ | 若使用 OpenAI（api.openai.com），数据出境至美国；需学生/家长知情同意 + 数据最小化 |
| DeepSeek API 调用（境内） | ✅ | DeepSeek 为境内服务，无出境风险 |
| Mock 模式无网络请求 | ✅ | OCR_FORCE_MOCK=1 + 无 LLM_API_KEY 时全程本地，零数据外传 |
| 建议 | — | 生产环境默认使用 DeepSeek（境内）；OpenAI 仅用于 A/B 测试，需额外合规审批 |

## 5. 未成年人特殊保护

| 检查项 | 状态 | 说明 |
|--------|------|------|
| 不收集非必要个人信息 | ✅ | 系统仅收集学生 ID、姓名（昵称）、班级、答题数据；不收集手机号/身份证/位置 |
| 家长知情同意机制 | ✅ | Sprint 4: 首次登录展示知情同意页（/consent），未同意前不可提交作业；users 表新增 consent_given 字段；demo 模式可跳过 |
| 数据删除权 | ✅ | Sprint 4: DELETE /api/student/<id>/data 删除 submissions/corrections/analytics；GET /api/student/<id>/export 导出全部数据为 JSON；均 @login_required + 权限校验；JSON+PG 双路径 |
| 最短保留期限 | ⚠️ | 学情数据无自动过期；建议毕业后自动归档/匿名化（如保留 2 年后删除身份关联） |
| 评语内容审查 | ✅ | 情感化评语由 prompt 约束为正面引导，不含负面评价/标签化语言 |
| 订正数据不用于商业目的 | ✅ | 订正数据仅用于学情分析和闭环教学，不共享给第三方 |

## 6. 合规改进优先级

| 优先级 | 事项 | 负责人 | 截止 |
|--------|------|--------|------|
| P0 | 家长知情同意机制（首次登录弹窗） | ✅ 已实现 | Sprint 4 |
| P0 | LLM API 调用 student_id 匿名化 | ✅ 已实现 | Sprint 4 |
| P1 | 数据删除/导出功能（管理员后台） | ✅ 已实现 | Sprint 4 |
| P1 | PG 数据库加密（pgcrypto / 磁盘级） | 全栈开发工程师 | ECS 部署时 |
| P1 | 定期备份策略（pg_dump + 异地） | 全栈开发工程师 | ECS 部署时 |
| P2 | 访问日志 IP 截断存储 | 全栈开发工程师 | Sprint 5 |
| P2 | 学情数据自动过期/归档机制 | 全栈代码审查官 | Sprint 5 |
| P2 | 教师按班级过滤学生数据 | 全栈代码审查官 | Sprint 5 |
