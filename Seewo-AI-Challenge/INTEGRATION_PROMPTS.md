# prompts/ 集成说明(给 Agent 编排工程师 + 队长合入用)

## 概述

本目录提供 3 个 LLM system prompt 的**外部文件化版本**,替代 `engine/llm/openai_provider.py` 里的 3 个 inline 字符串常量。**Provider 接口零变化**——只是把 `_INLINE_PROMPT_*` 改为读文件。

## 文件清单

| 文件 | 作用 | 大小(实际) |
|---|---|---|
| `math_step_grading.md` | 高数大题步骤级批改(含防注入 + 2 few-shot) | ~7 KB |
| `correction_validation.md` | 订正语义校验(替代 V-5 字符串匹配漏洞) | ~5 KB |
| `comment_generation.md` | 苏格拉底式个性化评语(三档) | ~7 KB |
| `__init__.py` | 包入口 + loader API | — |
| `loader.py` | 别名 facade(给 provider 用,可省略) | — |

## 给 Agent 编排工程师(合入 P1)

`openai_provider.py` 里原本应有 3 个 inline 字符串(类似):

```python
_INLINE_PROMPT_MATH_STEP_GRADING = """你是一位资深高中数学教师..."""
_INLINE_PROMPT_CORRECTION_VALIDATION = """你是一位高中数学教研组长..."""
_INLINE_PROMPT_COMMENT_GENERATION = """你是一位善于鼓励的高中数学老师..."""
```

替换为:

```python
from prompts import (
    load_math_step_grading,
    load_correction_validation,
    load_comment_generation,
)

SYSTEM_PROMPT_MATH_STEP_GRADING = load_math_step_grading()
SYSTEM_PROMPT_CORRECTION_VALIDATION = load_correction_validation()
SYSTEM_PROMPT_COMMENT_GENERATION = load_comment_generation()
```

**3 个方法(`grade_step` / `validate_correction` / `generate_comment`)内部把对应的 `SYSTEM_PROMPT_*` 拼到 messages[0] 即可**,其余逻辑不变。

## 给队长(合入 P0)

`prompts/` 和 `eval/` 两个目录均为**新增**,不修改任何既有文件。可直接复制粘贴。

## 设计要点(why)

1. **每条 .md = 一段完整的 system prompt 文本**,不带 frontmatter / wrapper / YAML 头——loader 直接 `read_text()`。这样 .md 既能被人类阅读、也能被机器读取,减少格式转换。
2. **2 个 few-shot 示例**:每条 prompt 都用真实学生数据(s01-s05 的 q5/q6 作答)构造,**不是泛泛的「假设学生写了 X」**——few-shot 来自实际生产数据,降低模型输出 drift。
3. **防注入条款统一在文末**:3 条 prompt 的防注入条款结构一致(`数据/不修改 schema/不放松标准/违规内容中性处理`),便于审计。
4. **错误类型严格枚举**:`计算错误 / 概念混淆 / 逻辑跳跃 / 未作答 / 表述不严谨`——与 `engine.grader._get_suggested_fix()` 的 keys 100% 对齐,前端模板零修改。
5. **JSON schema 严格匹配 `grader.py` 返回值**:
   - `grade_step` → 顶层 5 字段(`step_results / error_types / confidence / overall_feedback / need_teacher_review`)+ step_results 子字段(`step / content / correct / comment / [error_type] / [suggested_fix]`)
   - `validate_correction` → 顶层 5 字段(`is_correct / feedback / loop_closed / diagnosis / confidence`)+ diagnosis 子字段(`identified_original_error / redo_logically_correct / addresses_original_question`)
   - `generate_comment` → 顶层 2 字段(`tier / comment`)

## 验证步骤

```bash
cd Seewo-AI-Challenge/demo
python -c "from prompts import list_prompts; import json; print(json.dumps(list_prompts(), indent=2, ensure_ascii=False))"
```

期望输出(3 条,size_bytes 与文件实际大小一致):
```json
[
  {"name": "math_step_grading", "path": ".../prompts/math_step_grading.md", "size_bytes": "...", "version": "1.0.0"},
  {"name": "correction_validation", "path": ".../prompts/correction_validation.md", "size_bytes": "...", "version": "1.0.0"},
  {"name": "comment_generation", "path": ".../prompts/comment_generation.md", "size_bytes": "...", "version": "1.0.0"}
]
```

## 后续可扩展(留给 Phase 1.5/2)

- 增加 `ocr_recognition.md`(手写体识别 prompt, Phase 2 接入 PaddleOCR 后用)
- 增加 `strategy_recommendation.md`(薄弱点补救策略推荐, Phase 3 用)
- 引入 prompt 版本号在 JSON schema 中(目前 version 在 loader module-level,未来需要在每次 LLM call 时 log 到 trace)
