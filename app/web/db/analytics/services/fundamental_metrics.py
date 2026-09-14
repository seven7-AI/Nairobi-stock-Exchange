"""Persist and query fundamental metrics. No business rules here.

codegraph explore "upsert_fundamental_metrics FundamentalRow load_fundamental_metrics"
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import date
from typing import Any

from sqlalchemy import select
from sqlalchemy.dialects.sqlite import insert
from sqlalchemy.orm import Session

from app.web.db.analytics.models import FundamentalMetric
from app.web.db.analytics.models.mixins import utcnow


@dataclass(frozen=True, slots=True)
class FundamentalRow:
    ticker_symbol: str
    as_of_date: date
    metric: str
    value: float | None
    status: str
    reason: str | None = None
    period_end: date | None = None
    period_type: str | None = None
    provenance: list[dict[str, Any]] = field(default_factory=list)


def upsert_fundamental_metrics(
    session: Session, rows: Iterable[FundamentalRow], *, calc_version_id: int
) -> int:
    stamp = utcnow()
    payload = [
        {
            "ticker_symbol": r.ticker_symbol,
            "as_of_date": r.as_of_date,
            "metric": r.metric,
            "period_end": r.period_end,
            "period_type": r.period_type,
            "value": r.value,
            "status": r.status,
            "reason": r.reason,
            "provenance": r.provenance or None,
            "calc_version_id": calc_version_id,
            "computed_at": stamp,
        }
        for r in rows
    ]
    if not payload:
        return 0
    statement = insert(FundamentalMetric).values(payload)
    statement = statement.on_conflict_do_update(
        index_elements=["ticker_symbol", "as_of_date", "metric", "calc_version_id"],
        set_={
            "period_end": statement.excluded.period_end,
            "period_type": statement.excluded.period_type,
            "value": statement.excluded.value,
            "status": statement.excluded.status,
            "reason": statement.excluded.reason,
            "provenance": statement.excluded.provenance,
            "computed_at": statement.excluded.computed_at,
        },
    )
    session.execute(statement)
    session.flush()
    return len(payload)


def load_fundamental_metrics(
    session: Session,
    *,
    ticker_symbol: str | None = None,
    as_of_date: date | None = None,
    metric: str | None = None,
) -> list[FundamentalMetric]:
    stmt = select(FundamentalMetric)
    if ticker_symbol is not None:
        stmt = stmt.where(FundamentalMetric.ticker_symbol == ticker_symbol.upper())
    if as_of_date is not None:
        stmt = stmt.where(FundamentalMetric.as_of_date == as_of_date)
    if metric is not None:
        stmt = stmt.where(FundamentalMetric.metric == metric)
    stmt = stmt.order_by(
        FundamentalMetric.ticker_symbol, FundamentalMetric.as_of_date, FundamentalMetric.metric
    )
    return list(session.execute(stmt).scalars())


__all__ = ["FundamentalRow", "load_fundamental_metrics", "upsert_fundamental_metrics"]
