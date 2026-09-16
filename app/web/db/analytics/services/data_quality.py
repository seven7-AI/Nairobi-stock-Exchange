"""Persist data-quality findings across runs. No business rules here.

codegraph explore "reconcile_findings open_findings DataQualityFinding"
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.web.db.analytics.models import DataQualityFinding, JobRun, JobStatus
from app.web.db.analytics.models.mixins import utcnow

if TYPE_CHECKING:
    from app.web.services.analytics.quality.checks import Finding


@dataclass(frozen=True)
class ReconcileResult:
    created: int
    still_open: int
    resolved: int


def reconcile_findings(
    session: Session,
    findings: Iterable[Finding],
    *,
    run_id: int | None,
    now: datetime | None = None,
) -> ReconcileResult:
    """Upsert this run's findings and resolve the open ones it no longer reports.

    Identity is ``(check, ticker, trade_date, detail_hash)``. Idempotent: the same
    findings twice create nothing new and resolve nothing.
    """
    stamp = now or utcnow()
    current = {f.identity: f for f in findings}
    open_rows = (
        session.execute(select(DataQualityFinding).where(DataQualityFinding.resolved_at.is_(None)))
        .scalars()
        .all()
    )
    created = still_open = resolved = 0
    seen: set[tuple[str, str | None, object, str]] = set()
    for row in open_rows:
        identity = (row.check_name, row.ticker_symbol, row.trade_date, row.detail_hash)
        finding = current.get(identity)
        if finding is None:
            row.resolved_at = stamp
            resolved += 1
            continue
        row.last_seen_at = stamp
        row.last_seen_run_id = run_id
        row.severity = finding.severity
        row.context = finding.context or None
        still_open += 1
        seen.add(identity)
    # A finding that was resolved earlier and is back gets a fresh row: its history
    # (resolved once, reappeared) is exactly the point of keeping resolved rows.
    for identity, finding in current.items():
        if identity in seen:
            continue
        session.add(
            DataQualityFinding(
                check_name=finding.check,
                severity=finding.severity,
                ticker_symbol=finding.ticker_symbol,
                trade_date=finding.trade_date,
                detail=finding.detail,
                detail_hash=finding.detail_hash,
                context=finding.context or None,
                first_seen_run_id=run_id,
                last_seen_run_id=run_id,
                first_seen_at=stamp,
                last_seen_at=stamp,
            )
        )
        created += 1
    session.flush()
    return ReconcileResult(created, still_open, resolved)


def open_findings(session: Session, *, severity: str | None = None) -> list[DataQualityFinding]:
    stmt = select(DataQualityFinding).where(DataQualityFinding.resolved_at.is_(None))
    if severity is not None:
        stmt = stmt.where(DataQualityFinding.severity == severity)
    stmt = stmt.order_by(
        DataQualityFinding.severity, DataQualityFinding.check_name, DataQualityFinding.ticker_symbol
    )
    return list(session.execute(stmt).scalars())


def has_earlier_quality_run(session: Session, run_id: int, job_name: str) -> bool:
    """Whether a quality run completed before ``run_id`` - the baseline that makes
    "new" meaningful. On the very first run every finding is new by construction."""
    stmt = select(JobRun.id).where(
        JobRun.job_name == job_name, JobRun.id < run_id, JobRun.status == JobStatus.SUCCEEDED
    )
    return session.execute(stmt.limit(1)).first() is not None


def new_error_findings(session: Session, run_id: int) -> list[DataQualityFinding]:
    """Error-severity findings first seen by ``run_id`` (still open)."""
    return list(
        session.execute(
            select(DataQualityFinding)
            .where(
                DataQualityFinding.first_seen_run_id == run_id,
                DataQualityFinding.severity == "error",
                DataQualityFinding.resolved_at.is_(None),
            )
            .order_by(DataQualityFinding.id)
        ).scalars()
    )


__all__ = [
    "ReconcileResult",
    "has_earlier_quality_run",
    "new_error_findings",
    "open_findings",
    "reconcile_findings",
]
