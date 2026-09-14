"""Compute and store fundamental metrics for the universe as of a date.

Point-in-time by construction: statements are loaded through the availability
rules in ``statements.py``, the sector comes from the classification index as of
the date, and sector-relative growth compares against peers evaluated the same way.

    codegraph explore "compute_fundamentals fundamental_metrics sector_relative"
"""

from __future__ import annotations

from datetime import UTC, date, datetime

from app.web.config import Settings
from app.web.db.analytics import analytics_session
from app.web.db.analytics.models import JobRun, JobStatus
from app.web.db.analytics.services.classifications import load_classifications
from app.web.db.analytics.services.fundamental_metrics import (
    FundamentalRow,
    upsert_fundamental_metrics,
)
from app.web.services.analytics.classification.lookup import ClassificationIndex
from app.web.services.analytics.config import DEFAULT_CONFIG, AnalyticsConfig, register_calc_version
from app.web.services.analytics.fundamentals.engine import (
    FundamentalResult,
    fundamental_metrics,
    sector_relative,
)
from app.web.services.analytics.fundamentals.statements import StatementRow, load_statement_rows
from app.web.services.analytics.measure import Measure
from app.web.services.analytics.returns.service import ComputeResult
from app.web.services.market_data.sources.nse_scraper import NseScraperSource
from app.web.utils.logger import get_logger

logger = get_logger(__name__)

JOB_NAME = "fundamentals"
RELATIVE_GROWTH = ("revenue_growth_1y", "eps_growth_1y", "revenue_cagr_3y", "eps_cagr_3y")


def fundamental_rows(
    ticker: str, as_of: date, results: dict[str, FundamentalResult]
) -> list[FundamentalRow]:
    return [
        FundamentalRow(
            ticker_symbol=ticker,
            as_of_date=as_of,
            metric=metric,
            value=r.measure.value,
            status=r.measure.status.value,
            reason=r.measure.reason,
            period_end=r.period_end,
            period_type=r.period_type,
            provenance=[p.as_dict() for p in r.measure.provenance],
        )
        for metric, r in results.items()
    ]


def load_statements(
    source: NseScraperSource, tickers: list[str], config: AnalyticsConfig
) -> dict[str, list[StatementRow]]:
    if not source.has_financial_statements():
        return {t: [] for t in tickers}
    return {
        ticker: load_statement_rows(source.fetch_financial_statements(ticker), config)
        for ticker in tickers
    }


def compute_fundamentals(
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
            instruments = [i["ticker_symbol"] for i in source.fetch_instruments()]
            requested = {t.strip().upper() for t in tickers} if tickers else set(instruments)
            statements = load_statements(source, instruments, config)
            # Every instrument's metrics are needed for the sector-relative ones.
            results: dict[str, dict[str, FundamentalResult]] = {}
            skipped: dict[str, str] = {}
            for ticker in instruments:
                rows = statements.get(ticker, [])
                if not rows:
                    skipped[ticker] = "no financial statements captured"
                    continue
                assignment = index.sector_for(ticker, day)
                results[ticker] = fundamental_metrics(
                    rows,
                    day,
                    sector_code=assignment.sector_code if assignment else None,
                    config=config,
                )
            written = 0
            processed: list[str] = []
            known: dict[str, int] = {}
            for ticker, own in results.items():
                if ticker not in requested:
                    continue
                peers = [p for p in index.peers_for(ticker, day) if p in results]
                for metric in RELATIVE_GROWTH:
                    peer_measures: list[Measure] = [results[p][metric].measure for p in peers]
                    own[f"{metric}_vs_sector"] = FundamentalResult(
                        sector_relative(
                            own[metric].measure,
                            peer_measures,
                            name=f"{metric} vs sector",
                            min_peers=config.fundamentals.min_peers,
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
        "fundamentals_computed",
        as_of=day.isoformat(),
        processed=len(processed),
        skipped=len(skipped),
        rows=written,
        calc_version_id=version_id,
    )
    return ComputeResult(JOB_NAME, day, version_id, written, tuple(processed), skipped, known)


__all__ = [
    "JOB_NAME",
    "RELATIVE_GROWTH",
    "compute_fundamentals",
    "fundamental_rows",
    "load_statements",
]
