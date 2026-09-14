"""Compute and store factor scores for a date from the stored metric tables.

The universe is every instrument classified in an operating sector on the date
(indices, ETFs and REITs are excluded from the cross-section). Metrics are read
from ``market_metrics`` and ``fundamental_metrics`` as already computed for the
date; run the metric jobs first.

    codegraph explore "compute_factors score_factors metric_table_for"
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, date, datetime

from app.web.config import Settings
from app.web.db.analytics import analytics_session
from app.web.db.analytics.models import JobRun, JobStatus
from app.web.db.analytics.services.classifications import load_classifications
from app.web.db.analytics.services.factor_scores import metric_table_for, upsert_factor_scores
from app.web.services.analytics.classification.lookup import ClassificationIndex
from app.web.services.analytics.classification.taxonomy import OPERATING_SECTORS
from app.web.services.analytics.config import DEFAULT_CONFIG, AnalyticsConfig, register_calc_version
from app.web.services.analytics.factors.engine import FactorScore, score_factors
from app.web.utils.logger import get_logger

logger = get_logger(__name__)

JOB_NAME = "factors"


@dataclass(frozen=True)
class FactorRunResult:
    as_of: date
    calc_version_id: int
    rows_written: int
    universe: tuple[str, ...]
    #: factor -> instruments with a known score
    known_counts: dict[str, int]
    scores: tuple[FactorScore, ...]


def factor_universe(
    index: ClassificationIndex, as_of: date
) -> tuple[list[str], dict[str, dict[str, str | None]]]:
    """Tickers in an operating sector on ``as_of`` plus their sector / industry membership."""
    universe: list[str] = []
    sector: dict[str, str | None] = {}
    industry: dict[str, str | None] = {}
    for ticker in index.tickers:
        assignment = index.sector_for(ticker, as_of)
        if assignment is None or assignment.sector_code not in OPERATING_SECTORS:
            continue
        universe.append(ticker)
        sector[ticker] = assignment.sector_code
        industry[ticker] = assignment.industry
    return universe, {"sector": sector, "industry": industry}


def compute_factors(
    settings: Settings,
    *,
    as_of: date | None = None,
    config: AnalyticsConfig = DEFAULT_CONFIG,
) -> FactorRunResult:
    day = as_of or datetime.now(UTC).date()
    started = datetime.now(UTC)
    with analytics_session(settings) as session:
        version = register_calc_version(session, config)
        run = JobRun(job_name=JOB_NAME, started_at=started, as_of_date=day)
        session.add(run)
        session.flush()
        try:
            index = ClassificationIndex(load_classifications(session))
            universe, groups = factor_universe(index, day)
            metrics = metric_table_for(session, day)
            scores = score_factors(metrics, universe, groups, config)
            written = upsert_factor_scores(
                session, scores, as_of_date=day, calc_version_id=version.id
            )
        except Exception as exc:
            run.status = JobStatus.FAILED
            run.error = f"{type(exc).__name__}: {exc}"
            run.finished_at = datetime.now(UTC)
            raise
        known: dict[str, int] = {}
        for s in scores:
            if s.measure.is_known:
                known[s.factor] = known.get(s.factor, 0) + 1
        run.status = JobStatus.SUCCEEDED
        run.finished_at = datetime.now(UTC)
        run.rows_written = written
        run.watermark = day.isoformat()
        run.details = {
            "calc_version_id": version.id,
            "universe": len(universe),
            "metrics_available": len(metrics),
            "known_counts": known,
        }
        version_id = version.id
    logger.info(
        "factors_computed",
        as_of=day.isoformat(),
        universe=len(universe),
        rows=written,
        known=known,
        calc_version_id=version_id,
    )
    return FactorRunResult(day, version_id, written, tuple(universe), known, tuple(scores))


__all__ = ["JOB_NAME", "FactorRunResult", "compute_factors", "factor_universe"]
