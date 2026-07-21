# 08 Demo 说明

## 运行方式

```bash
cd demo
pip install flask
python app.py
# → http://localhost:5000
```

Windows 用户也可双击 `demo\start.bat`。

---

## Demo 结构

```
demo/
├── app.py                       # Flask 主应用（20+ 路由）
├── start.bat / start.sh         # 启动脚本
├── requirements.txt
├── engine/
│   └── grader.py                # 模拟AI引擎（批改/订正验证/知识雷达/学情聚合/Agent追踪/Math Coach）
├── data/
│   ├── questions.json           # 题库（6题：2选择+2填空+2解答题）
│   ├── students.json            # 5名学生
│   ├── answers.json             # 5人×6题预设作答（覆盖5种错误类型）
│   ├── corrections.json         # 订正记录（含AI验证结果）
│   ├── variants.json            # 变式题（每道错题3档难度×3题）
│   ├── agent_traces.json        # 多Agent决策轨迹
│   ├── knowledge_tree.json      # 知识树结构
│   ├── student_dashboard.json   # 学生首页数据
│   ├── growth_report.json       # 成长报告数据
│   └── math_coach.json          # Math Coach对话场景
├── templates/                   # 18个模板
│   ├── index.html               # 首页·角色选择+创新亮点卡片
│   ├── base.html                # 基础布局
│   │
│   ├── 教师端 (6页)
│   │   ├── teacher_dashboard.html      # 作业管理
│   │   ├── teacher_grade.html          # AI批改详情（步骤级分析）
│   │   ├── teacher_review.html         # AI低置信度复核队列
│   │   ├── teacher_correction.html     # 订正闭环看板
│   │   ├── teacher_agent_trace.html    # 多Agent决策追踪
│   │   └── teacher_analytics.html      # 学情仪表盘
│   │
│   ├── 学生端 (7页)
│   │   ├── student_dashboard.html      # 学习首页 (Today Dashboard)
│   │   ├── student_error_book.html     # AI错题本（根因分析+知识链）
│   │   ├── student_knowledge_tree.html # 知识树（颜色=掌握度）
│   │   ├── student_coach.html          # Math Coach（苏格拉底式）
│   │   ├── student_growth.html         # 成长报告（趋势+AI预测）
│   │   ├── student_correction.html     # 订正练习（变式题分层推送）
│   │   └── student_radar.html          # 知识雷达图（SVG）
│   │
│   ├── 其他
│   │   ├── student_list.html           # 学生选择页
│   │   ├── student_view.html           # 旧版批改详情（保留）
│   │   └── classroom.html              # 课堂互动（师生联动）
│   │
│   └── static/css/style.css
```

---

## 演示路径

### 路径A：教师视角（核心竞争力演示）

| 步骤 | 页面 | 看点 |
|------|------|------|
| 1 | 首页 →「教师端演示」 | — |
| 2 | 教师Dashboard | 作业概览、题目列表、知识点覆盖 |
| 3 | 批改详情 `/teacher/grade/hw_001` | **步骤级分析**：Q5/Q6的逐步骤正误标注、错因分类、AI评语 |
| 4 | AI复核队列 `/teacher/review/hw_001` | **智教π独有**：按置信度从低到高排序，标记~15%需教师复核的判定 |
| 5 | Agent追踪 `/teacher/agent-trace/hw_001` | **智教π独有**：每个学生的多Agent决策轨迹、逐题置信度、需复核项 |
| 6 | 订正闭环 `/teacher/correction-loop/hw_001` | **智教π独有**：全班订正进度、每人闭环率、脱环提醒 |
| 7 | 学情分析 `/teacher/analytics/hw_001` | 热力图、班级对比、逐题分析、AI教学建议 |

### 路径B：学生视角（学习端全功能）

