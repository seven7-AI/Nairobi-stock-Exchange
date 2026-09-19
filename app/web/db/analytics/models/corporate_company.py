"""The canonical company universe and the evidence it is built from.

``corporate_companies`` is one row per listed company (ordinary shares, REITs and
ETFs; preference shares fold into their parent). It is not bitemporal: the fields
describe the company as currently known, and every change appends to
``name_history`` / ``status_history`` rather than overwriting. ``field_sources``
says, per field, which source supplied it, with what confidence and evidence.

``corporate_sightings`` is append-only: one row per (company, source, run), the raw
evidence the status rules are computed from. A company that is *not* sighted by a
source on a run has no row - absence is inferred from the run timestamps of the
rows that exist, never stored as a fact.

    codegraph explore "CorporateCompany CorporateSighting upsert_companies"
"""

from __future__ import annotations

from datetime import date as date_type
from datetime import datetime
from typing import Any

from sqlalchemy import JSON, Date, Float, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.web.db.analytics.base import AnalyticsBase
from app.web.db.analytics.models.mixins import IntIdMixin, UTCDateTime, utcnow

#: Tradability of the listing. Names change without the listing changing, so a
#: rename is history (``name_history``), not a status.
LISTING_STATUSES: tuple[str, ...] = ("listed", "newly_listed", "suspended", "delisted", "unknown")

#: Where a sighting comes from.
SIGHTING_SOURCES: tuple[str, ...] = (
    "scraper_instruments",
    "nse_listed_page",
    "stockanalysis_profile",
    "gleif",
    "announcement",
)


class CorporateCompany(IntIdMixin, AnalyticsBase):
    __tablename__ = "corporate_companies"

    ticker_symbol: Mapped[str] = mapped_column(String(24), nullable=False, unique=True)
    canonical_name: Mapped[str] = mapped_column(String(160), nullable=False)
    legal_name: Mapped[str | None] = mapped_column(String(200), nullable=True)
    instrument_type: Mapped[str] = mapped_column(String(16), nullable=False)
    sector_code: Mapped[str | None] = mapped_column(String(32), nullable=True, index=True)
    home_country: Mapped[str] = mapped_column(String(2), nullable=False)
    isin: Mapped[str | None] = mapped_column(String(12), nullable=True, index=True)
    lei: Mapped[str | None] = mapped_column(String(20), nullable=True, index=True)
    registration_number: Mapped[str | None] = mapped_column(String(64), nullable=True)
    #: ``{"NSE": "KCB", "RSE": "BK"}`` - the company's codes on each exchange it trades on.
    exchange_ids: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    website: Mapped[str | None] = mapped_column(String(300), nullable=True)
    ir_url: Mapped[str | None] = mapped_column(String(300), nullable=True)
    listing_status: Mapped[str] = mapped_column(String(16), nullable=False, index=True)
    status_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    first_listed: Mapped[date_type | None] = mapped_column(Date, nullable=True)
    delisted_on: Mapped[date_type | None] = mapped_column(Date, nullable=True)
    #: ``[{"ticker": "BBK", "reason": "rebrand", "evidence": "...", "recorded": "..."}]``
    name_history: Mapped[list[dict[str, Any]]] = mapped_column(JSON, nullable=False, default=list)
    #: ``[{"status": "listed", "from": "...", "reason": "...", "recorded": "..."}]``
    status_history: Mapped[list[dict[str, Any]]] = mapped_column(JSON, nullable=False, default=list)
    #: ``{"isin": {"source": "nse_listed_page", "confidence": 0.9, "evidence": "..."}}``
    field_sources: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    #: The lowest confidence among the identity fields (ticker, names, home country).
    confidence: Mapped[float] = mapped_column(Float, nullable=False)
    first_seen_at: Mapped[datetime] = mapped_column(UTCDateTime(), nullable=False, default=utcnow)
    last_seen_at: Mapped[datetime] = mapped_column(UTCDateTime(), nullable=False, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime(), nullable=False, default=utcnow)

    def __repr__(self) -> str:
        return f"<CorporateCompany {self.ticker_symbol} {self.listing_status}>"


class CorporateSighting(IntIdMixin, AnalyticsBase):
    __tablename__ = "corporate_sightings"
    __table_args__ = (
        UniqueConstraint(
            "ticker_symbol",
            "source",
            "payload_hash",
            "seen_at",
            name="uq_corporate_sighting_identity",
        ),
    )

    ticker_symbol: Mapped[str] = mapped_column(String(24), nullable=False, index=True)
    source: Mapped[str] = mapped_column(String(24), nullable=False, index=True)
    #: One timestamp per run: every sighting a run records shares it, so "how many
    #: runs since this company was last sighted" is a count of distinct values.
    seen_at: Mapped[datetime] = mapped_column(UTCDateTime(), nullable=False, index=True)
    payload_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    payload: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)

    def __repr__(self) -> str:
        return f"<CorporateSighting {self.ticker_symbol} {self.source} {self.seen_at:%Y-%m-%d}>"


__all__ = ["LISTING_STATUSES", "SIGHTING_SOURCES", "CorporateCompany", "CorporateSighting"]
