"""Sprint 3 订正批改 + 情感化评语 mock fixtures（提示词工程师线）.

包含:
  - CORRECTION_FIXTURES: 订正对比批改 mock 样本（mastered/partial/not_mastered 各 ≥2 条）
  - EMOTIONAL_FEEDBACK_FIXTURES: 情感化评语质量评测对比样本（≥3 组，有/无历史数据差异）
"""
from __future__ import annotations

# ═══════════════════════════════════════════════════════════════════════
# 订正对比批改 mock fixtures
# 每条样本含: id, question_stem, original_answer, original_grading,
# correction_text, expected_mastery_level, expected_analysis
# ═══════════════════════════════════════════════════════════════════════

CORRECTION_FIXTURES = [
    # ── mastered #1: 数学·逻辑跳跃→完整订正 ──
    {
        "id": "cg_mastered_01",
        "subject": "math_calculation",
        "question_stem": "讨论函数 f(x) = x³ - 3ax² + 3a²x (a∈R) 的单调性。",
        "original_answer": "f'(x)=3x²-6ax+3a²=3(x-a)²\n所以单调递增",
        "original_grading": {
            "is_correct": False, "score": 8, "max_score": 12,
            "error_types": ["逻辑跳跃"],
            "step_results": [
                {"step": 1, "correct": True, "comment": "求导正确"},
                {"step": 2, "correct": False, "comment": "未说明 (x-a)²≥0 的理由"},
            ],
        },
        "correction_text": "原答案错在直接写 f'(x)≥0 但没说理由。f'(x)=3(x-a)²,因为完全平方≥0恒成立,所以 f'(x)≥0,因此 f(x) 在 R 上单调递增。",
        "expected_mastery_level": "mastered",
        "expected_analysis": {
            "mastery_level": "mastered",
            "comparison": "原答案配方正确但逻辑跳跃,订正明确指出错因并补全推理链。",
            "encouragement": "你精准定位了原答案的跳跃所在,并用'完全平方非负'补全了推理。",
            "next_steps": "延伸:把 a 取具体值画图验证,体会参数对函数形状的影响。",
            "confidence": 0.92,
        },
    },
    # ── mastered #2: 物理·符号错误→修正+解释 ──
    {
        "id": "cg_mastered_02",
        "subject": "physics_short",
        "question_stem": "质量 m=2kg 的物体以 a=2m/s² 加速上升,求绳的拉力 T(g=10m/s²)。",
        "original_answer": "T=m(g+a)=2×(10-2)=16N",
        "original_grading": {
            "is_correct": False, "score": 6, "max_score": 10,
            "error_types": ["计算错误"],
            "step_results": [
                {"step": 1, "correct": True, "comment": "受力分析正确"},
                {"step": 2, "correct": False, "comment": "a 符号代错,应+a"},
            ],
        },
        "correction_text": "原答案错在加速上升 a 应取正,我代成了负号。T=m(g+a)=2×(10+2)=24N。加速上升时拉力大于重力,所以 a 取正。",
        "expected_mastery_level": "mastered",
        "expected_analysis": {
            "mastery_level": "mastered",
            "comparison": "原答案符号代错,订正修正符号并解释了物理意义。",
            "encouragement": "你不仅改了符号,还说明了'加速上升 a 取正'的物理意义。",
            "next_steps": "练习 3 道加速/减速题,先标正方向再代入。",
            "confidence": 0.90,
        },
    },
    # ── partial #1: 数学·只改结论未解释 ──
    {
        "id": "cg_partial_01",
        "subject": "math_calculation",
        "question_stem": "求 f(x)=x³-3x 的极值。",
        "original_answer": "f'(x)=3x²-3=0, x=±1, 极大值 f(1)=-2",
        "original_grading": {
            "is_correct": False, "score": 5, "max_score": 10,
            "error_types": ["概念混淆"],
            "step_results": [
                {"step": 1, "correct": True, "comment": "求导正确"},
                {"step": 2, "correct": False, "comment": "x=1 是极小值不是极大值"},
            ],
        },
        "correction_text": "f(1)=-2 是极小值, f(-1)=2 是极大值。",
        "expected_mastery_level": "partial",
        "expected_analysis": {
            "mastery_level": "partial",
            "comparison": "订正结论正确但未解释为什么 x=1 是极小值而非极大值。",
            "encouragement": "结论改对了,如果能补充二阶导数或符号分析就更好。",
            "next_steps": "用二阶导数 f''(x) 判断极值性质,练习 3 道题。",
            "confidence": 0.78,
        },
    },
    # ── partial #2: 化学·只补了一处错 ──
    {
        "id": "cg_partial_02",
        "subject": "chemistry_short",
        "question_stem": "写出实验室制取 CO₂ 的化学方程式并指出反应类型。",
        "original_answer": "CaCO₃+HCl=CaCl₂+H₂O+CO₂, 复分解反应",
        "original_grading": {
            "is_correct": False, "score": 6, "max_score": 10,
            "error_types": ["方程式错误", "配平错误"],
            "step_results": [
                {"step": 1, "correct": False, "comment": "方程式未配平, HCl 前应加 2"},
                {"step": 2, "correct": True, "comment": "反应类型判断正确"},
            ],
        },
        "correction_text": "CaCO₃+2HCl=CaCl₂+H₂O+CO₂",
        "expected_mastery_level": "partial",
        "expected_analysis": {
            "mastery_level": "partial",
            "comparison": "订正修正了配平但未说明原配平错误的原因。",
            "encouragement": "配平修正了,如果能说明'为什么需要 2 个 HCl'就更好。",
            "next_steps": "复习化学方程式配平步骤,练习 3 道配平题。",
            "confidence": 0.80,
        },
    },
    # ── not_mastered #1: 空白订正 ──
    {
        "id": "cg_not_mastered_01",
        "subject": "math_calculation",
        "question_stem": "求不定积分 ∫(2x+1)dx。",
        "original_answer": "x²+x",
        "original_grading": {
            "is_correct": False, "score": 4, "max_score": 10,
            "error_types": ["表述不严谨"],
            "step_results": [
                {"step": 1, "correct": False, "comment": "漏写常数 C"},
            ],
        },
        "correction_text": "不会",
        "expected_mastery_level": "not_mastered",
        "expected_analysis": {
            "mastery_level": "not_mastered",
            "comparison": "订正为空白'不会',未回应原批改指出的漏写常数C。",
            "encouragement": "没关系,不定积分的结果需要加常数C,这是基本规则。",
            "next_steps": "复习不定积分定义,重新订正并补上常数C。",
            "confidence": 0.90,
        },
    },
    # ── not_mastered #2: 订正仍错 ──
    {
        "id": "cg_not_mastered_02",
        "subject": "math_application",
        "question_stem": "某厂利润 P(x)=-x²+200x-1500,求最大利润及对应产量。",
        "original_answer": "P'(x)=-2x+200=0, x=100, P(100)=8000",
        "original_grading": {
            "is_correct": False, "score": 6, "max_score": 10,
            "error_types": ["计算错误"],
            "step_results": [
                {"step": 1, "correct": True, "comment": "求导正确"},
                {"step": 2, "correct": True, "comment": "极值点正确"},
                {"step": 3, "correct": False, "comment": "P(100)=-10000+20000-1500=8500, 非 8000"},
            ],
        },
        "correction_text": "P(100)=-10000+20000-1500=8000, 最大利润 8000。",
        "expected_mastery_level": "not_mastered",
        "expected_analysis": {
            "mastery_level": "not_mastered",
            "comparison": "订正仍重复了原计算错误(-10000+20000-1500=8000),实际应等于 8500。",
            "encouragement": "你的求导和找极值点都对了,差在最后一步负数加法。",
            "next_steps": "重新计算 -10000+20000-1500,注意负数加法。",
            "confidence": 0.88,
        },
    },
]


