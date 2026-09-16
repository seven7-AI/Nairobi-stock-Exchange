"""ResearchNarrative - one generated (or rejected) narrative for one instrument."""

from __future__ import annotations

from datetime import date as date_type
from datetime import datetime
from typing import Any

from sqlalchemy import JSON, Date, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.web.db.analytics.base import AnalyticsBase
from app.web.db.analytics.models.mixins import IntIdMixin, UTCDateTime, utcnow


class ResearchNarrative(IntIdMixin, AnalyticsBase):
    __tablename__ = "research_narratives"

    ticker_symbol: Mapped[str] = mapped_column(String(24), nullable=False, index=True)
    as_of_date: Mapped[date_type] = mapped_column(Date, nullable=False, index=True)
    model: Mapped[str] = mapped_column(String(64), nullable=False)
    prompt_version: Mapped[str] = mapped_column(String(16), nullable=False)
    #: sha256 of the context the model saw; the same context is never sent twice
    context_hash: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    #: known, rejected (cited a number not in the context), unavailable
    status: Mapped[str] = mapped_column(String(16), nullable=False)
    reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    narrative: Mapped[str | None] = mapped_column(Text, nullable=True)
    context: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), nullable=False, default=utcnow)

    def __repr__(self) -> str:
        return f"<ResearchNarrative {self.ticker_symbol} {self.as_of_date} {self.status}>"


__all__ = ["ResearchNarrative"]
