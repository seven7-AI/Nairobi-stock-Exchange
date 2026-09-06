"""Market data schemas."""

from __future__ import annotations

import uuid
from datetime import date as date_type
from decimal import Decimal

from pydantic import BaseModel, ConfigDict


class PriceBarRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    bar_date: date_type
    open_price: Decimal | None
    high_price: Decimal | None
    low_price: Decimal | None
    close_price: Decimal
    adjusted_close: Decimal | None
    previous_close: Decimal | None
    volume: int | None
    source: str


class QuoteRead(BaseModel):
    """Latest known price for one instrument."""

    instrument_id: uuid.UUID
    ticker_symbol: str
    company_name: str
    sector: str | None
    bar_date: date_type
    close_price: Decimal
    previous_close: Decimal | None
    change: Decimal | None
    change_pct: float | None


class HistoryCoverage(BaseModel):
    """How much history exists — the constraint on which indicators can be computed."""

    ticker_symbol: str
    bar_count: int
    supports_weekly: bool
    supports_monthly: bool
    supports_ma_200: bool


__all__ = ["HistoryCoverage", "PriceBarRead", "QuoteRead"]
