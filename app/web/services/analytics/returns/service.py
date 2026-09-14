"""Compute and store trailing returns for the universe as of a date.

The first market-metrics job. Reads every instrument's observations in one
query, builds a ``PriceSeries`` per ticker, evaluates ``trailing_returns`` as of
the requested date and upserts the rows under the current ``calc_version``.
Records a ``job_runs`` row either way.

    codegraph explore "compute_returns trailing_returns upsert_market_metrics"
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, date, datetime

from app.web.config import Settings
from app.web.db.analytics import analytics_session
from app.web.db.analytics.models import JobRun, JobStatus
from app.web.db.analytics.services.market_metrics import MetricRow, upsert_market_metrics
from app.web.services.analytics.config import DEFAULT_CONFIG, AnalyticsConfig, register_calc_version
from app.web.services.analytics.returns.engine import WindowResult, trailing_returns
from app.web.services.analytics.series import PriceSeries, build_price_series
from app.web.services.market_data.sources.nse_scraper import NseScraperSource
from app.web.utils.logger import get_logger

logger = get_logger(__name__)

JOB_NAME = "returns"


@dataclass(frozen=True)
class ComputeResult:
    job_name: str
    as_of: date
    calc_version_id: int
    rows_written: int
    tickers_processed: tuple[str, ...]
    #: ticker -> why nothing was computed for it (no observations at all).
    tickers_skipped: dict[str, str] = field(default_factory=dict)
    #: metric name -> how many instruments have a KNOWN value for it.
    known_counts: dict[str, int] = field(default_factory=dict)


def metric_rows(ticker: str, as_of: date, results: dict[str, WindowResult]) -> list[MetricRow]:
    rows = []
    for metric, result in results.items():
        measure = result.measure
        rows.append(
            MetricRow(
                ticker_symbol=ticker,
                as_of_date=as_of,
                metric=metric,
                value=measure.value,
                status=measure.status.value,
                reason=measure.reason,
                window_start=result.start,
                window_end=result.end,
                contains_flagged=result.contains_flagged,
                provenance=[p.as_dict() for p in measure.provenance],
            )
        )
    return rows


def load_universe(
    source: NseScraperSource, config: AnalyticsConfig, *, tickers: list[str] | None = None
) -> dict[str, PriceSeries]:
    """Every instrument's full series (or the requested subset), one bulk read."""
    instruments = source.fetch_instruments()
    wanted = [i["ticker_symbol"] for i in instruments]
    if tickers:
        requested = {t.strip().upper() for t in tickers}
        wanted = [t for t in wanted if t in requested]
    observations = source.fetch_observations_bulk(wanted)
    return {
        ticker: build_price_series(ticker, observations.get(ticker, []), config)
        for ticker in wanted
    }


def compute_returns(
    settings: Settings,
    source: NseScraperSource,
    *,
    as_of: date | None = None,
    tickers: list[str] | None = None,
    config: AnalyticsConfig = DEFAULT_CONFIG,
) -> ComputeResult:
    """Trailing returns for every instrument as of ``as_of`` (default: today, UTC)."""
    day = as_of or datetime.now(UTC).date()
    started = datetime.now(UTC)
    with analytics_session(settings) as session:
        version = register_calc_version(session, config)
        run = JobRun(job_name=JOB_NAME, started_at=started, as_of_date=day)
        session.add(run)
        session.flush()
        try:
            universe = load_universe(source, config, tickers=tickers)
            written = 0
            processed: list[str] = []
            skipped: dict[str, str] = {}
            known: dict[str, int] = {}
            for ticker, series in universe.items():
                if series.is_empty:
                    skipped[ticker] = "no observations"
                    continue
                results = trailing_returns(series.as_of(day), day)
                written += upsert_market_metrics(
                    session, metric_rows(ticker, day, results), calc_version_id=version.id
                )
                processed.append(ticker)
                for metric, result in results.items():
                    if result.measure.is_known:
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
            "processed": len(processed),
            "skipped": skipped,
            "known_counts": known,
        }
        version_id = version.id
    logger.info(
        "returns_computed",
        as_of=day.isoformat(),
        processed=len(processed),
        skipped=len(skipped),
        rows=written,
        calc_version_id=version_id,
    )
    return ComputeResult(JOB_NAME, day, version_id, written, tuple(processed), skipped, known)


__all__ = ["JOB_NAME", "ComputeResult", "compute_returns", "load_universe", "metric_rows"]
