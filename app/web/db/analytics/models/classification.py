"""Classification - which sector (and industry) an instrument belonged to, and when.

One row per (ticker, validity range). The NSE sector files are yearly snapshots
(2013, 2020, 2021, 2022, 2023/24), so a company that moved sectors gets one row
per stint and a point-in-time lookup picks the row whose range covers the date.
``industry`` is the finer stockanalysis label (e.g. "Commercial Banks"); it is
captured from 2026 onwards and applied to every row of the ticker as a
documented assumption (industries rarely change; sectors do get re-filed).
"""

from __future__ import annotations

from datetime import date as date_type

from sqlalchemy import Date, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.web.db.analytics.base import AnalyticsBase
from app.web.db.analytics.models.mixins import CreatedAtMixin, IntIdMixin


class Classification(IntIdMixin, CreatedAtMixin, AnalyticsBase):
    """A sector/industry assignment with its validity range and its evidence."""

    __tablename__ = "classifications"
    __table_args__ = (
        UniqueConstraint("ticker_symbol", "valid_from", name="uq_classification_ticker_from"),
    )

    #: Canonical ticker (ABSA, never BBK).
    ticker_symbol: Mapped[str] = mapped_column(String(24), nullable=False, index=True)
    #: Normalised sector code from the taxonomy (``banking``, ``energy`` ...).
    sector_code: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    #: The official NSE label as printed in the source at the time.
    sector_label: Mapped[str] = mapped_column(String(64), nullable=False)
    industry: Mapped[str | None] = mapped_column(String(120), nullable=True, index=True)
    valid_from: Mapped[date_type] = mapped_column(Date, nullable=False)
    #: NULL means "still valid".
    valid_to: Mapped[date_type | None] = mapped_column(Date, nullable=True)
    #: ``sector_file:2013`` · ``curated`` · ``instrument_type``; industry source is in evidence.
    source: Mapped[str] = mapped_column(String(64), nullable=False)
    evidence: Mapped[str] = mapped_column(Text, nullable=False)

    def covers(self, as_of: date_type) -> bool:
        return self.valid_from <= as_of and (self.valid_to is None or as_of <= self.valid_to)

    def __repr__(self) -> str:
        span = f"{self.valid_from}->{self.valid_to}"
        return f"<Classification {self.ticker_symbol} {self.sector_code} {span}>"


__all__ = ["Classification"]
