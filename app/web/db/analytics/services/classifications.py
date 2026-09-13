"""Persist and query classifications. No business rules here.

codegraph explore "replace_classifications load_classifications Classification"
"""

from __future__ import annotations

from collections.abc import Iterable

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.web.db.analytics.models import Classification
from app.web.services.analytics.classification.builder import ClassificationRecord


def replace_classifications(session: Session, records: Iterable[ClassificationRecord]) -> int:
    """Rebuild the table from scratch inside the caller's transaction.

    The table is derived entirely from the sector files, the curated map and the
    scraper's instrument master, so a full rebuild is the idempotent operation:
    running it twice on the same inputs yields identical rows.
    """
    session.execute(delete(Classification))
    rows = [
        Classification(
            ticker_symbol=r.ticker_symbol,
            sector_code=r.sector_code,
            sector_label=r.sector_label,
            industry=r.industry,
            valid_from=r.valid_from,
            valid_to=r.valid_to,
            source=r.source,
            evidence=r.evidence,
        )
        for r in records
    ]
    session.add_all(rows)
    session.flush()
    return len(rows)


def load_classifications(session: Session) -> list[Classification]:
    """Every row, ordered by ticker then validity start."""
    return list(
        session.execute(
            select(Classification).order_by(Classification.ticker_symbol, Classification.valid_from)
        ).scalars()
    )


__all__ = ["load_classifications", "replace_classifications"]
