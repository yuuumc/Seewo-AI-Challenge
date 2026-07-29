"""LLM 专用 worker 入口: `python -m infra.celery.worker_llm`.

只消费 llm 队列，concurrency=1（防 OOM），time_limit=30min.
生产部署见 docker-compose.prod.yml 的 worker-llm 服务。
"""
from __future__ import annotations

import logging

from infra.celery.celery_app import llm_worker_app

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")

if __name__ == "__main__":
    app = llm_worker_app()
    app.worker_main(argv=["worker", "--loglevel=INFO", "--concurrency=1", "-Q", "llm"])
