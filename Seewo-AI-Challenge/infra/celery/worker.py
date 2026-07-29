"""Celery worker 入口: `python -m infra.celery.worker`.

启动一个 worker，消费 infra.celery.tasks 中的任务。
"""
from __future__ import annotations

import logging

from infra.celery.celery_app import celery_app

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")

if __name__ == "__main__":
    celery_app.worker_main(argv=["worker", "--loglevel=INFO", "--concurrency=2"])
