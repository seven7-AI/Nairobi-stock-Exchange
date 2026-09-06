"""Market analytics schemas."""

from __future__ import annotations

from datetime import date as date_type

from pydantic import BaseModel, Field


class MoverRow(BaseModel):
    ticker_symbol: str
    company_name: str | None = None
    sector: str | None = None
    stock_price: float | None = None
    change_pct: float | None = Field(
        default=None, description="null means the change could not be computed"
    )


class MarketSummary(BaseModel):
    """Market-level view for one horizon.

    ``excluded_missing_change`` is reported rather than hidden: instruments
    whose change could not be computed are left out of the rankings instead of
    being counted as 0.00% movers.
    """

    as_of_date: date_type
    horizon: str
    market_trend: str
    mean_change_pct: float | None
    ranked_instruments: int
    excluded_missing_change: int
    top_gainers: list[MoverRow]
    top_losers: list[MoverRow]


class SectorPerformance(BaseModel):
    sector: str
    instrument_count: int
    mean_change_pct: float | None
    best_ticker: str | None
    worst_ticker: str | None


class SectorPerformanceReport(BaseModel):
    as_of_date: date_type
    horizon: str
    sectors: list[SectorPerformance]


__all__ = [
    "MarketSummary",
    "MoverRow",
    "SectorPerformance",
    "SectorPerformanceReport",
]
