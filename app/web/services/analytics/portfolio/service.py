"""Resolve a hypothetical portfolio's inputs for a date, analyse it, store the result.

codegraph explore "analyse_hypothetical_portfolio analyse_portfolio resolve_window"
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, date, datetime

import pandas as pd

from app.web.config import Settings
from app.web.db.analytics import analytics_session
from app.web.db.analytics.models import JobRun, JobStatus
from app.web.db.analytics.services.classifications import load_classifications
from app.web.db.analytics.services.factor_scores import metric_table_for
from app.web.db.analytics.services.portfolio_analyses import save_portfolio_analysis
from app.web.services.analytics.classification.lookup import ClassificationIndex
from app.web.services.analytics.config import DEFAULT_CONFIG, AnalyticsConfig, register_calc_version
from app.web.services.analytics.measure import Measure
from app.web.services.analytics.portfolio.engine import (
    PortfolioAnalysis,
    PortfolioInputs,
    analyse_portfolio,
    validate_weights,
)
from app.web.services.analytics.returns.service import load_universe
from app.web.services.analytics.risk.engine import resolve_window
from app.web.services.analytics.series import PriceSeries
from app.web.services.market_data.sources.nse_scraper import NseScraperSource
from app.web.utils.logger import get_logger

logger = get_logger(__name__)

JOB_NAME = "portfolio"


@dataclass(frozen=True)
class PortfolioRunResult:
    name: str
    as_of: date
    calc_version_id: int
    row_id: int
    analysis: PortfolioAnalysis


def window_returns(
    series: PriceSeries, as_of: date, config: AnalyticsConfig
) -> pd.Series | Measure:
    """In-segment daily returns over the window, or the measure saying why not."""
    window = resolve_window(series, as_of, config.portfolio.window, "portfolio")
    if isinstance(window, Measure):
        return window
    return window.part.close.pct_change().dropna()


def analyse_hypothetical_portfolio(
    settings: Settings,
    source: NseScraperSource,
    weights: Mapping[str, float],
    *,
    name: str = "adhoc",
    as_of: date | None = None,
    config: AnalyticsConfig = DEFAULT_CONFIG,
) -> PortfolioRunResult:
    day = as_of or datetime.now(UTC).date()
    started = datetime.now(UTC)
    clean = validate_weights(weights, config)
    with analytics_session(settings) as session:
        version = register_calc_version(session, config)
        run = JobRun(job_name=JOB_NAME, started_at=started, as_of_date=day)
        session.add(run)
        session.flush()
        try:
            index = ClassificationIndex(load_classifications(session))
            wanted = [*clean, config.market.benchmark_index]
            universe = load_universe(source, config, tickers=wanted)
            returns: dict[str, pd.Series] = {}
            for ticker in clean:
                series = universe.get(ticker)
                if series is None or series.is_empty:
                    continue
                daily = window_returns(series, day, config)
                if not isinstance(daily, Measure):
                    returns[ticker] = daily
            benchmark_series = universe.get(config.market.benchmark_index)
            benchmark: pd.Series | None = None
            benchmark_reason: str | None = f"no series for {config.market.benchmark_index}"
            if benchmark_series is not None:
                located = window_returns(benchmark_series, day, config)
                if isinstance(located, Measure):
                    benchmark_reason = located.reason
                else:
                    benchmark, benchmark_reason = located, None
            sectors: dict[str, str | None] = {}
            industries: dict[str, str | None] = {}
            for ticker in clean:
                assignment = index.sector_for(ticker, day)
                sectors[ticker] = assignment.sector_code if assignment else None
                industries[ticker] = assignment.industry if assignment else None
            turnover = metric_table_for(session, day).get(("market", "avg_daily_turnover"), {})
            analysis = analyse_portfolio(
                PortfolioInputs(
                    clean, returns, benchmark, sectors, industries, turnover, benchmark_reason
                ),
                config,
            )
            row = save_portfolio_analysis(
                session,
                analysis,
                name=name,
                as_of_date=day,
                notional=config.portfolio.notional,
                calc_version_id=version.id,
            )
        except Exception as exc:
            run.status = JobStatus.FAILED
            run.error = f"{type(exc).__name__}: {exc}"
            run.finished_at = datetime.now(UTC)
            raise
        run.status = JobStatus.SUCCEEDED
        run.finished_at = datetime.now(UTC)
        run.rows_written = 1
        run.watermark = day.isoformat()
        run.details = {
            "calc_version_id": version.id,
            "name": name,
            "positions": len(clean),
            "coverage": analysis.coverage,
            "warnings": len(analysis.warnings),
        }
        version_id, row_id = version.id, row.id
    logger.info(
        "portfolio_analysed",
        name=name,
        as_of=day.isoformat(),
        positions=len(clean),
        coverage=analysis.coverage,
        warnings=len(analysis.warnings),
    )
    return PortfolioRunResult(name, day, version_id, row_id, analysis)


__all__ = ["JOB_NAME", "PortfolioRunResult", "analyse_hypothetical_portfolio", "window_returns"]
