"""Persist and query forecasts and their evaluations. No business rules here.

codegraph explore "upsert_forecasts load_forecasts unevaluated_forecasts upsert_evaluations"
"""

from __future__ import annotations

from collections.abc import Iterable
from datetime import date
from typing import TYPE_CHECKING, Any

from sqlalchemy import select
from sqlalchemy.dialects.sqlite import insert
from sqlalchemy.orm import Session

from app.web.db.analytics.models import Forecast, ForecastEvaluation
from app.web.db.analytics.models.mixins import utcnow

if TYPE_CHECKING:
    from app.web.services.analytics.forecasting.engine import Evaluation
    from app.web.services.analytics.forecasting.engine import Forecast as ForecastResult

IDENTITY = (
    "ticker_symbol",
    "as_of_date",
    "horizon_months",
    "model",
    "model_version",
    "calc_version_id",
)


def upsert_forecasts(
    session: Session,
    forecasts: Iterable[ForecastResult],
    *,
    as_of_date: date,
    model_version: str,
    benchmark: str | None,
    drawdown_threshold: float,
    calc_version_id: int,
) -> int:
    stamp = utcnow()
    payload: list[dict[str, Any]] = []
    for f in forecasts:
        payload.append(
            {
                "ticker_symbol": f.ticker_symbol,
                "as_of_date": as_of_date,
                "horizon_months": f.horizon_months,
                "model": f.model,
                "model_version": model_version,
                "status": f.measure.status.value,
                "reason": f.measure.reason,
                "expected_return": f.measure.value,
                "mean_log": f.mean_log,
                "sd_log": f.sd_log,
                "q05": f.quantiles.get("q05"),
                "q25": f.quantiles.get("q25"),
                "q50": f.quantiles.get("q50"),
                "q75": f.quantiles.get("q75"),
                "q95": f.quantiles.get("q95"),
                "p_positive": f.p_positive,
                "p_outperform": f.p_outperform,
                "expected_vol": f.expected_vol,
                "p_drawdown": f.p_drawdown,
                "drawdown_threshold": drawdown_threshold if f.p_drawdown is not None else None,
                "benchmark": benchmark if f.p_outperform is not None else None,
                "inputs": f.inputs or None,
                "provenance": [p.as_dict() for p in f.measure.provenance] or None,
                "calc_version_id": calc_version_id,
                "computed_at": stamp,
            }
        )
    if not payload:
        return 0
    statement = insert(Forecast).values(payload)
    columns = [c for c in payload[0] if c not in IDENTITY]
    statement = statement.on_conflict_do_update(
        index_elements=list(IDENTITY),
        set_={c: getattr(statement.excluded, c) for c in columns},
    )
    session.execute(statement)
    session.flush()
    return len(payload)


def load_forecasts(
    session: Session,
    *,
    as_of_date: date | None = None,
    ticker_symbol: str | None = None,
    model: str | None = None,
    horizon_months: int | None = None,
) -> list[Forecast]:
    stmt = select(Forecast)
    if as_of_date is not None:
        stmt = stmt.where(Forecast.as_of_date == as_of_date)
    if ticker_symbol is not None:
        stmt = stmt.where(Forecast.ticker_symbol == ticker_symbol.upper())
    if model is not None:
        stmt = stmt.where(Forecast.model == model)
    if horizon_months is not None:
        stmt = stmt.where(Forecast.horizon_months == horizon_months)
    return list(
        session.execute(
            stmt.order_by(
                Forecast.ticker_symbol, Forecast.as_of_date, Forecast.horizon_months, Forecast.model
            )
        ).scalars()
    )


def unevaluated_forecasts(
    session: Session, *, tickers: Iterable[str] | None = None
) -> list[Forecast]:
    """Known forecasts with no evaluation row yet."""
    evaluated = select(ForecastEvaluation.forecast_id)
    stmt = select(Forecast).where(
        Forecast.status.in_(["known", "zero"]), Forecast.id.not_in(evaluated)
    )
    if tickers is not None:
        stmt = stmt.where(Forecast.ticker_symbol.in_([t.upper() for t in tickers]))
    return list(
        session.execute(stmt.order_by(Forecast.ticker_symbol, Forecast.as_of_date)).scalars()
    )


def upsert_evaluations(session: Session, items: Iterable[tuple[int, Evaluation]]) -> int:
    stamp = utcnow()
    payload = [
        {
            "forecast_id": forecast_id,
            "realised_return": e.realised_return,
            "realised_benchmark_return": e.realised_benchmark_return,
            "realised_end_date": e.end_date,
            "error": e.error,
            "directional_hit": e.directional_hit,
            "benchmark_hit": e.benchmark_hit,
            "within_interval": e.within_interval,
            "evaluated_at": stamp,
        }
        for forecast_id, e in items
    ]
    if not payload:
        return 0
    statement = insert(ForecastEvaluation).values(payload)
    statement = statement.on_conflict_do_update(
        index_elements=["forecast_id"],
        set_={c: getattr(statement.excluded, c) for c in payload[0] if c != "forecast_id"},
    )
    session.execute(statement)
    session.flush()
    return len(payload)


def load_evaluations(
    session: Session, *, model: str | None = None, horizon_months: int | None = None
) -> list[tuple[Forecast, ForecastEvaluation]]:
    stmt = select(Forecast, ForecastEvaluation).join(
        ForecastEvaluation, ForecastEvaluation.forecast_id == Forecast.id
    )
    if model is not None:
        stmt = stmt.where(Forecast.model == model)
    if horizon_months is not None:
        stmt = stmt.where(Forecast.horizon_months == horizon_months)
    return [(f, e) for f, e in session.execute(stmt.order_by(Forecast.as_of_date))]


__all__ = [
    "load_evaluations",
    "load_forecasts",
    "unevaluated_forecasts",
    "upsert_evaluations",
    "upsert_forecasts",
]
