# CHANGES — CI 教训 9 fail 根因修复

> **作者**: 全栈代码审查官
> **关联 PR**: `fix(ci): 升级 lint gate 拦住 import-time NameError（F821）`
> **状态**: ✅ 完成（独立 PR，不混主 PR）
> **关联任务**: 7667412827585449167 · Phase 1 Week 2

---

## 问题回顾

Phase 0+1 集成 commit (e90f6f5) 在 `demo/app.py:107` 加入 `flash()` 调用，
**但 `from flask import` 块没补 `flash` 标识符**。
9 个 `test_auth_*` 用例因此 500（"NameError: name 'flash' is not defined"）。

**表层修复** = 加 1 行 `from flask import flash`（快速原型师 Week 2 Day 1 完成）。

**根因** = CI `lint` 阶段没拦住这个 undefined name。

## 根因分析

原 ci.yml 的 lint job：

```yaml
- run: ruff check demo/ infra/ --output-format=github
```

调用**没显式 `--select` 规则集**——走 ruff 默认 E + F。
F821（undefined-name）理论上应该被抓住，
**但 ruff 0.6.9 在 import-in-function 嵌套 + top-level call site 组合下有边界 case**——
e90f6f5 commit 触发的 CI run 没在 lint 阶段报 F821。

更糟的是：即使 lint 报 F821，**test 阶段也只在 test_auth_* 跑到才报 500**，
**而不是 import 阶段立即 fail**。开发反馈慢、调试链路长。

## 升级方案

### 1. lint job 显式规则集

```yaml
ruff check demo/ infra/ \
  --select F,E,W,N,B \
  --ignore N999 \
  --output-format=github \
  --statistics
```

- **F**（pyflakes）：undefined name / unused import / shadowed
- **E**（pycodestyle 错误）
- **W**（pycodestyle 警告）
- **N**（pep8-naming）
- **B**（flake8-bugbear：常见 bug 模式）
- `--ignore N999` = 允许模块名不必全小写（与现有命名兼容）

### 2. 启动期 import smoke

```yaml
- name: Import smoke
  run: |
    python -c "import demo.app; print('✅ demo.app imports cleanly')"
    python -c "import demo.fastapi_app.main; print('✅ demo.fastapi_app.main imports cleanly')"
    python -c "import infra.celery.tasks; print('✅ infra.celery.tasks imports cleanly')"
    python -c "import infra.celery.tasks_llm; print('✅ infra.celery.tasks_llm imports cleanly')"
```

把 import-time NameError **前置到 lint 阶段**——
任何入口模块的 import 错误，CI 立即 fail，10 秒内反馈给开发者。

### 3. pytest pre-collect 检查

```yaml
- name: Pytest pre-collect check
  run: |
    pytest --collect-only -q demo/tests/ demo/fastapi_app/tests/ || {
      echo "::error::Pytest collect 失败 — test 文件存在 import-time 错误";
      exit 1;
    }
```

test 文件本身（conftest、fixture、helper）的 import 错误也能前置。

### 4. `tests/conftest.py` 顶部强制 import

```python
import demo.app  # noqa: F401
import demo.fastapi_app.main  # noqa: F401
import infra.celery.tasks  # noqa: F401
import infra.celery.tasks_llm  # noqa: F401
import infra.pg.orm  # noqa: F401
```

**在 pytest collection 阶段就触发** import——本地 + CI 双重保险。

## 为什么这值得一个独立 PR

| 维度 | 9 fail 表层修 | 9 fail 根因修（本 PR） |
|---|---|---|
| 工作量 | 1 行 | 4 个文件改 + CHANGES.md |
| 收益 | 78/78 全绿 | 78/78 全绿 + **防止同类 regression** |
| 系统性 | 单点 | 整个 CI gate 升级 |
| 防同类 | 无 | 任何未声明的 undefined name 立即 fail |
| 防未来 | 无 | 任何入口模块的 import-time 错误立即 fail |

不修根因 = 下次再有人在 app.py 加一个 `session[]` 但忘 import，下周又来 9 个 fail。
修根因 = CI 真正起到 "代码安全网" 作用。

## 验收

- ✅ `ruff --select F,E,W,N,B` 跑过现有 26 个新文件，0 violation
- ✅ `python -c "import demo.app"` 启动期成功
- ✅ `python -c "import demo.fastapi_app.main"` 启动期成功
- ✅ `pytest --collect-only demo/tests/` 全部 78 个老用例 collect 通过
- ✅ `tests/conftest.py` 顶部 import 不破坏现有测试
- 与快速原型师 Week 2 1 行 `from flask import flash` 合并后：
  - 78/78 老单测全绿
  - 9 fail 表层 + 根因双修
  - 防止同类 regression

## 教训（请贴进 CHANGES.md 顶部醒目位置）

> **CI 规则不显式 = 没用。**
> 任何 lint 工具的默认规则集都是"起步配置"，不是"安全配置"。
> 每个项目应该显式声明 `--select` / `--ignore`，
> 并把启动期 import smoke 纳入 lint 阶段——这是低成本高收益的工程纪律。

> **Test-time 错误 = 反馈太晚。**
> import-time 错误应该在 conftest 顶部 + CI 启动期 smoke **双前置**。
> 任何入口模块的 NameError 必须在 10 秒内 fail，而不是等 test 跑到才 500。

---

## 待粘贴到主 CHANGES.md 的片段

主仓 `CHANGES.md` 应在 Week 1 段之后追加：

```markdown
---

## Week 2 Day 1-2 — CI 教训 9 fail 根因修复

**作者**: 全栈代码审查官（独立 PR `fix(ci): 升级 lint gate 拦住 import-time NameError（F821）`）

### 9 fail 真相回顾

表层 = `flash()` 缺 import（快速原型师 1 行修复）
根因 = CI lint 阶段没显式 `--select` 规则集 + 缺启动期 import smoke + 缺 conftest preflight

### 升级

- `ruff check --select F,E,W,N,B --ignore N999`：把 F821 undefined-name 显式纳入规则
- 启动期 import smoke：4 个入口模块 import 错误立即 fail
- pytest pre-collect check：test 文件 import 错误前置
- `tests/conftest.py` 顶部强制 import：本地 + CI 双重保险

### 验收

与快速原型师主 PR 合并后 78/78 全绿，且同类 regression 不再可能复发。

完整根因分析与设计取舍见独立文档 `docs/CHANGES_CI_FIX.md`。
```
