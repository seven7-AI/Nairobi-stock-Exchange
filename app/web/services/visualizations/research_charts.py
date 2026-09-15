"""Diagrams drawn from the analytics store: sector performance, factor ranking,
fair value vs price, forecast fan, backtest equity, portfolio risk.

Each ``*_figure`` is pure over a small dataclass; the ``load_*`` functions read the
store. A chart with nothing to show says why instead of drawing an empty axis.

    codegraph explore "sector_figure ranking_figure valuation_figure forecast_figure"
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from statistics import median

import matplotlib.dates as mdates
import matplotlib.pyplot as plt
import numpy as np
from matplotlib.figure import Figure
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.web.db.analytics.models import (
    Forecast,
    MarketMetric,
    StockRanking,
    Valuation,
)
from app.web.db.analytics.services.backtests import (
    load_backtest_equity,
    load_backtest_results,
    load_backtest_runs,
)
from app.web.db.analytics.services.classifications import load_classifications
from app.web.db.analytics.services.forecasts import load_forecasts
from app.web.db.analytics.services.market_metrics import load_metrics
from app.web.db.analytics.services.portfolio_analyses import load_portfolio_analyses
from app.web.db.analytics.services.stock_rankings import load_rankings
from app.web.db.analytics.services.valuations import load_valuations
from app.web.services.analytics.classification.lookup import ClassificationIndex
from app.web.services.analytics.series import PriceSeries
from app.web.services.visualizations.common import (
    BLUE,
    GREEN,
    GREY,
    ORANGE,
    PURPLE,
    RED,
    TALL,
    WIDE,
    broken_line,
    empty_figure,
    series_dates,
    shade_gaps,
    tidy,
    write_png,
    year_axis,
)

FACTOR_COLOURS = {
    "quality": BLUE,
    "value": GREEN,
    "growth": ORANGE,
    "momentum": PURPLE,
    "risk": RED,
    "dividend": "#0b7285",
    "liquidity": GREY,
}


def latest_as_of(session: Session, model: type) -> date | None:  # type: ignore[type-arg]
    return session.execute(select(func.max(model.as_of_date))).scalar_one_or_none()


# --- sector analysis ---------------------------------------------------------------------


@dataclass(frozen=True)
class SectorPerformance:
    as_of: date
    metric: str
    #: sector label -> (median value, member count)
    sectors: dict[str, tuple[float, int]]


def load_sector_performance(
    session: Session, *, as_of: date | None = None, metric: str = "return_12m"
) -> SectorPerformance | None:
    day = as_of or latest_as_of(session, MarketMetric)
    if day is None:
        return None
    index = ClassificationIndex(load_classifications(session))
    rows = load_metrics(session, as_of_date=day, metric=metric)
    by_sector: dict[str, list[float]] = {}
    for r in rows:
        if r.status not in ("known", "zero") or r.value is None:
            continue
        assignment = index.sector_for(r.ticker_symbol, day)
        if assignment is None or assignment.sector_code in ("indices", "etf"):
            continue
        by_sector.setdefault(assignment.sector_label, []).append(float(r.value))
    sectors = {k: (float(median(v)), len(v)) for k, v in by_sector.items() if v}
    return SectorPerformance(day, metric, dict(sorted(sectors.items(), key=lambda kv: kv[1][0])))


def sector_figure(data: SectorPerformance | None) -> Figure:
    if data is None or not data.sectors:
        return empty_figure("Sector performance", "no market metrics stored yet")
    fig, ax = plt.subplots(figsize=WIDE)
    labels = list(data.sectors)
    values = [v for v, _ in data.sectors.values()]
    counts = [n for _, n in data.sectors.values()]
    colours = [GREEN if v >= 0 else RED for v in values]
    bars = ax.barh(labels, values, color=colours, alpha=0.85)
    for bar, value, n in zip(bars, values, counts, strict=True):
        ax.annotate(
            f"{value:+.1%} · {n}",
            xy=(bar.get_width(), bar.get_y() + bar.get_height() / 2),
            xytext=(4 if value >= 0 else -4, 0),
            textcoords="offset points",
            ha="left" if value >= 0 else "right",
            va="center",
            fontsize=8,
        )
    ax.axvline(0, color=GREY, linewidth=0.8)
    ax.xaxis.set_major_formatter(plt.FuncFormatter(lambda v, _: f"{v:.0%}"))
    ax.set_xlabel(f"median {data.metric.replace('_', ' ')} across members")
    tidy(ax)
    fig.suptitle(f"Sector performance as of {data.as_of}", fontsize=14, x=0.01, ha="left")
    ax.set_title(
        "median of the sector's members with a known value · count after the value",
        fontsize=9,
        color="#555",
        loc="left",
    )
    fig.tight_layout(rect=(0, 0, 1, 0.965))
    return fig


# --- factor ranking ----------------------------------------------------------------------


@dataclass(frozen=True)
class RankingBars:
    as_of: date
    model: str
    #: ticker -> (overall, classification, factor -> percentile)
    rows: list[tuple[str, float, str | None, dict[str, float | None]]]


def load_ranking_bars(
    session: Session, *, as_of: date | None = None, top: int = 15
) -> RankingBars | None:
    day = as_of or latest_as_of(session, StockRanking)
    if day is None:
        return None
    rows = [r for r in load_rankings(session, as_of_date=day) if r.overall_score is not None]
    rows.sort(key=lambda r: r.market_rank or 10**6)
    out = [
        (
            r.ticker_symbol,
            float(r.overall_score or 0.0),
            r.classification,
            {
                "quality": r.quality_score,
                "value": r.value_score,
                "growth": r.growth_score,
                "momentum": r.momentum_score,
                "risk": r.risk_score,
                "dividend": r.dividend_score,
                "liquidity": r.liquidity_score,
            },
        )
        for r in rows[:top]
    ]
    model = f"{rows[0].model_name} v{rows[0].model_version}" if rows else "factor-model"
    return RankingBars(day, model, out)


def ranking_figure(data: RankingBars | None) -> Figure:
    if data is None or not data.rows:
        return empty_figure("Factor ranking", "no scored rankings stored yet")
    fig, (left, right) = plt.subplots(1, 2, figsize=TALL, gridspec_kw={"width_ratios": [1, 2]})
    tickers = [t for t, _, _, _ in data.rows][::-1]
    overall = [o for _, o, _, _ in data.rows][::-1]
    classes = [c or "" for _, _, c, _ in data.rows][::-1]
    left.barh(tickers, overall, color=BLUE, alpha=0.85)
    for i, (o, c) in enumerate(zip(overall, classes, strict=True)):
        left.annotate(
            f"{o:.0f} · {c}",
            xy=(o, i),
            xytext=(4, 0),
            textcoords="offset points",
            va="center",
            fontsize=8,
        )
    left.set_xlim(0, 115)
    left.set_xlabel("overall score (0-100)")
    tidy(left)
    factors = list(FACTOR_COLOURS)
    width = 0.8 / len(factors)
    ys = np.arange(len(tickers))
    for j, factor in enumerate(factors):
        values = [(per.get(factor) or 0.0) for _, _, _, per in data.rows][::-1]
        right.barh(
            ys + (j - len(factors) / 2) * width + width / 2,
            values,
            height=width,
            color=FACTOR_COLOURS[factor],
            label=factor,
        )
    right.set_yticks(ys)
    right.set_yticklabels(tickers)
    right.set_xlim(0, 100)
    right.set_xlabel("factor percentile in the market (missing = 0, drawn empty)")
    right.legend(loc="lower right", frameon=False, fontsize=8, ncol=2)
    tidy(right)
    fig.suptitle(
        f"Top {len(data.rows)} by {data.model} as of {data.as_of}", fontsize=14, x=0.01, ha="left"
    )
    fig.tight_layout(rect=(0, 0, 1, 0.965))
    return fig


# --- valuation ----------------------------------------------------------------------------


@dataclass(frozen=True)
class ValuationBars:
    as_of: date
    #: ticker -> (fair_low, intrinsic, fair_high, price, actionable)
    rows: list[tuple[str, float, float, float, float, bool | None]]


def load_valuation_bars(session: Session, *, as_of: date | None = None) -> ValuationBars | None:
    day = as_of or latest_as_of(session, Valuation)
    if day is None:
        return None
    rows = []
    for v in load_valuations(session, as_of_date=day, method="blended"):
        if (
            v.status != "known"
            or v.base is None
            or v.fair_low is None
            or v.fair_high is None
            or not v.price
        ):
            continue
        rows.append(
            (
                v.ticker_symbol,
                float(v.fair_low),
                float(v.base),
                float(v.fair_high),
                float(v.price),
                v.actionable,
            )
        )
    rows.sort(key=lambda r: r[2] / r[4] - 1.0)
    return ValuationBars(day, rows)


def valuation_figure(data: ValuationBars | None) -> Figure:
    if data is None or not data.rows:
        return empty_figure("Fair value vs price", "no blended valuations stored yet")
    fig, ax = plt.subplots(figsize=WIDE)
    rows = sorted(data.rows, key=lambda r: r[2] / r[4] - 1.0)  # by upside, whatever the order given
    xs = np.arange(len(rows))
    for i, (_ticker, low, mid, high, price, actionable) in enumerate(rows):
        colour = BLUE if actionable else GREY
        ax.plot(
            [i, i],
            [low / price - 1, high / price - 1],
            color=colour,
            linewidth=6,
            alpha=0.35,
            solid_capstyle="butt",
        )
        ax.plot(i, mid / price - 1, "o", color=colour, markersize=6)
    ax.axhline(0, color=RED, linewidth=0.9, linestyle="--")
    ax.set_xticks(xs)
    ax.set_xticklabels([r[0] for r in rows], rotation=45, ha="right")
    ax.yaxis.set_major_formatter(plt.FuncFormatter(lambda v, _: f"{v:+.0%}"))
    ax.set_ylabel("fair value relative to price (range = mean of bears … bulls)")
    tidy(ax)
    fig.suptitle(f"Fair value vs price as of {data.as_of}", fontsize=14, x=0.01, ha="left")
    ax.set_title(
        "dot = blended intrinsic value · grey = uncertainty at or above the threshold "
        "(margin not actionable)",
        fontsize=9,
        color="#555",
        loc="left",
    )
    fig.tight_layout(rect=(0, 0, 1, 0.965))
    return fig


# --- forecasts ---------------------------------------------------------------------------


@dataclass(frozen=True)
class FanChart:
    ticker_symbol: str
    model: str
    origin: date
    price: float
    history_dates: list[date]
    history: list[float]
    gaps: tuple
    #: horizon months -> (q05, q25, q50, q75, q95) as prices
    quantiles: dict[int, tuple[float, float, float, float, float]]


def load_fan_chart(
    session: Session,
    series: PriceSeries,
    *,
    model: str = "ar1",
    as_of: date | None = None,
    months_back: int = 24,
) -> FanChart | None:
    day = (
        as_of
        or session.execute(
            select(func.max(Forecast.as_of_date)).where(
                Forecast.ticker_symbol == series.ticker_symbol
            )
        ).scalar_one_or_none()
    )
    if day is None:
        return None
    rows = [
        r
        for r in load_forecasts(
            session, as_of_date=day, ticker_symbol=series.ticker_symbol, model=model
        )
        if r.status in ("known", "zero")
    ]
    located = series.close_on_or_before(day)
    if not rows or located is None:
        return None
    price = located[1]
    start = date(day.year - (months_back // 12), day.month, 1) if months_back >= 12 else day
    part = series.between(start, day)
    quantiles = {
        r.horizon_months: tuple(
            price * (1.0 + float(q)) for q in (r.q05, r.q25, r.q50, r.q75, r.q95)
        )
        for r in rows
        if None not in (r.q05, r.q25, r.q50, r.q75, r.q95)
    }
    return FanChart(
        series.ticker_symbol,
        model,
        day,
        price,
        series_dates(part),
        list(part.close.to_numpy(dtype=float)),
        part.gaps,
        quantiles,
    )  # type: ignore[arg-type]


def forecast_figure(data: FanChart | None, *, ticker: str = "") -> Figure:
    if data is None or not data.quantiles:
        return empty_figure(f"{ticker} — forecast", "no known forecast stored for this instrument")
    fig, ax = plt.subplots(figsize=WIDE)
    xs, ys = broken_line(data.history_dates, data.history, data.gaps)
    ax.plot(xs, ys, color=BLUE, linewidth=1.1, label="close")
    shade_gaps(ax, data.gaps)
    horizons = sorted(data.quantiles)
    origin = mdates.date2num(data.origin)
    fan_x = [origin] + [origin + h * 30.4 for h in horizons]
    q = data.quantiles
    for lo_i, hi_i, alpha, label in ((0, 4, 0.15, "q05-q95"), (1, 3, 0.30, "q25-q75")):
        lows = [data.price] + [q[h][lo_i] for h in horizons]
        highs = [data.price] + [q[h][hi_i] for h in horizons]
        ax.fill_between(fan_x, lows, highs, color=PURPLE, alpha=alpha, label=label)
    ax.plot(
        fan_x,
        [data.price] + [q[h][2] for h in horizons],
        color=PURPLE,
        linewidth=1.2,
        linestyle="--",
        label="median",
    )
    ax.axvline(origin, color=GREY, linewidth=0.8)
    ax.legend(loc="upper left", frameon=False)
    ax.set_ylabel("close, KES")
    year_axis(ax)
    fig.suptitle(
        f"{data.ticker_symbol} — {data.model} forecast fan from {data.origin}",
        fontsize=14,
        x=0.01,
        ha="left",
    )
    twelve = q.get(12)
    note = ""
    if twelve:
        note = (
            f"12M median {twelve[2] / data.price - 1:+.1%} · "
            f"q05 {twelve[0] / data.price - 1:+.1%} · q95 {twelve[4] / data.price - 1:+.1%}"
        )
    ax.set_title(
        f"normal in log returns, stated as such · {note}", fontsize=9, color="#555", loc="left"
    )
    fig.tight_layout(rect=(0, 0, 1, 0.965))
    return fig


# --- backtests -----------------------------------------------------------------------------


@dataclass(frozen=True)
class EquityCurves:
    run_id: int
    name: str
    start: date
    end: date
    dates: list[date]
    segments: list[str]
    equity: list[float]
    benchmarks: dict[str, list[float | None]]
    summary: dict[str, str] = field(default_factory=dict)


def load_equity_curves(
    session: Session, *, run_id: int | None = None, name: str | None = None
) -> EquityCurves | None:
    runs = load_backtest_runs(session, name=name)
    runs = [r for r in runs if r.status == "known"]
    if run_id is not None:
        runs = [r for r in runs if r.id == run_id]
    elif name is None:
        runs = [r for r in runs if r.purpose == "run"] or runs  # the model runs, not companions
    if not runs:
        return None
    run = runs[-1]
    rows = load_backtest_equity(session, run.id)
    if not rows:
        return None
    names: list[str] = []
    for r in rows:
        for b in r.benchmarks or {}:
            if b not in names:
                names.append(b)
    results = {(r.segment, r.series, r.metric): r for r in load_backtest_results(session, run.id)}
    summary = {}
    for key, label in (
        ("total_return", "return"),
        ("cagr", "CAGR"),
        ("sharpe", "Sharpe"),
        ("max_drawdown", "MDD"),
    ):
        row = results.get(("1", "portfolio", key))
        summary[label] = (
            f"{row.value:.1%}"
            if row is not None and row.value is not None and key != "sharpe"
            else (f"{row.value:.2f}" if row is not None and row.value is not None else "n/a")
        )
    return EquityCurves(
        run.id,
        run.name,
        run.start_date,
        run.end_date,
        [r.day for r in rows],
        [r.segment for r in rows],
        [float(r.equity) for r in rows],
        {b: [(r.benchmarks or {}).get(b) for r in rows] for b in names},
        summary,
    )


def backtest_figure(data: EquityCurves | None) -> Figure:
    if data is None:
        return empty_figure("Backtest", "no stored backtest run")
    fig, (top, bottom) = plt.subplots(2, 1, figsize=TALL, sharex=True)
    xs = [mdates.date2num(d) for d in data.dates]

    # break lines between segments (a data gap): NaN at each segment change
    def broken(values: Sequence[float | None]) -> list[float]:
        out: list[float] = []
        for i, v in enumerate(values):
            if i > 0 and data.segments[i] != data.segments[i - 1]:
                out.append(np.nan)
            else:
                out.append(np.nan if v is None else float(v))
        return out

    top.plot(xs, broken(data.equity), color=BLUE, linewidth=1.2, label=data.name)
    for name, values in data.benchmarks.items():
        top.plot(
            xs,
            broken(values),
            color=GREY if name.startswith("^NASI") else ORANGE,
            linewidth=0.9,
            label=name,
        )
    top.set_ylabel("equity, KES (each segment starts at the notional)")
    top.legend(loc="upper left", frameon=False)
    year_axis(top)
    equity = np.array(data.equity, dtype=float)
    dd = np.zeros(len(equity))
    peak = -np.inf
    for i, v in enumerate(equity):
        if i == 0 or data.segments[i] != data.segments[i - 1]:
            peak = v
        peak = max(peak, v)
        dd[i] = v / peak - 1.0
    bottom.fill_between(xs, broken(list(dd)), 0, color=RED, alpha=0.25)
    bottom.set_ylabel("portfolio drawdown")
    year_axis(bottom)
    fig.suptitle(
        f"Backtest run {data.run_id} '{data.name}' {data.start} → {data.end}",
        fontsize=14,
        x=0.01,
        ha="left",
    )
    top.set_title(
        "segment 1: " + " · ".join(f"{k} {v}" for k, v in data.summary.items()),
        fontsize=9,
        color="#555",
        loc="left",
    )
    fig.tight_layout(rect=(0, 0, 1, 0.965))
    return fig


# --- portfolio risk ------------------------------------------------------------------------


@dataclass(frozen=True)
class PortfolioRisk:
    as_of: date
    name: str
    correlation: dict[str, dict[str, float]]
    #: ticker -> (volatility, return_12m) for the risk/return scatter
    scatter: dict[str, tuple[float, float]]
    warnings: list[str]


def load_portfolio_risk(
    session: Session, *, name: str | None = None, as_of: date | None = None
) -> PortfolioRisk | None:
    analyses = load_portfolio_analyses(session, name=name)
    if not analyses:
        return None
    row = analyses[-1]
    day = as_of or latest_as_of(session, MarketMetric) or row.as_of_date
    vol = {
        r.ticker_symbol: float(r.value)
        for r in load_metrics(session, as_of_date=day, metric="volatility_annualised")
        if r.value is not None and r.status in ("known", "zero")
    }
    ret = {
        r.ticker_symbol: float(r.value)
        for r in load_metrics(session, as_of_date=day, metric="return_12m")
        if r.value is not None and r.status in ("known", "zero")
    }
    scatter = {t: (vol[t], ret[t]) for t in vol if t in ret and not t.startswith("^")}
    return PortfolioRisk(
        row.as_of_date, row.name, dict(row.correlation or {}), scatter, list(row.warnings)
    )


def portfolio_figure(data: PortfolioRisk | None) -> Figure:
    if data is None:
        return empty_figure("Portfolio risk", "no stored portfolio analysis")
    fig, (left, right) = plt.subplots(1, 2, figsize=(16, 7))
    tickers = list(data.correlation)
    if tickers:
        matrix = np.array([[data.correlation[a].get(b, np.nan) for b in tickers] for a in tickers])
        image = left.imshow(matrix, cmap="RdBu_r", vmin=-1, vmax=1)
        left.set_xticks(range(len(tickers)))
        left.set_yticks(range(len(tickers)))
        left.set_xticklabels(tickers, rotation=45, ha="right")
        left.set_yticklabels(tickers)
        for i in range(len(tickers)):
            for j in range(len(tickers)):
                left.text(
                    j,
                    i,
                    f"{matrix[i, j]:.2f}",
                    ha="center",
                    va="center",
                    fontsize=7,
                    color="black" if abs(matrix[i, j]) < 0.6 else "white",
                )
        fig.colorbar(image, ax=left, fraction=0.046, pad=0.04)
    else:
        left.set_axis_off()
        left.text(
            0.5,
            0.5,
            "correlation unavailable\n(positions lack history)",
            ha="center",
            va="center",
            color="#a33",
        )
    left.set_title(
        f"'{data.name}' pairwise correlation as of {data.as_of}", fontsize=10, loc="left"
    )
    held = set(tickers) or set()
    for ticker, (v, r) in data.scatter.items():
        colour = BLUE if ticker in held else GREY
        right.plot(
            v,
            r,
            "o",
            color=colour,
            markersize=5 if ticker in held else 3,
            alpha=0.9 if ticker in held else 0.5,
        )
        if ticker in held:
            right.annotate(ticker, xy=(v, r), xytext=(4, 2), textcoords="offset points", fontsize=8)
    right.set_xlabel("annualised volatility")
    right.set_ylabel("12-month return")
    right.xaxis.set_major_formatter(plt.FuncFormatter(lambda x, _: f"{x:.0%}"))
    right.yaxis.set_major_formatter(plt.FuncFormatter(lambda y, _: f"{y:+.0%}"))
    right.axhline(0, color=GREY, linewidth=0.8)
    right.set_title(
        "risk / return of every scored stock · held positions in blue", fontsize=10, loc="left"
    )
    tidy(right)
    fig.suptitle("Portfolio risk", fontsize=14, x=0.01, ha="left")
    if data.warnings:
        fig.text(
            0.01,
            0.01,
            "warnings: " + " · ".join(w[:60] for w in data.warnings[:3]),
            fontsize=8,
            color="#a33",
        )
    fig.tight_layout(rect=(0, 0.03, 1, 0.965))
    return fig


# --- writers ------------------------------------------------------------------------------


def write_sector(session: Session, diagrams_dir: Path, *, as_of: date | None = None) -> Path:
    data = load_sector_performance(session, as_of=as_of)
    return write_png(
        sector_figure(data),
        diagrams_dir,
        "sector-analysis",
        f"sector-performance-{data.as_of if data else 'none'}",
    )


def write_ranking(session: Session, diagrams_dir: Path, *, as_of: date | None = None) -> Path:
    data = load_ranking_bars(session, as_of=as_of)
    return write_png(
        ranking_figure(data),
        diagrams_dir,
        "factor-ranking",
        f"top-ranking-{data.as_of if data else 'none'}",
    )


def write_valuation(session: Session, diagrams_dir: Path, *, as_of: date | None = None) -> Path:
    data = load_valuation_bars(session, as_of=as_of)
    return write_png(
        valuation_figure(data),
        diagrams_dir,
        "valuation",
        f"fair-value-vs-price-{data.as_of if data else 'none'}",
    )


def write_forecast(
    session: Session, series: PriceSeries, diagrams_dir: Path, *, as_of: date | None = None
) -> Path:
    data = load_fan_chart(session, series, as_of=as_of)
    return write_png(
        forecast_figure(data, ticker=series.ticker_symbol),
        diagrams_dir,
        "forecasts",
        series.ticker_symbol,
    )


def write_backtest(
    session: Session, diagrams_dir: Path, *, run_id: int | None = None, name: str | None = None
) -> Path:
    data = load_equity_curves(session, run_id=run_id, name=name)
    label = f"run-{data.run_id}-{data.name}" if data else "none"
    return write_png(backtest_figure(data), diagrams_dir, "backtests", label.replace(":", "-"))


def write_all_backtests(session: Session, diagrams_dir: Path) -> list[Path]:
    """One chart per stored model run (purpose ``run``); a placeholder when there is none."""
    runs = [r for r in load_backtest_runs(session) if r.purpose == "run" and r.status == "known"]
    if not runs:
        return [write_backtest(session, diagrams_dir)]
    return [write_backtest(session, diagrams_dir, run_id=r.id) for r in runs]


def write_portfolio(session: Session, diagrams_dir: Path, *, name: str | None = None) -> Path:
    data = load_portfolio_risk(session, name=name)
    return write_png(
        portfolio_figure(data),
        diagrams_dir,
        "portfolio-risk",
        (data.name if data else "none").replace("/", "-"),
    )


def write_all_portfolios(session: Session, diagrams_dir: Path) -> list[Path]:
    """One chart per analysis name (its latest analysis); a placeholder when none."""
    names = sorted({a.name for a in load_portfolio_analyses(session)})
    if not names:
        return [write_portfolio(session, diagrams_dir)]
    return [write_portfolio(session, diagrams_dir, name=n) for n in names]


__all__ = [
    "EquityCurves",
    "FanChart",
    "PortfolioRisk",
    "RankingBars",
    "SectorPerformance",
    "ValuationBars",
    "backtest_figure",
    "forecast_figure",
    "latest_as_of",
    "load_equity_curves",
    "load_fan_chart",
    "load_portfolio_risk",
    "load_ranking_bars",
    "load_sector_performance",
    "load_valuation_bars",
    "portfolio_figure",
    "ranking_figure",
    "sector_figure",
    "valuation_figure",
    "write_all_backtests",
    "write_all_portfolios",
    "write_backtest",
    "write_forecast",
    "write_portfolio",
    "write_ranking",
    "write_sector",
    "write_valuation",
]
