"""Pytest 全局 preflight：触发 import-time 错误前置.

CI 教训背景（Week 2 Day 1-2）：
  Phase 0+1 集成 commit (e90f6f5) 在 demo/app.py:107 加入 flash() 调用，
  但 from flask import 块没补 flash 标识符。
  9 个 test_auth_* 用例因此 500（NameError: name 'flash' is not defined）。

  表层修复 = 加 1 行 from flask import flash（快速原型师完成）。
  根因     = CI lint 阶段没拦住这个 undefined name（ruff 0.6.9 边界 case）。

本文件职责：
  1. 在 pytest collection 阶段强制 import 关键入口模块
  2. import-time 错误立即 fail，**不**留到 test 运行时才 500
  3. 给出清晰的"哪里 import 失败"信息

设计取舍：
  - 不依赖 CI 配置（conftest 在本地 + CI 都生效）
  - 顶部 import 而非 fixture：collection 阶段就跑，不等 test 触发
  - 同时覆盖 Flask 单体 + FastAPI 入口 + Celery 任务
"""
from __future__ import annotations

import pytest

# —— Preflight: 强制 import 关键入口模块 ——
# 用 noqa 标记因为这些 import 看似"未使用"，实际就是触发 import 错误前置。
import demo.app  # noqa: F401  Phase 0 Flask 单体入口
import demo.fastapi_app.main  # noqa: F401  Phase 1 Week 1+ FastAPI 入口
import infra.celery.tasks  # noqa: F401  Celery default 队列
import infra.celery.tasks_llm  # noqa: F401  Celery llm 队列
import infra.pg.orm  # noqa: F401  SQLAlchemy 模型


def pytest_configure(config: pytest.Config) -> None:
    """pytest 配置钩子：preflight 通过时打印一行状态（CI 日志可见）."""
    print("\n[conftest] preflight OK: demo.app / demo.fastapi_app.main / infra.celery.{tasks,tasks_llm} / infra.pg.orm all import cleanly")


# —— 可选：收集错误钩子（让 import-time 错误的 stack 更清晰）——
def pytest_collectstart(collector: pytest.Collector) -> None:
    """collection 阶段 import 错误时给出明确提示."""
    pass
