"""Persist and query backtest runs, results, positions and equity curves.

codegraph explore "save_backtest load_backtest_runs load_backtest_results"
"""

from __future__ import annotations

from datetime import date
from typing import TYPE_CHECKING, Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.web.db.analytics.models import (
    BacktestEquity,
    BacktestPosition,
    BacktestResult,
    BacktestRun,
)

if TYPE_CHECKING:
    from app.web.services.analytics.backtesting.engine import BacktestResult as EngineResult


def save_backtest(
    session: Session,
    result: EngineResult,
    *,
    name: str,
    model_name: str,
    model_version: str,
    purpose: str,
    config_hash: str,
    top_n: int,
    weights: dict[str, float],
    costs: dict[str, float],
    benchmarks: list[str],
    details: dict[str, Any] | None,
    calc_version_id: int,
) -> BacktestRun:
    status = "known" if result.segments else "unavailable"
    reason = None if result.segments else "; ".join(result.notes) or "no segments"
    run = BacktestRun(
        name=name,
        model_name=model_name,
        model_version=model_version,
        purpose=purpose,
        config_hash=config_hash,
        start_date=result.start,
        end_date=result.end,
        top_n=top_n,
        weights=weights,
        costs=costs,
        benchmarks=benchmarks,
        status=status,
        reason=reason,
        segments=len(result.segments),
        details={**(details or {}), "notes": result.notes},
        calc_version_id=calc_version_id,
    )
    session.add(run)
    session.flush()
    rows: list[BacktestResult] = []
    for number, segment in enumerate(result.segments, start=1):
        label = str(number)
        for series, metrics in segment.metrics.items():
            for metric, measure in metrics.items():
                rows.append(
                    BacktestResult(
                        run_id=run.id,
                        segment=label,
                        series=series,
                        metric=metric,
                        value=measure.value,
                        status=measure.status.value,
                        reason=measure.reason,
                    )
                )
        rows.append(
            BacktestResult(
                run_id=run.id,
                segment=label,
                series="portfolio",
                metric="costs_paid",
                value=segment.costs_paid,
                status="known",
                reason=None,
            )
        )
        targets_by_day = {r.day: r.targets for r in segment.rebalances}
        session.add_all(
            BacktestPosition(
                run_id=run.id,
                segment=label,
                day=t.day,
                ticker_symbol=t.ticker_symbol,
                action=t.action,
                shares=t.shares,
                price=t.price,
                price_date=t.price_date,
                value=t.value,
                cost=t.cost,
                weight=targets_by_day.get(t.day, {}).get(t.ticker_symbol),
            )
            for t in segment.trades
        )
        levels = dict(segment.benchmarks)
        stamps = [str(stamp) for stamp in segment.equity.index]
        values = segment.equity.to_numpy(dtype=float)
        level_values = {n: lv.to_numpy(dtype=float) for n, lv in levels.items()}
        session.add_all(
            BacktestEquity(
                run_id=run.id,
                segment=label,
                day=date.fromisoformat(stamp[:10]),
                equity=float(value),
                benchmarks={n: float(arr[i]) for n, arr in level_values.items()} or None,
            )
            for i, (stamp, value) in enumerate(zip(stamps, values, strict=True))
        )
    for metric, measure in result.linked.items():
        rows.append(
            BacktestResult(
                run_id=run.id,
                segment="linked",
                series="portfolio",
                metric=metric,
                value=measure.value,
                status=measure.status.value,
                reason=measure.reason,
            )
        )
    session.add_all(rows)
    session.flush()
    return run


def load_backtest_runs(
    session: Session, *, name: str | None = None, purpose: str | None = None
) -> list[BacktestRun]:
    stmt = select(BacktestRun)
    if name is not None:
        stmt = stmt.where(BacktestRun.name == name)
    if purpose is not None:
        stmt = stmt.where(BacktestRun.purpose == purpose)
    return list(session.execute(stmt.order_by(BacktestRun.id)).scalars())


def load_backtest_results(session: Session, run_id: int) -> list[BacktestResult]:
    return list(
        session.execute(
            select(BacktestResult)
            .where(BacktestResult.run_id == run_id)
            .order_by(BacktestResult.segment, BacktestResult.series, BacktestResult.metric)
        ).scalars()
    )


def load_backtest_positions(
    session: Session, run_id: int, *, until: date | None = None
) -> list[BacktestPosition]:
    stmt = select(BacktestPosition).where(BacktestPosition.run_id == run_id)
    if until is not None:
        stmt = stmt.where(BacktestPosition.day <= until)
    return list(
        session.execute(
            stmt.order_by(BacktestPosition.day, BacktestPosition.ticker_symbol, BacktestPosition.id)
        ).scalars()
    )


def load_backtest_equity(session: Session, run_id: int) -> list[BacktestEquity]:
    return list(
        session.execute(
            select(BacktestEquity)
            .where(BacktestEquity.run_id == run_id)
            .order_by(BacktestEquity.day)
        ).scalars()
    )


__all__ = [
    "load_backtest_equity",
    "load_backtest_positions",
    "load_backtest_results",
    "load_backtest_runs",
    "save_backtest",
]
