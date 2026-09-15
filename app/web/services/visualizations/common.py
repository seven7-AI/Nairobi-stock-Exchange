"""Shared plotting helpers for the research diagrams.

Every chart module follows ``stock_growth.py``: a pure ``figure_for(data)`` that
returns a matplotlib ``Figure``, ``render_png`` to bytes, and a ``write_*`` that
puts the PNG under ``diagrams/<kind>/``. Gaps in a price series are drawn as gaps
(a NaN breaks the line and a shaded span names the hole); nothing is interpolated.

    codegraph explore "broken_line shade_gaps render_png DIAGRAM_KINDS"
"""

from __future__ import annotations

import io
import math
from collections.abc import Iterable, Sequence
from datetime import date
from pathlib import Path

import matplotlib

matplotlib.use("Agg")  # headless; must precede the pyplot import

import matplotlib.dates as mdates
import matplotlib.pyplot as plt
from matplotlib.axes import Axes
from matplotlib.figure import Figure

from app.web.services.analytics.series import Gap, PriceSeries

DEFAULT_DPI = 140
WIDE = (14, 6.2)
TALL = (14, 8.5)
SQUARE = (9, 8)
BLUE = "#1f5fbf"
GREEN = "#2b8a3e"
RED = "#c92a2a"
ORANGE = "#d9480f"
PURPLE = "#862e9c"
GREY = "#868e96"
GAP_FILL = (0.78, 0.24, 0.24, 0.10)
GAP_EDGE = (0.78, 0.24, 0.24, 0.55)

DIAGRAM_KINDS = (
    "volatility",
    "momentum",
    "sector-analysis",
    "factor-ranking",
    "valuation",
    "forecasts",
    "backtests",
    "portfolio-risk",
)


def broken_line(
    days: Sequence[date], values: Sequence[float], gaps: Iterable[Gap]
) -> tuple[list[float], list[float]]:
    """x/y with a NaN inserted after every gap start so matplotlib never draws across it."""
    starts = {g.after for g in gaps}
    xs: list[float] = []
    ys: list[float] = []
    for d, v in zip(days, values, strict=True):
        xs.append(mdates.date2num(d))
        ys.append(float(v))
        if d in starts:
            xs.append(mdates.date2num(d))
            ys.append(math.nan)
    return xs, ys


def shade_gaps(ax: Axes, gaps: Iterable[Gap], *, label: bool = True) -> None:
    for gap in gaps:
        ax.axvspan(
            mdates.date2num(gap.after),
            mdates.date2num(gap.before),
            facecolor=GAP_FILL,
            edgecolor=GAP_EDGE,
            linestyle=":",
        )
        if label:
            ax.annotate(
                f"no data · {gap.days} days",
                xy=(mdates.date2num(gap.after), 1.0),
                xycoords=("data", "axes fraction"),
                xytext=(6, -12),
                textcoords="offset points",
                fontsize=8,
                color="#a33",
                va="top",
            )


def series_dates(series: PriceSeries) -> list[date]:
    return [stamp.date() for stamp in series.dates]


def year_axis(ax: Axes) -> None:
    ax.xaxis.set_major_locator(mdates.AutoDateLocator())
    ax.xaxis.set_major_formatter(mdates.ConciseDateFormatter(ax.xaxis.get_major_locator()))
    ax.grid(True, alpha=0.25)
    for side in ("top", "right"):
        ax.spines[side].set_visible(False)


def tidy(ax: Axes) -> None:
    ax.grid(True, alpha=0.25)
    for side in ("top", "right"):
        ax.spines[side].set_visible(False)


def render_png(fig: Figure, *, dpi: int = DEFAULT_DPI) -> bytes:
    """PNG bytes; closes the figure so ``plot --all`` never holds hundreds open."""
    buffer = io.BytesIO()
    try:
        fig.savefig(buffer, format="png", dpi=dpi, bbox_inches="tight")
    finally:
        plt.close(fig)
    return buffer.getvalue()


def write_png(fig: Figure, diagrams_dir: Path, kind: str, name: str) -> Path:
    kind_dir = diagrams_dir / kind
    kind_dir.mkdir(parents=True, exist_ok=True)
    out = kind_dir / f"{name}.png"
    out.write_bytes(render_png(fig))
    return out


def empty_figure(title: str, reason: str, *, figsize: tuple[float, float] = WIDE) -> Figure:
    """A chart that says why it has nothing to show - never a blank or a made-up line."""
    fig, ax = plt.subplots(figsize=figsize)
    ax.set_axis_off()
    fig.suptitle(title, fontsize=14, x=0.01, ha="left")
    ax.text(0.5, 0.5, reason, ha="center", va="center", fontsize=12, color="#a33", wrap=True)
    return fig


__all__ = [
    "BLUE",
    "DEFAULT_DPI",
    "DIAGRAM_KINDS",
    "GREEN",
    "GREY",
    "ORANGE",
    "PURPLE",
    "RED",
    "SQUARE",
    "TALL",
    "WIDE",
    "broken_line",
    "empty_figure",
    "render_png",
    "series_dates",
    "shade_gaps",
    "tidy",
    "write_png",
    "year_axis",
]
