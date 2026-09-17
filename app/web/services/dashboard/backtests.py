"""Backtest runs for the dashboard: the list with headline metrics (shared with the
research router), and one run's equity curve, running drawdown, results table,
turnover and costs.

    codegraph explore "list_backtests backtest_detail load_equity_curves load_backtest_results"
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import date
from typing import Any

from app.web.config import Settings
from app.web.db.analytics import analytics_session
from app.web.db.analytics.services.backtests import (
    load_backtest_positions,
    load_backtest_results,
    load_backtest_runs,
)
from app.web.services.dashboard.common import measure
from app.web.services.visualizations.research_charts import load_equity_curves

HEADLINE: tuple[str, ...] = (
    "total_return",
    "cagr",
    "volatility",
    "sharpe",
    "max_drawdown",
    "alpha_vs_^NASI",
    "beta_vs_^NASI",
)
DISCLAIMER = (
    "Simulated, point-in-time, after modelled costs, on the archive's prices; past "
    "performance says nothing about the future and this is not investment advice."
)


@dataclass(frozen=True)
class BacktestSummary:
    run_id: int
    name: str
    purpose: str
    model: str
    start_date: date
    end_date: date
    top_n: int
    cost_rate: float
    segments: int
    status: str
    reason: str | None
    linked_total_return: dict[str, Any]
    first_segment: dict[str, dict[str, Any]]
    benchmarks: list[str]


@dataclass(frozen=True)
class BacktestPage:
    items: list[BacktestSummary]
    next_cursor: str | None
    total: int

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class BacktestDetail:
    run: BacktestSummary
    weights: dict[str, float]
    costs: dict[str, float]
    results: dict[str, dict[str, dict[str, dict[str, Any]]]]
    equity: list[dict[str, Any]]
    max_drawdown: dict[str, Any]
    turnover: list[dict[str, Any]]
    disclaimer: str

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


def _summary(session: Any, run: Any) -> BacktestSummary:
    results = {(r.segment, r.series, r.metric): r for r in load_backtest_results(session, run.id)}
    linked = results.get(("linked", "portfolio", "total_return"))
    first = {
        k: measure(row.value, str(row.status), row.reason)
        for k in HEADLINE
        if (row := results.get(("1", "portfolio", k))) is not None
    }
    return BacktestSummary(
        run.id,
        run.name,
        run.purpose,
        f"{run.model_name} v{run.model_version}",
        run.start_date,
        run.end_date,
        run.top_n,
        float((run.costs or {}).get("rate", 0.0)),
        run.segments,
        run.status,
        run.reason,
        measure(linked.value, str(linked.status), linked.reason)
        if linked
        else measure(None, str(run.status), run.reason),
        first,
        list(run.benchmarks or []),
    )


def list_backtests(
    settings: Settings, *, limit: int = 50, cursor: str | None = None
) -> BacktestPage:
    """Stored runs, oldest first, paginated by run id (the research router serves the
    same page shape)."""
    with analytics_session(settings) as session:
        runs = load_backtest_runs(session)
        start = 0
        if cursor:
            start = next((i for i, r in enumerate(runs) if str(r.id) == cursor), -1) + 1
        page = runs[start : start + limit]
        items = [_summary(session, run) for run in page]
        next_cursor = str(page[-1].id) if start + limit < len(runs) and page else None
    return BacktestPage(items, next_cursor, len(runs))


def backtest_detail(settings: Settings, run_id: int) -> BacktestDetail | None:
    with analytics_session(settings) as session:
        run = next((r for r in load_backtest_runs(session) if r.id == run_id), None)
        if run is None:
            return None
        summary = _summary(session, run)
        results: dict[str, dict[str, dict[str, dict[str, Any]]]] = {}
        for r in load_backtest_results(session, run.id):
            results.setdefault(r.segment, {}).setdefault(r.series, {})[r.metric] = measure(
                r.value, str(r.status), r.reason
            )
        curves = load_equity_curves(session, run_id=run.id)
        equity: list[dict[str, Any]] = []
        max_dd: dict[str, Any] = measure(None, "unavailable", "no equity curve stored")
        if curves is not None:
            peak = float("-inf")
            worst = 0.0
            for i, day in enumerate(curves.dates):
                level = curves.equity[i]
                peak = max(peak, level)
                drawdown = level / peak - 1.0 if peak > 0 else 0.0
                worst = min(worst, drawdown)
                equity.append(
                    {
                        "day": day,
                        "segment": curves.segments[i] if i < len(curves.segments) else "",
                        "equity": level,
                        "drawdown": drawdown,
                        "benchmarks": {
                            name: (series[i] if i < len(series) else None)
                            for name, series in curves.benchmarks.items()
                        },
                    }
                )
            max_dd = measure(worst, "known", None)
        turnover: dict[tuple[date, str], dict[str, Any]] = {}
        for p in load_backtest_positions(session, run.id):
            key = (p.day, p.segment)
            row = turnover.setdefault(
                key,
                {
                    "day": p.day,
                    "segment": p.segment,
                    "buys": 0,
                    "sells": 0,
                    "exits": 0,
                    "traded_value": 0.0,
                    "cost": 0.0,
                },
            )
            if p.action == "buy":
                row["buys"] += 1
            elif p.action == "sell":
                row["sells"] += 1
            else:
                row["exits"] += 1
            row["traded_value"] += float(p.value)
            row["cost"] += float(p.cost)
        return BacktestDetail(
            summary,
            dict(run.weights or {}),
            dict(run.costs or {}),
            results,
            equity,
            max_dd,
            [turnover[k] for k in sorted(turnover)],
            DISCLAIMER,
        )


__all__ = [
    "DISCLAIMER",
    "HEADLINE",
    "BacktestDetail",
    "BacktestPage",
    "BacktestSummary",
    "backtest_detail",
    "list_backtests",
]
