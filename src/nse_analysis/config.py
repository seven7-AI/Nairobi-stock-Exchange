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
    stock_table: str = Field(default="stock_data", alias="SUPABASE_TABLE")
    stockanalysis_table: str = Field(default="stockanalysis_stocks", alias="STOCKANALYSIS_TABLE")
    reports_dir: Path = ROOT_DIR / "reports" / "daily"
    logs_dir: Path = ROOT_DIR / "logs"
    historical_data_dir: Path = ROOT_DIR / "NSE_DATA"
    indicators_file: Path = ROOT_DIR / "indicators.txt"
    log_level: str = "INFO"
    default_history_days: int = 365


def get_settings() -> Settings:
    """Load and validate settings from .env and process env."""
    load_dotenv(ENV_FILE)
    settings = Settings()  # type: ignore[call-arg]
    settings.reports_dir.mkdir(parents=True, exist_ok=True)
    settings.logs_dir.mkdir(parents=True, exist_ok=True)
    return settings
