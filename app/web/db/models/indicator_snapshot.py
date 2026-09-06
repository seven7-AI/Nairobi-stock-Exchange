"""IndicatorSnapshot — computed indicator payload for one instrument on one date.

Persisting these makes analytics queries cheap and gives reports a reproducible
input: a report can be regenerated from the snapshot that produced it.
"""

from __future__ import annotations

import uuid
from datetime import date as date_type
from decimal import Decimal
from typing import TYPE_CHECKING, Any

from sqlalchemy import Date, ForeignKey, Numeric, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.web.db.base import Base
from app.web.db.models.base import TimestampMixin, UUIDMixin

if TYPE_CHECKING:
    from app.web.db.models.instrument import Instrument


class IndicatorSnapshot(UUIDMixin, TimestampMixin, Base):
    """The indicator set computed for an instrument as of a given date."""

    __tablename__ = "indicator_snapshots"
    __table_args__ = (
        UniqueConstraint("instrument_id", "as_of_date", name="uq_indicator_snapshot"),
    )

    instrument_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("instruments.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    as_of_date: Mapped[date_type] = mapped_column(Date, nullable=False, index=True)

    # Hot columns worth indexing and sorting on; the long tail lives in `metrics`.
    close_price: Mapped[Decimal | None] = mapped_column(Numeric(18, 4), nullable=True)
    price_change_1d_pct: Mapped[Decimal | None] = mapped_column(Numeric(12, 6), nullable=True)
    price_change_1w_pct: Mapped[Decimal | None] = mapped_column(Numeric(12, 6), nullable=True)
    price_change_1m_pct: Mapped[Decimal | None] = mapped_column(Numeric(12, 6), nullable=True)
    rsi_14: Mapped[Decimal | None] = mapped_column(Numeric(12, 6), nullable=True)
    moving_average_20d: Mapped[Decimal | None] = mapped_column(Numeric(18, 4), nullable=True)
    moving_average_50d: Mapped[Decimal | None] = mapped_column(Numeric(18, 4), nullable=True)
    moving_average_200d: Mapped[Decimal | None] = mapped_column(Numeric(18, 4), nullable=True)

    metrics: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)

    instrument: Mapped[Instrument] = relationship(back_populates="indicator_snapshots")

    def __repr__(self) -> str:
        return f"<IndicatorSnapshot {self.instrument_id} {self.as_of_date}>"


__all__ = ["IndicatorSnapshot"]
