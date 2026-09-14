"""Persist and query valuations. No business rules here.

codegraph explore "upsert_valuations load_valuations Valuation"
"""

from __future__ import annotations

from collections.abc import Iterable
from datetime import date
from typing import TYPE_CHECKING, Any

from sqlalchemy import select
from sqlalchemy.dialects.sqlite import insert
from sqlalchemy.orm import Session

from app.web.db.analytics.models import Valuation
from app.web.db.analytics.models.mixins import utcnow

if TYPE_CHECKING:
    from app.web.services.analytics.fair_value.engine import Valuation as ValuationResult

UPDATABLE = (
    "status",
    "reason",
    "bear",
    "base",
    "bull",
    "fair_low",
    "fair_high",
    "price",
    "upside",
    "margin_of_safety",
    "uncertainty",
    "actionable",
    "assumptions",
    "provenance",
    "computed_at",
)


def valuation_rows(
    result: ValuationResult, *, as_of_date: date, calc_version_id: int
) -> list[dict[str, Any]]:
    stamp = utcnow()
    rows: list[dict[str, Any]] = []
    for m in result.methods:
        rows.append(
            {
                "ticker_symbol": result.ticker_symbol,
                "as_of_date": as_of_date,
                "method": m.method,
                "status": m.measure.status.value,
                "reason": m.measure.reason,
                "bear": m.bear,
                "base": m.base,
                "bull": m.bull,
                "fair_low": None,
                "fair_high": None,
                "price": result.price,
                "upside": (m.base / result.price - 1.0)
                if m.base is not None and result.price
                else None,
                "margin_of_safety": None,
                "uncertainty": None,
                "actionable": None,
                "assumptions": m.assumptions or None,
                "provenance": [p.as_dict() for p in m.measure.provenance] or None,
                "calc_version_id": calc_version_id,
                "computed_at": stamp,
            }
        )
    rows.append(
        {
            "ticker_symbol": result.ticker_symbol,
            "as_of_date": as_of_date,
            "method": "blended",
            "status": result.intrinsic.status.value,
            "reason": result.intrinsic.reason,
            "bear": result.fair_low,
            "base": result.intrinsic.value,
            "bull": result.fair_high,
            "fair_low": result.fair_low,
            "fair_high": result.fair_high,
            "price": result.price,
            "upside": result.upside.value,
            "margin_of_safety": result.margin_of_safety.value,
            "uncertainty": result.uncertainty,
            "actionable": result.actionable,
            "assumptions": result.assumptions or None,
            "provenance": [p.as_dict() for p in result.intrinsic.provenance] or None,
            "calc_version_id": calc_version_id,
            "computed_at": stamp,
        }
    )
    return rows


def upsert_valuations(
    session: Session,
    results: Iterable[ValuationResult],
    *,
    as_of_date: date,
    calc_version_id: int,
) -> int:
    payload: list[dict[str, Any]] = []
    for result in results:
        payload.extend(
            valuation_rows(result, as_of_date=as_of_date, calc_version_id=calc_version_id)
        )
    if not payload:
        return 0
    statement = insert(Valuation).values(payload)
    statement = statement.on_conflict_do_update(
        index_elements=["ticker_symbol", "as_of_date", "method", "calc_version_id"],
        set_={c: getattr(statement.excluded, c) for c in UPDATABLE},
    )
    session.execute(statement)
    session.flush()
    return len(payload)


def load_valuations(
    session: Session,
    *,
    as_of_date: date | None = None,
    ticker_symbol: str | None = None,
    method: str | None = None,
) -> list[Valuation]:
    stmt = select(Valuation)
    if as_of_date is not None:
        stmt = stmt.where(Valuation.as_of_date == as_of_date)
    if ticker_symbol is not None:
        stmt = stmt.where(Valuation.ticker_symbol == ticker_symbol.upper())
    if method is not None:
        stmt = stmt.where(Valuation.method == method)
    return list(session.execute(stmt.order_by(Valuation.ticker_symbol, Valuation.method)).scalars())


__all__ = ["load_valuations", "upsert_valuations", "valuation_rows"]
