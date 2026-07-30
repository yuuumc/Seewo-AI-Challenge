"""多学科 golden set mock fixtures（Sprint 1 · 提示词工程师线）。

为 7 个学科/题型各造 1 个 mock 样本，用于验证 prompt 输出格式一致性。
与 eval/golden_set.json（12 条数学 long_answer）互补，这里覆盖：
  math_application / chinese_essay / english_cloze / english_essay
  / physics_short / chemistry_short
（math_calculation 复用 eval/golden_set.json 已有样本，不重复造。）

每个样本的 expected_analysis schema 与 engine.grader.grade_long_answer()
返回值兼容：step_results / error_types / confidence / overall_feedback
/ need_teacher_review。
"""
from __future__ import annotations

# 各学科允许的 error_types 词表（与对应 prompt .md 一致）
ERROR_TYPES_BY_SUBJECT = {
    "math_calculation": frozenset({
        "计算错误", "概念混淆", "逻辑跳跃", "未作答", "表述不严谨",
    }),
    "math_application": frozenset({
        "建模错误", "计算错误", "概念混淆", "逻辑跳跃",
        "单位遗漏", "实际意义忽略", "未作答", "表述不严谨",
    }),
    "chinese_essay": frozenset({
        "偏题", "立意浅", "结构混乱", "论据不当",
        "语言平淡", "语病较多", "字数不足", "未作答",
    }),
    "english_cloze": frozenset({
        "词汇辨析", "上下文逻辑", "语法结构", "固定搭配",
        "词义复现", "未作答",
    }),
    "english_essay": frozenset({
        "内容不全", "结构混乱", "词汇贫乏", "语法错误",
        "拼写错误", "字数不足", "未作答",
    }),
    "physics_short": frozenset({
        "受力分析错误", "状态分析错误", "公式选用错误", "计算错误",
        "单位错误", "方向遗漏", "概念混淆", "未作答", "表述不严谨",
    }),
    "chemistry_short": frozenset({
        "方程式错误", "原理错误", "计算错误", "条件遗漏",
        "配平错误", "现象描述不当", "概念混淆", "未作答", "表述不严谨",
    }),
}

