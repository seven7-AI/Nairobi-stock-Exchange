"""Persist and query market metrics. No business rules here.

codegraph explore "upsert_market_metrics MetricRow load_metrics"
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import date
from typing import Any

from sqlalchemy import select
from sqlalchemy.dialects.sqlite import insert
from sqlalchemy.orm import Session

from app.web.db.analytics.models import MarketMetric
from app.web.db.analytics.models.mixins import utcnow


@dataclass(frozen=True, slots=True)
class MetricRow:
    """What a writer hands over: one measure, already flattened."""

    ticker_symbol: str
    as_of_date: date
    metric: str
    value: float | None
    status: str
    reason: str | None = None
    window_start: date | None = None
    window_end: date | None = None
    contains_flagged: bool = False
    provenance: list[dict[str, Any]] = field(default_factory=list)


def upsert_market_metrics(
    session: Session, rows: Iterable[MetricRow], *, calc_version_id: int
) -> int:
    """Insert or replace on the natural key. Re-running a job rewrites identical rows."""
    stamp = utcnow()
    payload = [
        {
            "ticker_symbol": r.ticker_symbol,
            "as_of_date": r.as_of_date,
            "metric": r.metric,
            "window_start": r.window_start,
            "window_end": r.window_end,
            "value": r.value,
            "status": r.status,
            "reason": r.reason,
            "contains_flagged": r.contains_flagged,
            "provenance": r.provenance or None,
            "calc_version_id": calc_version_id,
            "computed_at": stamp,
        }
        for r in rows
    ]
    if not payload:
        return 0
    statement = insert(MarketMetric).values(payload)
    statement = statement.on_conflict_do_update(
        index_elements=["ticker_symbol", "as_of_date", "metric", "calc_version_id"],
        set_={
            "window_start": statement.excluded.window_start,
            "window_end": statement.excluded.window_end,
            "value": statement.excluded.value,
            "status": statement.excluded.status,
            "reason": statement.excluded.reason,
            "contains_flagged": statement.excluded.contains_flagged,
            "provenance": statement.excluded.provenance,
            "computed_at": statement.excluded.computed_at,
        },
    )
    session.execute(statement)
    session.flush()
    return len(payload)


def load_metrics(
    session: Session,
    *,
    ticker_symbol: str | None = None,
    as_of_date: date | None = None,
    metric: str | None = None,
    calc_version_id: int | None = None,
) -> list[MarketMetric]:
    stmt = select(MarketMetric)
    if ticker_symbol is not None:
        stmt = stmt.where(MarketMetric.ticker_symbol == ticker_symbol.upper())
    if as_of_date is not None:
        stmt = stmt.where(MarketMetric.as_of_date == as_of_date)
    if metric is not None:
        stmt = stmt.where(MarketMetric.metric == metric)
    if calc_version_id is not None:
        stmt = stmt.where(MarketMetric.calc_version_id == calc_version_id)
    stmt = stmt.order_by(MarketMetric.ticker_symbol, MarketMetric.as_of_date, MarketMetric.metric)
    return list(session.execute(stmt).scalars())


__all__ = ["MetricRow", "load_metrics", "upsert_market_metrics"]
