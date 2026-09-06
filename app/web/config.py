"""Application configuration and environment validation.

Settings are the single source of truth for every runtime knob. Nothing in this
codebase reads ``os.environ`` directly — inject ``Settings`` instead, so that a
value can be traced to one declaration.

    codegraph explore "get_settings Settings AppState lifespan"
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Literal

from dotenv import load_dotenv
from pydantic import Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

ROOT_DIR = Path(__file__).resolve().parents[2]
ENV_FILE = ROOT_DIR / ".env"

DEV_JWT_SECRET = "dev-secret-change-me"


class Settings(BaseSettings):
    """Typed app settings loaded from environment."""

    model_config = SettingsConfigDict(
        env_file=ENV_FILE,
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # --- service identity -------------------------------------------------
    app_name: str = Field(default="nse-be", alias="APP_NAME")
    environment: Literal["local", "development", "staging", "production"] = Field(
        default="local", alias="ENVIRONMENT"
    )
    debug: bool = Field(default=False, alias="DEBUG")
    api_v1_prefix: str = Field(default="/api/v1", alias="API_V1_PREFIX")
    cors_origins: list[str] = Field(default_factory=lambda: ["*"], alias="CORS_ORIGINS")

    # --- upstream market data (external scraper owns this table) ----------
    supabase_url: str = Field(alias="SUPABASE_URL")
    supabase_key: str = Field(alias="SUPABASE_KEY")
    stockanalysis_table: str = Field(default="stockanalysis_stocks", alias="STOCKANALYSIS_TABLE")

    # --- database (tables this repo owns) ---------------------------------
    database_url: str = Field(
        default="postgresql+asyncpg://postgres:postgres@localhost:5432/nse",
        alias="DATABASE_URL",
        description="Async SQLAlchemy DSN. Must use the asyncpg driver.",
    )
    db_echo: bool = Field(default=False, alias="DB_ECHO")
    db_pool_size: int = Field(default=10, alias="DB_POOL_SIZE")
    db_max_overflow: int = Field(default=20, alias="DB_MAX_OVERFLOW")

    # --- security ---------------------------------------------------------
    jwt_secret_key: str = Field(default=DEV_JWT_SECRET, alias="JWT_SECRET_KEY")
    jwt_algorithm: str = Field(default="HS256", alias="JWT_ALGORITHM")
    access_token_expire_minutes: int = Field(default=30, alias="ACCESS_TOKEN_EXPIRE_MINUTES")
    refresh_token_expire_days: int = Field(default=7, alias="REFRESH_TOKEN_EXPIRE_DAYS")

    # --- redis / celery ---------------------------------------------------
    redis_url: str = Field(default="redis://localhost:6379/0", alias="REDIS_URL")
    celery_broker_url: str = Field(default="redis://localhost:6379/1", alias="CELERY_BROKER_URL")
    celery_result_backend: str = Field(
        default="redis://localhost:6379/2", alias="CELERY_RESULT_BACKEND"
    )
    celery_beat_enabled: bool = Field(
        default=False,
        alias="CELERY_BEAT_ENABLED",
        description=(
            "Off by default: the daily/weekly/monthly GitHub Actions workflows already "
            "generate those reports through the CLI. Enabling beat without disabling "
            "those workflows double-generates every report."
        ),
    )

    # --- email ------------------------------------------------------------
    smtp_host: str = Field(default="", alias="SMTP_HOST")
    smtp_port: int = Field(default=587, alias="SMTP_PORT")
    smtp_user: str = Field(default="", alias="SMTP_USER")
    smtp_password: str = Field(default="", alias="SMTP_PASSWORD")
    email_from: str = Field(default="no-reply@nse-analytics.local", alias="EMAIL_FROM")

    # --- filesystem paths -------------------------------------------------
    reports_dir: Path = ROOT_DIR / "reports" / "daily"
    weekly_reports_dir: Path = ROOT_DIR / "reports" / "weekly"
    monthly_reports_dir: Path = ROOT_DIR / "reports" / "monthly"
    logs_dir: Path = ROOT_DIR / "logs"
    indicators_file: Path = ROOT_DIR / "indicators.txt"
    research_data_dir: Path = ROOT_DIR / "research" / "data"

    # --- analytics --------------------------------------------------------
    log_level: str = Field(default="INFO", alias="LOG_LEVEL")
    historical_days_back: int = Field(
        default=365,
        alias="HISTORICAL_DAYS_BACK",
        description="Days of history to load when computing indicators.",
    )

    @property
    def sync_database_url(self) -> str:
        """Blocking DSN for Alembic and Celery tasks only. Never use in a request path."""
        return self.database_url.replace("+asyncpg", "+psycopg2")

    @property
    def is_production(self) -> bool:
        return self.environment == "production"

    @model_validator(mode="after")
    def _reject_dev_secrets_in_production(self) -> Settings:
        """A deployed service must never run on the development signing key."""
        if self.is_production and self.jwt_secret_key == DEV_JWT_SECRET:
            raise ValueError(
                "JWT_SECRET_KEY is still the development default in a production "
                "environment. Set a real secret before deploying."
            )
        return self


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Load and validate settings, creating the directories the app writes to."""
    load_dotenv(ENV_FILE)
    settings = Settings()
    for directory in (
        settings.reports_dir,
        settings.weekly_reports_dir,
        settings.monthly_reports_dir,
        settings.logs_dir,
    ):
        directory.mkdir(parents=True, exist_ok=True)
    return settings
