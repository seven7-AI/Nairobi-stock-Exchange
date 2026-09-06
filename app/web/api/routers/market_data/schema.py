"""Market data schemas."""

from __future__ import annotations

import uuid
from datetime import date as date_type
from datetime import datetime
from decimal import Decimal
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


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


class SourceTableRead(BaseModel):
    name: str
    row_count: int
    newest_scraped_at: datetime | None = None


class MarketDataSourceRead(BaseModel):
    """Where nse-be gets its raw NSE data, and whether that data is trustworthy.

    ``status`` distinguishes three failure shapes an operator needs to tell
    apart: ``unreachable`` (cannot read it), ``stale`` (readable but not
    refreshed recently), and ``degraded`` (fresh, but the scraper's own quality
    gate failed on the last run).
    """

    name: str
    status: str
    reachable: bool
    location: str
    detail: str
    newest_scraped_at: datetime | None = None
    age_hours: float | None = None
    is_stale: bool = False
    quality_ok: bool | None = None
    tables: list[SourceTableRead] = Field(default_factory=list)


class ScrapedRow(BaseModel):
    """One raw scraped row, preserved as the scraper produced it.

    The five metrics blobs and ``price_history`` are passed through untouched -
    no transformation, per the integration brief - so future analytics can work
    from the original fields.
    """

    model_config = ConfigDict(extra="allow")

    ticker_symbol: str
    company_name: str | None = None
    rank: int | None = None
    stock_price: float | None = None
    stock_change: float | None = None
    scraped_at: str | None = None
    overview_metrics: dict[str, Any] = Field(default_factory=dict)
    performance_metrics: dict[str, Any] = Field(default_factory=dict)
    dividends_metrics: dict[str, Any] = Field(default_factory=dict)
    price_metrics: dict[str, Any] = Field(default_factory=dict)
    profile_metrics: dict[str, Any] = Field(default_factory=dict)
    price_history: list[dict[str, Any]] = Field(default_factory=list)


__all__ = [
    "HistoryCoverage",
    "MarketDataSourceRead",
    "PriceBarRead",
    "QuoteRead",
    "ScrapedRow",
    "SourceTableRead",
]
