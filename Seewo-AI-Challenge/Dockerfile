# Seewo AI Challenge — Demo (Flask) 部署镜像
# 基线镜像：python:3.11-slim（最小 Debian footprint；与 P0-12 FastAPI 迁移期共存）
# 交付：Phase 0 部署包 — 快速原型师

FROM python:3.11-slim AS base

# 防止 Python 写 .pyc，强制 stdout/stderr 不缓冲
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

# 装 curl 给 HEALTHCHECK 用 + tini 给 PID 1 用（正确处理 SIGTERM）
# 注意：保持层缓存友好 — apt-get update 和 install 在同一 RUN
RUN apt-get update \
 && apt-get install -y --no-install-recommends \
      curl \
      tini \
 && rm -rf /var/lib/apt/lists/*

# 创建非 root 用户（uid 1000 对齐 K8s runAsUser 惯例）
RUN groupadd -r -g 1000 appuser \
 && useradd -r -u 1000 -g appuser -m -d /home/appuser -s /bin/bash appuser

WORKDIR /app

# 先 copy requirements 单独成层 — 依赖变更时才重装
COPY demo/requirements.txt /app/requirements.txt

# 生产依赖（基线）+ leader 集成后会追加的依赖
# 注：flask-wtf / flask-limiter / gunicorn 当前 demo/requirements.txt 不含，
# 由 leader 在根 requirements.txt 合并时一并补；这里先安装以让镜像独立可跑
RUN pip install --upgrade pip \
 && pip install --no-cache-dir \
      -r /app/requirements.txt \
      flask-wtf \
      flask-limiter \
      gunicorn

# 复制应用代码（demo 目录整树）
COPY demo/ /app/demo/

# 把 demo/ 作为 PYTHONPATH（与 CI 一致 — gunicorn 启动时 import demo.app:app）
ENV PYTHONPATH=/app

# 配置文件（gunicorn / .env 模板）
COPY gunicorn.conf.py /app/gunicorn.conf.py
COPY .env.example /app/.env.example

# 数据目录归属非 root 用户（写场景少但 grade_long_answer 写 cache）
RUN chown -R appuser:appuser /app

# 切到非 root
USER appuser

EXPOSE 5000

# 健康检查：ping 首页
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD curl -fsS http://localhost:5000/ || exit 1

# tini 收僵尸进程 + SIGTERM 转发；gunicorn 从 PYTHONPATH/dotenv 启动
ENTRYPOINT ["/usr/bin/tini", "--"]
CMD ["gunicorn", "-c", "gunicorn.conf.py", "demo.app:app"]
