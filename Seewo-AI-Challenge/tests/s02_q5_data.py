"""s02/q5 等价率评测数据（C-08 验收）。

设计目标
--------
在新架构（demo/engine/llm/ 下的 provider 抽象）下，等价率测试同时承担两个角色：

    1. **Mock 路径自洽性（dry_run 复测）**：baseline = 直接调规则引擎
       ``grader.grade_long_answer``；candidate = 通过
       ``engine.llm.factory.get_provider()``（无 LLM_API_KEY 时返回
       MockProvider）。两者都走同一规则引擎，输出理应一致——**16/16
       通过证明 provider 层的接入链路正确**（shape、字段、异常
       处理都没破）。内容无关。

    2. **真 DeepSeek-Math 等价率（Week 3-4 联调）**：candidate =
       DeepSeekProvider（设 LLM_API_KEY + LLM_MODEL=deepseek-math），
       baseline = MockProvider fixture。两者在同一 (question, sa) 上
       的 ``(is_correct, score)`` 一致率 ≥80% 即为通过。

数据策略
--------
- **有 demo-data 时**（推荐，ECS 上）：从 ``demo/data/questions.json``
  读真实的 s02/q5 题目，从 ``demo/data/answers.json`` 读 s02 的真实答
  案；对真实答案做 15 个机械变异（前后空白、前缀、截断、答非所问
  等），加上原始答案共 16 条。
- **无 demo-data 时**（沙箱/CI）：用内置 ``QUESTION_FIXTURE``（合成一
  元一次方程） + ``DATASET_FIXTURE`` 16 条——仍可跑 mock 自洽性
  16/16。**注意**：用 fixture 跑 ``--provider deepseek-math`` 无意义
  （DeepSeek 答的题与 fixture mock 答的题不是同一道，等价率会被题
  面 mismatch 污染）——eval 脚本此时会明确报错拒绝。
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

# ---------------------------------------------------------------------------
# 内置 fixture（沙箱/CI 兜底用；w2 zip 当时未携带 demo/data/）。
# ---------------------------------------------------------------------------
QUESTION_FIXTURE: Dict[str, Any] = {
    "id": "q5",
    "stem": "解方程 2x + 3 = 11，求 x 的值。",
    "knowledge": "一元一次方程",
    "type": "long_answer",
    "answer": "x = 4",
    "score": 5,
    "steps": [],
}

# 16 条合成学生答案（覆盖 5 档质量分布）
DATASET_FIXTURE: List[Dict[str, Any]] = [
    {"sa": "x = 4", "expected_is_correct": True, "expected_score": 5, "tier": "full"},
    {"sa": "x=4", "expected_is_correct": True, "expected_score": 5, "tier": "full"},
    {"sa": "答案是 x = 4", "expected_is_correct": True, "expected_score": 5, "tier": "full"},
    {"sa": "4", "expected_is_correct": True, "expected_score": 5, "tier": "full"},
    {"sa": "x = 4，因为 2*4+3 = 8+3 = 11，等式成立", "expected_is_correct": True, "expected_score": 5, "tier": "full"},
    {"sa": "2x + 3 = 11，2x = 8，x = 4", "expected_is_correct": True, "expected_score": 5, "tier": "full"},
    {"sa": "x = 4.0", "expected_is_correct": True, "expected_score": 5, "tier": "full"},
    {"sa": "　x = 4　", "expected_is_correct": True, "expected_score": 5, "tier": "full"},
    {"sa": "4 = x", "expected_is_correct": True, "expected_score": 5, "tier": "full"},
    {"sa": "我先移项得 2x = 8，然后 x = 4", "expected_is_correct": True, "expected_score": 5, "tier": "full"},
    {"sa": "2x = 8，所以 x = ?", "expected_is_correct": False, "expected_score": 2, "tier": "partial"},
    {"sa": "解：2x = 11 - 3 = 8", "expected_is_correct": False, "expected_score": 1, "tier": "partial"},
    {"sa": "x = 5", "expected_is_correct": False, "expected_score": 0, "tier": "wrong"},
    {"sa": "x = 3", "expected_is_correct": False, "expected_score": 0, "tier": "wrong"},
    {"sa": "先加再减", "expected_is_correct": False, "expected_score": 0, "tier": "wrong"},
    {"sa": "", "expected_is_correct": False, "expected_score": 0, "tier": "blank"},
]


# ---------------------------------------------------------------------------
# Demo-data 加载 + 真实答案变异
# ---------------------------------------------------------------------------
def _demo_data_dir() -> Path:
    """``demo/data/`` 绝对路径。脚本可独立跑，无需 sys.path。"""
    # this file is tests/s02_q5_data.py; data dir is demo/data/
    return Path(__file__).resolve().parent.parent / "demo" / "data"


def load_question_from_demo_data(qid: str = "q5") -> Optional[Dict[str, Any]]:
    """从 ``demo/data/questions.json`` 读 ``qid`` 题面；不存在返回 None。

    题目 JSON 结构（与 grader.py load_json 一致）：::

        {assignment_id: {"title": ..., "questions": [...]}, ...}

    遍历每个 assignment 的 questions，找 ``id == qid`` 的题返回。
    """
    p = _demo_data_dir() / "questions.json"
    if not p.is_file():
        return None
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return None
    for _aid, blk in data.items():
        if not isinstance(blk, dict):
            continue
        for q in blk.get("questions", []) or []:
            if q.get("id") == qid:
                return q
    return None


def load_student_answer_from_demo_data(
    student_id: str, qid: str, assignment_id: str = "hw_001"
) -> Optional[str]:
    """从 ``demo/data/answers.json`` 读 ``student_id/assignment_id/qid`` 答案。

    结构：``{student_id_assignment_id: {"answers": {qid: text, ...}}}``
    """
    p = _demo_data_dir() / "answers.json"
    if not p.is_file():
        return None
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return None
    key = f"{student_id}_{assignment_id}"
    blk = data.get(key) or {}
    answers = blk.get("answers") or {}
    val = answers.get(qid)
    return val if isinstance(val, str) else None


def _variants_of(
    real: str, correct: str, stem: str
) -> List[Dict[str, Any]]:
    """对真实答案做 15 个机械变异 + 原版 = 16 条；标签均为 None（真模式按 gold / fixture 判定）。"""
    r = real or ""
    c = correct or ""
    s = stem or ""
    items: List[Tuple[str, str]] = [
        (r, "raw"),
        ("  " + r + "  ", "ws_pad"),
        ("答：" + r, "prefix_ans"),
        (r + "。（完）", "suffix_done"),
        ("".join(r.split()), "collapse_ws"),
        (r[: max(1, len(r) // 2)], "trunc_half"),
        ("", "blank"),
        (c, "correct_answer"),
        ("答案：" + c, "correct_prefixed"),
        (r + "\n答：" + c, "hybrid"),
        ("我不会", "refusal"),
        (s, "echo_stem"),
        ("今天天气不错", "irrelevant"),
        ("...", "dots"),
        ("　" + r + "　", "fullwidth_pad"),
        (r + "\n\n" + r, "duplicated"),
    ]
    return [
        {
            "sa": sa,
            "tag": tag,
            "expected_is_correct": None,
            "expected_score": None,
            "tier": "real:" + tag,
        }
        for sa, tag in items
    ]


# ---------------------------------------------------------------------------
# Calculus 变体金标（deepseek 模式的真 baseline）
# ---------------------------------------------------------------------------
GOLD_CALCULUS_PATH = Path(__file__).with_name("s02_q5_gold_calculus.json")


def load_calculus_gold() -> Dict[str, Dict[str, Any]]:
    """读 ``tests/s02_q5_gold_calculus.json``：``{tag: {is_correct, score}}``。

    文件不存在或损坏返回空 dict（对应样本回落到 fixture-baseline 判定，
    并在报表里以 ``judged_against=fixture`` 标出）。金标由人工标注，
    eval 脚本只消费、不生成。
    """
    if not GOLD_CALCULUS_PATH.is_file():
        return {}
    try:
        data = json.loads(GOLD_CALCULUS_PATH.read_text(encoding="utf-8"))
    except Exception:
        return {}
    return {k: v for k, v in data.items() if not k.startswith("_")}


def build_dataset(
    question: Dict[str, Any], real_answer: Optional[str] = None
) -> List[Dict[str, Any]]:
    """组装 16 条样本。

    - ``real_answer`` 非 None：真实 s02 答案 + 15 个机械变异；若
      ``tests/s02_q5_gold_calculus.json`` 里存在对应 tag 的金标，
      把 ``expected_is_correct/expected_score`` 填上（deepseek 模式
      将以金标为 baseline）。
    - ``real_answer`` 为 None：使用 ``DATASET_FIXTURE`` 16 条合成样本
      （自带金标）。
    """
    if real_answer is not None:
        gold = load_calculus_gold()
        rows = _variants_of(real_answer, question.get("answer", ""), question.get("stem", ""))
        for row in rows:
            g = gold.get(row["tag"])
            if g is not None:
                row["expected_is_correct"] = g.get("is_correct")
                row["expected_score"] = g.get("score")
        return rows
    return list(DATASET_FIXTURE)


# ---------------------------------------------------------------------------
# 数据集统计
# ---------------------------------------------------------------------------
def summary(rows: List[Dict[str, Any]]) -> str:
    n = len(rows)
    by_tier: Dict[str, int] = {}
    for r in rows:
        by_tier[r["tier"]] = by_tier.get(r["tier"], 0) + 1
    parts = ", ".join(f"{k}={v}" for k, v in sorted(by_tier.items()))
    return f"dataset: n={n} ({parts})"
