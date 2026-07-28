# PATCHES.md — `engine/grader.py` 三个挂接点

> **本文件是「给队长（<at id="agent_4knrs833f0b3b28" type="agent">全栈开发工程师</at>）的精确片段清单」**。
> 你的安全 + 工程化重构 PR 在合入时，**按顺序**应用 P1→P2→P3。
> 每段都标了「替换前 / 替换后 / 行号 / 影响面」，可直接复制粘贴。
> **不应用本 PATCHES，engine/llm/ 仍然可独立 import + 测试通过；只有路由层 trace 才会仍走预制 JSON。**

---

## 集成总览

```
engine/llm/        ← 我新加的（已上传 zip）
   __init__.py        公开 API
   base.py            LLMProvider ABC + TraceRecord + TraceCollector
   trace.py           (内联在 base.py)
   mock_provider.py   MockProvider
   openai_provider.py OpenAIProvider (stdlib only)
   factory.py         get_provider / get_runtime_trace / store_trace / reset

grader.py          ← 队长独占，本次 3 个挂接点
   P1 顶部 import      （5 行新增）
   P2 新增 traced 包装 （1 个新函数，约 30 行）
   P3 替换 get_agent_trace body （1 个函数体改写）
```

应用完 P1-P3 后，路由 `/teacher/agent-trace/<id>` 会自动从「读预制 JSON」升级到「先查运行时 trace，没有就降级预制 JSON」——**对前端模板零侵入**（因为 return shape 没变）。

---

## P1：顶部 import 挂接点（5 行新增）

**位置**：`engine/grader.py` 第 7 行（`from pathlib import Path` 之后、空白行之前）

**替换前**（第 1-8 行）：

```python
"""AI grading engine — homework grading with step-level analysis, error classification,
knowledge-point mapping, personalized comments, and multi-agent collaboration traces.
"""

import json
import math
import re
from pathlib import Path
```

**替换后**（在 `from pathlib import Path` 之后插入 5 行）：

```python
"""AI grading engine — homework grading with step-level analysis, error classification,
knowledge-point mapping, personalized comments, and multi-agent collaboration traces.
"""

import json
import math
import re
from pathlib import Path

# LLM provider abstraction (see engine/llm/). Optional dependency: the
# functions in this module continue to work even if the engine.llm
# package is absent (older deployments). The wrappers added by
# ``PATCHES.md`` P2 and P3 guard against that with a try/except.
try:
    from engine.llm import (
        get_provider as _get_llm_provider,
        TraceCollector as _TraceCollector,
        store_trace as _store_trace,
        get_runtime_trace as _get_runtime_trace,
    )
    _LLM_LAYER_AVAILABLE = True
except Exception:  # pragma: no cover - defensive for legacy deploys
    _LLM_LAYER_AVAILABLE = False
```

**影响面**：零。`grader.py` 的 24 个现有函数行为完全不变。`get_provider` 等只在 P2/P3 中使用，所以 `_LLM_LAYER_AVAILABLE` 主要是文档作用，不影响运行时分支。

---

## P2：新增 `grade_long_answer_with_trace` 包装函数（30 行新增）

**位置**：建议加在 `grade_long_answer` 函数定义之后（约第 205 行 `_get_suggested_fix` 之前）。也可放在文件末尾的「Agent Trace」段落里，靠近 `get_agent_trace`。

**替换前**（在 `grade_long_answer` 之后、`_get_suggested_fix` 之前，**插入位置**）：

```python
# (此处直接接 _get_suggested_fix 函数的现有定义)
def _get_suggested_fix(step: dict, error_type: str) -> str:
```

**替换后**（在 `_get_suggested_fix` 之前**插入**以下 30 行）：

```python
def grade_long_answer_with_trace(
    student_answer: str,
    question: dict,
    student_id: str,
    assignment_id: str = "hw_001",
) -> dict:
    """Wrap ``grade_long_answer`` with a real-LLM provider and a runtime trace.

    Behaviour:
        * Returns the same dict shape as ``grade_long_answer`` (drop-in).
        * Routes the call through ``engine.llm.get_provider()``, which
          auto-selects between MockProvider (no env var) and
          OpenAIProvider (``LLM_API_KEY`` set).
        * Records a single :class:`TraceRecord` per call and stores it
          in the in-process trace store so ``get_runtime_trace`` can
          surface it on the agent-trace page.
        * Falls back to the rule engine when the LLM layer is not
          importable (e.g. the older deployment path that doesn't ship
          the engine.llm package).

    This function is the recommended entry point for app.py. It does
    NOT modify the existing ``grade_long_answer`` signature, so
    callers that pass only the three positional args continue to
    compile and run.
    """
    if not _LLM_LAYER_AVAILABLE:
        return grade_long_answer(student_answer, question, student_id)

    provider = _get_llm_provider()
    collector = _TraceCollector(
        student_id=student_id, assignment_id=assignment_id
    )
    result = provider.grade_step(
        question=question,
        student_answer=student_answer,
        standard_answer=question.get("answer", ""),
        student_id=student_id,
        trace=collector,
    )
    _store_trace(collector)
    return result
```

