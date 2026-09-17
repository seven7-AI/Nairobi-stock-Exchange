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


class FactorCellOut(BaseModel):
    score: Measure
    coverage: float
    percentile_market: float | None
    percentile_sector: float | None
    percentile_industry: float | None


class AnalyticsRowOut(BaseModel):
    ticker_symbol: str
    sector: str | None
    industry: str | None
    overall: Measure
    classification: str | None
    confidence: float
    market_rank: int | None
    sector_rank: int | None
    industry_rank: int | None
    value_trap_risk: int | None
    compounder_score: float | None
    positive_factors: list[str]
    negative_factors: list[str]
    factors: dict[str, FactorCellOut]
    relative: dict[str, Measure]


class AnalyticsOut(BaseModel):
    as_of: date_type
    model: str
    available_dates: list[date_type]
    factor_names: list[str]
    rows: list[AnalyticsRowOut]
    coverage: dict[str, dict[str, int]]
    latest_known_as_of: date_type | None


class ForecastCellOut(BaseModel):
    expected_return: Measure
    q05: float | None
    q25: float | None
    q50: float | None
    q75: float | None
    q95: float | None
    p_positive: float | None
    p_outperform: float | None
    expected_vol: float | None
    p_drawdown: float | None
    drawdown_threshold: float | None
    benchmark: str | None


class TickerForecastsOut(BaseModel):
    ticker_symbol: str
    sector: str | None
    as_of: date_type
    price: float | None
    models: dict[str, dict[str, ForecastCellOut]]
    scenarios: dict[str, Any] | None
    simulation: dict[str, Any] | None


class ForecastsOut(BaseModel):
    as_of: date_type
    availability: Availability
    latest_known_as_of: date_type | None
    available_dates: list[date_type]
    tickers: list[str]
    items: list[TickerForecastsOut]
    accuracy: dict[str, dict[str, dict[str, Any]]]
    regime: dict[str, Any]
    models: list[dict[str, Any]]
    disclaimer: str


class SignalItemOut(BaseModel):
    ticker_symbol: str
    sector: str | None
    classification: str | None
    overall_score: Measure
    confidence: float
    market_rank: int | None
    positive_factors: list[str]
    negative_factors: list[str]
    link: str
    extra: dict[str, Any] = Field(default_factory=dict)


class RiskFlagOut(BaseModel):
    kind: str
    ticker_symbol: str | None
    severity: str
    check_name: str | None
    detail: str
    trade_date: date_type | None
    link: str | None


class SignalsOut(BaseModel):
    as_of: date_type
    model: str
    universe: int
    scored: int
    unscored: int
    unscored_reasons: dict[str, int]
    buy_candidates: list[SignalItemOut]
    watch: list[SignalItemOut]
    neutral: list[SignalItemOut]
    weak: list[SignalItemOut]
    avoid: list[SignalItemOut]
    value_traps: list[SignalItemOut]
    compounders: list[SignalItemOut]
    compounder_threshold: float
    valuation_upside: list[dict[str, Any]]
    valuation_downside: list[dict[str, Any]]
    risk_flags: list[RiskFlagOut]
    factor_combinations: dict[str, list[SignalItemOut]]
    disclaimer: str


class BacktestSummaryOut(BaseModel):
    run_id: int
    name: str
    purpose: str
    model: str
    start_date: date_type
    end_date: date_type
    top_n: int
    cost_rate: float
    segments: int
    status: str
    reason: str | None
    linked_total_return: Measure
    first_segment: dict[str, Measure]
    benchmarks: list[str]


class BacktestPageOut(BaseModel):
    items: list[BacktestSummaryOut]
    next_cursor: str | None
    total: int


class BacktestDetailOut(BaseModel):
    run: BacktestSummaryOut
    weights: dict[str, float]
    costs: dict[str, float]
    results: dict[str, dict[str, dict[str, Measure]]]
    equity: list[dict[str, Any]]
    max_drawdown: Measure
    turnover: list[dict[str, Any]]
    disclaimer: str


__all__ = [
    "AnalyticsOut",
    "AnalyticsRowOut",
    "Availability",
    "BacktestDetailOut",
    "BacktestPageOut",
    "BacktestSummaryOut",
    "CronEntryOut",
    "FactorCellOut",
    "FiscalYearOut",
    "ForecastCellOut",
    "ForecastsOut",
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
    "RiskFlagOut",
    "SectorComparisonRow",
    "SectorPerfOut",
    "SignalItemOut",
    "SignalsOut",
    "StatementsOut",
    "StatusOut",
    "StockDetailOut",
    "StockListPage",
    "StockRowOut",
    "TableCoverageOut",
    "TickerForecastsOut",
    "VersionOut",
]
