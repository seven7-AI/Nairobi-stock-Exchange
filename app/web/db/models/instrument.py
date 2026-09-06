"""Instrument — an NSE-listed security with its sector classification.

Seeded from ``research/data/ticker_master.parquet`` (88 tickers).
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from sqlalchemy import Boolean, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.web.db.base import Base
from app.web.db.models.base import TimestampMixin, UUIDMixin
from app.web.db.models.enums import InstrumentStatus, pg_enum

if TYPE_CHECKING:
    from app.web.db.models.indicator_snapshot import IndicatorSnapshot
    from app.web.db.models.price_bar import PriceBar
    from app.web.db.models.watchlist import WatchlistItem


class Instrument(UUIDMixin, TimestampMixin, Base):
    """A tradable NSE ticker. Reference data, shared across all organizations."""

    __tablename__ = "instruments"

    ticker_symbol: Mapped[str] = mapped_column(
        String(24), nullable=False, unique=True, index=True
    )
    company_name: Mapped[str] = mapped_column(String(255), nullable=False)
    sector: Mapped[str | None] = mapped_column(String(120), nullable=True, index=True)
    exchange: Mapped[str] = mapped_column(String(16), nullable=False, default="NSE")
    currency: Mapped[str] = mapped_column(String(3), nullable=False, default="KES")
    status: Mapped[InstrumentStatus] = mapped_column(
        pg_enum(InstrumentStatus, "instrument_status"),
        nullable=False,
        default=InstrumentStatus.ACTIVE,
    )
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, index=True)

    price_bars: Mapped[list[PriceBar]] = relationship(
        back_populates="instrument", cascade="all, delete-orphan"
    )
    indicator_snapshots: Mapped[list[IndicatorSnapshot]] = relationship(
        back_populates="instrument", cascade="all, delete-orphan"
    )
    watchlist_items: Mapped[list[WatchlistItem]] = relationship(
        back_populates="instrument", cascade="all, delete-orphan"
    )

    def __repr__(self) -> str:
        return f"<Instrument {self.ticker_symbol}>"


__all__ = ["Instrument"]
