# Phase 1 多阶段 Dockerfile
# 目标：runtime 镜像 < 500MB，秒级启动
#
# 构建:  docker build -t seewo-api:phase1 -f Dockerfile .
# 跑:     docker run -p 8000:8000 seewo-api:phase1

# ============== Stage 1: builder ==============
FROM python:3.11-slim AS builder

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

# 装编译依赖（asyncpg / psycopg2 需要）
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    libpq-dev \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# 先装依赖（利用 Docker 层缓存：源码变动不重装）
COPY requirements.txt requirements-fastapi.txt ./
RUN pip install --prefix=/install -r requirements.txt -r requirements-fastapi.txt

# ============== Stage 2: runtime ==============
FROM python:3.11-slim AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PATH="/install/bin:${PATH}" \
    PYTHONPATH="/install/lib/python3.11/site-packages"

# 运行时只装 libpq（无 gcc），省 ~150MB
RUN apt-get update && apt-get install -y --no-install-recommends \
    libpq5 \
    curl \
    && rm -rf /var/lib/apt/lists/*

# 创建非 root 用户
RUN groupadd -r seewo && useradd -r -g seewo -d /app -s /sbin/nologin seewo

WORKDIR /app

# 拷贝 builder 阶段安装好的 site-packages
COPY --from=builder /install /install

# 拷贝源码
COPY --chown=seewo:seewo demo/ ./demo/
COPY --chown=seewo:seewo infra/ ./infra/
COPY --chown=seewo:seewo alembic.ini ./

USER seewo

EXPOSE 8000

# 健康检查（容器内）
HEALTHCHECK --interval=10s --timeout=3s --start-period=20s --retries=5 \
    CMD curl -fsS http://localhost:8000/api/v1/health || exit 1

CMD ["uvicorn", "demo.fastapi_app.main:app", "--host", "0.0.0.0", "--port", "8000"]
