"""Forecast jobs: compute, evaluate once the horizon has elapsed, walk-forward.

Forecasts see only prices on or before their origin (``PriceSeries.as_of``); the
evaluation reads the full series and writes a row only when the target date has
data within the gap threshold and the path does not cross a data gap. Model rows
in ``model_registry`` carry the out-of-sample summary per horizon; a candidate is
admitted (``active``) only when it beats every baseline.

    codegraph explore "compute_forecasts evaluate_forecasts walk_forward admit_models"
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from typing import Any

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
from app.web.db.analytics.services.forecasts import (
    load_evaluations,
    unevaluated_forecasts,
    upsert_evaluations,
    upsert_forecasts,
)
from app.web.services.analytics.classification.lookup import ClassificationIndex
from app.web.services.analytics.classification.taxonomy import OPERATING_SECTORS
from app.web.services.analytics.config import DEFAULT_CONFIG, AnalyticsConfig, register_calc_version
from app.web.services.analytics.forecasting.engine import (
    Evaluation,
    Forecast,
    beats_baselines,
    evaluate_forecast,
    forecast_returns,
    monthly_series,
    realised_return,
    shift_forward,
    summarise,
)
from app.web.services.analytics.measure import Measure
from app.web.services.analytics.returns.service import load_universe
from app.web.services.analytics.series import PriceSeries
from app.web.services.market_data.sources.nse_scraper import NseScraperSource
from app.web.utils.logger import get_logger

logger = get_logger(__name__)

JOB_FORECAST = "forecasts"
JOB_EVALUATE = "forecast_evaluation"
JOB_WALK_FORWARD = "forecast_walk_forward"
MODEL_VERSION = "1"


@dataclass(frozen=True)
class ForecastRunResult:
    as_of: date
    calc_version_id: int
    rows_written: int
    tickers: tuple[str, ...]
    #: model -> forecasts with a known expected return
    known_counts: dict[str, int]
    skipped: dict[str, str] = field(default_factory=dict)


@dataclass(frozen=True)
class EvaluationRunResult:
    as_of: date
    evaluated: int
    pending: int
    skipped: dict[str, int]
    summary: dict[str, dict[str, Any]]
    admitted: tuple[str, ...]


def register_models(session: Session, config: AnalyticsConfig) -> dict[str, ModelRegistryEntry]:
    out: dict[str, ModelRegistryEntry] = {}
    cfg = config.forecast
    for name in tuple(cfg.models) + tuple(cfg.candidate_models):
        entry = session.execute(
            select(ModelRegistryEntry).where(
                ModelRegistryEntry.name == name, ModelRegistryEntry.version == MODEL_VERSION
            )
        ).scalar_one_or_none()
        if entry is None:
            entry = ModelRegistryEntry(
                name=name,
                version=MODEL_VERSION,
                kind=ModelKind.FORECAST,
                status=ModelStatus.ACTIVE if name in cfg.models else ModelStatus.CANDIDATE,
                description=(
                    f"{name} return-forecast "
                    f"{'baseline' if name in cfg.models else 'candidate'} on monthly log returns"
                ),
                features=["monthly_log_returns"],
                params=cfg.model_dump(mode="json"),
            )
            session.add(entry)
            session.flush()
        out[name] = entry
    return out


def forecast_universe(index: ClassificationIndex, tickers: Sequence[str], as_of: date) -> list[str]:
    """Operating-sector instruments classified on the date (indices are benchmarks, not targets)."""
    return [
        t
        for t in tickers
        if (a := index.sector_for(t, as_of)) is not None and a.sector_code in OPERATING_SECTORS
    ]


def _forecast_one(
    ticker: str,
    series: PriceSeries,
    benchmark: PriceSeries | None,
    as_of: date,
    config: AnalyticsConfig,
) -> list[Forecast]:
    stock = monthly_series(series, as_of, config)
    bench = monthly_series(benchmark, as_of, config) if benchmark is not None else None
    return forecast_returns(stock, bench, config, ticker=ticker)


def compute_forecasts(
    settings: Settings,
    source: NseScraperSource,
    *,
    as_of: date | None = None,
    tickers: list[str] | None = None,
    config: AnalyticsConfig = DEFAULT_CONFIG,
) -> ForecastRunResult:
    day = as_of or datetime.now(UTC).date()
    started = datetime.now(UTC)
    with analytics_session(settings) as session:
        version = register_calc_version(session, config)
        register_models(session, config)
        run = JobRun(job_name=JOB_FORECAST, started_at=started, as_of_date=day)
        session.add(run)
        session.flush()
        try:
            index = ClassificationIndex(load_classifications(session))
            universe = load_universe(source, config)
            benchmark = universe.get(config.market.benchmark_index)
            wanted = forecast_universe(index, list(universe), day)
            if tickers:
                requested = {t.strip().upper() for t in tickers}
                wanted = [t for t in wanted if t in requested]
            forecasts: list[Forecast] = []
            skipped: dict[str, str] = {}
            for ticker in wanted:
                series = universe[ticker]
                if series.is_empty:
                    skipped[ticker] = "no observations"
                    continue
                forecasts.extend(_forecast_one(ticker, series, benchmark, day, config))
            written = upsert_forecasts(
                session,
                forecasts,
                as_of_date=day,
                model_version=MODEL_VERSION,
                benchmark=config.market.benchmark_index,
                drawdown_threshold=config.forecast.drawdown_threshold,
                calc_version_id=version.id,
            )
        except Exception as exc:
            run.status = JobStatus.FAILED
            run.error = f"{type(exc).__name__}: {exc}"
            run.finished_at = datetime.now(UTC)
            raise
        known: dict[str, int] = {}
        for f in forecasts:
            if f.measure.is_known:
                known[f.model] = known.get(f.model, 0) + 1
        run.status = JobStatus.SUCCEEDED
        run.finished_at = datetime.now(UTC)
        run.rows_written = written
        run.watermark = day.isoformat()
        run.details = {
            "calc_version_id": version.id,
            "universe": len(wanted),
            "known_counts": known,
            "skipped": len(skipped),
        }
        version_id = version.id
    logger.info(
        "forecasts_computed", as_of=day.isoformat(), universe=len(wanted), rows=written, known=known
    )
    return ForecastRunResult(day, version_id, written, tuple(wanted), known, skipped)


def _evaluate_rows(
    session: Session,
    universe: dict[str, PriceSeries],
    benchmark: PriceSeries | None,
    as_of: date,
    config: AnalyticsConfig,
    *,
    tickers: Sequence[str] | None,
) -> tuple[int, int, dict[str, int]]:
    """Write evaluations for every known forecast whose horizon has elapsed by ``as_of``."""
    pending = unevaluated_forecasts(session, tickers=tickers)
    items: list[tuple[int, Evaluation]] = []
    not_yet = 0
    skipped: dict[str, int] = {}
    for row in pending:
        if shift_forward(row.as_of_date, row.horizon_months) > as_of:
            not_yet += 1
            continue
        series = universe.get(row.ticker_symbol)
        if series is None:
            skipped["no series"] = skipped.get("no series", 0) + 1
            continue
        realised = realised_return(series.as_of(as_of), row.as_of_date, row.horizon_months, config)
        if isinstance(realised, Measure):
            key = (realised.reason or "unavailable").split(":")[0]
            skipped[key] = skipped.get(key, 0) + 1
            continue
        value, end_day = realised
        bench_value: float | None = None
        if benchmark is not None and row.p_outperform is not None:
            bench = realised_return(
                benchmark.as_of(as_of), row.as_of_date, row.horizon_months, config
            )
            bench_value = None if isinstance(bench, Measure) else bench[0]
        forecast = Forecast(
            row.ticker_symbol,
            row.horizon_months,
            row.model,
            Measure.known(float(row.expected_return or 0.0))
            if row.expected_return
            else Measure.zero(),
            quantiles={"q05": row.q05, "q95": row.q95}
            if row.q05 is not None and row.q95 is not None
            else {},
            p_positive=row.p_positive,
            p_outperform=row.p_outperform,
        )
        items.append((row.id, evaluate_forecast(forecast, value, bench_value, end_day)))
    written = upsert_evaluations(session, items)
    return written, not_yet, skipped


def summarise_models(session: Session, config: AnalyticsConfig) -> dict[str, dict[str, Any]]:
    """Out-of-sample summary per model and horizon from every stored evaluation."""
    summary: dict[str, dict[str, Any]] = {}
    for model in tuple(config.forecast.models) + tuple(config.forecast.candidate_models):
        per_horizon: dict[str, Any] = {}
        for horizon in config.forecast.horizons:
            pairs = load_evaluations(session, model=model, horizon_months=horizon)
            evaluations = [
                Evaluation(
                    e.realised_return,
                    e.realised_benchmark_return,
                    e.error,
                    e.directional_hit,
                    e.benchmark_hit,
                    e.within_interval,
                    e.realised_end_date,
                )
                for _, e in pairs
            ]
            per_horizon[f"{horizon}m"] = summarise(evaluations)
        summary[model] = per_horizon
    return summary


def admit_models(
    session: Session, summary: dict[str, dict[str, Any]], config: AnalyticsConfig
) -> list[str]:
    """Store the summary on every model row; activate candidates that beat the baselines
    at every horizon with evaluations, retire the ones that do not."""
    cfg = config.forecast
    models = register_models(session, config)
    admitted: list[str] = []
    for name, entry in models.items():
        entry.performance = summary.get(name)
        if name in cfg.models:
            continue
        verdicts: list[bool] = []
        for horizon in cfg.horizons:
            key = f"{horizon}m"
            candidate = summary.get(name, {}).get(key, {})
            baselines = [summary.get(b, {}).get(key, {}) for b in cfg.models]
            if candidate.get("n"):
                verdicts.append(beats_baselines(candidate, baselines, margin=cfg.admit_margin))
        if verdicts and all(verdicts):
            entry.status = ModelStatus.ACTIVE
            admitted.append(name)
        elif verdicts:
            entry.status = ModelStatus.RETIRED
    session.flush()
    return admitted


def evaluate_forecasts(
    settings: Settings,
    source: NseScraperSource,
    *,
    as_of: date | None = None,
    tickers: list[str] | None = None,
    config: AnalyticsConfig = DEFAULT_CONFIG,
) -> EvaluationRunResult:
    day = as_of or datetime.now(UTC).date()
    started = datetime.now(UTC)
    with analytics_session(settings) as session:
        run = JobRun(job_name=JOB_EVALUATE, started_at=started, as_of_date=day)
        session.add(run)
        session.flush()
        try:
            universe = load_universe(source, config)
            benchmark = universe.get(config.market.benchmark_index)
            written, pending, skipped = _evaluate_rows(
                session, universe, benchmark, day, config, tickers=tickers
            )
            summary = summarise_models(session, config)
            admitted = admit_models(session, summary, config)
        except Exception as exc:
            run.status = JobStatus.FAILED
            run.error = f"{type(exc).__name__}: {exc}"
            run.finished_at = datetime.now(UTC)
            raise
        run.status = JobStatus.SUCCEEDED
        run.finished_at = datetime.now(UTC)
        run.rows_written = written
        run.watermark = day.isoformat()
        run.details = {
            "evaluated": written,
            "pending": pending,
            "skipped": skipped,
            "admitted": admitted,
        }
    logger.info("forecasts_evaluated", as_of=day.isoformat(), evaluated=written, pending=pending)
    return EvaluationRunResult(day, written, pending, skipped, summary, tuple(admitted))


def walk_forward(
    settings: Settings,
    source: NseScraperSource,
    *,
    tickers: list[str],
    start: date,
    end: date,
    config: AnalyticsConfig = DEFAULT_CONFIG,
) -> EvaluationRunResult:
    """Forecast at every monthly origin in [start, end] (each seeing only its own
    past), then evaluate what has elapsed by ``end`` and summarise the models."""
    started = datetime.now(UTC)
    with analytics_session(settings) as session:
        version = register_calc_version(session, config)
        register_models(session, config)
        run = JobRun(job_name=JOB_WALK_FORWARD, started_at=started, as_of_date=end)
        session.add(run)
        session.flush()
        try:
            universe = load_universe(source, config)
            benchmark = universe.get(config.market.benchmark_index)
            requested = [t.strip().upper() for t in tickers if t.strip().upper() in universe]
            origins: list[date] = []
            step = 0
            while (origin := shift_forward(start, step)) <= end:  # anchored: no day drift
                origins.append(origin)
                step += config.forecast.walk_forward_step_months
            forecasts_written = 0
            for origin in origins:
                batch: list[Forecast] = []
                for ticker in requested:
                    batch.extend(_forecast_one(ticker, universe[ticker], benchmark, origin, config))
                forecasts_written += upsert_forecasts(
                    session,
                    batch,
                    as_of_date=origin,
                    model_version=MODEL_VERSION,
                    benchmark=config.market.benchmark_index,
                    drawdown_threshold=config.forecast.drawdown_threshold,
                    calc_version_id=version.id,
                )
            evaluated, pending, skipped = _evaluate_rows(
                session, universe, benchmark, end, config, tickers=requested
            )
            summary = summarise_models(session, config)
            admitted = admit_models(session, summary, config)
        except Exception as exc:
            run.status = JobStatus.FAILED
            run.error = f"{type(exc).__name__}: {exc}"
            run.finished_at = datetime.now(UTC)
            raise
        run.status = JobStatus.SUCCEEDED
        run.finished_at = datetime.now(UTC)
        run.rows_written = forecasts_written + evaluated
        run.watermark = end.isoformat()
        run.details = {
            "calc_version_id": version.id,
            "tickers": requested,
            "origins": len(origins),
            "forecasts": forecasts_written,
            "evaluated": evaluated,
            "pending": pending,
            "skipped": skipped,
            "admitted": admitted,
        }
    logger.info(
        "forecast_walk_forward",
        tickers=len(requested),
        origins=len(origins),
        forecasts=forecasts_written,
        evaluated=evaluated,
    )
    return EvaluationRunResult(end, evaluated, pending, skipped, summary, tuple(admitted))


__all__ = [
    "JOB_EVALUATE",
    "JOB_FORECAST",
    "JOB_WALK_FORWARD",
    "MODEL_VERSION",
    "EvaluationRunResult",
    "ForecastRunResult",
    "admit_models",
    "compute_forecasts",
    "evaluate_forecasts",
    "forecast_universe",
    "register_models",
    "summarise_models",
    "walk_forward",
]
