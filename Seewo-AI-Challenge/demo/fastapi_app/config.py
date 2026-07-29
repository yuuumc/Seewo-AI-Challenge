"""Phase 1 配置：Pydantic v2 Settings + 生产环境强制校验.

P0-2 修复：FLASK_SECRET_KEY 在 env=production 时必须显式注入且不能等于默认值。
启动期校验：缺失必填项或类型错误立即抛错，不带病运行。

C-08 修复（Week 3）：LLM 配置走 Pydantic Settings（与 secret 同套校验体系）.
  - LLM_API_KEY 未设 → 走 mock
  - LLM_API_KEY 已设 → 走真 LLM
  - 生产环境必须有 LLM_API_KEY 且 LLM_BASE_URL 非默认占位符（C-08 强约束）

C-08 同时扩展 env 取值：新增 "test" profile（仅用于 pytest，绕过生产校验）.
"""
from __future__ import annotations

from functools import lru_cache
from typing import Literal, Optional

from pydantic import Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

# 公开已知的兜底默认值（生产环境禁止等于这些值）
_FORBIDDEN_SECRET_VALUES: frozenset[str] = frozenset({
    "dev-secret-change-in-prod",
    "change-me",
    "",
    "seewo-ai-challenge-demo-secret-2026",
})


class Settings(BaseSettings):
    """全局配置。"""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # —— 运行时环境 ——
    # C-08 新增 "test"：与 "development" 等价（绕过 production 严格校验）
    env: Literal["development", "staging", "production", "test"] = "development"
    log_level: str = "INFO"

    # —— 数据库 ——
    database_url: str = Field(
        default="postgresql+asyncpg://seewo:seewo@localhost:5432/seewo",
        description="SQLAlchemy async DSN（asyncpg 驱动）",
    )
    database_url_sync: str = Field(
        default="postgresql+psycopg2://seewo:seewo@localhost:5432/seewo",
        description="Alembic 迁移用的 sync DSN（psycopg2 驱动）",
    )
    db_pool_size: int = 10
    db_max_overflow: int = 20

    # —— Redis ——
    redis_url: str = "redis://localhost:6379/0"
    celery_broker_url: str = "redis://localhost:6379/1"
    celery_result_backend: str = "redis://localhost:6379/2"

    # —— Flask 兼容（保持老 session 解析） ——
    # P0-2: 生产环境强制注入；开发/staging 允许默认值
    flask_secret_key: str = "dev-secret-change-in-prod"

    # —— 业务参数（Phase 0 既有约束） ——
    max_upload_mb: int = 4
    rate_limit_per_minute: int = 60

    # —— Demo 模式守门（P0 条件，队长拍板） ——
    # 见 main.py / app.py 启动期分支：env==production 时 SEEWO_DEMO_MODE 必须为 0/未设
    demo_mode: bool = Field(
        default=False,
        description="True 时启用 demo 模式（演示账号 + 内存替身）；生产必须为 False",
    )

    # —— C-08 LLM 配置 ——
    # 与 demo/app.py L31-33 env-var 约定一致：未设 LLM_API_KEY → mock
    llm_api_key: Optional[str] = Field(
        default=None,
        description="LLM 鉴权密钥；未设走 mock，设了走真 LLM",
    )
    llm_base_url: str = Field(
        default="https://api.openai.com/v1",
        description="OpenAI 兼容 base URL（C-08 切 DeepSeek-Math 时改为 https://api.deepseek.com/v1）",
    )
    llm_model: str = Field(
        default="gpt-4o-mini",
        description="模型名（C-08 切 deepseek-math）",
    )
    llm_dry_run: bool = Field(
        default=False,
        description="True 时真 provider 但本地模拟响应（用于等价率测试，禁用 HTTP）",
    )

    @model_validator(mode="after")
    def _validate_production_secrets(self) -> "Settings":
        """P0-2: production 环境强制要求强密钥 + C-08 真 LLM 必须配置.

        "test" profile 视为 development（不强制生产级密钥）.
        """
        effective_env = "development" if self.env == "test" else self.env
        if effective_env == "production":
            if self.flask_secret_key in _FORBIDDEN_SECRET_VALUES:
                raise ValueError(
                    "FLASK_SECRET_KEY 在 production 环境不能使用默认值或空值。"
                    "请用 `openssl rand -hex 32` 生成强随机密钥并通过环境变量注入。"
                )
            if len(self.flask_secret_key) < 32:
                raise ValueError(
                    f"FLASK_SECRET_KEY 长度 {len(self.flask_secret_key)} < 32，"
                    "production 环境必须使用 32 字节以上的强随机密钥。"
                )
            if self.demo_mode:
                raise ValueError(
                    "SEEWO_DEMO_MODE 在 production 环境必须为 False（防止 demo 镜像进 staging/prod）"
                )
            # C-08：生产环境真 LLM 必填（避免线上意外走 mock）
            if not self.llm_api_key:
                raise ValueError(
                    "LLM_API_KEY 在 production 环境必须显式注入（未设会自动降级 mock，"
                    "production 不允许该降级）。"
                )
            if self.llm_dry_run:
                raise ValueError(
                    "LLM_DRY_RUN 在 production 环境必须为 False（dry_run 仅用于测试等价率）。"
                )
            # 禁默认 base URL（默认 URL 在生产可能是错的 / 收费的）
            if self.llm_base_url == "https://api.openai.com/v1":
                raise ValueError(
                    "LLM_BASE_URL 在 production 环境不能使用默认 OpenAI URL，"
                    "请显式配置为生产供应商的 base URL（如 https://api.deepseek.com/v1）。"
                )
        return self


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """单例 settings。测试时可通过 `get_settings.cache_clear()` 重置。"""
    return Settings()
