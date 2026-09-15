"""What the live system last did: per job, per table, per model.

codegraph explore "job_status JobsStatus analytics_db_status"
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from sqlalchemy import func, select, text

from app.web.config import Settings
from app.web.db.analytics import analytics_session
from app.web.db.analytics.models import JobRun, ModelRegistryEntry
from app.web.services.analytics.store import analytics_db_status

#: Tables with a ``computed_at`` (or equivalent) stamp worth reporting.
STAMPED_TABLES: dict[str, str] = {
    "market_metrics": "computed_at",
    "fundamental_metrics": "computed_at",
    "factor_scores": "computed_at",
    "stock_rankings": "computed_at",
    "valuations": "computed_at",
    "forecasts": "computed_at",
    "forecast_evaluations": "evaluated_at",
    "simulations": "computed_at",
    "regimes": "computed_at",
    "portfolio_analyses": "computed_at",
    "backtest_runs": "created_at",
    "data_quality_findings": "first_seen_at",
    "classifications": "created_at",
}


@dataclass(frozen=True)
class JobLast:
    job_name: str
    status: str
    started_at: datetime
    finished_at: datetime | None
    as_of: str | None
    rows_written: int
    error: str | None
    details: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class JobsStatus:
    revision: str | None
    head: str | None
    tables: dict[str, int]
    last_update: dict[str, str | None]
    jobs: list[JobLast]
    models: list[dict[str, Any]]
    open_findings: int


def job_status(settings: Settings) -> JobsStatus:
    db = analytics_db_status(settings.analytics_db_path)
    if not db.exists:
        return JobsStatus(None, db.head_revision, {}, {}, [], [], 0)
    with analytics_session(settings) as session:
        last_update: dict[str, str | None] = {}
        for table, column in STAMPED_TABLES.items():
            if table not in db.tables:
                continue
            stamp = session.execute(text(f'SELECT MAX("{column}") FROM "{table}"')).scalar()
            last_update[table] = str(stamp) if stamp else None
        latest_ids = (
            select(JobRun.job_name, func.max(JobRun.id).label("id")).group_by(JobRun.job_name)
        ).subquery()
        rows = session.execute(
            select(JobRun).join(latest_ids, JobRun.id == latest_ids.c.id).order_by(JobRun.job_name)
        ).scalars()
        jobs = [
            JobLast(
                r.job_name,
                str(r.status),
                r.started_at,
                r.finished_at,
                r.as_of_date.isoformat() if r.as_of_date else None,
                r.rows_written,
                r.error,
                dict(r.details or {}),
            )
            for r in rows
        ]
        models = [
            {
                "name": m.name,
                "version": m.version,
                "kind": str(m.kind),
                "status": str(m.status),
                "performance": m.performance,
            }
            for m in session.execute(
                select(ModelRegistryEntry).order_by(
                    ModelRegistryEntry.name, ModelRegistryEntry.version
                )
            ).scalars()
        ]
        open_findings = 0
        if "data_quality_findings" in db.tables:
            open_findings = int(
                session.execute(
                    text("SELECT COUNT(*) FROM data_quality_findings WHERE resolved_at IS NULL")
                ).scalar()
                or 0
            )
    return JobsStatus(
        db.current_revision,
        db.head_revision,
        dict(db.tables),
        last_update,
        jobs,
        models,
        open_findings,
    )


__all__ = ["STAMPED_TABLES", "JobLast", "JobsStatus", "job_status"]
