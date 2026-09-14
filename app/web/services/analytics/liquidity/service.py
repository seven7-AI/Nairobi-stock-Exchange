"""Compute and store liquidity metrics and the cross-sectional score as of a date.

codegraph explore "compute_liquidity liquidity_inputs liquidity_scores"
"""

from __future__ import annotations

from datetime import UTC, date, datetime

from app.web.config import Settings
from app.web.db.analytics import analytics_session
from app.web.db.analytics.models import JobRun, JobStatus
from app.web.db.analytics.services.market_metrics import upsert_market_metrics
from app.web.services.analytics.config import DEFAULT_CONFIG, AnalyticsConfig, register_calc_version
from app.web.services.analytics.liquidity.engine import (
    LiquidityInputs,
    liquidity_inputs,
    liquidity_scores,
)
from app.web.services.analytics.momentum.service import result_rows
from app.web.services.analytics.returns.service import ComputeResult, load_universe
from app.web.services.market_data.sources.nse_scraper import NseScraperSource
from app.web.utils.logger import get_logger

logger = get_logger(__name__)

JOB_NAME = "liquidity"


def compute_liquidity(
    settings: Settings,
    source: NseScraperSource,
    *,
    as_of: date | None = None,
    tickers: list[str] | None = None,
    config: AnalyticsConfig = DEFAULT_CONFIG,
) -> ComputeResult:
    """Per-instrument liquidity metrics plus the universe-wide score.

    The score is a percentile rank across the whole universe, so the inputs are
    computed for every instrument even when only some are written.
    """
    day = as_of or datetime.now(UTC).date()
    started = datetime.now(UTC)
    with analytics_session(settings) as session:
        version = register_calc_version(session, config)
        run = JobRun(job_name=JOB_NAME, started_at=started, as_of_date=day)
        session.add(run)
        session.flush()
        try:
            universe = load_universe(source, config)
            requested = {t.strip().upper() for t in tickers} if tickers else set(universe)
            inputs: dict[str, LiquidityInputs] = {}
            skipped: dict[str, str] = {}
            for ticker, series in universe.items():
                if series.is_empty:
                    skipped[ticker] = "no observations"
                    continue
                snapshots = source.fetch_fundamental_snapshots(ticker, view="overview", end=day)
                inputs[ticker] = liquidity_inputs(series.as_of(day), day, snapshots, config)
            scores = liquidity_scores(inputs, day, config)
            written = 0
            processed: list[str] = []
            known: dict[str, int] = {}
            for ticker, item in inputs.items():
                if ticker not in requested:
                    continue
                results = dict(item.metrics)
                results["liquidity_score"], results["liquidity_bucket"] = scores[ticker]
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
            "processed": len(processed),
            "skipped": skipped,
            "known_counts": known,
        }
        version_id = version.id
    logger.info(
        "liquidity_computed",
        as_of=day.isoformat(),
        processed=len(processed),
        rows=written,
        calc_version_id=version_id,
    )
    return ComputeResult(JOB_NAME, day, version_id, written, tuple(processed), skipped, known)


__all__ = ["JOB_NAME", "compute_liquidity"]
