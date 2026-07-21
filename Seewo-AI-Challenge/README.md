# 希沃智教π — AI智能作业批改系统

> **"每个学生都被认真对待。"**
>
> 多Agent AI架构 · 步骤级批改 · 苏格拉底式辅导 · 拍照即批改 · 批改即分析 · 分析即推送

---

## 快速开始

```bash
cd demo
pip install flask
python app.py
# 浏览器打开 http://localhost:5000
```

Windows 用户也可双击 `demo/start.bat` 自动启动。

---

## 项目结构

```
├── README.md                 # 本文件
├── 命题.txt                   # 比赛命题
│
├── 01_需求分析.md             # 需求分析（功能需求·非功能需求·优先级矩阵）
├── 02_用户研究.md             # 用户研究（教师/教研组长/信息化主任三角色画像）
├── 03_竞品分析.md             # 竞品分析（讯飞/七天/飞象/小猿对比）
├── 04_产品设计.md             # 产品设计（信息架构·交互流程·UI原则）
├── 05_技术方案.md             # 技术方案（多Agent架构·Agent Card·通信时序图）
├── 06_PRD.md                 # PRD（MVP范围·功能规格·成功标准）
├── 07_PPT.md                 # 演示PPT大纲（12页结构）
├── 08_Demo.md                # Demo说明（运行方式·演示路径·创新点对照）
├── 09_报名材料.md             # 报名材料（项目简介·创新点·附件清单）
│
├── 学生端/                    # 学生端设计源文件（9个）
│
└── demo/                     # 可运行Demo
    ├── start.bat             # Windows一键启动
    ├── start.sh              # macOS/Linux启动
    ├── app.py                # Flask主应用（20+路由）
    ├── engine/grader.py      # 模拟AI引擎（批改/订正/知识雷达/Agent追踪）
    ├── data/                 # 10个JSON数据文件
    ├── templates/            # 17个HTML模板
    └── static/css/style.css  # 全局样式（Tailwind + CSS动画）
```

---

## Demo 功能一览

### 教师端（6页）

| 页面 | 路径 | 亮点 |
|------|------|------|
| 作业管理 | `/teacher` | 题目概览、学生列表 |
| AI批改详情 | `/teacher/grade/hw_001` | **步骤级分析** — 解答题逐步骤正误+错因分类 |
| AI复核队列 | `/teacher/review/hw_001` | **置信度排序** — 教师仅需处理~15%低置信度结果 |
| 订正闭环看板 | `/teacher/correction-loop/hw_001` | 全班订正进度追踪、脱环提醒 |
| Agent协作追踪 | `/teacher/agent-trace/hw_001` | **8 Agent决策轨迹**透明可追溯 |
| 学情分析 | `/teacher/analytics/hw_001` | 热力图、班级对比、AI教学建议 |

### 学生端（7页）

| 页面 | 路径 | 亮点 |
|------|------|------|
| 学习首页 | `/student/s02/dashboard` | Today Dashboard — 任务+AI建议+智能提醒 |
| AI错题本 | `/student/s02/error-book` | **根因分析+知识链**（前置→当前→后置） |
| 知识树 | `/student/s02/knowledge-tree` | 树形可视化，颜色=掌握度 |
| Math Coach | `/student/s02/coach` | **苏格拉底式**辅导 — 追问不给答案 |
| 成长报告 | `/student/s02/growth` | 趋势追踪+AI预测 |
| 订正练习 | `/student/s02/correction` | **变式题分层推送**（错1练3，A/B/C三档） |
| 知识雷达 | `/student/s02/radar` | SVG多边形雷达图 |

### 其他

| 页面 | 路径 | 亮点 |
|------|------|------|
| 课堂互动 | `/classroom` | 教师提问→学生提交→AI分析→白板展示 |

---

## 核心创新点

| 创新点 | 竞品现状 |
|--------|---------|
| **步骤级分析**（非二元对错） | 竞品多为"对/错"判断 |
| **AI置信度复核**（标注不确定性） | 竞品AI不标注置信度 |
| **多Agent协作追踪**（8 Agent透明决策） | 竞品为黑盒单模型 |
| **订正闭环**（批改→订正→验证→闭环） | 竞品批完即止 |
| **AI错题本**（根因分析+知识链） | 竞品只记"哪道题错了" |
| **Math Coach**（苏格拉底式辅导） | 竞品做"拍照搜答案" |
| **知识树**（颜色可视化+递归下钻） | 竞品用列表 |
| **成长报告**（趋势+AI预测） | 竞品只展示分数 |
| **课堂互动联动**（师生+AI+白板） | 竞品无课堂场景 |

---

## 技术栈（Demo）

| 类别 | 选型 |
|------|------|
| 框架 | Python Flask |
| CSS | Tailwind CSS (CDN) |
| 图标 | Lucide Icons |
| 动画 | CSS @keyframes |
| 数据 | JSON 文件（模拟AI引擎） |

---

## API

```bash
curl http://localhost:5000/api/grade/s02/hw_001       # 单生批改
curl http://localhost:5000/api/analytics/hw_001        # 班级学情
curl http://localhost:5000/api/correction-loop/hw_001  # 订正闭环
curl http://localhost:5000/api/review-queue/hw_001     # 复核队列
curl http://localhost:5000/api/radar/s02               # 知识雷达
curl http://localhost:5000/api/variants/q5/B           # 变式题
```

---

## 设计风格

教育感 · 专业感 · 极简 · 数据驱动

---

*Seewo AI Grading Pi · 2026*
