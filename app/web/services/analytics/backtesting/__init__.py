"""Look-ahead-safe, survivorship-aware, costed backtesting of the ranking model.

codegraph explore "run_backtest run_model_backtest weight_search ranking_signal"
"""

from __future__ import annotations

from app.web.services.analytics.backtesting.engine import (
    BacktestResult,
    Segment,
    Trade,
    run_backtest,
)
from app.web.services.analytics.backtesting.service import (
    BacktestRunResult,
    WeightSearchResult,
    market_only_ranking,
    run_model_backtest,
    weight_search,
)
from app.web.services.analytics.backtesting.signals import (
    SignalContext,
    ranking_signal,
    rankings_at,
)

__all__ = [
    "BacktestResult",
    "BacktestRunResult",
    "Segment",
    "SignalContext",
    "Trade",
    "WeightSearchResult",
    "market_only_ranking",
    "ranking_signal",
    "rankings_at",
    "run_backtest",
    "run_model_backtest",
    "weight_search",
]
