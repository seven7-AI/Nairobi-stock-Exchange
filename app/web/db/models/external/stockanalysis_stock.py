"""Read-only mapping of ``stockanalysis_stocks``.

**This table is not owned by this repository.** An external scraper, which lives
outside this codebase, creates and writes it. We only ever read from it.

Two mechanisms keep Alembic away from it:

1. ``info={"skip_autogenerate": True}`` on the table, and
2. the ``include_object`` hook in ``app/alembic/env.py`` that honours that flag.

If ``alembic revision --autogenerate`` ever emits an operation against this
table, the hook is broken. Fix the hook — never accept the migration, and never
hand-edit it to drop the operation.

    codegraph explore "StockAnalysisStock include_object env.py skip_autogenerate"
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import DateTime, Float, Integer, String
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.web.db.base import Base

#: Applied to the table so the Alembic hook can recognise it generically.
EXTERNAL_TABLE_INFO: dict[str, Any] = {"skip_autogenerate": True, "owner": "external-scraper"}


class StockAnalysisStock(Base):
    """One scraped snapshot of one ticker. Read-only."""

    __tablename__ = "stockanalysis_stocks"
    __table_args__ = {"info": EXTERNAL_TABLE_INFO}

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=False)

    ticker_symbol: Mapped[str | None] = mapped_column(String, nullable=True, index=True)
    company_name: Mapped[str | None] = mapped_column(String, nullable=True)
    rank: Mapped[int | None] = mapped_column(Integer, nullable=True)
    stock_price: Mapped[float | None] = mapped_column(Float, nullable=True)
    stock_change: Mapped[float | None] = mapped_column(Float, nullable=True)
    scraped_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, index=True
    )

    # JSONB payloads produced by the scraper.
    overview_metrics: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    performance_metrics: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    dividends_metrics: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    price_metrics: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    profile_metrics: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    price_history: Mapped[list[dict[str, Any]] | None] = mapped_column(JSONB, nullable=True)

    def __repr__(self) -> str:
        return f"<StockAnalysisStock {self.ticker_symbol} @{self.scraped_at}>"


__all__ = ["EXTERNAL_TABLE_INFO", "StockAnalysisStock"]
