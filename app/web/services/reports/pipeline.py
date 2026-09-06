"""Report pipeline orchestration.

**The single implementation of "generate a report".** The HTTP layer reaches it
through a Celery task, and the ``nse-analysis`` CLI calls it directly. Neither
holds a copy of these steps — logic that lives in only one of those paths is a
bug, not a shortcut.

    codegraph explore "run_daily_pipeline report_tasks.py app/cli/main.py"
"""

from __future__ import annotations

from calendar import monthrange
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any

from app.web.config import Settings
from app.web.db.models.enums import ReportKind
from app.web.services.indicators.calculator import (
    calculate_batch,
    classify_market_insights,
    classify_monthly_market_insights,
    classify_weekly_market_insights,
    unavailable_requirements,
)
from app.web.services.indicators.feasibility import analyze_feasibility, summarize_feasibility
from app.web.services.indicators.registry import parse_indicators
from app.web.services.market_data.fetcher import DataFetcher
from app.web.services.market_data.supabase_client import SupabaseConnection
from app.web.services.market_data.validator import validate_merged_rows
from app.web.services.reports.generator import (
    write_daily_report,
    write_monthly_report,
    write_weekly_report,
)
from app.web.utils.logger import get_logger

logger = get_logger("app.web.services.reports.pipeline")


@dataclass(slots=True)
class PipelineResult:
    """RORO result of one report generation."""

    kind: ReportKind
    report_path: Path
    instruments_analyzed: int
    market_summary: dict[str, Any] = field(default_factory=dict)
    period_start: date | None = None
    period_end: date | None = None


@dataclass(slots=True)
class MarketData:
    """Everything one pipeline run needs, fetched exactly once."""

    merged_rows: list[dict[str, Any]]
    calculated: list[dict[str, Any]]
    validation: dict[str, Any]


def load_market_data(settings: Settings, conn: SupabaseConnection) -> MarketData:
    """Fetch, deduplicate, validate and compute indicators — one upstream pass.

    ``merged_rows`` is handed to ``load_historical_from_supabase`` rather than
    letting it re-fetch, which previously doubled every pipeline's reads.
    """
    fetcher = DataFetcher(settings, conn)
    analysis_rows = fetcher.fetch_daily_window(as_of_utc=datetime.now(tz=UTC))
    merged_rows = fetcher.merge_current_data(analysis_rows)
    validation = validate_merged_rows(merged_rows)
    historical = fetcher.load_historical_from_supabase(merged_rows)
    calculated = calculate_batch(merged_rows, historical)

    logger.info(
        "market_data_loaded",
        merged_rows=len(merged_rows),
        calculated_rows=len(calculated),
        historical_rows=len(historical),
    )
    return MarketData(
        merged_rows=merged_rows,
        calculated=calculated,
        validation=validation.model_dump(),
    )


def run_daily_pipeline(settings: Settings, conn: SupabaseConnection) -> PipelineResult:
    """Pull, validate, calculate and render the daily report."""
    data = load_market_data(settings, conn)

    definitions = parse_indicators(settings.indicators_file)
    feasibility_records = analyze_feasibility(definitions)
    market_summary = classify_market_insights(data.calculated)

    report_path = write_daily_report(
        settings=settings,
        market_summary=market_summary,
        indicator_rows=data.calculated,
        feasibility_summary=summarize_feasibility(feasibility_records),
        not_calculable=unavailable_requirements(feasibility_records),
        data_quality=data.validation,
    )
    today = datetime.now(tz=UTC).date()
    logger.info("daily_pipeline_done", report_path=str(report_path))
    return PipelineResult(
        kind=ReportKind.DAILY,
        report_path=report_path,
        instruments_analyzed=len(data.calculated),
        market_summary=market_summary,
        period_start=today,
        period_end=today,
    )


def run_weekly_pipeline(settings: Settings, conn: SupabaseConnection) -> PipelineResult:
    """Render the weekly report for the trailing seven days."""
    data = load_market_data(settings, conn)
    market_summary = classify_weekly_market_insights(data.calculated)

    week_end = datetime.now(tz=UTC).date()
    week_start = week_end - timedelta(days=6)
    report_path = write_weekly_report(
        settings=settings,
        market_summary=market_summary,
        indicator_rows=data.calculated,
        week_start_date=week_start.isoformat(),
        week_end_date=week_end.isoformat(),
    )
    logger.info("weekly_pipeline_done", report_path=str(report_path))
    return PipelineResult(
        kind=ReportKind.WEEKLY,
        report_path=report_path,
        instruments_analyzed=len(data.calculated),
        market_summary=market_summary,
        period_start=week_start,
        period_end=week_end,
    )


def run_monthly_pipeline(settings: Settings, conn: SupabaseConnection) -> PipelineResult:
    """Render the monthly report for the current calendar month."""
    data = load_market_data(settings, conn)
    market_summary = classify_monthly_market_insights(data.calculated)

    now = datetime.now(tz=UTC)
    report_path = write_monthly_report(
        settings=settings,
        market_summary=market_summary,
        indicator_rows=data.calculated,
        month=now.month,
        year=now.year,
    )
    logger.info("monthly_pipeline_done", report_path=str(report_path))
    return PipelineResult(
        kind=ReportKind.MONTHLY,
        report_path=report_path,
        instruments_analyzed=len(data.calculated),
        market_summary=market_summary,
        period_start=date(now.year, now.month, 1),
        period_end=date(now.year, now.month, monthrange(now.year, now.month)[1]),
    )


#: Dispatch table so a caller can select a pipeline by ReportKind.
PIPELINES = {
    ReportKind.DAILY: run_daily_pipeline,
    ReportKind.WEEKLY: run_weekly_pipeline,
    ReportKind.MONTHLY: run_monthly_pipeline,
}


def run_pipeline(kind: ReportKind, settings: Settings, conn: SupabaseConnection) -> PipelineResult:
    """Run the pipeline for one report kind."""
    return PIPELINES[kind](settings, conn)


__all__ = [
    "PIPELINES",
    "MarketData",
    "PipelineResult",
    "load_market_data",
    "run_daily_pipeline",
    "run_monthly_pipeline",
    "run_pipeline",
    "run_weekly_pipeline",
]
