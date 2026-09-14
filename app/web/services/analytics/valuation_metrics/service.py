"""Compute and store valuation multiples, dividend metrics and the sector/market medians.

codegraph explore "compute_valuation_metrics valuation_metrics relative_to_group"
"""

from __future__ import annotations

from datetime import UTC, date, datetime

from app.web.config import Settings
from app.web.db.analytics import analytics_session
from app.web.db.analytics.models import JobRun, JobStatus
from app.web.db.analytics.services.classifications import load_classifications
from app.web.db.analytics.services.fundamental_metrics import upsert_fundamental_metrics
from app.web.services.analytics.classification.lookup import ClassificationIndex
from app.web.services.analytics.classification.taxonomy import OPERATING_SECTORS
from app.web.services.analytics.config import DEFAULT_CONFIG, AnalyticsConfig, register_calc_version
from app.web.services.analytics.fundamentals.engine import FundamentalResult
from app.web.services.analytics.fundamentals.service import fundamental_rows, load_statements
from app.web.services.analytics.returns.service import ComputeResult, load_universe
from app.web.services.analytics.valuation_metrics.engine import relative_to_group, valuation_metrics
from app.web.services.market_data.sources.nse_scraper import NseScraperSource
from app.web.utils.logger import get_logger

logger = get_logger(__name__)

JOB_NAME = "valuation_metrics"
RELATIVE_MULTIPLES = ("pe", "pb", "ps", "ev_ebitda", "dividend_yield")


def compute_valuation_metrics(
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
            universe = load_universe(source, config)
            instruments = list(universe)
            requested = {t.strip().upper() for t in tickers} if tickers else set(instruments)
            statements = load_statements(source, instruments, config)
            results: dict[str, dict[str, FundamentalResult]] = {}
            skipped: dict[str, str] = {}
            for ticker in instruments:
                rows = statements.get(ticker, [])
                if not rows:
                    skipped[ticker] = "no financial statements captured"
                    continue
                assignment = index.sector_for(ticker, day)
                results[ticker] = valuation_metrics(
                    rows,
                    universe[ticker].as_of(day),
                    day,
                    sector_code=assignment.sector_code if assignment else None,
                    config=config,
                )
            market = [
                t
                for t in results
                if (a := index.sector_for(t, day)) is not None
                and a.sector_code in OPERATING_SECTORS
            ]
            written = 0
            processed: list[str] = []
            known: dict[str, int] = {}
            for ticker, own in results.items():
                if ticker not in requested:
                    continue
                peers = [p for p in index.peers_for(ticker, day) if p in results]
                others = [m for m in market if m != ticker]
                for metric in RELATIVE_MULTIPLES:
                    own[f"{metric}_vs_sector"] = FundamentalResult(
                        relative_to_group(
                            own[metric].measure,
                            [results[p][metric].measure for p in peers],
                            name=f"{metric} vs sector",
                            min_members=config.valuation.min_peers,
                        ),
                        own[metric].period_end,
                        own[metric].period_type,
                    )
                    own[f"{metric}_vs_market"] = FundamentalResult(
                        relative_to_group(
                            own[metric].measure,
                            [results[m][metric].measure for m in others],
                            name=f"{metric} vs market",
                            min_members=config.valuation.min_peers,
                        ),
                        own[metric].period_end,
                        own[metric].period_type,
                    )
                written += upsert_fundamental_metrics(
                    session, fundamental_rows(ticker, day, own), calc_version_id=version.id
                )
                processed.append(ticker)
                for metric, r in own.items():
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
        "valuation_metrics_computed",
        as_of=day.isoformat(),
        processed=len(processed),
        skipped=len(skipped),
        rows=written,
        calc_version_id=version_id,
    )
    return ComputeResult(JOB_NAME, day, version_id, written, tuple(processed), skipped, known)


__all__ = ["JOB_NAME", "RELATIVE_MULTIPLES", "compute_valuation_metrics"]
