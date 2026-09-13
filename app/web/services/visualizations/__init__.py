"""Visualizations of the canonical NSE timeline.

Every module here is a pure function of data already in ``stock_observations`` — no
second source of prices, no interpolation. ``growth_series`` shapes the data;
``stock_growth`` draws it. Future kinds (sector performance, market index, comparison)
are siblings of ``stock_growth`` and write to siblings of ``diagrams/stock-growth/``.

    codegraph explore "build_growth_series figure_for write_diagram plot_stock"
"""

from app.web.services.visualizations.growth_series import (
    GAP_THRESHOLD_DAYS,
    Gap,
    GrowthPoint,
    StockGrowthSeries,
    build_growth_series,
)
from app.web.services.visualizations.stock_growth import (
    DIAGRAM_KIND,
    figure_for,
    load_growth_series,
    render_png,
    write_diagram,
)

__all__ = [
    "DIAGRAM_KIND",
    "GAP_THRESHOLD_DAYS",
    "Gap",
    "GrowthPoint",
    "StockGrowthSeries",
    "build_growth_series",
    "figure_for",
    "load_growth_series",
    "render_png",
    "write_diagram",
]
