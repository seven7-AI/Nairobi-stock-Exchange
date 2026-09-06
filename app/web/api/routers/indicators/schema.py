"""Indicator schemas."""

from __future__ import annotations

from datetime import date as date_type
from decimal import Decimal
from typing import Any

from pydantic import BaseModel, ConfigDict


class IndicatorSnapshotRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    as_of_date: date_type
    close_price: Decimal | None
    price_change_1d_pct: Decimal | None
    price_change_1w_pct: Decimal | None
    price_change_1m_pct: Decimal | None
    rsi_14: Decimal | None
    moving_average_20d: Decimal | None
    moving_average_50d: Decimal | None
    moving_average_200d: Decimal | None
    metrics: dict[str, Any]


class TickerIndicators(BaseModel):
    ticker_symbol: str
    company_name: str
    snapshot: IndicatorSnapshotRead


class FeasibilityRow(BaseModel):
    indicator: str
    category: str
    status: str
    source: str
    missing_data: list[str]
    notes: str


class FeasibilityReport(BaseModel):
    """Which of the catalogued indicators are computable with available data."""

    calculable: int
    partially_calculable: int
    not_calculable: int
    total: int
    categories: int
    rows: list[FeasibilityRow]


__all__ = [
    "FeasibilityReport",
    "FeasibilityRow",
    "IndicatorSnapshotRead",
    "TickerIndicators",
]
