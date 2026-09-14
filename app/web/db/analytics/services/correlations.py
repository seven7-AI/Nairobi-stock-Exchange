"""Persist and query pairwise correlations. No business rules here.

codegraph explore "upsert_correlations load_correlations Correlation"
"""

from __future__ import annotations

from collections.abc import Iterable
from datetime import date

from sqlalchemy import select
from sqlalchemy.dialects.sqlite import insert
from sqlalchemy.orm import Session

from app.web.db.analytics.models import Correlation
from app.web.db.analytics.models.mixins import utcnow


def upsert_correlations(
    session: Session,
    pairs: Iterable[tuple[str, str, float, int]],
    *,
    as_of_date: date,
    window: str,
    calc_version_id: int,
) -> int:
    stamp = utcnow()
    payload = [
        {
            "as_of_date": as_of_date,
            "window": window,
            "ticker_a": min(a, b),
            "ticker_b": max(a, b),
            "value": value,
            "n_obs": n_obs,
            "calc_version_id": calc_version_id,
            "computed_at": stamp,
        }
        for a, b, value, n_obs in pairs
    ]
    if not payload:
        return 0
    statement = insert(Correlation).values(payload)
    statement = statement.on_conflict_do_update(
        index_elements=["as_of_date", "window", "ticker_a", "ticker_b", "calc_version_id"],
        set_={
            "value": statement.excluded.value,
            "n_obs": statement.excluded.n_obs,
            "computed_at": statement.excluded.computed_at,
        },
    )
    session.execute(statement)
    session.flush()
    return len(payload)


def load_correlations(
    session: Session, *, as_of_date: date, window: str, tickers: Iterable[str] | None = None
) -> list[Correlation]:
    stmt = select(Correlation).where(
        Correlation.as_of_date == as_of_date, Correlation.window == window
    )
    if tickers is not None:
        wanted = {t.upper() for t in tickers}
        stmt = stmt.where(Correlation.ticker_a.in_(wanted), Correlation.ticker_b.in_(wanted))
    return list(
        session.execute(stmt.order_by(Correlation.ticker_a, Correlation.ticker_b)).scalars()
    )


__all__ = ["load_correlations", "upsert_correlations"]
