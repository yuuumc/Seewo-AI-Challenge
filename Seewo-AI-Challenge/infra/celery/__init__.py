"""infra.celery 子包入口."""
from infra.celery.celery_app import celery_app

__all__ = ["celery_app"]
