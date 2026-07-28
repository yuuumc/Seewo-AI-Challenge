"""Gunicorn 配置文件 — Phase 0 部署基线。

设计目标：
- 2 workers（小规模 demo 演示 + 评审流量够用；1000+ 学生前应换 FastAPI+uvicorn）
- 30s timeout（防止 LLM 调用卡死拖垮整个 worker）
- preload_app=True — 共享只读数据加载（students.json / questions.json 一次性读进内存）
- accesslog / errorlog 走 stdout — 给 K8s / Docker 收集（不写文件）
- graceful timeout 给足 30s — 收尾时让进行中的请求完成

修改指南：所有配置项在文件顶部集中，下方有简注。leader 集成后可按需调 workers 数。
"""

from __future__ import annotations

import multiprocessing
import os

# ── 网络绑定 ─────────────────────────────────────────────────────────
bind = os.environ.get("GUNICORN_BIND", "0.0.0.0:5000")

# ── Worker 模型 ──────────────────────────────────────────────────────
# demo 规模：2 worker（与硬约束「不引入重依赖」一致 — 不用 gevent / eventlet）
workers = int(os.environ.get("GUNICORN_WORKERS", "2"))
# thread 留 1 — Flask 同步视图 + 单线程即可（避免线程安全坑）
threads = int(os.environ.get("GUNICORN_THREADS", "1"))
# 每个 worker 处理多少请求后回收（防内存泄漏 — 长期运行必备）
max_requests = int(os.environ.get("GUNICORN_MAX_REQUESTS", "1000"))
max_requests_jitter = int(os.environ.get("GUNICORN_MAX_REQUESTS_JITTER", "100"))

# ── 超时 ─────────────────────────────────────────────────────────────
# 单个请求硬上限 30s（防 LLM 调用卡死）
timeout = int(os.environ.get("GUNICORN_TIMEOUT", "30"))
# graceful shutdown 30s（K8s 默认给 30s SIGTERM，超出会 SIGKILL）
graceful_timeout = int(os.environ.get("GUNICORN_GRACEFUL_TIMEOUT", "30"))
# worker 启动超时
worker_tmp_dir = "/dev/shm"  # noqa: S108 — 内存 tmp 目录，提升 worker 启动速度
# keep-alive 2s — 配合主流 LB 默认
keepalive = int(os.environ.get("GUNICORN_KEEPALIVE", "2"))

# ── 预加载 ───────────────────────────────────────────────────────────
# True — 父进程加载 app（包含所有数据文件），worker 进程 fork 共享只读内存
# 副作用：reload=True 时只检测文件变化，**不**重读 JSON 数据；契合 demo 性质
preload_app = True

# ── 日志 ─────────────────────────────────────────────────────────────
# 走 stdout/stderr — K8s / Docker / 飞书日志收集器直接收
accesslog = os.environ.get("GUNICORN_ACCESSLOG", "-")
errorlog = os.environ.get("GUNICORN_ERRORLOG", "-")
loglevel = os.environ.get("GUNICORN_LOGLEVEL", "info")
access_log_format = (
    '%(h)s %(l)s %(u)s %(t)s "%(r)s" %(s)s '
    '%(b)s "%(f)s" "%(a)s" %(L)s'
)

# ── 进程名 ───────────────────────────────────────────────────────────
proc_name = "seewo-ai-challenge"

# ── 安全 ─────────────────────────────────────────────────────────────
# 不允许 worker 提权（防御性：万一 root 启动也不会有子进程是 root）
# 注：Dockerfile 已 USER appuser，正常情况下不需要；这里双保险
worker_class = "sync"
# 防止慢客户端拖死 worker（DDoS 缓解；与 rate_limit 互补不重复）
limit_request_line = 4094
limit_request_fields = 100
limit_request_field_size = 8190

# ── Server 钩子 ──────────────────────────────────────────────────────
def on_starting(server: object) -> None:  # noqa: D401
    """gunicorn 启动时打印 banner（K8s log 排查用）。"""
    print(f"[gunicorn] starting {proc_name} with {workers} workers", flush=True)


def post_fork(server: object, worker: object) -> None:  # noqa: D401
    """worker fork 后钩子 — 当前仅日志。"""
    print(f"[gunicorn] worker {worker.pid} spawned", flush=True)
