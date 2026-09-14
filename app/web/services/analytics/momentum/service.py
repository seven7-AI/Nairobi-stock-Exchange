"""Compute and store momentum metrics for the universe as of a date.

Loads every series once, the benchmark index and the point-in-time sector
membership, then evaluates ``momentum_metrics`` per instrument.

    codegraph explore "compute_momentum momentum_metrics ClassificationIndex"
"""

from __future__ import annotations

from datetime import UTC, date, datetime

from app.web.config import Settings
from app.web.db.analytics import analytics_session
from app.web.db.analytics.models import JobRun, JobStatus
from app.web.db.analytics.services.classifications import load_classifications
from app.web.db.analytics.services.market_metrics import MetricRow, upsert_market_metrics
from app.web.services.analytics.classification.lookup import ClassificationIndex
from app.web.services.analytics.config import DEFAULT_CONFIG, AnalyticsConfig, register_calc_version
from app.web.services.analytics.momentum.engine import MetricResult, momentum_metrics
from app.web.services.analytics.returns.service import ComputeResult, load_universe
from app.web.services.analytics.series import PriceSeries, build_price_series
from app.web.services.market_data.sources.nse_scraper import NseScraperSource
from app.web.utils.logger import get_logger

logger = get_logger(__name__)

JOB_NAME = "momentum"


def result_rows(ticker: str, as_of: date, results: dict[str, MetricResult]) -> list[MetricRow]:
    return [
        MetricRow(
            ticker_symbol=ticker,
            as_of_date=as_of,
            metric=metric,
            value=r.measure.value,
            status=r.measure.status.value,
            reason=r.measure.reason,
            window_start=r.window_start,
            window_end=r.window_end,
            contains_flagged=r.contains_flagged,
            provenance=[p.as_dict() for p in r.measure.provenance],
        )
        for metric, r in results.items()
    ]


def load_benchmark(source: NseScraperSource, config: AnalyticsConfig) -> PriceSeries:
    """The configured benchmark index, falling back to the secondary when it is empty."""
    for symbol in (config.market.benchmark_index, config.market.secondary_benchmark_index):
        series = build_price_series(symbol, source.fetch_observations(symbol), config)
        if not series.is_empty:
            return series
    return build_price_series(config.market.benchmark_index, [], config)


def compute_momentum(
    settings: Settings,
    source: NseScraperSource,
    *,
    as_of: date | None = None,
    tickers: list[str] | None = None,
    config: AnalyticsConfig = DEFAULT_CONFIG,
) -> ComputeResult:
    day = as_of or datetime.now(UTC).date()
    started = datetime.now(UTC)
    with analytics_session(settings) as session:
        version = register_calc_version(session, config)
        run = JobRun(job_name=JOB_NAME, started_at=started, as_of_date=day)
        session.add(run)
        session.flush()
        try:
            index = ClassificationIndex(load_classifications(session))
            # Peers need the whole universe even when only some tickers are requested.
            universe = load_universe(source, config)
            benchmark = load_benchmark(source, config)
            requested = {t.strip().upper() for t in tickers} if tickers else set(universe)
            written = 0
            processed: list[str] = []
            skipped: dict[str, str] = {}
            known: dict[str, int] = {}
            for ticker, series in universe.items():
                if ticker not in requested:
                    continue
                if series.is_empty:
                    skipped[ticker] = "no observations"
                    continue
                peers = {
                    peer: universe[peer].as_of(day)
                    for peer in index.peers_for(ticker, day)
                    if peer in universe and not universe[peer].is_empty
                }
                results = momentum_metrics(
                    series.as_of(day),
                    day,
                    benchmark=benchmark.as_of(day),
                    peers=peers,
                    config=config,
                )
                written += upsert_market_metrics(
                    session, result_rows(ticker, day, results), calc_version_id=version.id
                )
                processed.append(ticker)
                for metric, r in results.items():
                    if r.measure.is_known:
                        known[metric] = known.get(metric, 0) + 1
        except Exception as exc:
            run.status = JobStatus.FAILED
            run.error = f"{type(exc).__name__}: {exc}"
            run.finished_at = datetime.now(UTC)
            raise
        run.status = JobStatus.SUCCEEDED
        run.finished_at = datetime.now(UTC)
        run.rows_written = written
        run.rows_skipped = len(skipped)
        run.watermark = day.isoformat()
        run.details = {
            "calc_version_id": version.id,
            "benchmark": benchmark.ticker_symbol,
            "processed": len(processed),
            "skipped": skipped,
            "known_counts": known,
        }
        version_id = version.id
    logger.info(
        "momentum_computed",
        as_of=day.isoformat(),
        processed=len(processed),
        skipped=len(skipped),
        rows=written,
        calc_version_id=version_id,
    )
    return ComputeResult(JOB_NAME, day, version_id, written, tuple(processed), skipped, known)


__all__ = ["JOB_NAME", "compute_momentum", "load_benchmark", "result_rows"]
