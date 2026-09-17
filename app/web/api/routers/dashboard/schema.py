"""Response models for the public dashboard.

Every number is a ``Measure`` - ``{value, status, reason}`` - so a client can never
read missing as zero. Dates are ISO dates; timestamps ISO datetimes.
"""

from __future__ import annotations

from datetime import date as date_type
from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field

from app.web.api.routers.research.schema import Measure


class VersionOut(BaseModel):
    version: str = Field(description="Changes whenever either SQLite file changes")
    analytics_updated_at: datetime | None
    scraper_updated_at: datetime | None
    latest_market_date: date_type | None
    latest_analytics_date: date_type | None
    generated_at: datetime


class JobRowOut(BaseModel):
    job_name: str
    status: str
    started_at: datetime
    finished_at: datetime | None
    as_of: str | None
    rows_written: int
    seconds: float | None
    error: str | None
    details: dict[str, Any] = Field(default_factory=dict)


class PipelineOut(BaseModel):
    pipeline: str
    schedule: str
    timezone: str
    description: str
    last_run: JobRowOut | None
    last_success: JobRowOut | None
    steps: list[dict[str, Any]]


class CronEntryOut(BaseModel):
    pipeline: str
    expression: str
    timezone: str
    description: str


class StatusOut(BaseModel):
    version: VersionOut
    store: dict[str, Any]
    pipelines: list[PipelineOut]
    jobs: list[JobRowOut]
    models: list[dict[str, Any]]
    open_findings: int
    source: dict[str, Any]
    watermarks: dict[str, str]
    cron: list[CronEntryOut]


class TableCoverageOut(BaseModel):
    as_of: date_type | None
    counts: dict[str, int]
    latest_known_as_of: date_type | None


class OverviewOut(BaseModel):
    version: VersionOut
    tracked_stocks: int
    scraped_stocks: int
    classified_universe: int
    latest_market_date: date_type | None
    stocks_with_data_on_latest: int
    source: dict[str, Any]
    pipelines: list[PipelineOut]
    analytics: dict[str, TableCoverageOut]
    forecasts: TableCoverageOut
    open_findings: dict[str, int]
    store_revision: str | None
    store_migrated: bool
    last_update: dict[str, str | None]


class QuoteOut(BaseModel):
    ticker_symbol: str
    company_name: str | None
    sector: str | None
    industry: str | None
    price: Measure
    change_pct: Measure
    volume: Measure
    low_52w: Measure
    high_52w: Measure
    market_cap: Measure
    close: Measure
    close_date: date_type | None
    scraped_at: datetime | None
    facts: dict[str, Any] = Field(default_factory=dict)
    source: str


class SectorPerfOut(BaseModel):
    sector: str
    members: int
    known_members: int
    median: Measure


class IndexAvailability(BaseModel):
    status: str
    reason: str | None
    latest_known_as_of: date_type | None
    last: float | None


class MarketOut(BaseModel):
    as_of: date_type
    latest_market_date: date_type | None
    stocks_with_data: int
    universe: int
    quotes: list[QuoteOut]
    performance: dict[str, list[SectorPerfOut]]
    top_movers: list[QuoteOut]
    bottom_movers: list[QuoteOut]
    index: dict[str, IndexAvailability]
    coverage: dict[str, dict[str, int]]


__all__ = [
    "CronEntryOut",
    "IndexAvailability",
    "JobRowOut",
    "MarketOut",
    "Measure",
    "OverviewOut",
    "PipelineOut",
    "QuoteOut",
    "SectorPerfOut",
    "StatusOut",
    "TableCoverageOut",
    "VersionOut",
]
