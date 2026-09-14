"""Persist and query stock rankings. No business rules here.

codegraph explore "upsert_rankings load_rankings StockRanking"
"""

from __future__ import annotations

from collections.abc import Iterable
from datetime import date
from typing import TYPE_CHECKING

from sqlalchemy import select
from sqlalchemy.dialects.sqlite import insert
from sqlalchemy.orm import Session

from app.web.db.analytics.models import StockRanking
from app.web.db.analytics.models.mixins import utcnow

if TYPE_CHECKING:
    from app.web.services.analytics.ranking.engine import Ranking


def upsert_rankings(
    session: Session,
    rankings: Iterable[Ranking],
    *,
    as_of_date: date,
    model_name: str,
    model_version: str,
    calc_version_id: int,
) -> int:
    stamp = utcnow()
    payload = []
    for r in rankings:
        trap = r.value_trap.measure
        payload.append(
            {
                "ticker_symbol": r.ticker_symbol,
                "as_of_date": as_of_date,
                "model_name": model_name,
                "model_version": model_version,
                "overall_score": r.overall.value,
                "status": r.overall.status.value,
                "reason": r.overall.reason,
                "confidence": r.confidence,
                "classification": r.classification,
                "value_score": r.factor_scores.get("value"),
                "quality_score": r.factor_scores.get("quality"),
                "growth_score": r.factor_scores.get("growth"),
                "momentum_score": r.factor_scores.get("momentum"),
                "risk_score": r.factor_scores.get("risk"),
                "dividend_score": r.factor_scores.get("dividend"),
                "liquidity_score": r.factor_scores.get("liquidity"),
                "market_rank": r.market_rank,
                "sector_rank": r.sector_rank,
                "industry_rank": r.industry_rank,
                "value_trap_risk": int(trap.value)
                if trap.is_known and trap.value is not None
                else None,
                "compounder_score": r.compounder.measure.value,
                "explanation": r.explanation,
                "calc_version_id": calc_version_id,
                "computed_at": stamp,
            }
        )
    if not payload:
        return 0
    statement = insert(StockRanking).values(payload)
    columns = [
        c
        for c in payload[0]
        if c
        not in ("ticker_symbol", "as_of_date", "model_name", "model_version", "calc_version_id")
    ]
    statement = statement.on_conflict_do_update(
        index_elements=[
            "ticker_symbol",
            "as_of_date",
            "model_name",
            "model_version",
            "calc_version_id",
        ],
        set_={c: getattr(statement.excluded, c) for c in columns},
    )
    session.execute(statement)
    session.flush()
    return len(payload)


def load_rankings(
    session: Session,
    *,
    as_of_date: date | None = None,
    ticker_symbol: str | None = None,
    model_name: str | None = None,
    limit: int | None = None,
) -> list[StockRanking]:
    stmt = select(StockRanking)
    if as_of_date is not None:
        stmt = stmt.where(StockRanking.as_of_date == as_of_date)
    if ticker_symbol is not None:
        stmt = stmt.where(StockRanking.ticker_symbol == ticker_symbol.upper())
    if model_name is not None:
        stmt = stmt.where(StockRanking.model_name == model_name)
    stmt = stmt.order_by(StockRanking.market_rank.nulls_last(), StockRanking.ticker_symbol)
    if limit is not None:
        stmt = stmt.limit(limit)
    return list(session.execute(stmt).scalars())


__all__ = ["load_rankings", "upsert_rankings"]
