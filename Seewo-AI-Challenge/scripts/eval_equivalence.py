"""s02/q5 等价率评测脚本（C-08 验收）v4.

运行模式
--------

**Mock 自洽性（dry_run 复测）**::

    python scripts/eval_equivalence.py --provider mock

无 LLM_API_KEY（默认）时 ``get_provider()`` 返回 ``MockProvider``。
candidate = provider 层（委托规则引擎），baseline = 直调规则引擎。
两者逐字段一致 → 16/16，证明 provider 层接入链路无回归。
mock 模式**永远**走 fixture-baseline（这是接入完整性检查，不是
准确度测试）。

**真 DeepSeek-Math 等价率（Week 3-4 联调）**::

    export LLM_API_KEY=sk-...
    export LLM_MODEL=deepseek-math
    export LLM_API_MODEL=deepseek-v4-pro    # 必填！见「防假绿」
    python scripts/eval_equivalence.py --provider deepseek-math --json-out /tmp/c08_real.json

判定口径（deepseek 模式）：
    样本带金标（``expected_is_correct/expected_score`` 非 None，来自
    ``tests/s02_q5_data.py`` 内置 fixture 或
    ``tests/s02_q5_gold_calculus.json`` 人工标注）→ **candidate vs
    金标**（``judged_against=gold``）。
    无金标 → candidate vs 规则引擎 fixture（``judged_against=
    fixture``，弱信号——s02/q5 恰是规则引擎弱项，仅作参考）。

防假绿三层防线（v4 新增）
------------------------
背景：``LLM_MODEL=deepseek-math`` 是**逻辑名**，上游 API 不一定认。
若忘设 ``LLM_API_MODEL`` 把逻辑名原样发给上游 → 400 →
OpenAIProvider 契约降级 MockProvider → 输出与 fixture 逐字段一致
→ **假绿 16/16 PASS**，整个验收作废。防线：

    1. 文档：``C08_REWORK_NOTES.md`` + ``.env.example`` 把
       ``LLM_API_MODEL`` 标为 deepseek-math 路径必填；
    2. 启动警告：deepseek 模式下 ``LLM_API_MODEL`` 未设时 stderr
       红字提示（不阻断——私有部署可能真把上游模型命名为
       deepseek-math）；
    3. **运行期硬检测**：每样本传入 TraceCollector，凡 trace 出现
       ``fallback`` stage 即记一次降级。deepseek 模式下只要降级
       数 > 0，整轮判定 INVALID（exit 2），打印降级样本清单——
       宁可 FAIL 不可假绿。

退出码：0 = PASS（等价率 ≥80% 且无降级）；1 = 等价率 <80%；
2 = INVALID（deepseek 模式发生降级 / 配置错误）。
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import sys
from pathlib import Path

# 让脚本可独立跑。两处 sys.path 注入（顺序敏感）：
#   [0] ROOT/tests  —— 让 ``s02_q5_data`` 可被直接 import（绕开
#       demo/tests regular package 与 repo-root tests namespace
#       portion 的 PEP 420 抢名问题，v3 已修）。
#   [1] ROOT/demo   —— 让 ``from engine.X import Y`` 解析到
#       ``demo/engine/X``（与 demo/tests/conftest.py 的路径处理一致）。
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "demo"))
sys.path.insert(0, str(ROOT / "tests"))

# 现在可以 import 了
from engine import grader  # noqa: E402
from engine.llm import TraceCollector, factory as llm_factory  # noqa: E402
from engine.llm.mock_provider import MockProvider  # noqa: E402
from s02_q5_data import (  # noqa: E402
    DATASET_FIXTURE,
    QUESTION_FIXTURE,
    build_dataset,
    load_calculus_gold,
    load_question_from_demo_data,
    load_student_answer_from_demo_data,
    summary as dataset_summary,
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("eval_c08")

PASS_THRESHOLD = 0.8
EXIT_PASS, EXIT_METRIC_FAIL, EXIT_INVALID = 0, 1, 2


# ---------------------------------------------------------------------------
# Provider 解析
# ---------------------------------------------------------------------------
def _resolve_provider(name: str):
    """按 --provider 设 env 变量，强制 factory 重新解析 singleton。"""
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
            # 防线 2：启动警告。不阻断（私有部署可能真用 deepseek-math
            # 作上游模型 id），但运行期 fallback 硬检测（防线 3）会
            # 兜底——忘设导致 400 降级时整轮 INVALID。
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
    """baseline(fixture) = 直调规则引擎（不经 provider 层）。"""
    return grader.grade_long_answer(sa, question, student_id)


def _grade_candidate(
    provider, sa: str, question: dict, student_id: str, trace: TraceCollector
) -> dict:
    """candidate = provider.grade_step（mock 走规则引擎，deepseek 走真 LLM）。

    ``trace`` 必须逐样本新建——fallback 检测依赖 trace 里是否出现
    ``fallback`` stage（OpenAIProvider 契约：降级前记录该 stage）。
    """
    return provider.grade_step(
        question=question,
        student_answer=sa,
        standard_answer=question.get("answer", ""),
        student_id=student_id,
        trace=trace,
    )


def _same_verdict(a: dict, b_is_correct, b_score) -> bool:
    """candidate 与参照（金标或 baseline）的 (is_correct, score) 一致。"""
    return (
        bool(a.get("is_correct")) == bool(b_is_correct)
        and int(a.get("score", -1)) == int(b_score if b_score is not None else -2)
    )


def run(provider_name: str, *, question: dict, dataset: list) -> dict:
    provider = _resolve_provider(provider_name)
    logger.info(
        "provider=%s model=%s question_id=%s n=%d",
        provider_name,
        getattr(provider, "name", "?"),
        question.get("id", "?"),
        len(dataset),
    )

    eq_count = 0
    fallback_count = 0
    gold_judged = 0
    rows = []
    for i, d in enumerate(dataset, 1):
        sa = d["sa"]
        baseline = _grade_baseline(sa, question, "s02")
        trace = TraceCollector("s02", "hw_001")
        try:
            candidate = _grade_candidate(provider, sa, question, "s02", trace)
        except Exception as exc:  # pragma: no cover - 上游 provider 异常
            candidate = {
                "is_correct": False,
                "score": 0,
                "error": f"provider raised: {type(exc).__name__}: {exc}",
            }
        fell_back = any(r.stage == "fallback" for r in trace.records)
        fallback_count += int(fell_back)

        # 判定口径：mock 模式永远 fixture-baseline（接入完整性）；
        # deepseek 模式优先金标（准确度），无金标回落 fixture（弱信号）。
        gold_ic, gold_sc = d.get("expected_is_correct"), d.get("expected_score")
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
            exp_ic, exp_sc = baseline.get("is_correct"), baseline.get("score")

        eq_count += int(eq)
        rows.append(
            {
                "i": i,
                "sa": sa,
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
        "question_id": question.get("id", "?"),
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
            "fixture_judged": n - gold_judged,
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
        f"  C-08 s02/q5 等价率评测 — provider={result['provider']} (model={result['model']})",
        f"  question_id={result['question_id']}  样本={result['n']}  "
        f"等价={result['equivalent_count']}  等价率={result['rate']:.1%}",
        f"  通过阈值: ≥{PASS_THRESHOLD:.0%}  →  {verdict}",
    ]
    if result["provider"] != "mock":
        s = result["summary"]
        lines.append(
            f"  判定口径: gold={s['gold_judged']} 条 / fixture={s['fixture_judged']} 条"
            f"  降级={s['fallback_count']} 条"
        )
    lines.append("=" * 78)
    for r in result["rows"]:
        ok = "✅" if r["equivalent"] else "❌"
        fb = "⚡FALLBACK " if r["fallback"] else ""
        sa = r["sa"] if r["sa"] else "(空白)"
        if len(sa) > 32:
            sa = sa[:29] + "..."
        exp = r["expected"]
        cand = r["candidate"]
        base = r["baseline"]
        lines.append(
            f"  [{r['i']:2d}] {ok} {fb}{r['tier']:16s} "
            f"[{r['judged_against']:7s}] "
            f"exp=({str(exp['is_correct']):5s},{exp['score']}) "
            f"base=({str(base['is_correct']):5s},{base['score']}) "
            f"got=({str(cand.get('is_correct')):5s},{cand.get('score')})"
        )
        lines.append(f"        sa={sa!r}")
    fails = [r for r in result["rows"] if not r["equivalent"]]
    if fails:
        lines.append("")
        lines.append(f"  不等价样本（{len(fails)} 条）：")
        for r in fails:
            sa = r["sa"] if r["sa"] else "(空白)"
            if len(sa) > 30:
                sa = sa[:27] + "..."
            exp = r["expected"]
            cand = r["candidate"]
            lines.append(
                f"    - [{r['i']:2d}] {r['tier']:16s} [{r['judged_against']:7s}] sa={sa!r:32s} "
                f"exp=({exp['is_correct']!s:5s},{exp['score']}) "
                f"got=({cand['is_correct']!s:5s},{cand['score']})"
            )
    fbs = [r for r in result["rows"] if r["fallback"]]
    if fbs:
        lines.append("")
        lines.append(
            f"  🚫 降级样本（{len(fbs)} 条，走 MockProvider 兜底，deepseek 模式下整轮 INVALID）："
        )
        for r in fbs:
            lines.append(f"    - [{r['i']:2d}] {r['tier']}")
        lines.append(
            "  排查：① LLM_API_MODEL 是否设为上游真实模型 id（如 deepseek-v4-pro）；"
            "② LLM_API_KEY 是否有效；③ LLM_BASE_URL 是否可达。"
        )
    lines.append("=" * 78)
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# 入口
# ---------------------------------------------------------------------------
def main() -> int:
    p = argparse.ArgumentParser(description="C-08 s02/q5 等价率评测")
    p.add_argument(
        "--provider",
        choices=["mock", "deepseek-math"],
        default="mock",
        help="mock=dry_run 自洽性；deepseek-math=真模型（需 LLM_API_KEY）",
    )
    p.add_argument(
        "--json-out", default=None, help="可选：把结果以 JSON 写到文件"
    )
    p.add_argument(
        "--force-fixture",
        action="store_true",
        help="跳过 demo-data 加载，强制用内置 fixture（仅沙箱/CI 用）",
    )
    args = p.parse_args()

    # 1) 解析题面 + 数据集
    question = None
    real_answer: str | None = None
    if not args.force_fixture:
        question = load_question_from_demo_data("q5")
        if question is not None:
            real_answer = load_student_answer_from_demo_data("s02", "q5")
            gold = load_calculus_gold()
            logger.info(
                "使用 demo-data 真实题面 s02/q5 + 真实答案（机械变异 16 条）；"
                "calculus 金标 %d/16 已标注",
                len(gold),
            )
    if question is None:
        question = QUESTION_FIXTURE
        if args.provider == "deepseek-math":
            raise SystemExit(
                "ERROR: --provider deepseek-math 需要真实 demo-data "
                "(demo/data/questions.json + answers.json)；当前未找到，"
                "fixture 模式仅供 mock 自洽性。如确需强制，加 --force-fixture。"
            )
        logger.info("未找到 demo-data，使用内置 fixture（仅支持 mock 自洽性）")

    dataset = build_dataset(question, real_answer=real_answer)
    logger.info("dataset: %s", dataset_summary(dataset))

    # 2) 跑评测
    result = run(args.provider, question=question, dataset=dataset)
    print(render(result))

    if args.json_out:
        Path(args.json_out).write_text(
            json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        logger.info("wrote %s", args.json_out)

    if result["invalid"]:
        return EXIT_INVALID
    return EXIT_PASS if result["rate"] >= PASS_THRESHOLD else EXIT_METRIC_FAIL


if __name__ == "__main__":
    raise SystemExit(main())
