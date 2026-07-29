"""Celery beat 入口: `python -m infra.celery.beat`.

启动 beat 调度器，按 beat_schedule 派发周期任务。
注意：beat 和 worker 必须在不同进程中跑（同一进程跑会冲突）。
"""
from __future__ import annotations

import logging

from infra.celery.celery_app import celery_app

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")

if __name__ == "__main__":
    celery_app.worker_main(argv=["beat", "--loglevel=INFO"])
