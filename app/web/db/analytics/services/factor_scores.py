"""Persist and query factor scores. No business rules here.

codegraph explore "upsert_factor_scores load_factor_scores metric_table_for"
"""

from __future__ import annotations

from collections.abc import Iterable
from datetime import date
from typing import TYPE_CHECKING

from sqlalchemy import select
from sqlalchemy.dialects.sqlite import insert
from sqlalchemy.orm import Session

from app.web.db.analytics.models import FactorScore, FundamentalMetric, MarketMetric
from app.web.db.analytics.models.mixins import utcnow

if TYPE_CHECKING:
    from app.web.services.analytics.factors.engine import FactorScore as FactorScoreResult


def metric_table_for(
    session: Session, as_of_date: date, *, calc_version_ids: Iterable[int] | None = None
) -> dict[tuple[str, str], dict[str, float]]:
    """Known market and fundamental metric values for a date: (source, metric) -> ticker -> value.

    When several calc versions hold rows for the date the newest computation wins.
    """
    table: dict[tuple[str, str], dict[str, float]] = {}

    def collect(source: str, model: type[MarketMetric] | type[FundamentalMetric]) -> None:
        stmt = select(model.ticker_symbol, model.metric, model.value, model.computed_at).where(
            model.as_of_date == as_of_date, model.status.in_(["known", "zero"])
        )
        if calc_version_ids is not None:
            stmt = stmt.where(model.calc_version_id.in_(list(calc_version_ids)))
        # ordered by computed_at, so the newest computation overwrites older ones
        for ticker, metric, value, _computed_at in session.execute(
            stmt.order_by(model.computed_at)
        ):
            if value is None:
                continue
            table.setdefault((source, metric), {})[ticker] = float(value)

    collect("market", MarketMetric)
    collect("fundamental", FundamentalMetric)
    return table


def upsert_factor_scores(
    session: Session, scores: Iterable[FactorScoreResult], *, as_of_date: date, calc_version_id: int
) -> int:
    stamp = utcnow()
    payload = [
        {
            "ticker_symbol": s.ticker_symbol,
            "as_of_date": as_of_date,
            "factor": s.factor,
            "score": s.measure.value,
            "status": s.measure.status.value,
            "reason": s.measure.reason,
            "coverage": s.coverage,
            "percentile_market": s.percentile_market,
            "percentile_sector": s.percentile_sector,
            "percentile_industry": s.percentile_industry,
            "group_sizes": s.group_sizes or None,
            "inputs": s.inputs_json(),
            "calc_version_id": calc_version_id,
            "computed_at": stamp,
        }
        for s in scores
    ]
    if not payload:
        return 0
    statement = insert(FactorScore).values(payload)
    statement = statement.on_conflict_do_update(
        index_elements=["ticker_symbol", "as_of_date", "factor", "calc_version_id"],
        set_={
            column: getattr(statement.excluded, column)
            for column in (
                "score",
                "status",
                "reason",
                "coverage",
                "percentile_market",
                "percentile_sector",
                "percentile_industry",
                "group_sizes",
                "inputs",
                "computed_at",
            )
        },
    )
    session.execute(statement)
    session.flush()
    return len(payload)


def load_factor_scores(
    session: Session,
    *,
    as_of_date: date | None = None,
    ticker_symbol: str | None = None,
    factor: str | None = None,
) -> list[FactorScore]:
    stmt = select(FactorScore)
    if as_of_date is not None:
        stmt = stmt.where(FactorScore.as_of_date == as_of_date)
    if ticker_symbol is not None:
        stmt = stmt.where(FactorScore.ticker_symbol == ticker_symbol.upper())
    if factor is not None:
        stmt = stmt.where(FactorScore.factor == factor)
    return list(
        session.execute(stmt.order_by(FactorScore.ticker_symbol, FactorScore.factor)).scalars()
    )


__all__ = ["load_factor_scores", "metric_table_for", "upsert_factor_scores"]