# 6 个 mock 样本（math_calculation 已在 eval/golden_set.json 覆盖，不重复）
MOCK_SAMPLES = [
    {
        "id": "ms_math_app_01",
        "subject_type": "math_application",
        "question_stem": "某厂月产量 x 件，利润 P(x)=-x²+200x-1500，求最大利润及对应产量。",
        "max_score": 10,
        "reference_steps": [
            {"step": 1, "content": "求导 P'(x)=-2x+200"},
            {"step": 2, "content": "令 P'=0 得 x=100"},
            {"step": 3, "content": "P(100)=-10000+20000-1500=8500"},
            {"step": 4, "content": "结论：产量 100 件时最大利润 8500 元"},
        ],
        "student_answer": "P'(x)=-2x+200=0, x=100, P(100)=8000, 最大利润 8000。",
        "expected_analysis": {
            "step_results": [
                {"step": 1, "content": "求导 P'(x)=-2x+200", "correct": True, "comment": "求导正确"},
                {"step": 2, "content": "令 P'=0 得 x=100", "correct": True, "comment": "极值点正确"},
                {"step": 3, "content": "P(100)=-10000+20000-1500=8500", "correct": False,
                 "comment": "代入对但计算错", "error_type": "计算错误", "suggested_fix": "复核负数加法"},
                {"step": 4, "content": "结论：产量 100 件时最大利润 8500 元", "correct": False,
                 "comment": "数值错且漏单位", "error_type": "单位遗漏", "suggested_fix": "修正后补单位"},
            ],
            "error_types": ["计算错误", "单位遗漏"],
            "confidence": 0.85,
            "overall_feedback": "建模与极值点正确，计算失误导致结论错。建议复核负数运算并写单位。",
            "need_teacher_review": False,
        },
    },
    {
        "id": "ms_cn_essay_01",
        "subject_type": "chinese_essay",
        "question_stem": "以「坚持」为题，写一篇不少于 800 字的议论文。",
        "max_score": 60,
        "reference_steps": [
            {"step": 1, "content": "内容（20分）"},
            {"step": 2, "content": "结构（15分）"},
            {"step": 3, "content": "语言（20分）"},
            {"step": 4, "content": "文面（5分）"},
        ],
        "student_answer": "坚持是成功的基石。爱迪生发明电灯试了上千次...（省略 700 字，第二段与第三段缺乏过渡）",
        "expected_analysis": {
            "step_results": [
                {"step": 1, "content": "内容（20分）", "correct": True, "comment": "立意切题，18/20"},
                {"step": 2, "content": "结构（15分）", "correct": False, "comment": "二三段逻辑断裂，10/15",
                 "error_type": "结构混乱", "suggested_fix": "加过渡句承接"},
                {"step": 3, "content": "语言（20分）", "correct": True, "comment": "表达准确，16/20"},
                {"step": 4, "content": "文面（5分）", "correct": True, "comment": "字数达标，5/5"},
            ],
            "error_types": ["结构混乱"],
            "confidence": 0.82,
            "overall_feedback": "立意深刻、论据充实，主要问题在结构断裂。建议训练分论点承接句式。",
            "need_teacher_review": False,
        },
    },
    {
        "id": "ms_en_cloze_01",
        "subject_type": "english_cloze",
        "question_stem": "完形填空（20 空，每空 1.5 分，共 30 分）。文章关于环境保护。",
        "max_score": 30,
        "reference_steps": [
            {"step": 1, "content": "空1: awareness"},
            {"step": 2, "content": "空2: forward to"},
            {"step": 3, "content": "空3: contribution"},
        ],
        "student_answer": "1. awareness  2. forward  3. contribution",
        "expected_analysis": {
            "step_results": [
                {"step": 1, "content": "空1: awareness", "correct": True, "comment": "名词辨析，选对"},
                {"step": 2, "content": "空2: forward to", "correct": False, "comment": "固定搭配漏 to",
                 "error_type": "固定搭配", "suggested_fix": "复习 look forward to doing"},
                {"step": 3, "content": "空3: contribution", "correct": True, "comment": "词义复现，选对"},
            ],
            "error_types": ["固定搭配"],
            "confidence": 0.88,
            "overall_feedback": "3 空答对 2，错误集中在固定搭配。建议系统复习高频动词词组。",
            "need_teacher_review": False,
        },
    },
    {
        "id": "ms_en_essay_01",
        "subject_type": "english_essay",
        "question_stem": "Write a letter to your school newspaper about a volunteer activity (≥80 words).",
        "max_score": 25,
        "reference_steps": [
            {"step": 1, "content": "内容（8分）"},
            {"step": 2, "content": "组织（6分）"},
            {"step": 3, "content": "词汇（5分）"},
            {"step": 4, "content": "语法（4分）"},
            {"step": 5, "content": "文面（2分）"},
        ],
        "student_answer": "Dear editor, I want to tell you about a good volunteer activity. It was good...",
        "expected_analysis": {
            "step_results": [
                {"step": 1, "content": "内容（8分）", "correct": True, "comment": "要点齐全，7/8"},
                {"step": 2, "content": "组织（6分）", "correct": True, "comment": "结构清晰，5/6"},
                {"step": 3, "content": "词汇（5分）", "correct": False, "comment": "反复用 good，3/5",
                 "error_type": "词汇贫乏", "suggested_fix": "用 meaningful/rewarding 替换 good"},
                {"step": 4, "content": "语法（4分）", "correct": True, "comment": "时态正确，3/4"},
                {"step": 5, "content": "文面（2分）", "correct": True, "comment": "字数达标，2/2"},
            ],
            "error_types": ["词汇贫乏"],
            "confidence": 0.85,
            "overall_feedback": "内容齐全、结构清晰，词汇单一。建议积累高级替换表达。",
            "need_teacher_review": False,
        },
    },
    {
        "id": "ms_physics_01",
        "subject_type": "physics_short",
        "question_stem": "质量 m=2kg 的物体用绳悬挂，以 a=2m/s² 加速上升，求绳的拉力 T（g=10m/s²）。",
        "max_score": 10,
        "reference_steps": [
            {"step": 1, "content": "受力分析：重力 mg 向下，拉力 T 向上"},
            {"step": 2, "content": "牛顿第二定律：T-mg=ma"},
            {"step": 3, "content": "代入：T=m(g+a)=2×(10+2)=24N"},
            {"step": 4, "content": "结论：T=24N"},
        ],
        "student_answer": "T-mg=ma, T=m(g+a)=2×(10-2)=16N, 所以 T=16N。",
        "expected_analysis": {
            "step_results": [
                {"step": 1, "content": "受力分析：重力 mg 向下，拉力 T 向上", "correct": True, "comment": "受力分析正确"},
                {"step": 2, "content": "牛顿第二定律：T-mg=ma", "correct": True, "comment": "公式正确"},
                {"step": 3, "content": "代入：T=m(g+a)=2×(10+2)=24N", "correct": False,
                 "comment": "a 的符号代错（应 +a 却 -a）", "error_type": "计算错误",
                 "suggested_fix": "加速上升 a 取正"},
                {"step": 4, "content": "结论：T=24N", "correct": False, "comment": "结论沿用错",
                 "error_type": "计算错误", "suggested_fix": "修正后代回"},
            ],
            "error_types": ["计算错误"],
            "confidence": 0.82,
            "overall_feedback": "受力与公式正确，符号处理失误。建议先规定正方向再代入。",
            "need_teacher_review": False,
        },
    },
    {
        "id": "ms_chem_01",
        "subject_type": "chemistry_short",
        "question_stem": "氢气还原氧化铜，写出化学方程式并计算还原 8g 氧化铜需要氢气的物质的量。",
        "max_score": 10,
        "reference_steps": [
            {"step": 1, "content": "方程式：H₂+CuO=Cu+H₂O（加热）"},
            {"step": 2, "content": "原理：H₂ 还原 CuO，CuO 失氧被还原"},
            {"step": 3, "content": "计算：n(CuO)=m/M=8/80=0.1mol，n(H₂)=n(CuO)=0.1mol"},
            {"step": 4, "content": "结论：需要 H₂ 0.1mol"},
        ],
        "student_answer": "H₂+CuO=Cu+H₂O, n(CuO)=8/80=0.1, 所以需要 0.1mol H₂。",
        "expected_analysis": {
            "step_results": [
                {"step": 1, "content": "H₂+CuO=Cu+H₂O（加热）", "correct": False,
                 "comment": "方程式缺加热条件", "error_type": "条件遗漏",
                 "suggested_fix": "补加热条件或△符号"},
                {"step": 2, "content": "原理：H₂ 还原 CuO", "correct": True, "comment": "原理正确"},
                {"step": 3, "content": "计算：n(CuO)=8/80=0.1mol", "correct": True, "comment": "计算正确"},
                {"step": 4, "content": "结论：需要 H₂ 0.1mol", "correct": True, "comment": "结论正确"},
            ],
            "error_types": ["条件遗漏"],
            "confidence": 0.85,
            "overall_feedback": "原理与计算正确，方程式缺反应条件。建议养成标注条件的习惯。",
            "need_teacher_review": False,
        },
    },
]
