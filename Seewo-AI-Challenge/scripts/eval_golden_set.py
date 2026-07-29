"""golden_set 12 条等价率评测脚本（A② 验收）v1.

跟 scripts/eval_equivalence.py (C-08 s02/q5) 平行：同样跑 baseline + candidate
双向对比，同样输出 rate / matched / diverged / gold_judged / fixture_judged / fallback_count，
但 fixture 来自 ``demo/eval/golden_set.json``（12 条真实学生作答 + 对抗样本）而不是
s02/q5 calculus gold。

为什么不直接扩展 eval_equivalence.py？v4 是 16/16 稳定契约，改它风险大；新建独立脚本
保留 v4 不动，golden set 有自己的入口和 review 节奏。

v1 现状
-------
- 12 条样本（10 真实学生 s01-s05 × q5/q6 + 2 对抗 prompt injection + empty）
- step_results → 整题级 is_correct + score 聚合（adapter 策略：all-correct + sum-of-step-scores）
- 跨 q5/q6：每条 sample 带自己 question 字段（不共享单题）
- mock 模式：candidate vs fixture-baseline（接入完整性，**永远** 12/12 fixture 一致）
- deepseek 模式：candidate vs golden（准确度；fallback 触发整轮 INVALID）

v2 路线
-------
- golden_set 扩到 30 题 × 6 变体 = 180 条（v1 是 12 条）
- step_results-aware 评测（细到每步 correct 校验，而不是聚合到整题级）
- 跨周复用：周报接入 rate 趋势图

运行
----
Mock 自洽性::

    python scripts/eval_golden_set.py --provider mock

真 DeepSeek-Math（v4 同样的防假绿三道）::

    export LLM_API_KEY=sk-...
    export LLM_MODEL=deepseek-math
    export LLM_API_MODEL=deepseek-v4-pro    # 必填！忘设会触发 INVALID
    python scripts/eval_golden_set.py --provider deepseek-math --json-out /tmp/gs_real.json

退出码：0 = PASS（等价率 ≥80% 且无降级）；1 = 等价率 <80%；2 = INVALID。
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import sys
from pathlib import Path
from typing import Any

# 让脚本可独立跑。两处 sys.path 注入（与 eval_equivalence.py 同款）：
#   [0] ROOT/demo   —— 让 ``from engine.X import Y`` 解析到 ``demo/engine/X``。
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "demo"))

from engine import grader  # noqa: E402
from engine.llm import TraceCollector, factory as llm_factory  # noqa: E402

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("eval_golden_set")

PASS_THRESHOLD = 0.8
EXIT_PASS, EXIT_METRIC_FAIL, EXIT_INVALID = 0, 1, 2
DEFAULT_GOLDEN_SET = ROOT / "demo" / "eval" / "golden_set.json"


# ---------------------------------------------------------------------------
# Adapter: step_results -> 整题级 is_correct + score
# ---------------------------------------------------------------------------
def aggregate_step_results(sample: dict) -> tuple[bool, int]:
    """把 sample['expected_analysis']['step_results'] 聚合成整题级 is_correct + score。

    策略
    ----
    - is_correct: 全部 step_results[i].correct=True 才算整题对
    - score: sum(reference_steps[i].score) for i where step_results[i].correct=True
    """
    ea = sample.get("expected_analysis", {})
    step_results = ea.get("step_results", [])
    reference_steps = sample.get("reference_steps", [])
    if not step_results:
        raise ValueError(f"sample {sample.get('id')} 缺 step_results")

    is_correct = all(bool(r.get("correct")) for r in step_results)
    score = 0
    for i, r in enumerate(step_results):
        if r.get("correct"):
            if i < len(reference_steps):
                score += int(reference_steps[i].get("score", 0))
            else:
                # 防御：reference_steps 跟 step_results 长度不匹配时，按每步均分
                score += int(sample.get("max_score", 0)) // len(step_results)
    return is_correct, score


def _sample_to_question(sample: dict) -> dict:
    """把 sample 转成 grader / provider 期望的 question dict。

    grader 期望字段（demo/engine/grader.py）：
        question.get("id"), question.get("answer"), question.get("knowledge"),
        question.get("steps") 等
    provider 期望字段：同 + rubric (steps 含 score) 给 deepseek prompt 用
    """
    return {
        "id": sample["question_id"],
        "stem": sample.get("question_stem", ""),
        "answer": "",  # golden set 没给标准答案，留空
        "knowledge": sample.get("knowledge", ""),
        "type": sample.get("question_type", "long_answer"),
        "score": sample.get("max_score", 15),  # grader 期望 question["score"]
        "max_score": sample.get("max_score", 15),  # provider 也可能用 max_score
        "steps": [
            {
                "step": s["step"],
                "content": s["content"],
                "score": s["score"],
            }
            for s in sample.get("reference_steps", [])
        ],
    }


def load_golden_set(path: Path) -> list[dict]:
    """加载 golden_set.json 转成 dataset list（每条带 question/sa/expected/tier）。"""
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)
    samples = data.get("samples", [])
    if not samples:
        raise ValueError(f"{path} 不含 samples")
    dataset = []
    for s in samples:
        is_correct, score = aggregate_step_results(s)
        dataset.append(
            {
                "id": s["id"],
                "question_id": s["question_id"],
                "question": _sample_to_question(s),
                "sa": s.get("student_answer", ""),
                "student_id": s.get("student_id", "anonymous"),
                "tier": s.get("kind", "real_student"),
                "expected_is_correct": is_correct,
                "expected_score": score,
            }
        )
    return dataset


# ---------------------------------------------------------------------------
# Provider 解析
# ---------------------------------------------------------------------------
def _resolve_provider(name: str):
    """按 --provider 设 env 变量，强制 factory 重新解析 singleton。

    跟 eval_equivalence.py 同款（防假绿三道在 v1 也保留：文档 + 启动警告 + 运行期硬检）。
    """
    if name == "mock":
        for k in ("LLM_API_KEY", "LLM_BASE_URL", "LLM_MODEL", "LLM_API_MODEL"):
            os.environ.pop(k, None)
    elif name == "deepseek-math":
        if not os.environ.get("LLM_API_KEY", "").strip():
            raise SystemExit(
                "ERROR: --provider deepseek-math 需要先 export LLM_API_KEY=<key>"
            )
        os.environ["LLM_MODEL"] = "deepseek-math"
        if not os.environ.get("LLM_API_MODEL", "").strip():
            print(
                "\033[31m[WARNING] LLM_API_MODEL 未设置：逻辑名 "
                "'deepseek-math' 将原样发给上游。若上游不识别该模型 id，"
                "请求会 400 并降级 MockProvider（本脚本会将其判为 "
                "INVALID，不会假绿）。公有云 DeepSeek 请设 "
                "LLM_API_MODEL=deepseek-v4-pro（或 deepseek-v4-flash）。"
                "\033[0m",
                file=sys.stderr,
            )
    else:
        raise SystemExit(f"unknown provider: {name}")
    llm_factory.reset_runtime_trace_store()
    return llm_factory.get_provider()


# ---------------------------------------------------------------------------
# 评测主流程
# ---------------------------------------------------------------------------
def _grade_baseline(sa: str, question: dict, student_id: str) -> dict:
    return grader.grade_long_answer(sa, question, student_id)


def _grade_candidate(provider, sa: str, question: dict, student_id: str, trace: TraceCollector) -> dict:
    return provider.grade_step(
        question=question,
        student_answer=sa,
        standard_answer=question.get("answer", ""),
        student_id=student_id,
        trace=trace,
    )


def _same_verdict(a: dict, b_is_correct, b_score) -> bool:
    return (
        bool(a.get("is_correct")) == bool(b_is_correct)
        and int(a.get("score", -1)) == int(b_score if b_score is not None else -2)
    )


def run(provider_name: str, dataset: list[dict]) -> dict:
    provider = _resolve_provider(provider_name)
    logger.info(
        "provider=%s model=%s n=%d", provider_name, getattr(provider, "name", "?"), len(dataset)
    )

    eq_count = 0
    fallback_count = 0
    gold_judged = 0
    fixture_judged = 0
    rows: list[dict[str, Any]] = []
    for i, d in enumerate(dataset, 1):
        sa = d["sa"]
        question = d["question"]
        student_id = d["student_id"]
        baseline = _grade_baseline(sa, question, student_id)
        trace = TraceCollector(student_id, f"gs_{d['question_id']}")
        try:
            candidate = _grade_candidate(provider, sa, question, student_id, trace)
        except Exception as exc:  # pragma: no cover
            candidate = {
                "is_correct": False,
                "score": 0,
                "error": f"provider raised: {type(exc).__name__}: {exc}",
            }
        fell_back = any(r.stage == "fallback" for r in trace.records)
        fallback_count += int(fell_back)

        gold_ic, gold_sc = d["expected_is_correct"], d["expected_score"]
        if provider_name != "mock" and gold_ic is not None:
            eq = _same_verdict(candidate, gold_ic, gold_sc)
            judged = "gold"
            gold_judged += 1
            exp_ic, exp_sc = gold_ic, gold_sc
        else:
            eq = _same_verdict(
                candidate, baseline.get("is_correct"), baseline.get("score")
            )
            judged = "fixture"
            fixture_judged += 1
            exp_ic, exp_sc = baseline.get("is_correct"), baseline.get("score")

        eq_count += int(eq)
        rows.append(
            {
                "i": i,
                "id": d["id"],
                "question_id": d["question_id"],
                "tier": d["tier"],
                "judged_against": judged,
                "fallback": fell_back,
                "expected": {"is_correct": exp_ic, "score": exp_sc},
                "baseline": {
                    "is_correct": baseline.get("is_correct"),
                    "score": baseline.get("score"),
                },
                "candidate": {
                    "is_correct": candidate.get("is_correct"),
                    "score": candidate.get("score"),
                },
                "equivalent": eq,
            }
        )
    n = len(rows)
    rate = eq_count / n if n else 0.0
    invalid = provider_name == "deepseek-math" and fallback_count > 0
    return {
        "provider": provider_name,
        "model": getattr(provider, "name", "?"),
        "n": n,
        "equivalent_count": eq_count,
        "rate": rate,
        "fallback_count": fallback_count,
        "invalid": invalid,
        "summary": {
            "equivalence_rate": rate,
            "total": n,
            "matched": eq_count,
            "diverged": n - eq_count,
            "gold_judged": gold_judged,
            "fixture_judged": fixture_judged,
            "fallback_count": fallback_count,
            "invalid": invalid,
        },
        "rows": rows,
    }


def render(result: dict) -> str:
    verdict = (
        "🚫 INVALID（发生降级，结果作废）"
        if result["invalid"]
        else ("✅ PASS" if result["rate"] >= PASS_THRESHOLD else "❌ FAIL")
    )
    lines = [
        "",
        "=" * 78,
        f"  A② golden_set 12 条等价率评测 — provider={result['provider']} (model={result['model']})",
        f"  样本={result['n']}  等价={result['equivalent_count']}  率={result['rate']*100:.2f}%  "
        f"gold_judged={result['summary']['gold_judged']}  fixture_judged={result['summary']['fixture_judged']}  "
        f"fallback={result['fallback_count']}",
        f"  判定：{verdict}（阈值 {PASS_THRESHOLD*100:.0f}%）",
        "=" * 78,
    ]
    for r in result["rows"]:
        mark = "✓" if r["equivalent"] else "✗"
        c = r["candidate"]
        e = r["expected"]
        b = r["baseline"]
        lines.append(
            f"  {mark} #{r['i']:>2} {r['id']:<22} q={r['question_id']} tier={r['tier']:<13} "
            f"judged={r['judged_against']:<7} "
            f"cand=(ic={int(bool(c['is_correct']))},sc={c['score']}) "
            f"exp=(ic={e['is_correct']!s},sc={e['score']!s}) "
            f"fix=(ic={int(bool(b['is_correct']))},sc={b['score']})"
        )
    lines.append("=" * 78)
    return "\n".join(lines)


def main():
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument(
        "--golden-set",
        default=str(DEFAULT_GOLDEN_SET),
        help=f"golden set 路径（默认 {DEFAULT_GOLDEN_SET}）",
    )
    p.add_argument(
        "--provider",
        choices=["mock", "deepseek-math"],
        default="mock",
        help="LLM provider（mock=规则引擎自洽性；deepseek-math=真模型验证）",
    )
    p.add_argument(
        "--json-out",
        default=None,
        help="把结果 JSON 写到指定路径（默认不写）",
    )
    args = p.parse_args()

    golden_path = Path(args.golden_set)
    if not golden_path.is_absolute():
        golden_path = (Path.cwd() / golden_path).resolve()
    if not golden_path.exists():
        raise SystemExit(f"ERROR: golden set not found: {golden_path}")

    dataset = load_golden_set(golden_path)
    result = run(args.provider, dataset=dataset)
    print(render(result))

    if args.json_out:
        json_path = Path(args.json_out)
        if not json_path.is_absolute():
            json_path = (Path.cwd() / json_path).resolve()
        with open(json_path, "w", encoding="utf-8") as f:
            json.dump(result, f, ensure_ascii=False, indent=2)
        print(f"\nJSON 写到: {json_path}")

    if result["invalid"]:
        return EXIT_INVALID
    if result["rate"] < PASS_THRESHOLD:
        return EXIT_METRIC_FAIL
    return EXIT_PASS


if __name__ == "__main__":
    sys.exit(main())
