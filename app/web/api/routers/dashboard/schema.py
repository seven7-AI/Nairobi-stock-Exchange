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


class StockRowOut(BaseModel):
    ticker_symbol: str
    company_name: str | None
    sector: str | None
    industry: str | None
    price: Measure
    change_pct: Measure
    volume: Measure
    market_cap: Measure
    pe: Measure
    pb: Measure
    dividend_yield: Measure
    factor_percentiles: dict[str, float | None]
    overall_score: Measure
    classification: str | None
    market_rank: int | None
    confidence: float | None
    value_trap_risk: int | None
    compounder_score: float | None
    as_of: date_type | None


class StockListPage(BaseModel):
    items: list[StockRowOut]
    next_cursor: str | None
    total: int
    as_of: date_type | None
    sort: str
    order: str


class PricePointOut(BaseModel):
    date: date_type
    close: float
    volume: float | None
    change_pct: float | None
    source: str
    flagged: bool


class GapOut(BaseModel):
    after: date_type
    before: date_type
    days: int


class Availability(BaseModel):
    value: float | None = None
    status: str
    reason: str | None = None
    latest_known_as_of: date_type | None = None


class PriceHistoryOut(BaseModel):
    ticker_symbol: str
    range: str
    interval: str
    start: date_type | None
    end: date_type | None
    points: list[PricePointOut]
    gaps: list[GapOut]
    gap_threshold_days: int
    n_observations: int
    availability: Availability
    source_tickers: list[str]
    missing_start: dict[str, Any] | None = None


class FiscalYearOut(BaseModel):
    period_end: date_type
    label: str
    currency: str | None
    values: dict[str, Measure]


class StatementsOut(BaseModel):
    ticker_symbol: str
    as_of: date_type
    period_type: str
    concepts: list[str]
    years: list[FiscalYearOut]
    availability: Availability


class SectorComparisonRow(BaseModel):
    metric: str
    stock: Measure
    sector_median: Measure
    sector_members: int
    known_peers: int
    percentile_in_sector: float | None


class GeographicOut(BaseModel):
    status: str
    reason: str
    segments: list[dict[str, Any]] = Field(default_factory=list)


class StockDetailOut(BaseModel):
    ticker_symbol: str
    quote: QuoteOut
    profile: dict[str, Any]
    prices: PriceHistoryOut
    sector_comparison: list[SectorComparisonRow]
    statements: StatementsOut
    facts: dict[str, Any]
    geographic: GeographicOut
    forecast_availability: Availability
    links: dict[str, str]


__all__ = [
    "Availability",
    "CronEntryOut",
    "FiscalYearOut",
    "GapOut",
    "GeographicOut",
    "IndexAvailability",
    "JobRowOut",
    "MarketOut",
    "Measure",
    "OverviewOut",
    "PipelineOut",
    "PriceHistoryOut",
    "PricePointOut",
    "QuoteOut",
    "SectorComparisonRow",
    "SectorPerfOut",
    "StatementsOut",
    "StatusOut",
    "StockDetailOut",
    "StockListPage",
    "StockRowOut",
    "TableCoverageOut",
    "VersionOut",
]
