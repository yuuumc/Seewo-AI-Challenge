#!/usr/bin/env python3
"""LLM 质量评测脚本 — Sprint 4.

对 correction_grading + emotional_feedback 两个 prompt 各跑 fixture 全集：
  1. 掌握度判定准确率（grade_correction vs CORRECTION_FIXTURES.expected_mastery_level）
  2. 评语特征命中率（generate_emotional_feedback vs
     EMOTIONAL_FEEDBACK_FIXTURES 的 with/without_history_expected_features）

支持 --provider mock|deepseek：
  mock     无需 key，规则引擎 + mock 模板，现在就能跑通
  deepseek 需要 LLM_API_KEY（DeepSeek 新 key 到位后直接可用）

用法:
  cd Seewo-AI-Challenge && python scripts/eval_llm_quality.py --provider mock
  cd Seewo-AI-Challenge && python scripts/eval_llm_quality.py --provider deepseek
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

# 让 demo/ 可被 import（脚本从仓库根运行）
ROOT = Path(__file__).resolve().parent.parent
DEMO = ROOT / "demo"
sys.path.insert(0, str(DEMO))


def _set_provider_env(provider: str) -> None:
    """按 --provider 切换运行环境.

    mock: 清空 LLM_API_KEY → 全程走规则引擎 + mock 模板
    deepseek: 保留/读取现有 LLM_API_KEY；未设置则提示
    """
    if provider == "mock":
        os.environ.pop("LLM_API_KEY", None)
    # deepseek: 不改环境，依赖外部已配置的 key
    # （旧 key sk-a845... 已泄露作废，须由用户新配 key 后再跑）


def eval_correction_grading() -> dict:
    """掌握度判定准确率评测."""
    from engine.correction_grader import grade_correction
    from tests._sprint3_fixtures import CORRECTION_FIXTURES

    total = 0
    correct = 0
    details = []
    for f in CORRECTION_FIXTURES:
        question = {
            "id": f["id"],
            "type": "long_answer",
            "score": f["original_grading"]["max_score"],
            "answer": f.get("question_stem", ""),  # 题干非标准答案，规则引擎靠关键词
            "knowledge": f.get("subject", ""),
            "steps": [],
        }
        # 用 fixture 的 correction_text 跑规则引擎
        result = grade_correction(
            question=question,
            original_answer=f["original_answer"],
            original_result=f["original_grading"],
            correction_text=f["correction_text"],
            student_id="eval",
        )
        expected = f["expected_mastery_level"]
        actual = result["mastery_level"]
        hit = actual == expected
        total += 1
        correct += int(hit)
        details.append({
            "fixture_id": f["id"],
            "expected": expected,
            "actual": actual,
            "hit": hit,
        })
    accuracy = round(correct / total * 100, 1) if total else 0.0
    return {
        "metric": "mastery_accuracy",
        "total": total,
        "correct": correct,
        "accuracy_pct": accuracy,
        "details": details,
    }


def eval_emotional_feedback() -> dict:
    """评语特征命中率评测（有/无历史数据差异化）."""
    from engine.emotional_feedback import (
        generate_emotional_feedback,
        feature_hits,
    )
    from tests._sprint3_fixtures import (
        EMOTIONAL_FEEDBACK_FIXTURES,
        FEEDBACK_QUALITY_RULES,
    )

    groups = []
    total_features = 0
    hit_features = 0
    for g in EMOTIONAL_FEEDBACK_FIXTURES:
        # with_history
        wh = g["with_history"]
        fb_with = generate_emotional_feedback(
            student_id=wh.get("student_name", "eval"),
            current_performance={
                "score": wh["current_score"],
                "max_score": wh["max_score"],
                "is_correct": False,
                "error_types": [],
                "knowledge": "",
            },
            student_history=wh,
        )
        hits_with = feature_hits(fb_with, g.get("with_history_expected_features", []))

        # without_history
        wo = g["without_history"]
        fb_without = generate_emotional_feedback(
            student_id=wo.get("student_name", "eval"),
            current_performance={
                "score": wo["current_score"],
                "max_score": wo["max_score"],
                "is_correct": False,
                "error_types": wo.get("error_types", []),
                "knowledge": "",
            },
            student_history={"has_history": False, "student_name": wo.get("student_name", "eval")},
        )
        hits_without = feature_hits(fb_without, g.get("without_history_expected_features", []))

        for h in (hits_with, hits_without):
            for feat, hit in h.items():
                total_features += 1
                hit_features += int(hit)

        groups.append({
            "fixture_id": g["id"],
            "student_name": g["student_name"],
            "with_history_feedback": fb_with,
            "with_history_hits": hits_with,
            "without_history_feedback": fb_without,
            "without_history_hits": hits_without,
        })

    hit_rate = round(hit_features / total_features * 100, 1) if total_features else 0.0
    return {
        "metric": "feedback_feature_hit_rate",
        "total_features": total_features,
        "hit_features": hit_features,
        "hit_rate_pct": hit_rate,
        "quality_rules": FEEDBACK_QUALITY_RULES,
        "groups": groups,
    }


def check_quality_rules(report: dict) -> list:
    """校验评语长度与禁忌词."""
    issues = []
    rules = report["emotional_feedback"]["quality_rules"]
    forbidden = rules["forbidden_phrases"]
    for g in report["emotional_feedback"]["groups"]:
        for key in ("with_history_feedback", "without_history_feedback"):
            fb = g[key]
            if not fb:
                issues.append(f"{g['fixture_id']}.{key}: 评语为空")
                continue
            if len(fb) < rules["min_length"]:
                issues.append(f"{g['fixture_id']}.{key}: 长度 {len(fb)} < {rules['min_length']}")
            if len(fb) > rules["max_length"]:
                issues.append(f"{g['fixture_id']}.{key}: 长度 {len(fb)} > {rules['max_length']}")
            for phrase in forbidden:
                if phrase in fb:
                    issues.append(f"{g['fixture_id']}.{key}: 含禁忌词「{phrase}」")
    return issues


def run(provider: str) -> dict:
    _set_provider_env(provider)

    if provider == "deepseek" and not os.environ.get("LLM_API_KEY", "").strip():
        print("⚠ DeepSeek 模式需要 LLM_API_KEY 环境变量（新 key 到位后配置）。")
        print("  当前未检测到 key，回退 mock 模式以验证脚本可用性。")
        _set_provider_env("mock")

    print(f"\n=== LLM 质量评测（provider={provider}）===\n")

    corr = eval_correction_grading()
    print(f"[掌握度判定准确率] {corr['correct']}/{corr['total']} = {corr['accuracy_pct']}%")
    if provider == "mock" or not os.environ.get("LLM_API_KEY", "").strip():
        print("  （mock 模式：规则引擎关键词匹配，准确率为基线；"
              "DeepSeek 模式反映 prompt 真实语义质量）")
    for d in corr["details"]:
        mark = "✓" if d["hit"] else "✗"
        print(f"  {mark} {d['fixture_id']}: expected={d['expected']} actual={d['actual']}")

    ef = eval_emotional_feedback()
    print(f"\n[评语特征命中率] {ef['hit_features']}/{ef['total_features']} = {ef['hit_rate_pct']}%")
    for g in ef["groups"]:
        wh_hits = sum(g["with_history_hits"].values())
        wh_total = len(g["with_history_hits"])
        wo_hits = sum(g["without_history_hits"].values())
        wo_total = len(g["without_history_hits"])
        print(f"  {g['fixture_id']} ({g['student_name']}): "
              f"with_history {wh_hits}/{wh_total}, without_history {wo_hits}/{wo_total}")

    report = {
        "provider": provider,
        "correction_grading": corr,
        "emotional_feedback": ef,
    }

    issues = check_quality_rules(report)
    report["quality_issues"] = issues
    if issues:
        print("\n[质量规则校验] 发现 %d 项问题:" % len(issues))
        for it in issues:
            print(f"  - {it}")
    else:
        print("\n[质量规则校验] 全部通过（长度/禁忌词）")

    return report


def main():
    parser = argparse.ArgumentParser(description="LLM 质量评测（correction_grading + emotional_feedback）")
    parser.add_argument(
        "--provider",
        choices=["mock", "deepseek"],
        default="mock",
        help="mock=规则引擎+模板（无需 key）；deepseek=真模型（需 LLM_API_KEY）",
    )
    parser.add_argument(
        "-o", "--output",
        default="",
        help="评测报告 JSON 输出路径（默认不写文件）",
    )
    args = parser.parse_args()

    report = run(args.provider)

    if args.output:
        out = Path(args.output)
        out.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"\n报告已写入: {out}")
    else:
        # 默认落到 artifacts（沙箱内组织，非交付步骤）
        default_out = ROOT / "artifacts" / "eval_llm_quality_report.json"
        default_out.parent.mkdir(parents=True, exist_ok=True)
        default_out.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"\n报告已写入: {default_out}")


if __name__ == "__main__":
    main()
