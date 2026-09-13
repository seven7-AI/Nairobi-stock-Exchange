"""Returns engine: trailing, YTD, rolling and cumulative returns on a PriceSeries.

codegraph explore "trailing_returns compute_returns PriceSeries"
"""

from __future__ import annotations

from app.web.services.analytics.returns.engine import (
    METRIC_NAMES,
    WINDOWS,
    WindowResult,
    cumulative_return,
    rolling_returns,
    trailing_returns,
    window_return,
    ytd_return,
)
from app.web.services.analytics.returns.service import ComputeResult, compute_returns

__all__ = [
    "METRIC_NAMES",
    "WINDOWS",
    "ComputeResult",
    "WindowResult",
    "compute_returns",
    "cumulative_return",
    "rolling_returns",
    "trailing_returns",
    "window_return",
    "ytd_return",
]
