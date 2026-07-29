# ADR-0001: Phase 1 技术栈选型

- **状态**: 提议（待 队长 确认）
- **日期**: 2026-07-28
- **作者**: 快速原型师
- **适用范围**: C-05（工程底座）+ C-07（CI/CD）

## 背景

Phase 0+1 集成后，单体 Flask + SQLite + 文件 session 已无法支撑：
- 多 worker 并发（gunicorn fork 后内存 session 互相不可见）
- 长任务（LLM 推理、OCR、批量批改）阻塞请求线程
- 真实部署（多人同时使用）的连接数与事务隔离

需要在不破坏现有 28 个路由、78 个单测的前提下，引入生产级底座。

## 决策

### D1 — Web 框架：FastAPI 作为入口，Flask 作为子应用

**选 FastAPI** 的原因：
- 原生 async，与 LLM 异步客户端（httpx / openai async）天然契合
- Pydantic v2 模型即请求/响应校验，少写一层 schema
- 自动 OpenAPI 文档，团队长/PM 可读
- uvicorn 多 worker 模型比 gunicorn sync worker 节省内存

**保留 Flask**（不重写）的原因：
- 现有 28 路由 + 4 个模板（login/dashboard/teacher/student）已稳定
- 重写 = 1.5 人月额外工作（Phase 0 经验：每条路由 0.5 人日）
- WSGIMiddleware 提供「渐进迁移」路径，新功能走 /api/v1/*，老路由保持 /

```
Client → uvicorn (8000)
            ├─ /api/v1/* → FastAPI native（新增）
            └─ /*         → WSGIMiddleware → Flask app（老路由）
```

### D2 — ORM：SQLAlchemy 2.x async + asyncpg

- SQLAlchemy 2.x 的 `DeclarativeBase` + `Mapped[...]` 类型注解比 1.x 的 `Column(...)` 清晰
- asyncpg 是当前 Python 异步 PG 驱动的事实标准，比 aiopg 快 3-5x
- Alembic 与 SQLAlchemy 2.x 兼容良好，迁移脚本可手写也可 autogenerate

**不选 Tortoise / SQLModel 的原因**：Tortoise 生态小、迁移工具弱；SQLModel 是 FastAPI 作者的，但与 Alembic 集成需要 workaround，且团队 SQLAlchemy 经验更通用。

### D3 — 任务队列：Celery 5.x + Redis broker

- LLM 调用、OCR、批量批改天然适合异步（30s+ 任务）
- Celery 5.x 成熟、文档全、与 Redis 集成简单
- **不选 Dramatiq / RQ**：Celery 的 chord/group 在批量批改场景下更顺手，beat 调度也直接内置

**Beat 调度计划**（草案，Week 2 细化）：
- 每日凌晨 3 点：清理过期 session
- 每 5 分钟：扫 `agent_trace` 失败任务，触发重试
- 每小时：聚合班级学情指标到 `analytics_daily`（未来表）

### D4 — 缓存 / Session：Redis 7

- 替代 Flask 内存 session，支持多 worker 共享
- 缓存班级列表、用户信息（减少 PG 查询）
- Celery broker/backend 共用一份 Redis（省一份运维）

**不选 Memcached**：Redis 的数据结构更丰富（sorted set 做排行榜、stream 做事件流），未来扩展友好。

### D5 — 配置：Pydantic v2 Settings

- 类型安全 + 环境变量自动加载 + .env 兼容
- 12-factor 友好
- 启动期配置错误直接抛错，不会带着错误配置跑

### D6 — 容器化：Docker Compose（开发/演示）+ Kubernetes manifest（生产，本期不写）

- Docker Compose：5 个服务（api / pg / redis / worker / beat）一键起
- Kubernetes：Phase 2 或更后，本期 ADR 仅记录选型动机
- 多阶段 Dockerfile：builder 装依赖、runtime 只拷 venv，镜像目标 < 500MB

### D7 — 迁移工具：Alembic

- 与 SQLAlchemy 同生态
- autogenerate 减少手写 DDL
- 迁移脚本纳入版本控制，CI 中自动跑 `alembic upgrade head` 验证

## 后果

### 正面

- FastAPI 异步路径可承载 C-08 真 LLM 接入的流式响应
- Celery 解决长任务阻塞问题
- PG 提供事务隔离，审计日志（audit_log）可保留 1 年
- Redis 7 多 worker session 一致，部署可水平扩展

### 负面 / 风险

- **WSGIMiddleware 性能开销**：约 5-10% 的额外延迟（每请求多一层 ASGI→WSGI 转换）。可接受，Phase 0 单测全过的前提下不算瓶颈。
- **Flask + FastAPI 双框架共存**：团队需要理解两套 API 风格（Flask 用 @app.route + render_template，FastAPI 用 @app.get + JSONResponse）。Week 2 培训 + ADR 文档化。
- **Celery 引入新故障面**：worker 挂了任务不跑、Redis 满了 broker 拒收。需要 Flower 监控（Week 7 CI/CD 一并接入）。

### 兼容性影响

- 现有 `demo/app.py` 580 行代码 0 改动（不动的渐进迁移）
- 现有 78 个单测 0 改动（仍跑 Flask 测试客户端）
- 新 FastAPI 测试走 `httpx.AsyncClient` + `ASGITransport`

## 备选方案（已拒绝）

| 方案 | 拒绝原因 |
|------|----------|
| 全量重写到 FastAPI | 1.5 人月，违反「不爆炸重写」约束 |
| Django 替代 Flask | 学习成本 + 模板渲染风格切换，工作量更大 |
| MongoDB 替代 PG | 团队 SQL 经验浪费，事务支持弱 |
| gRPC / Connect RPC | 浏览器端需额外封装，Phase 1 ROI 低 |

## 关联文档

- `infra/pg/schema.sql` — 4 表 DDL
- `infra/pg/orm.py` — SQLAlchemy 模型
- `docker-compose.yml` — 全栈编排
- ADR-0002（待写）: 认证方案迁移（Flask session → JWT 或 Redis session）
