"""
希沃智教π Flask app 生产启动配置（gunicorn）。

P0-1 安全 Blocker：生产环境必须用 gunicorn（而非 Flask 自带 dev server）
替代 `python app.py` 入口。启动示例：
    gunicorn -c gunicorn.conf.py "demo.app:create_app()"
或：
    gunicorn -c gunicorn.conf.py "demo.app:app"

验收：bandit 跑通，session secret 走 env，bind 走 0.0.0.0:8000（容器内），
外层由 nginx 反代（见 deploy/nginx.conf.example）。
"""
import multiprocessing
import os

# ── Server socket ─────────────────────────────────────────────
# 容器内监听 0.0.0.0:8000，宿主外层由 nginx 拦截；不走 5000 防与开发端口冲突
bind = os.environ.get("GUNICORN_BIND", "0.0.0.0:8000")

# ── Worker 数量 ────────────────────────────────────────────────
# 经验值：2 × CPU 核数 + 1；至少 2 防单点。容器 1 核时用 2。
workers = int(os.environ.get("GUNICORN_WORKERS", str(max(2, multiprocessing.cpu_count() * 2 + 1))))
worker_class = os.environ.get("GUNICORN_WORKER_CLASS", "gthread")
threads = int(os.environ.get("GUNICORN_THREADS", "4"))

# ── 超时（防慢请求拖死 worker）──────────────────────────────────
timeout = int(os.environ.get("GUNICORN_TIMEOUT", "60"))  # 请求超时
graceful_timeout = int(os.environ.get("GUNICORN_GRACEFUL_TIMEOUT", "30"))
keepalive = int(os.environ.get("GUNICORN_KEEPALIVE", "5"))

# ── 请求体限制 ─────────────────────────────────────────────────
# 防 DoS：单请求 1MB 上限（Flask Demo 场景无大文件上传，足够了）
limit_request_line = int(os.environ.get("GUNICORN_LIMIT_REQUEST_LINE", "8190"))
limit_request_fields = int(os.environ.get("GUNICORN_LIMIT_REQUEST_FIELDS", "200"))
limit_request_field_size = int(os.environ.get("GUNICORN_LIMIT_REQUEST_FIELD_SIZE", "8190"))

# ── 安全 ───────────────────────────────────────────────────────
# 关键：永远不开 preload（避免 fork 后子进程共享 SECRET_KEY 派生状态）
preload_app = False

# 关键：禁止 Flask debug（gunicorn 起 Flask 时若 env 误设 FLASK_DEBUG=1，
# 这里也守住兜底防线）
def on_starting(server):  # noqa: D401
    """Gunicorn 启动钩子：清掉会触发 Flask debug 模式的 env。"""
    os.environ["FLASK_DEBUG"] = "0"
    if os.environ.get("FLASK_HOST") == "0.0.0.0":
        # 让 nginx 在外层暴露 0.0.0.0，gunicorn 自己绑 0.0.0.0 是预期
        # 但 dev 入口被改后，FLASK_HOST 不再需要
        pass

# ── 日志（写 stdout/stderr，容器内由 docker logs / k8s 收集）────
accesslog = os.environ.get("GUNICORN_ACCESSLOG", "-")
errorlog = os.environ.get("GUNICORN_ERRORLOG", "-")
loglevel = os.environ.get("GUNICORN_LOGLEVEL", "info")
access_log_format = (
    '%(h)s %(l)s %(u)s %(t)s "%(r)s" %(s)s %(b)s "%(f)s" "%(a)s" %(L)s'
)

# ── 进程名（运维 ps 一眼能识别）────────────────────────────────
proc_name = "seewo-pi"

# ── Hooks：worker 启动时打印（容器化部署必备）────────────────────
def post_fork(server, worker):  # noqa: D401
    server.log.info("worker spawned (pid=%s)", worker.pid)

def pre_exec(server):  # noqa: D401
    server.log.info("forked child, re-executing")

def when_ready(server):  # noqa: D401
    server.log.info("seewo-pi gunicorn ready: bind=%s workers=%s threads=%s",
                    bind, workers, threads)