| 步骤 | 页面 | 看点 |
|------|------|------|
| 1 | 首页→「学生端演示」→ 陈雨桐(s02) | — |
| 2 | 学习首页 `/student/s02/dashboard` | 今日任务、AI学习建议、AI提醒（"连续3次在分类讨论失分"） |
| 3 | AI错题本 `/student/s02/error-book` | **不是传统错题本**：根因分析（"不是粗心，是配方法逆向操作不熟练"）+ 知识链（前置→当前→后置）+ 分层练习推荐 |
| 4 | 知识树 `/student/s02/knowledge-tree` | **不是列表**：递归树形、颜色=掌握度（红→黄→绿）、点击下钻 |
| 5 | Math Coach `/student/s02/coach` | **不是ChatGPT**：苏格拉底式引导——追问"为什么"、给提示不给答案 |
| 6 | 成长报告 `/student/s02/growth` | **不是看分数**：30天趋势↑12%、AI预测78±5分、强弱项标签 |
| 7 | 订正练习 `/student/s02/correction` | 闭环可视化 + 变式题分层推送（错1练3，A/B/C三档） |
| 8 | 知识雷达 `/student/s02/radar` | SVG多边形图 + 趋势箭头 + 强弱项卡片 |

### 路径C：对比不同学生（差异化诊断能力）

分别查看 s01(全对)→s02(计算+概念错误)→s03(未作答+逻辑跳跃)→s05(表述问题)：
- 同样的Q5/Q6，AI给每个学生**完全不同的诊断**
- 错题本中 AI 给出的根因分析各不相同
- 知识树的颜色分布反映了不同掌握度

### 路径D：课堂互动（希沃生态联动）

| 步骤 | 页面 | 看点 |
|------|------|------|
| 1 | `/classroom` | 教师提问→学生提交→AI分析→白板展示，解法分布+典型错误自动识别 |

---

## 创新点对照（Demo中可演示的差异化）

| 创新点 | Demo 页面 | 竞品现状 |
|--------|----------|---------|
| **步骤级分析** | teacher_grade | 竞品多为"对/错"二元判断 |
| **AI置信度复核** | teacher_review | 竞品AI不标注不确定性 |
| **多Agent协作追踪** | teacher_agent_trace | 竞品为黑盒单模型 |
| **订正闭环** | teacher_correction + student_correction | 竞品批完即止，无闭环 |
| **AI错题本（根因分析）** | student_error_book | 竞品只记"哪道题错了" |
| **知识树** | student_knowledge_tree | 竞品用列表，不展示知识关系 |
| **Math Coach（苏格拉底式）** | student_coach | 竞品做"拍照搜答案" |
| **成长报告（趋势+AI预测）** | student_growth | 竞品只展示分数 |
| **课堂互动联动** | classroom | 竞品无课堂场景 |
| **变式题分层推送** | student_correction | 竞品最多推荐相似题，不分层 |
| **UI/动效系统** | 全站 | Tailwind CSS + Lucide Icons + CSS动画，教育感/专业感/极简/数据驱动 |

---

## 技术栈（Demo）

| 类别 | 选型 | 用途 |
|------|------|------|
| 框架 | Python Flask | 后端路由与模板渲染 |
| CSS | Tailwind CSS (CDN) | 全局样式系统 |
| 图标 | Lucide Icons (CDN) | 矢量图标替代 Emoji |
| 动画 | CSS @keyframes | fadeIn / slideUp / scaleIn / stagger |
| 数据 | JSON 文件 | 模拟 AI 引擎输出 |

---

## API 端点

```bash
# 批改
curl http://localhost:5000/api/grade/s02/hw_001

# 学情分析
curl http://localhost:5000/api/analytics/hw_001

# 订正闭环统计
curl http://localhost:5000/api/correction-loop/hw_001

# AI复核队列
curl http://localhost:5000/api/review-queue/hw_001

# 知识雷达
curl http://localhost:5000/api/radar/s02

# 变式题
curl http://localhost:5000/api/variants/q5/B
```

---

## 数据说明

- 5名学生×6道题，覆盖**5种错误类型**：计算错误、概念混淆、逻辑跳跃、未作答、表述不严谨
- 同一道题不同学生犯错 → AI给不同的诊断 → 展示**差异化批改能力**
- 生产环境中 OCR+LLM 处理真实手写照片；Demo 用预设 JSON 模拟数据跑通全流程
- 订正闭环、变式题推送、Math Coach 等数据均为预设演示数据
