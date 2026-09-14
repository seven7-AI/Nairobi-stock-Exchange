"""Compute and store risk metrics (and the correlation matrix) as of a date.

codegraph explore "compute_risk risk_metrics correlation_matrix upsert_correlations"
"""

from __future__ import annotations

from datetime import UTC, date, datetime

from app.web.config import Settings
from app.web.db.analytics import analytics_session
from app.web.db.analytics.models import JobRun, JobStatus
from app.web.db.analytics.services.classifications import load_classifications
from app.web.db.analytics.services.correlations import upsert_correlations
from app.web.db.analytics.services.market_metrics import upsert_market_metrics
from app.web.services.analytics.classification.lookup import ClassificationIndex
from app.web.services.analytics.config import DEFAULT_CONFIG, AnalyticsConfig, register_calc_version
from app.web.services.analytics.momentum.service import load_benchmark, result_rows
from app.web.services.analytics.returns.service import ComputeResult, load_universe
from app.web.services.analytics.risk.engine import correlation_matrix, risk_metrics
from app.web.services.market_data.sources.nse_scraper import NseScraperSource
from app.web.utils.logger import get_logger

logger = get_logger(__name__)

JOB_NAME = "risk"


def compute_risk(
    settings: Settings,
    source: NseScraperSource,
    *,
    as_of: date | None = None,
    tickers: list[str] | None = None,
    config: AnalyticsConfig = DEFAULT_CONFIG,
    with_correlation_matrix: bool = True,
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
            universe = load_universe(source, config)
            benchmark = load_benchmark(source, config).as_of(day)
            requested = {t.strip().upper() for t in tickers} if tickers else set(universe)
            truncated = {t: s.as_of(day) for t, s in universe.items() if not s.is_empty}
            written = 0
            processed: list[str] = []
            skipped: dict[str, str] = {}
            known: dict[str, int] = {}
            for ticker in universe:
                if ticker not in requested:
                    continue
                series = truncated.get(ticker)
                if series is None or series.is_empty:
                    skipped[ticker] = f"no observations on or before {day}"
                    continue
                peers = {
                    peer: truncated[peer]
                    for peer in index.peers_for(ticker, day)
                    if peer in truncated
                }
                results = risk_metrics(series, day, benchmark=benchmark, peers=peers, config=config)
                written += upsert_market_metrics(
                    session, result_rows(ticker, day, results), calc_version_id=version.id
                )
                processed.append(ticker)
                for metric, r in results.items():
                    if r.measure.is_known:
                        known[metric] = known.get(metric, 0) + 1
            pairs = 0
            if with_correlation_matrix and not tickers:
                matrix = correlation_matrix(truncated, day, config.risk.correlation_window, config)
                pairs = upsert_correlations(
                    session,
                    matrix,
                    as_of_date=day,
                    window=config.risk.correlation_window,
                    calc_version_id=version.id,
                )
        except Exception as exc:
            run.status = JobStatus.FAILED
            run.error = f"{type(exc).__name__}: {exc}"
            run.finished_at = datetime.now(UTC)
            raise
        run.status = JobStatus.SUCCEEDED
        run.finished_at = datetime.now(UTC)
        run.rows_written = written + pairs
        run.rows_skipped = len(skipped)
        run.watermark = day.isoformat()
        run.details = {
            "calc_version_id": version.id,
            "benchmark": benchmark.ticker_symbol,
            "processed": len(processed),
            "skipped": skipped,
            "known_counts": known,
            "correlation_pairs": pairs,
        }
        version_id = version.id
    logger.info(
        "risk_computed",
        as_of=day.isoformat(),
        processed=len(processed),
        rows=written,
        correlation_pairs=pairs,
        calc_version_id=version_id,
    )
    return ComputeResult(
        JOB_NAME, day, version_id, written + pairs, tuple(processed), skipped, known
    )


__all__ = ["JOB_NAME", "compute_risk"]
