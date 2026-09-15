"""Momentum diagram: the stock and ^NASI rebased to 100, and their ratio (relative
strength). Computed from the canonical prices on the dates both have; gaps in
either series break the lines.

    codegraph explore "momentum_figure relative_strength"
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from pathlib import Path

import matplotlib.pyplot as plt
from matplotlib.figure import Figure

from app.web.services.analytics.series import Gap, PriceSeries
from app.web.services.visualizations.common import (
    BLUE,
    GREY,
    PURPLE,
    TALL,
    broken_line,
    empty_figure,
    shade_gaps,
    write_png,
    year_axis,
)

DIAGRAM_KIND = "momentum"


@dataclass(frozen=True)
class MomentumData:
    ticker_symbol: str
    benchmark: str
    dates: list[date]
    stock_rebased: list[float]
    benchmark_rebased: list[float]
    relative: list[float]  # stock / benchmark, rebased to 1 at the start
    gaps: tuple[Gap, ...]


def relative_strength(
    stock: PriceSeries, benchmark: PriceSeries, *, start: date | None = None
) -> MomentumData | None:
    common = stock.close.index.intersection(benchmark.close.index)
    if start is not None:
        common = common[common >= start.isoformat()]
    if len(common) < 2:
        return None
    s = stock.close.loc[common].to_numpy(dtype=float)
    b = benchmark.close.loc[common].to_numpy(dtype=float)
    dates = [stamp.date() for stamp in common]
    gaps = tuple(g for g in stock.gaps + benchmark.gaps if dates[0] <= g.after <= dates[-1])
    return MomentumData(
        stock.ticker_symbol,
        benchmark.ticker_symbol,
        dates,
        list(s / s[0] * 100.0),
        list(b / b[0] * 100.0),
        list((s / s[0]) / (b / b[0])),
        gaps,
    )


def figure_for(data: MomentumData | None, *, ticker: str = "") -> Figure:
    if data is None:
        return empty_figure(f"{ticker} — momentum", "no dates shared with the benchmark")
    fig, (top, bottom) = plt.subplots(2, 1, figsize=TALL, sharex=True)
    xs, ys = broken_line(data.dates, data.stock_rebased, data.gaps)
    top.plot(xs, ys, color=BLUE, linewidth=1.1, label=data.ticker_symbol)
    xs, ys = broken_line(data.dates, data.benchmark_rebased, data.gaps)
    top.plot(xs, ys, color=GREY, linewidth=1.0, label=data.benchmark)
    top.set_ylabel("rebased to 100")
    top.legend(loc="upper left", frameon=False)
    shade_gaps(top, data.gaps)
    year_axis(top)
    xs, ys = broken_line(data.dates, data.relative, data.gaps)
    bottom.plot(xs, ys, color=PURPLE, linewidth=1.0)
    bottom.axhline(1.0, color=GREY, linewidth=0.8, linestyle="--")
    bottom.set_ylabel(f"relative strength vs {data.benchmark}")
    shade_gaps(bottom, data.gaps, label=False)
    year_axis(bottom)
    fig.suptitle(
        f"{data.ticker_symbol} — momentum vs {data.benchmark}", fontsize=14, x=0.01, ha="left"
    )
    top.set_title(
        f"{data.dates[0]} → {data.dates[-1]} · {len(data.dates):,} common observations · "
        f"relative strength now {data.relative[-1]:.2f}",
        fontsize=9,
        color="#555",
        loc="left",
    )
    fig.tight_layout(rect=(0, 0, 1, 0.965))
    return fig


def write_momentum(stock: PriceSeries, benchmark: PriceSeries, diagrams_dir: Path) -> Path:
    data = relative_strength(stock, benchmark)
    return write_png(
        figure_for(data, ticker=stock.ticker_symbol),
        diagrams_dir,
        DIAGRAM_KIND,
        stock.ticker_symbol,
    )


__all__ = ["DIAGRAM_KIND", "MomentumData", "figure_for", "relative_strength", "write_momentum"]
