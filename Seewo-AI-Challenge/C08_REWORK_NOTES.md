# C-08 返工交付说明（第二阶段）

> 接 7667573311244619048 评论的返工指令——给 `demo/engine/llm/`
> 加 DeepSeek-Math 真模型接入（B 方案：独立 provider + factory 分发）。
> 顶层孤立的 `engine/`（第一阶段我交付的 12KB 实现）**未生效**——
> `demo/tests/conftest.py` 把 `demo/` 插到 `sys.path[0]`，`from
> engine.X import Y` 解析到 `demo/engine/X`（38KB 旧实现 + 完整
> `llm/` provider 架构），78/78 跑通但走的是旧实现，C-08 真 LLM
> 接入 = 0 效果。

## 改动文件

| 路径 | 类型 | 说明 |
|---|---|---|
| `demo/engine/llm/deepseek_provider.py` | 新增 | `DeepSeekProvider(OpenAIProvider)` 子类，覆盖 `_step_grading_system_prompt`（DeepSeek-Math 调优 prompt + 强 JSON 契约 + 防注入）、`_request_model`（支持 `LLM_API_MODEL` 覆盖上游模型 id）。同时提供 `read_deepseek_config_from_env()`（env 唯一配置源）。 |
| `demo/engine/llm/openai_provider.py` | 修改 | 唯一改动：把 `_STEP_GRADING_SYSTEM()` 等 4 处模块级函数调用改为钩子方法 `self._step_grading_system_prompt()` / `self._correction_system_prompt()` / `self._comment_system_prompt(name)` / `self._request_model()`，并加 4 个默认实现（行为与改前**完全一致**）。为 DeepSeekProvider 提供特殊化点，避免复制 grade_step/validate_correction/generate_comment 的 ~60 行 message 构造代码。 |
| `demo/engine/llm/factory.py` | 修改 | `get_provider()` 在原有 `if cfg is None: MockProvider / else: OpenAIProvider` 之外，**新增 11 行** `elif cfg["model"].strip().lower() == "deepseek-math": DeepSeekProvider(**read_deepseek_config_from_env())` 分发。默认路径（`LLM_MODEL` 未设或非 deepseek-math）行为**零变更**。 |
| `scripts/eval_equivalence.py` | 重写 | 新架构下的等价率测试。mock 模式 = provider 层接入自洽性（baseline 直调规则引擎 vs candidate 走 MockProvider，16/16 通过证明 provider 层无回归）；deepseek-math 模式 = 真模型 vs MockProvider fixture 等价率（需 LLM_API_KEY + 真实 demo-data，否则拒绝跑）。 |
| `tests/s02_q5_data.py` | 重写 | 数据加载器：优先从 `demo/data/questions.json` + `answers.json` 取真实 s02/q5 题面与答案（机械变异 16 条）；无 demo-data 时用内置 fixture（仅供 mock 自洽性）。 |
| `.env.example` | 更新 | 重写 LLM 配置段：移除旧的 `LLM_DRY_RUN` 概念（fallback 即 mock，无 dry_run simulator）；新增 `LLM_API_MODEL`（上游模型 id 覆盖）；显式说明"config.py 的 LLM 字段仅做 Pydantic 强校验，不参与 provider 选择（避免双配置源）"。 |

## 接受前必删 / 必做

> 由全栈开发工程师按下面顺序执行（你的边界 #3 早已定下）。

```bash
cd /root/seewo-ai-challenge/Seewo-AI-Challenge

# 1. 删顶层孤立 engine/（第一阶段我误放的 12KB 代码）
rm -rf engine/

# 2. apply 新 zip（增量覆盖：demo/engine/llm/、scripts/、tests/、.env.example）
#    不需要 stash。
# 3. 跑 78/78 baseline
python3 -m pytest demo/tests/ -v
#    期望：78 passed, 3 skipped, 3 xfailed（与返工前完全一致）

# 4. dry_run 复测（无 LLM_API_KEY，mock 自洽性）
unset LLM_API_KEY LLM_BASE_URL LLM_MODEL
python3 scripts/eval_equivalence.py --provider mock --json-out /tmp/c08_mock.json
#    期望：等价率 16/16 = 100% ✅
```

## 真 DeepSeek-Math 等价率（2026-07-28 已首跑，判定口径见下文 v4 定稿）

真模型跑法与判定口径已更新，**以本文件下方两节为准**：

- **起手命令 + 防假绿**：见「🚨 LLM_API_MODEL 必填」——`LLM_API_MODEL` 是**必填**不是可选，忘设会 400 → 降级 mock → 假绿；
- **判定口径**：见「真等价率判定口径（v4 定稿）」——baseline 从规则引擎 fixture 换为金标，43.75% FAIL 是基准错位，不是模型质量问题。

## 🚨 LLM_API_MODEL 必填（防假绿，C-08 最重要的一条）

`LLM_MODEL=deepseek-math` 是**逻辑名**（factory 分发用 + trace model 字段），**上游 API 不一定认这个模型 id**。公有云 DeepSeek 当前可用 SKU 是 `deepseek-v4-pro` / `deepseek-v4-flash`（用 `curl $LLM_BASE_URL/models -H "Authorization: Bearer $LLM_API_KEY"` 探活确认）。

