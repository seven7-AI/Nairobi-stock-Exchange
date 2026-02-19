"""Application configuration and environment validation."""

from __future__ import annotations

from pathlib import Path

from dotenv import load_dotenv
from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


ROOT_DIR = Path(__file__).resolve().parents[2]
ENV_FILE = ROOT_DIR / ".env"


class Settings(BaseSettings):
    """Typed app settings loaded from environment."""

    model_config = SettingsConfigDict(env_file=ENV_FILE, env_file_encoding="utf-8", extra="ignore")

    supabase_url: str = Field(alias="SUPABASE_URL")
    supabase_key: str = Field(alias="SUPABASE_KEY")
    stock_table: str = Field(
        default="stock_data",
        alias="SUPABASE_TABLE",
        description="Deprecated: No longer used. Kept for backward compatibility.",
    )
    stockanalysis_table: str = Field(default="stockanalysis_stocks", alias="STOCKANALYSIS_TABLE")
    reports_dir: Path = ROOT_DIR / "reports" / "daily"
    weekly_reports_dir: Path = ROOT_DIR / "reports" / "weekly"
    monthly_reports_dir: Path = ROOT_DIR / "reports" / "monthly"
    logs_dir: Path = ROOT_DIR / "logs"
    historical_data_dir: Path = Field(
        default=ROOT_DIR / "NSE_DATA",
        description="Deprecated: No longer used. Historical data now comes from stockanalysis_stocks table.",
    )
    indicators_file: Path = ROOT_DIR / "indicators.txt"
    log_level: str = "INFO"
    historical_days_back: int = Field(
        default=365,
        description="Number of days of historical data to fetch from stockanalysis_stocks table.",
    )
    default_history_days: int = Field(
        default=365,
        description="Deprecated: Use historical_days_back instead.",
    )


def get_settings() -> Settings:
    """Load and validate settings from .env and process env."""
    load_dotenv(ENV_FILE)
    settings = Settings()  # type: ignore[call-arg]
    settings.reports_dir.mkdir(parents=True, exist_ok=True)
    settings.weekly_reports_dir.mkdir(parents=True, exist_ok=True)
    settings.monthly_reports_dir.mkdir(parents=True, exist_ok=True)
    settings.logs_dir.mkdir(parents=True, exist_ok=True)
    return settings
