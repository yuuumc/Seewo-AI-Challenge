# eval/ 评测说明

## 概述

本目录提供「希沃智教π」**golden set 评测骨架**——12 个高质量样本,覆盖 5 种错误类型 + 2 类对抗样本,用于离线验证 LLM provider 的批改质量。

## 文件清单

| 文件 | 作用 |
|---|---|
| `golden_set.json` | 12 条评测样本(10 真实 + 2 对抗) |
| `__init__.py` | loader + schema validator |

## 样本构成

| 样本 ID | 学生 | 题目 | 关键错误类型 | 备注 |
|---|---|---|---|---|
| gs_001 | s01 | q5 | 无(全对) | 优秀档 |
| gs_002 | s02 | q5 | 计算错误 | 配方拆分错 |
| gs_003 | s03 | q5 | 逻辑跳跃 | 漏「完全平方非负」 |
| gs_004 | s04 | q5 | 无(全对) | 优秀档 |
| gs_005 | s05 | q5 | 逻辑跳跃 | 「3(x-a)²≥0」无说明 |
| gs_006 | s01 | q6 | 无(全对) | 优秀档 + 识别陷阱题 |
| gs_007 | s02 | q6 | 概念混淆 | 误判「不单调」需 a |
| gs_008 | s03 | q6 | 未作答 | 写「不会」 |
| gs_009 | s04 | q6 | 无(全对) | 优秀档 + 元认知 |
| gs_010 | s05 | q6 | 表述不严谨 | 「始终为负」模糊 |
| gs_011 | fake | q6 | 注入防护 | prompt injection |
| gs_012 | s03 | q6 | 未作答 | 空白答案 |

**5 种错误类型全部覆盖**:计算错误 / 概念混淆 / 逻辑跳跃 / 未作答 / 表述不严谨

## 验收步骤

```bash
cd Seewo-AI-Challenge/demo
python -c "
from eval import load_golden_set, validate_golden_set, list_samples
g = load_golden_set()
ok, errs = validate_golden_set(g)
print('valid:', ok)
print('errors:', errs)
print('total samples:', len(g['samples']))
print('real_student samples:', len(list_samples(g, kind='real_student')))
print('adversarial samples:', len(list_samples(g, kind='adversarial')))
"
```

期望输出:
```
valid: True
errors: []
total samples: 12
real_student samples: 10
adversarial samples: 2
```

## 后续扩展(Phase 1.5/2)

- **样本扩容**:从 12 条扩到 200+ 条,覆盖更多题目变体(q1-q4 选择填空也加入)
- **多学科**:高中物理/化学/英语也建独立 golden set
- **自动化评测**:`eval/runner.py` 调用 LLM provider 跑全部样本,对比 `expected_analysis` 计算 step 级 precision/recall/error_type F1
- **回归 CI**:prompt 改版前后跑同一 golden set,防止回退

## 关键设计

1. **真实学生作答**:10 条样本全部来自 `demo/data/answers.json` 的 s01-s05 在 q5/q6 的实际作答,**不臆造**。
2. **对抗样本**:2 条覆盖最常见的 LLM 风险点(prompt injection + 空答案)。
3. **schema 严格对齐**:`expected_analysis` 字段名/类型/枚举值与 `engine.grader.grade_long_answer()` 返回值 100% 兼容,LLM 输出可直接喂给前端模板。
4. **可执行的 validator**:`validate_golden_set()` 提供 CI 友好的 schema check,任何字段缺失/枚举越界立即报错。
