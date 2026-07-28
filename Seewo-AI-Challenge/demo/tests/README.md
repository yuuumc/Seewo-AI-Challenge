# Demo 测试套件

> 快速原型师交付 · 与 leader 安全 PR + 编排工程师 LLM PR 互补

## 1. 设计目标

| 目标 | 实现 |
|---|---|
| demo 模式零环境变量跑通 | `conftest.py` 自动 `os.environ.pop("LLM_API_KEY")` + `FLASK_ENV=production` |
| 集成前不红 | 依赖 leader 集成（`/login` / CSRF / Limiter）的测试 `xfail("TODO(leader-integration)")` |
| 集成后真问题立即暴露 | xfail 用 `strict=False`，集成后这些测试自动跑起来 |
| 不引入重依赖 | 只用 `pytest` / `pytest-flask`，不引入 redis / celery / pytest-cov 等 |

## 2. 测试分层

```
tests/
├── conftest.py              # 共享 fixture：app / client / 集成状态检测 / 演示账号表
├── test_grading_flow.py     # ✅ 不依赖 leader 集成 — 今天就能跑、集成后仍全绿
├── test_auth.py             # ⏸ 依赖 /login + RBAC + /logout — leader 集成后 pass
├── test_security.py         # ⏸ 依赖 CSRFProtect + Limiter + SECRET_KEY — leader 集成后 pass
└── README.md                # 本文件
```

## 3. 跑测试

```bash
# 在 demo/ 目录下
cd Seewo-AI-Challenge/demo

# 装最小依赖（CI workflow 会做）
pip install pytest pytest-flask flask-wtf flask-limiter

# 全跑
pytest tests/ -v

# 只跑不依赖 leader 集成的（即今天就能 pass 的）
pytest tests/test_grading_flow.py -v

# 收集但不跑（CI 烟测 / 排查导入错误）
pytest tests/ --collect-only
```

## 4. 集成状态机

`conftest.py` 暴露的 session-scope fixture：

| fixture | 含义 | True 时 | False 时 |
|---|---|---|---|
| `has_login` | `/login` 路由已注册 | auth 测试正常跑 | 全部 xfail |
| `has_logout` | `/logout` 路由已注册 | logout 测试跑 | xfail |
| `has_csrf_protect` | `flask_wtf.csrf.CSRFProtect(app)` | CSRF 测试跑 | xfail |
| `has_rate_limit` | `flask_limiter.Limiter(app)` | 限流测试跑 | xfail |
| `has_auth_module` | `engine.auth` 模块可 import | 后续可调 SSO helpers | 跳过 |

`test_auth.py` / `test_security.py` 的每个测试**显式**调 `require_integration(...)`，
传入相应 fixture + 中文描述。leader 集成后只要 fixture 返回 True，测试自动激活。

## 5. 演示账号约定

与前端 UI 线 `UI_PATCHES.md` / `CHANGES.md §2` 完全对齐：

| 账号 | 密码 | 角色 |
|---|---|---|
| `teacher` | `teacher123` | teacher |
| `head` | `head123` | head（教研组长） |
| `admin` | `admin123` | admin（信息化主任） |
| `s01` ~ `s05` | `student123` | student |

leader 集成时把账号表直接抄进 `engine.auth` 即可。

## 6. 与其他线的串联

- **编排工程师**：`tests/test_grading_flow.py::test_llm_factory_falls_back_to_mock` 依赖
  `engine.llm.factory.get_provider()`。该 PR 合入前 `pytest.skip`、合入后自动跑
- **提示词工程师**：`golden_set.json` 通过 `engine.eval.golden_set` 可被测试加载，
  由他那条线自带的 `tests/test_prompts_and_eval.py` 覆盖；我们不重复
- **前端 UI 线**：本套件**不**测试 4 个新模板（`login.html` / `errors/404.html` 等），
  由他的 `verify.py` 62 项断言负责；本套件只验证路由 + 错误处理器**注册**了
- **leader**：本套件**不**改 `app.py` / `engine/grader.py` / `templates/` 下任何既有
  文件；全部新增在 `tests/` 下

## 7. 已知未覆盖（留给后续 sprint）

- 并发请求安全（Flask 单进程天然不安全 — 应在 1000+ 学生规模前换 FastAPI+uvicorn）
- 真实 LLM 调用路径（无 key；Prompt 工程师的 golden set 离线评估是主战场）
- OCR 链路（mock_ocr 函数存在但无图片 fixture）
- 性能 / 压测（locust / k6 留 Phase 1.5）

## 8. 排错速查

| 症状 | 原因 |
|---|---|
| `ModuleNotFoundError: No module named 'app'` | cwd 不在 `demo/` 下；从 `demo/` 跑 `pytest` |
| `ImportError: No module named 'flask_wtf'` | 没装 `flask-wtf`；装 `pip install flask-wtf` 或跑 CI workflow |
| 全部 xfail | leader 集成尚未合入 — 这是预期行为 |
| 集成后 `test_login_with_wrong_password` 报 500 | leader 的 `engine.auth.check_password` 抛异常；让他看 traceback |
| `test_app_run_blocking_call_is_safe` 标 skipped | leader 已删 `app.run(...)` 由 gunicorn 接管 — 正确 |
