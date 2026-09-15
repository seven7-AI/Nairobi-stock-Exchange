"""The backtester: a monthly-rebalanced top-N simulation with the look-ahead, the
survivorship and the costs handled explicitly.

Pure. It takes the price series, a *signal* - a callable that, given a rebalance
date and the instruments listed on it, returns the candidates in preference order
using nothing after that date - and the config, and returns the daily equity
curve, every trade, and the metrics per segment.

* **Calendar and segments** - the trading calendar is the union of the universe's
  observation dates; a break longer than the gap threshold (the 2025 gap) ends a
  segment, and every segment is simulated and measured on its own from a fresh
  start. Nothing is interpolated across a gap.
* **Point-in-time universe** - a stock is a candidate on a rebalance date only if
  it is listed then (first observation <= date <= last observation) and its last
  price is recent; a stock that later delists is held until its last observation
  and sold at that last price on the next rebalance (survivorship kept, exit real).
* **Execution** - trades at the close on the rebalance date; per-side costs as a
  fraction of traded value; a position is capped at participation x execution
  days x the stock's average daily turnover (the remainder stays in cash).
* **Metrics** - per segment: total return, CAGR, annualised return and volatility,
  Sharpe, Sortino, max drawdown, Calmar, monthly win rate, best / worst calendar
  year, average monthly one-way turnover; against each benchmark: alpha (annualised,
  with its t-statistic), beta, information ratio - from monthly returns, and only
  where the benchmark has data in the segment.

    codegraph explore "run_backtest segment_metrics Signal BacktestResult"
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import date, timedelta

import numpy as np
import pandas as pd

from app.web.services.analytics.config import AnalyticsConfig
from app.web.services.analytics.measure import Measure, Provenance
from app.web.services.analytics.series import PriceSeries

#: Dispersion below this is floating-point noise, not volatility.
EPSILON = 1e-12
#: (rebalance date, listed tickers) -> candidates in preference order with a score.
Signal = Callable[[date, Sequence[str]], Sequence[tuple[str, float]]]
#: (rebalance date, ticker) -> average daily turnover in KES, or None when unknown.
TurnoverLookup = Callable[[date, str], float | None]


@dataclass(frozen=True, slots=True)
class Trade:
    day: date
    ticker_symbol: str
    action: str  # buy, sell, exit (a delisted stock sold at its last price)
    shares: float
    price: float
    price_date: date
    value: float
    cost: float


@dataclass(frozen=True, slots=True)
class Rebalance:
    day: date
    listed: int
    candidates: int
    targets: dict[str, float]
    notes: dict[str, str] = field(default_factory=dict)
    turnover: float = 0.0  # one-way, as a share of equity


@dataclass(frozen=True, slots=True)
class Segment:
    start: date
    end: date
    equity: pd.Series  # daily, starts at the notional
    benchmarks: dict[str, pd.Series]  # name -> level rebased to the notional at the start
    trades: tuple[Trade, ...]
    rebalances: tuple[Rebalance, ...]
    metrics: dict[str, dict[str, Measure]]  # series name -> metric -> measure
    costs_paid: float


@dataclass(frozen=True, slots=True)
class BacktestResult:
    start: date
    end: date
    segments: tuple[Segment, ...]
    linked: dict[str, Measure]
    notes: list[str] = field(default_factory=list)


# --- calendar --------------------------------------------------------------------------


def trading_calendar(prices: Mapping[str, PriceSeries], start: date, end: date) -> list[date]:
    days: set[date] = set()
    for series in prices.values():
        for stamp in series.dates:
            d = stamp.date()
            if start <= d <= end:
                days.add(d)
    return sorted(days)


def split_segments(days: Sequence[date], gap_threshold_days: int) -> list[list[date]]:
    segments: list[list[date]] = []
    current: list[date] = []
    for d in days:
        if current and (d - current[-1]).days > gap_threshold_days:
            segments.append(current)
            current = []
        current.append(d)
    if current:
        segments.append(current)
    return segments


def month_ends(days: Sequence[date]) -> list[date]:
    """The last calendar day of each (year, month) present."""
    last: dict[tuple[int, int], date] = {}
    for d in days:
        last[(d.year, d.month)] = d
    return [last[k] for k in sorted(last)]


def _price_at(series: PriceSeries, day: date) -> tuple[float, date] | None:
    located = series.close_on_or_before(day)
    if located is None:
        return None
    found_day, close = located
    return close, found_day


def listed_on(prices: Mapping[str, PriceSeries], day: date, max_age_days: int) -> list[str]:
    """Tickers listed on ``day`` with a price no older than ``max_age_days``."""
    out: list[str] = []
    for ticker, series in prices.items():
        first, last = series.first_date, series.last_date
        if (
            first is None
            or last is None
            or first > day
            or last < day - timedelta(days=max_age_days)
        ):
            continue
        located = _price_at(series, day)
        if located is None or (day - located[1]).days > max_age_days:
            continue
        out.append(ticker)
    return out


# --- simulation ----------------------------------------------------------------------


def target_weights(
    candidates: Sequence[tuple[str, float]],
    *,
    day: date,
    equity: float,
    top_n: int,
    config: AnalyticsConfig,
    turnover: TurnoverLookup | None,
) -> tuple[dict[str, float], dict[str, str]]:
    """Equal weights over the top N, each capped by the ADV rule; the rest is cash."""
    cfg = config.backtest
    chosen = [t for t, _ in candidates[:top_n]]
    if not chosen:
        return {}, {"signal": "no candidates"}
    weight = 1.0 / top_n
    targets: dict[str, float] = {}
    notes: dict[str, str] = {}
    for ticker in chosen:
        w = weight
        adv = turnover(day, ticker) if turnover is not None else None
        if adv is not None and adv > 0:
            cap_value = cfg.adv_participation * cfg.execution_days * adv
            cap = cap_value / equity if equity > 0 else 0.0
            if cap < w:
                notes[ticker] = (
                    f"trimmed from {w:.1%} to {cap:.1%} by the ADV cap "
                    f"({cfg.adv_participation:.0%} x {cfg.execution_days} d x KES {adv:,.0f})"
                )
                w = cap
        targets[ticker] = w
    return targets, notes


def simulate_segment(
    days: Sequence[date],
    prices: Mapping[str, PriceSeries],
    signal: Signal,
    config: AnalyticsConfig,
    *,
    turnover: TurnoverLookup | None,
    top_n: int | None = None,
    cost_rate: float | None = None,
) -> tuple[pd.Series, list[Trade], list[Rebalance], float]:
    cfg = config.backtest
    n = cfg.top_n if top_n is None else top_n
    rate = cfg.costs.rate if cost_rate is None else cost_rate
    cash = cfg.notional
    shares: dict[str, float] = {}
    last_price: dict[str, tuple[float, date]] = {}
    trades: list[Trade] = []
    rebalances: list[Rebalance] = []
    costs_paid = 0.0
    rebalance_days = set(month_ends(days))
    equity_values: list[float] = []

    def mark(day: date) -> float:
        total = cash
        for ticker, qty in shares.items():
            located = _price_at(prices[ticker], day)
            if located is not None:
                last_price[ticker] = located
            total += qty * last_price[ticker][0]
        return total

    for day in days:
        if day in rebalance_days:
            equity = mark(day)
            listed = listed_on(prices, day, cfg.max_price_age_days)
            candidates = list(signal(day, listed))
            targets, notes = target_weights(
                candidates, day=day, equity=equity, top_n=n, config=config, turnover=turnover
            )
            before = (
                {t: q * last_price[t][0] / equity for t, q in shares.items()} if equity > 0 else {}
            )
            # sells first (a delisted holding exits at its last price)
            for ticker in list(shares):
                target_value = targets.get(ticker, 0.0) * equity
                held_value = shares[ticker] * last_price[ticker][0]
                if held_value <= target_value + 1e-9:
                    continue
                sell_value = held_value - target_value
                price, price_day = last_price[ticker]
                qty = sell_value / price
                cost = sell_value * rate
                action = "exit" if (day - price_day).days > cfg.max_price_age_days else "sell"
                cash += sell_value - cost
                costs_paid += cost
                shares[ticker] -= qty
                if shares[ticker] <= 1e-12:
                    del shares[ticker]
                trades.append(Trade(day, ticker, action, -qty, price, price_day, sell_value, cost))
            # then buys, scaled so costs come out of the cash being deployed
            for ticker, weight in targets.items():
                target_value = weight * equity
                held_value = (
                    shares.get(ticker, 0.0) * last_price[ticker][0] if ticker in shares else 0.0
                )
                buy_value = target_value - held_value
                if buy_value <= 1e-9:
                    continue
                located = _price_at(prices[ticker], day)
                if located is None:
                    continue
                gross = min(buy_value, max(cash, 0.0)) / (1.0 + rate)
                if gross <= 0:
                    continue
                cost = gross * rate
                price, price_day = located
                last_price[ticker] = located
                shares[ticker] = shares.get(ticker, 0.0) + gross / price
                cash -= gross + cost
                costs_paid += cost
                trades.append(
                    Trade(day, ticker, "buy", gross / price, price, price_day, gross, cost)
                )
            after_equity = mark(day)
            after = (
                {t: q * last_price[t][0] / after_equity for t, q in shares.items()}
                if after_equity > 0
                else {}
            )
            one_way = 0.5 * sum(
                abs(after.get(t, 0.0) - before.get(t, 0.0)) for t in set(before) | set(after)
            )
            rebalances.append(Rebalance(day, len(listed), len(candidates), targets, notes, one_way))
        equity_values.append(mark(day))
    curve = pd.Series(equity_values, index=pd.DatetimeIndex([pd.Timestamp(d) for d in days]))
    return curve, trades, rebalances, costs_paid


def benchmark_level(
    series: PriceSeries, days: Sequence[date], notional: float, gap_threshold_days: int
) -> pd.Series | None:
    """The index rebased to the notional at its first value in the segment, NaN on the
    days it has no observation within the gap threshold (its own gaps stay holes);
    None when it has no data in the segment at all."""
    values: list[float] = []
    for d in days:
        located = _price_at(series, d)
        if located is None or (d - located[1]).days > gap_threshold_days:
            values.append(np.nan)
        else:
            values.append(located[0])
    array = np.array(values, dtype=float)
    valid = np.flatnonzero(~np.isnan(array))
    if len(valid) == 0 or array[valid[0]] <= 0:
        return None
    return pd.Series(
        array / array[valid[0]] * notional,
        index=pd.DatetimeIndex([pd.Timestamp(d) for d in days]),
    )


def longest_continuous(level: pd.Series) -> pd.Series:
    """The longest stretch without NaN - the part of a benchmark its metrics describe."""
    values = level.to_numpy(dtype=float)
    best_start = best_len = start = 0
    run = 0
    for i, v in enumerate(values):
        if np.isnan(v):
            run = 0
            continue
        if run == 0:
            start = i
        run += 1
        if run > best_len:
            best_start, best_len = start, run
    return level.iloc[best_start : best_start + best_len]


# --- metrics ---------------------------------------------------------------------------


def _monthly_returns(equity: pd.Series) -> pd.Series:
    by_month: dict[tuple[int, int], float] = {}
    for stamp, value in zip(equity.index, equity.to_numpy(dtype=float), strict=True):
        ts = pd.Timestamp(str(stamp))
        by_month[(ts.year, ts.month)] = float(value)
    keys = sorted(by_month)
    levels = np.array([by_month[k] for k in keys])
    first = float(equity.iloc[0])
    starts = np.concatenate([[first], levels[:-1]])
    return pd.Series(levels / starts - 1.0, index=[f"{y}-{m:02d}" for y, m in keys])


def series_metrics(
    equity: pd.Series,
    config: AnalyticsConfig,
    *,
    provenance: Provenance,
    turnover: float | None = None,
) -> dict[str, Measure]:
    periods = config.market.trading_days_per_year
    rf = config.market.risk_free_rate
    values = equity.to_numpy(dtype=float)
    days = (equity.index[-1] - equity.index[0]).days
    years = days / 365.25
    total = float(values[-1] / values[0] - 1.0)
    daily = np.diff(values) / values[:-1]
    out: dict[str, Measure] = {}

    def known(name: str, value: float) -> None:
        out[name] = Measure.known(value, provenance) if value != 0 else Measure.zero(provenance)

    known("total_return", total)
    if years >= 1.0:
        known("cagr", float((values[-1] / values[0]) ** (1.0 / years) - 1.0))
    else:
        out["cagr"] = Measure.unavailable(f"CAGR: {days} days of history, under a year")
    annual_return = float(daily.mean() * periods) if len(daily) else 0.0
    vol = float(daily.std(ddof=1) * np.sqrt(periods)) if len(daily) > 1 else 0.0
    vol = 0.0 if vol < EPSILON else vol
    known("annualised_return", annual_return)
    known("volatility", vol)
    out["sharpe"] = (
        Measure.known((annual_return - rf) / vol, provenance)
        if vol > 0
        else Measure.not_meaningful("Sharpe: zero volatility")
    )
    downside = daily[daily < 0]
    downside_dev = float(np.sqrt((downside**2).mean()) * np.sqrt(periods)) if len(downside) else 0.0
    downside_dev = 0.0 if downside_dev < EPSILON else downside_dev
    out["sortino"] = (
        Measure.known((annual_return - rf) / downside_dev, provenance)
        if downside_dev > 0
        else Measure.not_meaningful("Sortino: no negative days")
    )
    peak = np.maximum.accumulate(values)
    mdd = float((values / peak - 1.0).min())
    known("max_drawdown", mdd)
    cagr = out["cagr"].value
    out["calmar"] = (
        Measure.known(cagr / abs(mdd), provenance)
        if cagr is not None and mdd < 0
        else Measure.not_meaningful("Calmar: no drawdown or under a year")
    )
    monthly = _monthly_returns(equity)
    known("monthly_win_rate", float((monthly > 0).mean()) if len(monthly) else 0.0)
    out["months"] = Measure.known(float(len(monthly)), provenance)
    # calendar years fully inside the series
    yearly: dict[int, float] = {}
    for year in range(equity.index[0].year, equity.index[-1].year + 1):
        start, end = date(year, 1, 1), date(year, 12, 31)
        if equity.index[0].date() > start + timedelta(days=10) or equity.index[
            -1
        ].date() < end - timedelta(days=10):
            continue
        part = equity[(equity.index >= pd.Timestamp(start)) & (equity.index <= pd.Timestamp(end))]
        if len(part) > 1:
            yearly[year] = float(part.iloc[-1] / part.iloc[0] - 1.0)
    if yearly:
        best = max(yearly, key=lambda y: yearly[y])
        worst = min(yearly, key=lambda y: yearly[y])
        out["best_year"] = Measure.known(yearly[best], provenance, reason=str(best))
        out["worst_year"] = Measure.known(yearly[worst], provenance, reason=str(worst))
    else:
        out["best_year"] = Measure.unavailable("best year: no full calendar year in the segment")
        out["worst_year"] = Measure.unavailable("worst year: no full calendar year in the segment")
    if turnover is not None:
        known("avg_monthly_turnover", turnover)
    return out


def relative_metrics(
    equity: pd.Series, benchmark: pd.Series, config: AnalyticsConfig, *, provenance: Provenance
) -> dict[str, Measure]:
    """Alpha (annualised, with t-stat), beta and information ratio from monthly returns."""
    p = _monthly_returns(equity)
    b = _monthly_returns(benchmark)
    joined = pd.concat([p.rename("p"), b.rename("b")], axis=1).dropna()
    n = len(joined)
    out: dict[str, Measure] = {}
    if n < config.backtest.min_months_for_alpha:
        why = f"{n} common months, minimum {config.backtest.min_months_for_alpha}"
        for name in ("alpha", "alpha_t_stat", "beta", "information_ratio", "excess_return"):
            out[name] = Measure.unavailable(f"{name}: {why}")
        return out
    rf_m = config.market.risk_free_rate / 12.0
    x = joined["b"].to_numpy(dtype=float) - rf_m
    y = joined["p"].to_numpy(dtype=float) - rf_m
    x_mean, y_mean = x.mean(), y.mean()
    var_x = float(((x - x_mean) ** 2).sum())
    beta = float(((x - x_mean) * (y - y_mean)).sum() / var_x) if var_x > 0 else 0.0
    alpha_m = float(y_mean - beta * x_mean)
    residuals = y - (alpha_m + beta * x)
    dof = max(n - 2, 1)
    sigma = float(np.sqrt((residuals**2).sum() / dof))
    se_alpha = (
        sigma * float(np.sqrt(1.0 / n + x_mean**2 / var_x)) if var_x > 0 and sigma > 0 else 0.0
    )
    active = joined["p"].to_numpy(dtype=float) - joined["b"].to_numpy(dtype=float)
    tracking = float(active.std(ddof=1)) if n > 1 else 0.0
    tracking = 0.0 if tracking < EPSILON else tracking
    out["alpha"] = (
        Measure.known(alpha_m * 12.0, provenance) if alpha_m else Measure.zero(provenance)
    )
    out["alpha_t_stat"] = (
        Measure.known(alpha_m / se_alpha, provenance)
        if se_alpha > 0
        else Measure.not_meaningful("alpha t-stat: no residual variance")
    )
    out["beta"] = Measure.known(beta, provenance) if beta else Measure.zero(provenance)
    out["information_ratio"] = (
        Measure.known(float(active.mean() / tracking * np.sqrt(12.0)), provenance)
        if tracking > 0
        else Measure.not_meaningful("information ratio: no tracking error")
    )
    # excess return over the months both series have: compound the joined months
    total_p = float(np.prod(1.0 + joined["p"].to_numpy(dtype=float)) - 1.0)
    total_b = float(np.prod(1.0 + joined["b"].to_numpy(dtype=float)) - 1.0)
    out["excess_return"] = (
        Measure.known(total_p - total_b, provenance)
        if total_p != total_b
        else Measure.zero(provenance)
    )
    return out


def segment_metrics(
    equity: pd.Series,
    benchmarks: Mapping[str, pd.Series | None],
    rebalances: Sequence[Rebalance],
    config: AnalyticsConfig,
) -> dict[str, dict[str, Measure]]:
    start, end = equity.index[0].date(), equity.index[-1].date()
    provenance = Provenance(table="backtest", start=start, end=end, note="daily equity curve")
    turnover = float(np.mean([r.turnover for r in rebalances])) if rebalances else None
    out: dict[str, dict[str, Measure]] = {
        "portfolio": series_metrics(equity, config, provenance=provenance, turnover=turnover)
    }
    for name, level in benchmarks.items():
        if level is None:
            out[name] = {"total_return": Measure.unavailable(f"{name}: no data in the segment")}
            out["portfolio"][f"alpha_vs_{name}"] = Measure.unavailable(
                f"alpha vs {name}: no benchmark data in the segment"
            )
            continue
        stretch = longest_continuous(level)
        holes = int(level.isna().sum())
        note = (
            f"{name} over its longest continuous stretch {stretch.index[0].date()} -> "
            f"{stretch.index[-1].date()} ({holes} day(s) of the segment have no index value)"
            if holes
            else f"{name} over the whole segment"
        )
        bench_provenance = Provenance(
            table="stock_observations",
            ticker=name,
            start=stretch.index[0].date(),
            end=stretch.index[-1].date(),
            note=note,
        )
        out[name] = series_metrics(stretch, config, provenance=bench_provenance)
        for metric, measure in relative_metrics(
            equity, level, config, provenance=bench_provenance
        ).items():
            out["portfolio"][f"{metric}_vs_{name}"] = measure
    return out


def run_backtest(
    prices: Mapping[str, PriceSeries],
    signal: Signal,
    *,
    start: date,
    end: date,
    config: AnalyticsConfig,
    benchmarks: Mapping[str, PriceSeries],
    turnover: TurnoverLookup | None = None,
    top_n: int | None = None,
    cost_rate: float | None = None,
) -> BacktestResult:
    days = trading_calendar(prices, start, end)
    notes: list[str] = []
    if not days:
        return BacktestResult(
            start,
            end,
            (),
            {"total_return": Measure.unavailable("backtest: no trading days in the period")},
            ["no trading days"],
        )
    segments: list[Segment] = []
    for chunk in split_segments(days, config.market.gap_threshold_days):
        if len(month_ends(chunk)) < 2:
            notes.append(
                f"segment {chunk[0]} -> {chunk[-1]} has fewer than two month ends: skipped"
            )
            continue
        equity, trades, rebalances, costs_paid = simulate_segment(
            chunk, prices, signal, config, turnover=turnover, top_n=top_n, cost_rate=cost_rate
        )
        levels: dict[str, pd.Series | None] = {
            name: benchmark_level(
                series, chunk, config.backtest.notional, config.market.gap_threshold_days
            )
            for name, series in benchmarks.items()
        }
        metrics = segment_metrics(equity, levels, rebalances, config)
        segments.append(
            Segment(
                chunk[0],
                chunk[-1],
                equity,
                {k: v for k, v in levels.items() if v is not None},
                tuple(trades),
                tuple(rebalances),
                metrics,
                costs_paid,
            )
        )
    if len(segments) > 1:
        notes.append(
            f"{len(segments)} segments separated by data gaps; 'linked' compounds them and "
            "ignores the gap periods"
        )
    linked: dict[str, Measure] = {}
    if segments:
        growth = 1.0
        for s in segments:
            growth *= float(s.equity.iloc[-1] / s.equity.iloc[0])
        provenance = Provenance(
            table="backtest",
            start=segments[0].start,
            end=segments[-1].end,
            note=f"{len(segments)} segment(s) compounded",
        )
        linked["total_return"] = (
            Measure.known(growth - 1.0, provenance) if growth != 1.0 else Measure.zero(provenance)
        )
        traded_days = sum((s.end - s.start).days for s in segments) / 365.25
        linked["cagr"] = (
            Measure.known(growth ** (1.0 / traded_days) - 1.0, provenance)
            if traded_days >= 1.0
            else Measure.unavailable("CAGR: under a year of traded history")
        )
        linked["costs_paid"] = Measure.known(sum(s.costs_paid for s in segments), provenance)
    return BacktestResult(start, end, tuple(segments), linked, notes)


__all__ = [
    "BacktestResult",
    "Rebalance",
    "Segment",
    "Signal",
    "Trade",
    "TurnoverLookup",
    "benchmark_level",
    "listed_on",
    "longest_continuous",
    "month_ends",
    "relative_metrics",
    "run_backtest",
    "segment_metrics",
    "series_metrics",
    "simulate_segment",
    "split_segments",
    "target_weights",
    "trading_calendar",
]
