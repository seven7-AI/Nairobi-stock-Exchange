"""The stock-growth chart: one instrument, 2007 → latest scrape, gaps drawn as gaps.

``load_growth_series`` is the only I/O in this module and goes through
``NseScraperSource`` — the same read path everything else uses. ``figure_for`` and
``render_html`` are pure. ``write_diagram`` puts the result under
``diagrams/stock-growth/<TICKER>.html`` with ``plotly.min.js`` written once into
``diagrams/assets/`` so every chart is small and works offline.

    codegraph explore "figure_for write_diagram load_growth_series plot_stock read_growth"
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import plotly.graph_objects as go
import plotly.io as pio
from plotly.offline import get_plotlyjs

from app.web.core.exceptions import ResourceNotFoundError
from app.web.services.market_data.sources.nse_scraper import NseScraperSource
from app.web.services.visualizations.growth_series import StockGrowthSeries, build_growth_series
from app.web.utils.logger import get_logger

logger = get_logger("app.web.services.visualizations.stock_growth")

DIAGRAM_KIND = "stock-growth"
ASSETS_DIR_NAME = "assets"

LINE_COLOUR = "#1f5fbf"
GAP_COLOUR = "rgba(200, 60, 60, 0.10)"
GAP_LINE_COLOUR = "rgba(200, 60, 60, 0.55)"
ACTION_COLOUR = "#8a6d00"
HOVER_TEMPLATE = (
    "%{x|%Y-%m-%d}<br>close %{y:,.2f}<br>%{customdata[0]} · %{customdata[1]}<extra></extra>"
)
MARKER_COLOURS = {"first": "#2b8a3e", "last": "#1f5fbf", "high": "#d9480f", "low": "#862e9c"}


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
def figure_for(series: StockGrowthSeries) -> go.Figure:
    """A single-line time series with gaps broken and the key points annotated."""
    xs: list[Any] = []
    ys: list[float | None] = []
    custom: list[list[str]] = []
    gap_starts = {g.after for g in series.gaps}
    for point in series.points:
        xs.append(point.trade_date)
        ys.append(point.close)
        custom.append([point.data_source, point.source_ticker])
        if point.trade_date in gap_starts:
            # A None breaks the line: plotly draws nothing across the gap.
            xs.append(point.trade_date)
            ys.append(None)
            custom.append(["", ""])

    fig = go.Figure()
    fig.add_trace(
        go.Scatter(
            x=xs,
            y=ys,
            mode="lines",
            name="close (unadjusted)",
            line={"color": LINE_COLOUR, "width": 1.4},
            connectgaps=False,
            customdata=custom,
            # Rendered client-side from x/y/customdata, so the file carries no
            # per-point strings - ~5x smaller than prebuilt hover text.
            hovertemplate=HOVER_TEMPLATE,
        )
    )

    for action in series.corporate_actions:
        fig.add_vline(
            x=action.on.isoformat(),
            line={"width": 1, "color": ACTION_COLOUR, "dash": "dash"},
            annotation_text=f"x{action.ratio:.2f} step: suspected corporate action (unadjusted)",
            annotation_position="top right",
            annotation_font={"size": 9, "color": ACTION_COLOUR},
        )

    for gap in series.gaps:
        fig.add_vrect(
            x0=gap.after,
            x1=gap.before,
            fillcolor=GAP_COLOUR,
            line={"width": 1, "color": GAP_LINE_COLOUR, "dash": "dot"},
            layer="below",
            annotation_text=f"no data · {gap.days} days",
            annotation_position="top left",
            annotation_font={"size": 10, "color": "#a33"},
        )

    for label, point, position in (
        ("first", series.first, "bottom right"),
        ("last", series.last, "top left"),
        ("high", series.high, "top center"),
        ("low", series.low, "bottom center"),
    ):
        fig.add_trace(
            go.Scatter(
                x=[point.trade_date],
                y=[point.close],
                mode="markers+text",
                name=label,
                marker={"size": 9, "color": MARKER_COLOURS[label]},
                text=[f"{label}: {point.close:,.2f}"],
                textposition=position,
                textfont={"size": 10, "color": MARKER_COLOURS[label]},
                hovertext=[f"{label} · {point.trade_date.isoformat()} · {point.close:,.2f}"],
                hoverinfo="text",
                showlegend=False,
            )
        )

    change = series.overall_change_pct
    sign = "+" if change >= 0 else ""
    lineage = (
        f" · traded as {' → '.join(series.source_tickers)}"
        if len(series.source_tickers) > 1
        else ""
    )
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
    title_text = f"{series.ticker_symbol} — {series.company_name}{sector}<br><sup>{subtitle}</sup>"
    fig.update_layout(
        title={"text": title_text},
        xaxis={"title": "trade date", "dtick": "M12", "tickformat": "%Y", "showgrid": True},
        yaxis={"title": "close, KES (unadjusted)", "rangemode": "tozero"},
        template="plotly_white",
        hovermode="x unified",
        margin={"l": 60, "r": 30, "t": 90, "b": 60},
        height=520,
    )
    return fig


# -- output ----------------------------------------------------------------------------
def render_html(fig: go.Figure, *, include_plotlyjs: str | bool = "cdn") -> str:
    """Standalone HTML. ``"cdn"`` for a served page; a path string for a written file."""
    return pio.to_html(fig, include_plotlyjs=include_plotlyjs, full_html=True)


def write_diagram(series: StockGrowthSeries, diagrams_dir: Path) -> Path:
    """Write ``diagrams/stock-growth/<TICKER>.html``, sharing one ``assets/plotly.min.js``."""
    kind_dir = diagrams_dir / DIAGRAM_KIND
    assets_dir = diagrams_dir / ASSETS_DIR_NAME
    kind_dir.mkdir(parents=True, exist_ok=True)
    assets_dir.mkdir(parents=True, exist_ok=True)

    plotly_js = assets_dir / "plotly.min.js"
    if not plotly_js.exists():
        plotly_js.write_text(get_plotlyjs(), encoding="utf-8")

    fig = figure_for(series)
    html = render_html(fig, include_plotlyjs=f"../{ASSETS_DIR_NAME}/plotly.min.js")
    out = kind_dir / f"{series.ticker_symbol}.html"
    out.write_text(html, encoding="utf-8")
    logger.info(
        "diagram_written",
        kind=DIAGRAM_KIND,
        ticker=series.ticker_symbol,
        points=len(series.points),
        gaps=len(series.gaps),
        path=str(out),
    )
    return out


__all__ = ["DIAGRAM_KIND", "figure_for", "load_growth_series", "render_html", "write_diagram"]
