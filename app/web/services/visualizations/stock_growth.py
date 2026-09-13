"""The stock-growth chart: one instrument, 2007 → latest scrape, gaps drawn as gaps.

``load_growth_series`` is the only I/O in this module and goes through
``NseScraperSource`` — the same read path everything else uses. ``figure_for`` and
``render_png`` are pure. ``write_diagram`` puts a static PNG under
``diagrams/stock-growth/<TICKER>.png``: it renders on GitHub, needs no JavaScript, and
is a fraction of the size of the interactive HTML it replaced.

    codegraph explore "figure_for write_diagram load_growth_series plot_stock read_growth"
"""

from __future__ import annotations

import io
import math
from pathlib import Path

import matplotlib

matplotlib.use("Agg")  # headless; must precede the pyplot import

import matplotlib.dates as mdates
import matplotlib.pyplot as plt
from matplotlib.figure import Figure

from app.web.core.exceptions import ResourceNotFoundError
from app.web.services.market_data.sources.nse_scraper import NseScraperSource
from app.web.services.visualizations.growth_series import (
    StockGrowthSeries,
    build_growth_series,
)
from app.web.utils.logger import get_logger

logger = get_logger("app.web.services.visualizations.stock_growth")

DIAGRAM_KIND = "stock-growth"
DEFAULT_DPI = 140
FIGSIZE = (14, 6.2)

LINE_COLOUR = "#1f5fbf"
GAP_FILL = (0.78, 0.24, 0.24, 0.10)
GAP_EDGE = (0.78, 0.24, 0.24, 0.55)
ACTION_COLOUR = "#8a6d00"
MARKER_COLOURS = {"first": "#2b8a3e", "last": "#1f5fbf", "high": "#d9480f", "low": "#862e9c"}
MARKER_OFFSETS = {"first": (8, -14), "last": (-8, 10), "high": (0, 12), "low": (0, -16)}
MARKER_ALIGN = {"first": "left", "last": "right", "high": "center", "low": "center"}


# -- data ------------------------------------------------------------------------------
def load_growth_series(source: NseScraperSource, ticker_symbol: str) -> StockGrowthSeries:
    """Read one instrument's timeline and shape it. Raises if there is nothing to draw."""
    ticker = ticker_symbol.strip().upper()
    instrument = next(
        (i for i in source.fetch_instruments() if i.get("ticker_symbol") == ticker), None
    )
    observations = source.fetch_observations(ticker, limit=50_000)
    if not observations:
        raise ResourceNotFoundError(
            f"No observations found for {ticker}.", detail=f"growth: no rows for {ticker}"
        )
    return build_growth_series(observations, instrument)


# -- figure ----------------------------------------------------------------------------
def figure_for(series: StockGrowthSeries) -> Figure:
    """A single-line time series with gaps broken and the key points annotated."""
    # matplotlib's date axis is float days; convert once so every artist agrees.
    day = mdates.date2num
    xs: list[float] = []
    ys: list[float] = []
    gap_starts = {g.after for g in series.gaps}
    for point in series.points:
        xs.append(day(point.trade_date))
        ys.append(point.close)
        if point.trade_date in gap_starts:
            # A NaN breaks the line: matplotlib never draws across it.
            xs.append(day(point.trade_date))
            ys.append(math.nan)

    fig, ax = plt.subplots(figsize=FIGSIZE)
    ax.plot(xs, ys, color=LINE_COLOUR, linewidth=1.1)

    for gap in series.gaps:
        ax.axvspan(
            day(gap.after), day(gap.before), facecolor=GAP_FILL, edgecolor=GAP_EDGE, linestyle=":"
        )
        ax.annotate(
            f"no data · {gap.days} days",
            xy=(day(gap.after), 1.0),
            xycoords=("data", "axes fraction"),
            xytext=(6, -12),
            textcoords="offset points",
            fontsize=8.5,
            color="#a33",
            va="top",
        )

    for action in series.corporate_actions:
        ax.axvline(day(action.on), color=ACTION_COLOUR, linewidth=1, linestyle="--")
        ax.annotate(
            f"x{action.ratio:.2f} step: suspected corporate action (unadjusted)",
            xy=(day(action.on), 0.03),
            xycoords=("data", "axes fraction"),
            xytext=(4, 0),
            textcoords="offset points",
            fontsize=7.5,
            color=ACTION_COLOUR,
            rotation=90,
            va="bottom",
        )

    for label, point in (
        ("first", series.first),
        ("last", series.last),
        ("high", series.high),
        ("low", series.low),
    ):
        colour = MARKER_COLOURS[label]
        ax.plot(day(point.trade_date), point.close, "o", color=colour, markersize=6, zorder=5)
        ax.annotate(
            f"{label}: {point.close:,.2f}\n{point.trade_date.isoformat()}",
            xy=(day(point.trade_date), point.close),
            xytext=MARKER_OFFSETS[label],
            textcoords="offset points",
            fontsize=8,
            color=colour,
            ha=MARKER_ALIGN[label],
            va="center",
        )

    change = series.overall_change_pct
    sign = "+" if change >= 0 else ""
    lineage = ""
    if len(series.source_tickers) > 1:
        lineage = f" · traded as {' → '.join(series.source_tickers)}"
    subtitle = (
        f"{series.first.trade_date.isoformat()} → {series.last.trade_date.isoformat()} · "
        f"{len(series.points):,} observations · {sign}{change:.1f}% overall · "
        f"{len(series.gaps)} gap{'s' if len(series.gaps) != 1 else ''}{lineage}"
    )
    if series.corporate_actions:
        subtitle += (
            f" · {len(series.corporate_actions)} suspected corporate action(s), prices unadjusted"
        )
    sector = f" · {series.sector}" if series.sector else ""
    fig.suptitle(
        f"{series.ticker_symbol} — {series.company_name}{sector}", fontsize=14, x=0.01, ha="left"
    )
    ax.set_title(subtitle, fontsize=9, color="#555", loc="left")

    ax.set_xlabel("trade date")
    ax.set_ylabel("close, KES (unadjusted)")
    ax.set_ylim(bottom=0)
    ax.xaxis.set_major_locator(mdates.YearLocator())
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%Y"))
    ax.grid(True, alpha=0.25)
    for side in ("top", "right"):
        ax.spines[side].set_visible(False)
    fig.tight_layout(rect=(0, 0, 1, 0.965))
    return fig


# -- output ----------------------------------------------------------------------------
def render_png(fig: Figure, *, dpi: int = DEFAULT_DPI) -> bytes:
    """PNG bytes. Closes the figure afterwards so ``--all`` does not hold 100+ open."""
    buffer = io.BytesIO()
    try:
        fig.savefig(buffer, format="png", dpi=dpi, bbox_inches="tight")
    finally:
        plt.close(fig)
    return buffer.getvalue()


def write_diagram(series: StockGrowthSeries, diagrams_dir: Path) -> Path:
    """Write ``diagrams/stock-growth/<TICKER>.png``."""
    kind_dir = diagrams_dir / DIAGRAM_KIND
    kind_dir.mkdir(parents=True, exist_ok=True)
    out = kind_dir / f"{series.ticker_symbol}.png"
    out.write_bytes(render_png(figure_for(series)))
    logger.info(
        "diagram_written",
        kind=DIAGRAM_KIND,
        ticker=series.ticker_symbol,
        points=len(series.points),
        gaps=len(series.gaps),
        path=str(out),
    )
    return out


__all__ = ["DIAGRAM_KIND", "figure_for", "load_growth_series", "render_png", "write_diagram"]
