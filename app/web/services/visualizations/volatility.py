"""Volatility diagram: rolling annualised volatility and drawdown from peak.

Both panels are computed from the canonical price series in-segment (a gap
breaks the line and resets the drawdown peak; no value ever spans a hole).

    codegraph explore "volatility_figure rolling_volatility drawdown_series"
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
from matplotlib.figure import Figure

from app.web.services.analytics.config import DEFAULT_CONFIG, AnalyticsConfig
from app.web.services.analytics.series import PriceSeries
from app.web.services.visualizations.common import (
    BLUE,
    RED,
    TALL,
    broken_line,
    series_dates,
    shade_gaps,
    write_png,
    year_axis,
)

DIAGRAM_KIND = "volatility"
WINDOW_DAYS = 63


@dataclass(frozen=True)
class VolatilityData:
    series: PriceSeries
    window_days: int
    dates: list[date]
    rolling_vol: list[float]  # NaN until the window fills, and after every gap
    drawdown: list[float]  # <= 0, from the running peak within the segment


def rolling_volatility(series: PriceSeries, window: int, config: AnalyticsConfig) -> np.ndarray:
    closes = series.close.to_numpy(dtype=float)
    segments = series.segment.to_numpy()
    out = np.full(len(closes), np.nan)
    log_returns = np.diff(np.log(closes), prepend=np.nan)
    log_returns[np.r_[True, segments[1:] != segments[:-1]]] = np.nan  # never across a gap
    annualiser = np.sqrt(config.market.trading_days_per_year)
    for i in range(window, len(closes)):
        chunk = log_returns[i - window + 1 : i + 1]
        if np.isnan(chunk).any():
            continue
        out[i] = float(chunk.std(ddof=1) * annualiser)
    return out


def drawdown_series(series: PriceSeries) -> np.ndarray:
    closes = series.close.to_numpy(dtype=float)
    segments = series.segment.to_numpy()
    out = np.zeros(len(closes))
    peak = -np.inf
    current = None
    for i, (c, s) in enumerate(zip(closes, segments, strict=True)):
        if s != current:
            current, peak = s, c
        peak = max(peak, c)
        out[i] = c / peak - 1.0
    return out


def volatility_data(
    series: PriceSeries, *, window: int = WINDOW_DAYS, config: AnalyticsConfig = DEFAULT_CONFIG
) -> VolatilityData:
    return VolatilityData(
        series,
        window,
        series_dates(series),
        list(rolling_volatility(series, window, config)),
        list(drawdown_series(series)),
    )


def figure_for(data: VolatilityData) -> Figure:
    fig, (top, bottom) = plt.subplots(2, 1, figsize=TALL, sharex=True)
    xs, ys = broken_line(data.dates, data.rolling_vol, data.series.gaps)
    top.plot(xs, ys, color=BLUE, linewidth=1.0)
    top.set_ylabel(f"{data.window_days}-day volatility, annualised")
    top.set_ylim(bottom=0)
    shade_gaps(top, data.series.gaps)
    year_axis(top)
    xs, ys = broken_line(data.dates, data.drawdown, data.series.gaps)
    bottom.fill_between(xs, ys, 0, color=RED, alpha=0.25)
    bottom.plot(xs, ys, color=RED, linewidth=0.9)
    bottom.set_ylabel("drawdown from peak")
    bottom.set_ylim(top=0.02)
    shade_gaps(bottom, data.series.gaps, label=False)
    year_axis(bottom)
    known = [v for v in data.rolling_vol if not np.isnan(v)]
    worst = min(data.drawdown) if data.drawdown else 0.0
    subtitle = (
        f"{data.dates[0]} → {data.dates[-1]} · {len(data.dates):,} observations · "
        f"latest vol {known[-1]:.1%} · max drawdown {worst:.1%} · "
        f"{len(data.series.gaps)} gap{'s' if len(data.series.gaps) != 1 else ''}"
        if known
        else f"{len(data.dates)} observations: fewer than the {data.window_days}-day window"
    )
    fig.suptitle(
        f"{data.series.ticker_symbol} — volatility and drawdown", fontsize=14, x=0.01, ha="left"
    )
    top.set_title(subtitle, fontsize=9, color="#555", loc="left")
    fig.tight_layout(rect=(0, 0, 1, 0.965))
    return fig


def write_volatility(series: PriceSeries, diagrams_dir: Path) -> Path:
    return write_png(
        figure_for(volatility_data(series)), diagrams_dir, DIAGRAM_KIND, series.ticker_symbol
    )


__all__ = [
    "DIAGRAM_KIND",
    "VolatilityData",
    "drawdown_series",
    "figure_for",
    "rolling_volatility",
    "volatility_data",
    "write_volatility",
]
