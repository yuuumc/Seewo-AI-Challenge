"""FastAPI 路由包：grading API（异步 + Celery 派发）."""
from fastapi import APIRouter

router = APIRouter()

__all__ = ["router"]
