"""Return-forecast baselines, evaluation and the walk-forward harness.

codegraph explore "forecast_returns compute_forecasts evaluate_forecasts walk_forward"
"""

from __future__ import annotations

from app.web.services.analytics.forecasting.engine import Forecast, forecast_returns, monthly_series
from app.web.services.analytics.forecasting.service import (
    EvaluationRunResult,
    ForecastRunResult,
    compute_forecasts,
    evaluate_forecasts,
    walk_forward,
)

__all__ = [
    "EvaluationRunResult",
    "Forecast",
    "ForecastRunResult",
    "compute_forecasts",
    "evaluate_forecasts",
    "forecast_returns",
    "monthly_series",
    "walk_forward",
]
