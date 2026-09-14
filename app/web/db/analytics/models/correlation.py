"""Correlation - one pairwise daily-return correlation as of a date.

The stock-to-stock matrix the portfolio engine needs, stored as its upper
triangle (``ticker_a < ticker_b``) per ``(as_of_date, window, calc_version)``.
"""

from __future__ import annotations

from datetime import date as date_type
from datetime import datetime

from sqlalchemy import Date, Float, ForeignKey, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.web.db.analytics.base import AnalyticsBase
from app.web.db.analytics.models.mixins import IntIdMixin, UTCDateTime, utcnow


class Correlation(IntIdMixin, AnalyticsBase):
    __tablename__ = "correlations"
    __table_args__ = (
        UniqueConstraint(
            "as_of_date",
            "window",
            "ticker_a",
            "ticker_b",
            "calc_version_id",
            name="uq_correlation_identity",
        ),
    )

    as_of_date: Mapped[date_type] = mapped_column(Date, nullable=False, index=True)
    window: Mapped[str] = mapped_column(String(8), nullable=False)
    ticker_a: Mapped[str] = mapped_column(String(24), nullable=False, index=True)
    ticker_b: Mapped[str] = mapped_column(String(24), nullable=False, index=True)
    value: Mapped[float] = mapped_column(Float, nullable=False)
    #: Common daily-return observations the value is based on.
    n_obs: Mapped[int] = mapped_column(Integer, nullable=False)
    calc_version_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("calc_versions.id"), nullable=False, index=True
    )
    computed_at: Mapped[datetime] = mapped_column(UTCDateTime(), nullable=False, default=utcnow)

    def __repr__(self) -> str:
        return f"<Correlation {self.ticker_a}~{self.ticker_b} {self.window} {self.as_of_date}>"


__all__ = ["Correlation"]
