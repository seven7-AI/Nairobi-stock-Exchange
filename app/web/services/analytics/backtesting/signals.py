"""The ranking model as a backtest signal, recomputed in memory as of each date.

The backtester must rank with exactly the engines the live jobs use, seeing only
data on or before the rebalance date. ``SignalContext`` loads every input once
(prices, statements, fundamentals snapshots, classification) and ``rankings_at``
runs the same per-date pipeline the jobs run - returns, momentum, risk, liquidity,
fundamentals, valuation multiples, factor scores, composite ranking - without
touching the analytics store. Point-in-time is enforced by ``PriceSeries.as_of``
and the statements' availability dates; nothing is read from stored metrics.

    codegraph explore "SignalContext rankings_at metric_table_at ranking_signal"
"""

from __future__ import annotations

import time
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import date
from typing import Any

from app.web.services.analytics.backtesting.engine import Signal, TurnoverLookup
from app.web.services.analytics.classification.lookup import ClassificationIndex
from app.web.services.analytics.config import AnalyticsConfig
from app.web.services.analytics.factors.engine import MetricTable, score_factors
from app.web.services.analytics.factors.service import factor_universe
from app.web.services.analytics.fundamentals.engine import FundamentalResult
from app.web.services.analytics.fundamentals.service import fundamental_results
from app.web.services.analytics.fundamentals.statements import StatementRow
from app.web.services.analytics.liquidity.engine import (
    LiquidityInputs,
    liquidity_inputs,
    liquidity_scores,
)
from app.web.services.analytics.measure import Measure
from app.web.services.analytics.momentum.engine import MetricResult, momentum_metrics
from app.web.services.analytics.ranking.engine import FactorInput, Ranking, rank_universe
from app.web.services.analytics.ranking.service import DETECTOR_METRICS
from app.web.services.analytics.returns.engine import WindowResult, trailing_returns
from app.web.services.analytics.risk.engine import risk_metrics
from app.web.services.analytics.series import PriceSeries
from app.web.services.analytics.valuation_metrics.service import valuation_results
from app.web.utils.logger import get_logger

logger = get_logger(__name__)


@dataclass
class SignalContext:
    """Everything the ranking pipeline needs, loaded once for a whole backtest."""

    prices: Mapping[str, PriceSeries]
    statements: Mapping[str, Sequence[StatementRow]]
    snapshots: Mapping[str, Sequence[Mapping[str, Any]]]
    index: ClassificationIndex
    config: AnalyticsConfig
    #: Keep every date's metric table (a weight search runs several signals over the
    #: same dates); off, only the latest date is kept so a long run stays small.
    memoise_all: bool = False
    #: rebalance date -> (metric table, liquidity inputs) memo.
    _tables: dict[date, tuple[MetricTable, dict[str, LiquidityInputs]]] = field(
        default_factory=dict, repr=False
    )


def _known(
    results: Mapping[str, MetricResult | FundamentalResult | WindowResult],
) -> dict[str, float]:
    return {
        name: float(r.measure.value)
        for name, r in results.items()
        if r.measure.is_known and r.measure.value is not None
    }


