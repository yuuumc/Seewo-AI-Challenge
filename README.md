# 希沃智教π · AI 智能作业批改系统

> **"每个学生都被认真对待。"**
>
> 飞书 / 希沃 CVTE AI 大赛作品 · 模块化 AI 引擎 · 步骤级批改 · 苏格拉底式辅导

---

## 项目简介

**希沃智教π** 是一套面向中小学的 AI 智能作业批改系统。它不满足于"对 / 错"的二元判断,而是用**模块化 AI 引擎**做到:

- **步骤级分析** —— 解答题逐步骤判定正误、归类错因;
- **AI 置信度复核** —— 模型主动标注不确定性,教师只需处理约 15% 低置信度结果;
- **订正闭环** —— 批改 → 订正 → 验证 → 闭环,脱环自动提醒;
- **苏格拉底式辅导** —— Math Coach 只追问、不给答案,逼学生自己想通;
- **学情可视化** —— 知识树、知识雷达、成长报告,数据驱动教学决策。

设计标语:**拍照即批改 · 批改即分析 · 分析即推送**。

---

## 仓库结构

```
.
├── Seewo-AI-Challenge/        # 主交付物（本仓库核心）
│   ├── README.md              # 子目录详细说明（Demo 路由 / API / 创新点）
│   ├── 01_需求分析.md          # 功能 / 非功能需求 · 优先级矩阵
│   ├── 02_用户研究.md          # 教师 / 教研组长 / 信息化主任 三角色画像
│   ├── 03_竞品分析.md          # 讯飞 / 七天 / 飞象 / 小猿 对比
│   ├── 04_产品设计.md          # 信息架构 · 交互流程 · UI 原则
│   ├── 05_技术方案.md          # 技术方案 · AI 引擎架构 · 推理链路设计
│   ├── 06_PRD.md              # MVP 范围 · 功能规格 · 成功标准
│   ├── 07_PPT.md              # 演示 PPT 大纲（12 页）
│   ├── 08_Demo.md             # Demo 说明（运行 · 演示路径 · 创新点对照）
│   ├── 09_报名材料.md          # 项目简介 · 创新点 · 附件清单
│   ├── 学生端/                # 学生端设计源文件
│   └── demo/                  # 可运行 Flask Demo（见下）
│
├── research/                  # 调研素材（用户访谈 / 竞品截图 / 文献）
└── archive/                   # 历史版本归档（不参与版本控制）
```

> 完整的文档链、Demo 路由表、API 清单、创新点对照见 **[`Seewo-AI-Challenge/README.md`](Seewo-AI-Challenge/README.md)**。

---

## 快速开始（运行 Demo）

**本地开发**（dev 入口，仅 127.0.0.1，P0-1 安全 Blocker）：

```bash
cd Seewo-AI-Challenge/demo
pip install -r requirements.txt
python app.py
# 浏览器打开 http://localhost:5000
```

**生产 / 对外演示**（gunicorn + nginx，Phase 0 必修）：

```bash
# 1. 安装依赖（含 gunicorn）
cd Seewo-AI-Challenge/demo && pip install -r requirements.txt

# 2. 用 gunicorn 启动（多 worker 防单点崩溃）
cd ../..  # 回到仓库根
gunicorn -c gunicorn.conf.py "demo.app:app"
# 监听 0.0.0.0:8000，由 nginx 反代到 443

# 3. （可选）配 nginx 反代 + TLS
cp deploy/nginx.conf.example /etc/nginx/sites-available/seewo-pi.conf
# 修改 server_name 和证书路径后：
ln -s /etc/nginx/sites-available/seewo-pi.conf /etc/nginx/sites-enabled/
nginx -t && systemctl reload nginx
```

**安全约束**：
- `FLASK_HOST=0.0.0.0` 走 dev 入口会立即拒绝（防 RCE 误配）
- 生产模式 `DEMO_AUTH_OPEN=0` 强制 CSRF + RBAC + IDOR 全开
- session secret 必须设 `FLASK_SECRET_KEY` ≥32 字节（.env.example 模板）

> Demo 为**模拟 AI 引擎**（JSON 数据 + 规则引擎），无需任何外部 API Key 即可完整体验全部交互流程。

---

## 核心创新点

| 创新点 | 竞品现状 |
|--------|---------|
| **步骤级分析**（非二元对错） | 竞品多为"对 / 错"判断 |
| **AI 置信度复核**（标注不确定性） | 竞品 AI 不标注置信度 |
| **AI 决策追踪**（5 步推理透明可追溯） | 竞品为黑盒单模型 |
| **订正闭环**（批改 → 订正 → 验证） | 竞品批完即止 |
| **Math Coach**（苏格拉底式辅导） | 竞品做"拍照搜答案" |
| **知识树 / 知识雷达**（可视化掌握度） | 竞品用列表或仅展示分数 |

---

## 技术栈（Demo）

| 类别 | 选型 |
|------|------|
| 后端 | Python Flask |
| 前端 | Tailwind CSS (CDN) · Lucide Icons · CSS @keyframes |
| 数据 | JSON 文件（模拟 AI 引擎） |

---

## 设计风格

教育感 · 专业感 · 极简 · 数据驱动

---

*Seewo AI Grading Pi · 2026*
