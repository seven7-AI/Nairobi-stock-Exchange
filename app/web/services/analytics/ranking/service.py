"""Compute and store the composite ranking for a date from stored factor scores.

Reads ``factor_scores`` (the newest computation per ticker/factor for the date),
the known market and fundamental metric values the detectors need, and the
point-in-time sector / industry membership; writes ``stock_rankings`` and makes
sure the model is in ``model_registry``. Run the factor job first.

    codegraph explore "compute_rankings rank_universe upsert_rankings"
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, date, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.web.config import Settings
from app.web.db.analytics import analytics_session
from app.web.db.analytics.models import (
    JobRun,
    JobStatus,
    ModelKind,
    ModelRegistryEntry,
    ModelStatus,
)
from app.web.db.analytics.services.classifications import load_classifications
from app.web.db.analytics.services.factor_scores import load_factor_scores, metric_table_for
from app.web.db.analytics.services.stock_rankings import upsert_rankings
from app.web.services.analytics.classification.lookup import ClassificationIndex
from app.web.services.analytics.config import DEFAULT_CONFIG, AnalyticsConfig, register_calc_version
from app.web.services.analytics.factors.service import factor_universe
from app.web.services.analytics.measure import Measure
from app.web.services.analytics.ranking.engine import FactorInput, Ranking, rank_universe
from app.web.utils.logger import get_logger

logger = get_logger(__name__)

JOB_NAME = "rankings"

#: Metrics the detectors and gates read, by source table.
DETECTOR_METRICS: dict[str, tuple[str, ...]] = {
    "market": ("momentum_12m_1m", "liquidity_score"),
    "fundamental": (
        "pe_vs_market",
        "pb",
        "dividend_yield",
        "revenue_growth_1y",
        "eps_growth_1y",
        "revenue_cagr_3y",
        "eps_cagr_3y",
        "dividend_cagr_3y",
        "roe",
        "roa",
        "roe_trend",
        "net_margin_trend",
        "debt_to_equity_trend",
        "debt_to_equity",
        "fcf",
        "fcf_margin",
        "dividend_cut",
    ),
}


@dataclass(frozen=True)
class RankingRunResult:
    as_of: date
    calc_version_id: int
    model_id: int
    rows_written: int
    universe: tuple[str, ...]
    scored: int
    classes: dict[str, int]
    rankings: tuple[Ranking, ...]


def register_model(session: Session, config: AnalyticsConfig) -> ModelRegistryEntry:
    """Get-or-create the registry row for the configured factor model."""
    cfg = config.ranking
    existing = session.execute(
        select(ModelRegistryEntry).where(
            ModelRegistryEntry.name == cfg.model_name,
            ModelRegistryEntry.version == cfg.model_version,
        )
    ).scalar_one_or_none()
    if existing is not None:
        return existing
    entry = ModelRegistryEntry(
        name=cfg.model_name,
        version=cfg.model_version,
        kind=ModelKind.FACTOR,
        status=ModelStatus.CANDIDATE,
        description="Weighted market-percentile composite of the factor scores",
        features=list(cfg.weights),
        params=cfg.model_dump(mode="json"),
    )
    session.add(entry)
    session.flush()
    return entry


def factor_inputs_for(
    session: Session, as_of: date, universe: list[str]
) -> dict[str, dict[str, FactorInput]]:
    """The newest factor score per (ticker, factor) for the date, for the universe."""
    rows = load_factor_scores(session, as_of_date=as_of)
    wanted = set(universe)
    out: dict[str, dict[str, FactorInput]] = {}
    newest: dict[tuple[str, str], datetime] = {}
    for row in rows:
        if row.ticker_symbol not in wanted:
            continue
        key = (row.ticker_symbol, row.factor)
        if key in newest and newest[key] >= row.computed_at:
            continue
        newest[key] = row.computed_at
        out.setdefault(row.ticker_symbol, {})[row.factor] = FactorInput(
            factor=row.factor,
            percentile_market=row.percentile_market,
            percentile_sector=row.percentile_sector,
            percentile_industry=row.percentile_industry,
            coverage=row.coverage,
            status=row.status,
        )
    return out


def detector_metrics_for(session: Session, as_of: date) -> dict[str, dict[str, Measure]]:
    table = metric_table_for(session, as_of)
    out: dict[str, dict[str, Measure]] = {}
    for source, names in DETECTOR_METRICS.items():
        for name in names:
            for ticker, value in table.get((source, name), {}).items():
                out.setdefault(ticker, {})[name] = Measure.known(value)
    return out


def compute_rankings(
    settings: Settings,
    *,
    as_of: date | None = None,
    config: AnalyticsConfig = DEFAULT_CONFIG,
) -> RankingRunResult:
    day = as_of or datetime.now(UTC).date()
    started = datetime.now(UTC)
    with analytics_session(settings) as session:
        version = register_calc_version(session, config)
        model = register_model(session, config)
        run = JobRun(job_name=JOB_NAME, started_at=started, as_of_date=day)
        session.add(run)
        session.flush()
        try:
            index = ClassificationIndex(load_classifications(session))
            universe, groups = factor_universe(index, day)
            factors = factor_inputs_for(session, day, universe)
            metrics = detector_metrics_for(session, day)
            rankings = rank_universe(factors, metrics, groups, config)
            written = upsert_rankings(
                session,
                rankings,
                as_of_date=day,
                model_name=model.name,
                model_version=model.version,
                calc_version_id=version.id,
            )
        except Exception as exc:
            run.status = JobStatus.FAILED
            run.error = f"{type(exc).__name__}: {exc}"
            run.finished_at = datetime.now(UTC)
            raise
        classes: dict[str, int] = {}
        for r in rankings:
            label = r.classification or "unscored"
            classes[label] = classes.get(label, 0) + 1
        scored = sum(1 for r in rankings if r.overall.is_known)
        run.status = JobStatus.SUCCEEDED
        run.finished_at = datetime.now(UTC)
        run.rows_written = written
        run.watermark = day.isoformat()
        run.details = {
            "calc_version_id": version.id,
            "model": f"{model.name} v{model.version}",
            "universe": len(universe),
            "with_factors": len(factors),
            "scored": scored,
            "classes": classes,
        }
        version_id, model_id = version.id, model.id
    logger.info(
        "rankings_computed",
        as_of=day.isoformat(),
        universe=len(universe),
        scored=scored,
        rows=written,
        calc_version_id=version_id,
    )
    return RankingRunResult(
        day, version_id, model_id, written, tuple(universe), scored, classes, tuple(rankings)
    )


__all__ = [
    "DETECTOR_METRICS",
    "JOB_NAME",
    "RankingRunResult",
    "compute_rankings",
    "detector_metrics_for",
    "factor_inputs_for",
    "register_model",
]