**影响面**：零。**这是新增函数，app.py 现有的 6 处 `grade_long_answer(...)` 调用**保持原样不动**。是否切换由队长在 app.py 集成时决定：
- 最小切换：在 app.py 的 4 个 `grade_long_answer` 调用点改为 `grade_long_answer_with_trace(..., assignment_id="hw_001")`（仅 4 处字符串改动）
- 不切换：现有 demo 继续按原方式工作，新函数是 dead code（无害）

**为什么默认不改 app.py**：app.py 是队长独占；切换会同时触发「加载顺序」+「trace 存储占用」+「JSON dump 大小」三方面问题，应在队长自己的 PR 里处理。

---

## P3：替换 `get_agent_trace` 函数体（4 行改写）

**位置**：`engine/grader.py` 第 509-514 行

**替换前**：

```python
# ── Agent Trace ───────────────────────────────────────────────────────
def get_agent_trace(student_id: str, assignment_id: str) -> dict:
    """Get the multi-agent collaboration trace for a grading task."""
    traces = load_json("agent_traces.json")
    key = f"{student_id}_{assignment_id}"
    return traces.get(key, {"agents": [], "trace": "未找到追踪数据"})
```

**替换后**：

```python
# ── Agent Trace ───────────────────────────────────────────────────────
def get_agent_trace(student_id: str, assignment_id: str) -> dict:
    """Get the multi-agent collaboration trace for a grading task.

    Priority order:
        1. In-process runtime trace (recorded by the LLM provider
           when grade_long_answer_with_trace is used).
        2. Pre-baked JSON in agent_traces.json (legacy fallback so
           the original demo continues to work for users who never
           trigger a real grading flow).
    """
    if _LLM_LAYER_AVAILABLE:
        runtime = _get_runtime_trace(student_id, assignment_id)
        if runtime and runtime.get("agents"):
            return runtime
    traces = load_json("agent_traces.json")
    key = f"{student_id}_{assignment_id}"
    return traces.get(key, {"agents": [], "trace": "未找到追踪数据"})
```

**影响面**：

- 返回 dict 形状不变（`{agents, trace, review_needed, ...}`），所以 `teacher_agent_trace.html` 模板不需要改。
- 仅在「runtime trace 存在且 agents 非空」时升级到 LLM 真 trace；其他场景降级到原行为，**100% 向后兼容**。
- 模板不需要任何改动。

---

## 集成验收清单（队长自测）

应用 P1-P3 后，按顺序执行：

```bash
cd Seewo-AI-Challenge/demo

# 1. import 链路
python -c "from engine import grader; from engine.llm import get_provider; print(get_provider().name)"
# 预期输出: mock

# 2. demo 启动
python app.py    # 浏览器访问 http://localhost:5000 全部页面 OK

# 3. 单测（来自我上传的 tests/test_llm_providers.py）
cd ..
python -m unittest discover -s tests -p "test_llm_providers.py" -v
# 预期: 12/12 OK

# 4. LLM 接入（可选）
export LLM_API_KEY=sk-your-real-key
export LLM_BASE_URL=https://api.deepseek.com/v1
export LLM_MODEL=deepseek-chat
python -c "from engine.llm import get_provider; p=get_provider(); print(type(p).__name__, p.name)"
# 预期: OpenAIProvider deepseek-chat
```

如果第 1 步的 import 失败，说明 P1 没正确插入——请检查 `from engine.llm import (...)` 块是否在 `from pathlib import Path` 之后。

如果第 2 步某个页面 500，最可能是 trace 路径问题——请检查 P3 的 `_LLM_LAYER_AVAILABLE` 条件分支。

如果第 3 步失败，**请把 traceback 贴回评论**，我立刻修。

---

## 风险与未覆盖

1. **未做 trace 持久化**。当前 trace 存在内存，进程重启就丢。Phase 2 再做 PG 落库（与 05 §6 `grading_results.agent_trace` JSONB 对齐）。
2. **未做 trace 大小限制**。单条 trace 上限 ~5KB（学生答案最长 ~1KB + 评语 ~1KB + 元数据），单 session 8 条 = ~40KB，1000 学生并发 = 40MB——**Phase 2 必加 LRU 配额**。
3. **未做评分平均的 PII 脱敏**。`student_name` 原样落 trace；`engine.llm.openai_provider` 的 system prompt 也含 `student_name`。Phase 2 加脱敏中间件。
4. **未做 trace 对外暴露**。`/teacher/agent-trace/<id>` 是当前入口；学生端无入口（合理，trace 是教师工具）。
5. **未触发 LLM 真路径验收**。`test_with_key_returns_openai` 只验证了 provider 类型切换，没真发请求（避免在 CI 里打 fake API）。Phase 1 启动前用真 key 跑一遍 happy path。

---

## 提交后下一步

队长合并我的 PATCHES 后，我会：

1. 等队长回评论，**确认 P1-P3 已合入 main**
2. 在第二阶段（Phase 2）配合 LangGraph 接入，**把 grade_long_answer_with_trace 替换为 LangGraph 状态图节点**（预计 1-2 人周）
3. 增加 `engine.llm/strategies/` 子包，承接 Diagnosis/Strategy 两个 V1.1 规划 Agent（市场报告里 V1.1 优先项）

本轮不收口，**P1-P3 合入 + demo 重启全绿**即视为本线完成。