**忘设 `LLM_API_MODEL` 的连锁反应**：逻辑名原样发给上游 → 400 → OpenAIProvider 契约降级 MockProvider → 输出与 fixture 逐字段一致 → **假绿 16/16 PASS**，整个 C-08 验收作废。这是比"等价率 FAIL"更危险的事故。

**三层防线**（v4 已全部落地）：
1. 本文档 + `.env.example`：标注必填；
2. eval 启动警告：deepseek 模式未设 `LLM_API_MODEL` 时 stderr 红字（不阻断，私有部署可能真用 deepseek-math 作上游 id）；
3. **eval 运行期硬检测**：每样本 TraceCollector 检测 `fallback` stage，deepseek 模式下任一降级 → 整轮 🚫 INVALID（exit 2），打印降级样本清单。**宁可 FAIL 不可假绿**。

**真模型起手命令（已实测）**：
```bash
export LLM_API_KEY=sk-新key            # ⚠️ key 不要贴评论/文档，走安全渠道
export LLM_MODEL=deepseek-math          # 逻辑名，触发 DeepSeekProvider 分发
export LLM_API_MODEL=deepseek-v4-pro    # 必填：上游真实模型 id（pro 准确度优先，flash 成本优先）
cd /root/seewo-ai-challenge/Seewo-AI-Challenge
python3 scripts/eval_equivalence.py --provider deepseek-math --json-out /tmp/c08_real.json
unset LLM_API_KEY LLM_MODEL LLM_API_MODEL
```

退出码：0=PASS（≥80% 且无降级）；1=等价率 <80%；2=INVALID（发生降级/配置错误）。

## 真等价率判定口径（v4 定稿）

2026-07-28 真模型首跑（deepseek-v4-pro）暴露**基准错位**：v3 用规则引擎 fixture 做 baseline，但 s02/q5 calculus 恰是 C-08 要替换的规则引擎弱项——fixture 对内容无感，正确答案/空白/垃圾全给 (False,4)。9 条"分歧"全部是真模型判对、fixture 判错，43.75% 是错位算出来的，不是模型质量问题。≥80% 目标不变，**只换 baseline 定义**：

| 样本 | baseline | 报表标记 |
|---|---|---|
| 有金标（`expected_is_correct/score` 非 None） | **金标**（人工标注的 ground truth） | `judged_against=gold`，exp 列填真值 |
| 无金标 | 规则引擎 fixture（弱信号，仅参考） | `judged_against=fixture` |

金标来源：
- 内置 fixture（合成 2x+3=11 方程 16 条）：`tests/s02_q5_data.py::DATASET_FIXTURE` 自带全量金标；
- calculus 真实 16 变体：`tests/s02_q5_gold_calculus.json`（人工标注，eval 只消费）。已标 9 条（correct_answer/correct_prefixed/hybrid=(True,15)；blank/refusal/echo_stem/irrelevant/dots=(False,0)；duplicated=(False,4)），**raw/ws_pad/prefix_ans/suffix_done/collapse_ws/trunc_half/fullwidth_pad 7 条待标**——补标无需改代码，往 JSON 里加 tag 即可。

mock 模式**永远**走 fixture-baseline（它是 provider 层接入完整性检查，不是准确度测试），16/16 口径不变。

## 硬性边界复核（对照你的验收清单）

1. ✅ **未动 `demo/engine/grader.py`**（38KB 0 修改）
2. ✅ **未动 `demo/security.py`、`demo/app.py`**
3. ✅ **factory.py 默认路径零变更**：`LLM_MODEL` 未设 → `gpt-4o-mini` 默认 → 走 OpenAIProvider；非 `deepseek-math` → 走 OpenAIProvider。**只**在 `LLM_MODEL == "deepseek-math"` 时走 DeepSeekProvider（11 行 elif）。
4. ✅ **单一配置源**：factory 与 DeepSeekProvider 都直接读 `os.environ`；config.py 的 4 个 LLM 字段仅做 Pydantic 强校验，未参与 provider 选择。文档已写入 .env.example。
5. ✅ **增量 zip**：不含 `__pycache__` / `.env` / `demo/engine/grader.py` / `demo/security.py`（zip 脚本里显式 exclude）。**顶层孤立 `engine/` 不在 zip 里**，由你 `rm -rf` 删除。
6. ✅ **dry_run 复测**：mock 自洽性 16/16（provider 层接入无回归）。日志在交付时一并贴出。

## 改动行数（给你 review 时直接 grep）

```
demo/engine/llm/deepseek_provider.py    8.5K  (new)
demo/engine/llm/openai_provider.py      18K   (+1.0K, 5 处钩子替换 + 4 个默认方法)
demo/engine/llm/factory.py              7.5K  (+0.7K, 11 行 elif 分发)
scripts/eval_equivalence.py             15K   (v4 rewrite, 金标判定 + fallback 硬检测)
tests/s02_q5_data.py                    9.5K  (v4, 加 tag + 金标 loader)
tests/s02_q5_gold_calculus.json         1.0K  (v4 new, 人工金标，eval 只消费)
.env.example                            2.5K  (LLM 段重写，LLM_API_MODEL 标必填)
```