# ═══════════════════════════════════════════════════════════════════════
# 情感化评语质量评测对比样本
# 每组含: 有历史数据 vs 无历史数据 的输入 + 预期评语特征
# 验证"有历史数据 vs 无历史数据"的差异化
# ═══════════════════════════════════════════════════════════════════════

EMOTIONAL_FEEDBACK_FIXTURES = [
    # ── 对比组 1: 有历史 vs 无历史 ──
    {
        "id": "ef_compare_01",
        "student_name": "李明",
        "with_history": {
            "student_name": "李明",
            "current_score": 80,
            "max_score": 100,
            "score_trend": [85, 72, 68, 80],
            "strengths": ["导数求导步骤完整", "配方技巧熟练"],
            "weaknesses": ["逻辑跳跃", "符号计算粗心"],
            "correction_rate": 0.75,
            "correction_mastery": {"mastered": 2, "partial": 1, "not_mastered": 1},
        },
        "without_history": {
            "student_name": "李明",
            "current_score": 80,
            "max_score": 100,
            "note": "首次作业,无历史数据",
        },
        "with_history_expected_features": [
            "引用得分趋势(68→80进步)",
            "引用具体强项(配方步骤)",
            "引用具体弱项(符号计算)",
            "引用订正数据(75%订正率或掌握度)",
        ],
        "without_history_expected_features": [
            "不引用历史数据",
            "基于本次得分(80分)给反馈",
            "语气自然过渡(如'第一次批改')",
        ],
    },
    # ── 对比组 2: 有历史 vs 无历史 ──
    {
        "id": "ef_compare_02",
        "student_name": "张伟",
        "with_history": {
            "student_name": "张伟",
            "current_score": 95,
            "max_score": 100,
            "score_trend": [88, 92, 90, 95],
            "strengths": ["推理严密", "步骤完整"],
            "weaknesses": ["压轴题时间不足"],
            "correction_rate": 1.0,
            "correction_mastery": {"mastered": 4, "partial": 0, "not_mastered": 0},
        },
        "without_history": {
            "student_name": "张伟",
            "current_score": 95,
            "max_score": 100,
            "note": "首次作业,无历史数据",
        },
        "with_history_expected_features": [
            "引用连续上升趋势(88→92→90→95)",
            "引用订正质量(4次全mastered)",
            "针对压轴题时间给具体建议",
        ],
        "without_history_expected_features": [
            "基于本次95分评价",
            "不提及订正历史",
            "建议偏向通用(因无历史可引用)",
        ],
    },
    # ── 对比组 3: 有历史 vs 无历史 ──
    {
        "id": "ef_compare_03",
        "student_name": "王芳",
        "with_history": {
            "student_name": "王芳",
            "current_score": 55,
            "max_score": 100,
            "score_trend": [60, 58, 55, 55],
            "strengths": ["选择题准确率尚可"],
            "weaknesses": ["概念混淆", "未作答"],
            "correction_rate": 0.3,
            "correction_mastery": {"mastered": 0, "partial": 1, "not_mastered": 2},
        },
        "without_history": {
            "student_name": "王芳",
            "current_score": 55,
            "max_score": 100,
            "error_types": ["概念混淆", "未作答"],
            "note": "首次作业,无历史数据",
        },
        "with_history_expected_features": [
            "引用下降趋势(60→55)",
            "引用低订正率(30%)",
            "针对概念混淆给具体复习建议",
            "语气温暖不打击",
        ],
        "without_history_expected_features": [
            "基于本次55分评价",
            "不提及趋势或订正",
            "建议偏向首次作业通用引导",
        ],
    },
]

# 评语质量检查的通用规则（用于自动化校验）
FEEDBACK_QUALITY_RULES = {
    "min_length": 100,
    "max_length": 200,
    "forbidden_phrases": ["你真棒", "继续努力", "加油", "注意审题", "再接再厉"],
    "required_elements": ["具体引用", "温暖语气", "可操作建议"],
}
