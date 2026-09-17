"""Cheap aggregate reads the dashboard needs: status counts on a table's latest date,
the latest *known* date, the latest runs of a job.

    codegraph explore "status_counts_on_latest latest_known_as_of latest_runs"
"""

from __future__ import annotations

from datetime import date
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.web.db.analytics.models import JobRun

KNOWN_STATUSES: tuple[str, ...] = ("known", "zero")


def latest_as_of(session: Session, model: Any) -> date | None:
    """``MAX(as_of_date)`` of a result table (None when empty)."""
    return session.execute(select(func.max(model.as_of_date))).scalar_one_or_none()


def latest_known_as_of(
    session: Session, model: Any, *, ticker_symbol: str | None = None
) -> date | None:
    """The newest date on which the table holds at least one known (or zero) value -
    what a reader should ask for when the latest date is all ``unavailable``."""
    stmt = select(func.max(model.as_of_date)).where(model.status.in_(KNOWN_STATUSES))
    if ticker_symbol is not None:
        stmt = stmt.where(model.ticker_symbol == ticker_symbol.upper())
    return session.execute(stmt).scalar_one_or_none()


def status_counts_on_latest(session: Session, model: Any) -> tuple[date | None, dict[str, int]]:
    """``(latest as_of, {status: rows})`` for a result table - how much of the latest
    date is actually known versus unavailable."""
    day = latest_as_of(session, model)
    if day is None:
        return None, {}
    rows = session.execute(
        select(model.status, func.count()).where(model.as_of_date == day).group_by(model.status)
    ).all()
    return day, {str(status): int(count) for status, count in rows}


def latest_runs(
    session: Session, job_name: str, *, status: str | None = None, limit: int = 1
) -> list[JobRun]:
    """The newest ``job_runs`` rows for one job, optionally only those with ``status``."""
    stmt = select(JobRun).where(JobRun.job_name == job_name)
    if status is not None:
        stmt = stmt.where(JobRun.status == status)
    stmt = stmt.order_by(JobRun.id.desc()).limit(limit)
    return list(session.execute(stmt).scalars())


__all__ = [
    "KNOWN_STATUSES",
    "latest_as_of",
    "latest_known_as_of",
    "latest_runs",
    "status_counts_on_latest",
]
