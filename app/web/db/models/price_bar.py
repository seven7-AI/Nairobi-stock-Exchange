"""PriceBar — canonical daily OHLCV history, one row per (instrument, date).

Backfilled from ``research/data/canonical_nse_prices.parquet`` (267,310 rows
spanning 2007-01-02 to 2024-12-31) and kept current by the ingest task that
reads the externally-owned ``stockanalysis_stocks`` table.

This table is why weekly and monthly indicators can be computed at all: those
windows need >= 5 and >= 22 observations per ticker.
"""

from __future__ import annotations

import uuid
from datetime import date as date_type
from decimal import Decimal
from typing import TYPE_CHECKING

from sqlalchemy import BigInteger, Date, ForeignKey, Numeric, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.web.db.base import Base
from app.web.db.models.base import TimestampMixin, UUIDMixin

if TYPE_CHECKING:
    from app.web.db.models.instrument import Instrument


class PriceBar(UUIDMixin, TimestampMixin, Base):
    """One trading day of prices for one instrument."""

    __tablename__ = "price_bars"
    __table_args__ = (
        UniqueConstraint("instrument_id", "bar_date", name="uq_price_bar_instrument_date"),
    )

    instrument_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("instruments.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    bar_date: Mapped[date_type] = mapped_column(Date, nullable=False, index=True)

    open_price: Mapped[Decimal | None] = mapped_column(Numeric(18, 4), nullable=True)
    high_price: Mapped[Decimal | None] = mapped_column(Numeric(18, 4), nullable=True)
    low_price: Mapped[Decimal | None] = mapped_column(Numeric(18, 4), nullable=True)
    close_price: Mapped[Decimal] = mapped_column(Numeric(18, 4), nullable=False)
    adjusted_close: Mapped[Decimal | None] = mapped_column(Numeric(18, 4), nullable=True)
    previous_close: Mapped[Decimal | None] = mapped_column(Numeric(18, 4), nullable=True)
    volume: Mapped[int | None] = mapped_column(BigInteger, nullable=True)

    source: Mapped[str] = mapped_column(
        String(32), nullable=False, default="stockanalysis_stocks"
    )

    instrument: Mapped[Instrument] = relationship(back_populates="price_bars")

    def __repr__(self) -> str:
        return f"<PriceBar {self.instrument_id} {self.bar_date} close={self.close_price}>"


__all__ = ["PriceBar"]
