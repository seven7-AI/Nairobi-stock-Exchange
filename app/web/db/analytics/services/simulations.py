"""Persist and query simulations, scenario outcomes and regimes. No business rules here.

codegraph explore "upsert_simulations upsert_scenarios upsert_regimes load_regimes"
"""

from __future__ import annotations

from collections.abc import Iterable
from datetime import date
from typing import TYPE_CHECKING, Any

from sqlalchemy import select
from sqlalchemy.dialects.sqlite import insert
from sqlalchemy.orm import Session

from app.web.db.analytics.models import Regime, Simulation
from app.web.db.analytics.models.mixins import utcnow

if TYPE_CHECKING:
    from app.web.services.analytics.montecarlo.engine import Simulation as SimulationResult
    from app.web.services.analytics.regime.engine import Regime as RegimeResult
    from app.web.services.analytics.scenarios.engine import ScenarioOutcome

SIMULATION_IDENTITY = (
    "ticker_symbol",
    "as_of_date",
    "horizon_days",
    "method",
    "scenario",
    "calc_version_id",
)


def _write_simulations(session: Session, payload: list[dict[str, Any]]) -> int:
    if not payload:
        return 0
    statement = insert(Simulation).values(payload)
    columns = [c for c in payload[0] if c not in SIMULATION_IDENTITY]
    statement = statement.on_conflict_do_update(
        index_elements=list(SIMULATION_IDENTITY),
        set_={c: getattr(statement.excluded, c) for c in columns},
    )
    session.execute(statement)
    session.flush()
    return len(payload)


def upsert_simulations(
    session: Session, items: Iterable[SimulationResult], *, as_of_date: date, calc_version_id: int
) -> int:
    stamp = utcnow()
    payload = [
        {
            "ticker_symbol": s.ticker_symbol,
            "as_of_date": as_of_date,
            "horizon_days": s.horizon_days,
            "method": s.method,
            "scenario": "",
            "status": s.measure.status.value,
            "reason": s.measure.reason,
            "n_paths": s.n_paths or None,
            "seed": s.seed,
            "price": s.price,
            "mean_return": s.measure.value,
            "q05": s.quantiles.get("q05"),
            "q25": s.quantiles.get("q25"),
            "q50": s.quantiles.get("q50"),
            "q75": s.quantiles.get("q75"),
            "q95": s.quantiles.get("q95"),
            "p_positive": s.p_positive,
            "p_return_above": s.p_return_above or None,
            "p_drawdown_above": s.p_drawdown_above or None,
            "expected_max_drawdown": s.expected_max_drawdown,
            "implied_price": None,
            "assumptions": None,
            "inputs": s.inputs or None,
            "provenance": [p.as_dict() for p in s.measure.provenance] or None,
            "calc_version_id": calc_version_id,
            "computed_at": stamp,
        }
        for s in items
    ]
    return _write_simulations(session, payload)


def upsert_scenarios(
    session: Session,
    items: Iterable[ScenarioOutcome],
    *,
    as_of_date: date,
    horizon_days: int,
    calc_version_id: int,
) -> int:
    stamp = utcnow()
    payload = [
        {
            "ticker_symbol": o.ticker_symbol,
            "as_of_date": as_of_date,
            "horizon_days": horizon_days,
            "method": "scenario",
            "scenario": o.scenario,
            "status": o.measure.status.value,
            "reason": o.measure.reason,
            "n_paths": None,
            "seed": None,
            "price": o.assumptions.get("price"),
            "mean_return": o.measure.value,
            "q05": None,
            "q25": None,
            "q50": None,
            "q75": None,
            "q95": None,
            "p_positive": None,
            "p_return_above": None,
            "p_drawdown_above": None,
            "expected_max_drawdown": None,
            "implied_price": o.implied_price,
            "assumptions": {
                **o.assumptions,
                "beta_path_price": o.beta_path_price,
                "fundamental_path_price": o.fundamental_path_price,
            },
            "inputs": None,
            "provenance": [p.as_dict() for p in o.measure.provenance] or None,
            "calc_version_id": calc_version_id,
            "computed_at": stamp,
        }
        for o in items
    ]
    return _write_simulations(session, payload)


def load_simulations(
    session: Session,
    *,
    as_of_date: date | None = None,
    ticker_symbol: str | None = None,
    method: str | None = None,
) -> list[Simulation]:
    stmt = select(Simulation)
    if as_of_date is not None:
        stmt = stmt.where(Simulation.as_of_date == as_of_date)
    if ticker_symbol is not None:
        stmt = stmt.where(Simulation.ticker_symbol == ticker_symbol.upper())
    if method is not None:
        stmt = stmt.where(Simulation.method == method)
    return list(
        session.execute(
            stmt.order_by(
                Simulation.ticker_symbol,
                Simulation.method,
                Simulation.scenario,
                Simulation.horizon_days,
            )
        ).scalars()
    )


def upsert_regimes(session: Session, items: Iterable[RegimeResult], *, calc_version_id: int) -> int:
    stamp = utcnow()
    payload = [
        {
            "as_of_date": r.as_of,
            "index_symbol": r.index,
            "status": r.measure.status.value,
            "reason": r.measure.reason,
            "trend": r.trend,
            "volatility": r.volatility,
            "risk": r.risk,
            "risk_score": r.measure.value,
            "evidence": r.evidence or None,
            "weight_overrides": r.weight_overrides or None,
            "calc_version_id": calc_version_id,
            "computed_at": stamp,
        }
        for r in items
    ]
    if not payload:
        return 0
    statement = insert(Regime).values(payload)
    columns = [c for c in payload[0] if c not in ("as_of_date", "index_symbol", "calc_version_id")]
    statement = statement.on_conflict_do_update(
        index_elements=["as_of_date", "index_symbol", "calc_version_id"],
        set_={c: getattr(statement.excluded, c) for c in columns},
    )
    session.execute(statement)
    session.flush()
    return len(payload)


def load_regimes(
    session: Session,
    *,
    index_symbol: str | None = None,
    start: date | None = None,
    end: date | None = None,
) -> list[Regime]:
    stmt = select(Regime)
    if index_symbol is not None:
        stmt = stmt.where(Regime.index_symbol == index_symbol)
    if start is not None:
        stmt = stmt.where(Regime.as_of_date >= start)
    if end is not None:
        stmt = stmt.where(Regime.as_of_date <= end)
    return list(session.execute(stmt.order_by(Regime.as_of_date)).scalars())


__all__ = [
    "load_regimes",
    "load_simulations",
    "upsert_regimes",
    "upsert_scenarios",
    "upsert_simulations",
]