def metric_table_at(
    ctx: SignalContext, day: date, listed: Sequence[str]
) -> tuple[MetricTable, dict[str, LiquidityInputs]]:
    """(source, metric) -> ticker -> value for every listed instrument as of ``day``,
    computed with the live engines on ``as_of`` slices."""
    if day in ctx._tables:
        return ctx._tables[day]
    config = ctx.config
    table: dict[tuple[str, str], dict[str, float]] = {}

    def put(source: str, ticker: str, values: Mapping[str, float]) -> None:
        for metric, value in values.items():
            table.setdefault((source, metric), {})[ticker] = value

    started = time.perf_counter()
    truncated = {t: ctx.prices[t].as_of(day) for t in listed if t in ctx.prices}
    benchmark_series = ctx.prices.get(config.market.benchmark_index)
    benchmark = benchmark_series.as_of(day) if benchmark_series is not None else None
    liquidity: dict[str, LiquidityInputs] = {}
    # Sector-relative momentum and peer correlations are not factor inputs, so the
    # backtest signal skips the peer sets (an O(n^2) cost per date the live jobs pay
    # once a day but a 144-date simulation would pay 144 times).
    no_peers: dict[str, PriceSeries] = {}
    for ticker, series in truncated.items():
        if series.is_empty:
            continue
        put("market", ticker, _known(trailing_returns(series, day)))
        put(
            "market",
            ticker,
            _known(
                momentum_metrics(series, day, benchmark=benchmark, peers=no_peers, config=config)
            ),
        )
        put(
            "market",
            ticker,
            _known(risk_metrics(series, day, benchmark=benchmark, peers=no_peers, config=config)),
        )
        liquidity[ticker] = liquidity_inputs(series, day, ctx.snapshots.get(ticker, ()), config)
    scores = liquidity_scores(liquidity, day, config)
    for ticker, item in liquidity.items():
        merged: dict[str, MetricResult] = dict(item.metrics)
        merged["liquidity_score"], merged["liquidity_bucket"] = scores[ticker]
        put("market", ticker, _known(merged))
    statements = {t: ctx.statements.get(t, ()) for t in listed}
    fundamentals, _ = fundamental_results(statements, ctx.index, day, config)
    for ticker, own in fundamentals.items():
        put("fundamental", ticker, _known(own))
    valuation, _ = valuation_results(statements, truncated, ctx.index, day, config)
    for ticker, own in valuation.items():
        put("fundamental", ticker, _known(own))
    if not ctx.memoise_all:
        ctx._tables.clear()
    ctx._tables[day] = (table, liquidity)
    logger.info(
        "backtest_metrics_ready",
        as_of=day.isoformat(),
        listed=len(listed),
        metrics=len(table),
        seconds=round(time.perf_counter() - started, 1),
    )
    return ctx._tables[day]


def rankings_at(
    ctx: SignalContext, day: date, listed: Sequence[str], config: AnalyticsConfig | None = None
) -> list[Ranking]:
    """The composite ranking as of ``day`` over the listed instruments in an operating
    sector, under ``config`` (weights may differ from the context's; the metric table
    does not)."""
    cfg = config or ctx.config
    table, _ = metric_table_at(ctx, day, listed)
    universe, groups = factor_universe(ctx.index, day)
    universe = [t for t in universe if t in listed]
    groups = {level: {t: m.get(t) for t in universe} for level, m in groups.items()}
    scores = score_factors(table, universe, groups, cfg)
    factors: dict[str, dict[str, FactorInput]] = {}
    for s in scores:
        factors.setdefault(s.ticker_symbol, {})[s.factor] = FactorInput(
            s.factor,
            s.percentile_market,
            s.percentile_sector,
            s.percentile_industry,
            s.coverage,
            s.measure.status.value,
        )
    metrics: dict[str, dict[str, Measure]] = {}
    for source, names in DETECTOR_METRICS.items():
        for name in names:
            for ticker, value in table.get((source, name), {}).items():
                metrics.setdefault(ticker, {})[name] = Measure.known(value)
    return rank_universe(factors, metrics, groups, cfg)


def ranking_signal(ctx: SignalContext, config: AnalyticsConfig | None = None) -> Signal:
    """A ``Signal`` for ``run_backtest``: candidates ordered by market rank, only
    those with a known overall score and (when configured) a class at or above
    ``backtest.min_class``."""
    cfg = config or ctx.config
    order = ["Strong Candidate", "Buy Candidate", "Watch", "Neutral", "Weak", "Avoid"]
    floor = order.index(cfg.backtest.min_class) if cfg.backtest.min_class in order else None

    def signal(day: date, listed: Sequence[str]) -> list[tuple[str, float]]:
        ranked = [
            r
            for r in rankings_at(ctx, day, listed, cfg)
            if r.market_rank is not None and r.overall.value is not None
        ]
        if floor is not None:
            ranked = [r for r in ranked if r.classification in order[: floor + 1]]
        ranked.sort(key=lambda r: r.market_rank or 0)
        return [(r.ticker_symbol, float(r.overall.value or 0.0)) for r in ranked]

    return signal


def turnover_lookup(ctx: SignalContext) -> TurnoverLookup:
    """Average daily turnover as of the rebalance date (from the liquidity inputs)."""

    def lookup(day: date, ticker: str) -> float | None:
        _, liquidity = ctx._tables.get(day, ({}, {}))
        item = liquidity.get(ticker)
        return item.turnover if item is not None else None

    return lookup


__all__ = ["SignalContext", "metric_table_at", "ranking_signal", "rankings_at", "turnover_lookup"]
