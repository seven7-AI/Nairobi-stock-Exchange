"""Valuation - one fair-value method (or the blend) for one instrument as of one date.

Method rows carry bear / base / bull per share and the assumptions used; the
``blended`` row carries the intrinsic value, the fair range, upside, margin of safety,
the uncertainty score and whether the margin is actionable.
"""

from __future__ import annotations

from datetime import date as date_type
from datetime import datetime
from typing import Any

from sqlalchemy import (
    JSON,
    Boolean,
    Date,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.web.db.analytics.base import AnalyticsBase
from app.web.db.analytics.models.mixins import IntIdMixin, UTCDateTime, utcnow


class Valuation(IntIdMixin, AnalyticsBase):
    __tablename__ = "valuations"
    __table_args__ = (
        UniqueConstraint(
            "ticker_symbol",
            "as_of_date",
            "method",
            "calc_version_id",
            name="uq_valuation_identity",
        ),
    )

    ticker_symbol: Mapped[str] = mapped_column(String(24), nullable=False, index=True)
    as_of_date: Mapped[date_type] = mapped_column(Date, nullable=False, index=True)
    #: pb_roe, ddm, dcf, ev_ebitda, pe_relative, blended
    method: Mapped[str] = mapped_column(String(24), nullable=False, index=True)
    status: Mapped[str] = mapped_column(String(16), nullable=False)
    reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    bear: Mapped[float | None] = mapped_column(Float, nullable=True)
    base: Mapped[float | None] = mapped_column(Float, nullable=True)
    bull: Mapped[float | None] = mapped_column(Float, nullable=True)
    fair_low: Mapped[float | None] = mapped_column(Float, nullable=True)
    fair_high: Mapped[float | None] = mapped_column(Float, nullable=True)
    price: Mapped[float | None] = mapped_column(Float, nullable=True)
    upside: Mapped[float | None] = mapped_column(Float, nullable=True)
    margin_of_safety: Mapped[float | None] = mapped_column(Float, nullable=True)
    uncertainty: Mapped[float | None] = mapped_column(Float, nullable=True)
    actionable: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    assumptions: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    provenance: Mapped[list[dict[str, Any]] | None] = mapped_column(JSON, nullable=True)
    calc_version_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("calc_versions.id"), nullable=False, index=True
    )
    computed_at: Mapped[datetime] = mapped_column(UTCDateTime(), nullable=False, default=utcnow)

    def __repr__(self) -> str:
        return f"<Valuation {self.ticker_symbol} {self.as_of_date} {self.method} {self.status}>"


__all__ = ["Valuation"]
