"""Report generation tasks.

Each task calls ``app.web.services.reports.pipeline`` — the same function the
CLI runs — and records the outcome on the ``report_runs`` row.

    codegraph explore "generate_report_task run_pipeline ReportRun mark_succeeded"
"""

from __future__ import annotations

import uuid
from typing import Any

from app.celery_app import celery_app
from app.web.config import get_settings
from app.web.db.base import get_sync_session_factory
from app.web.db.models.enums import ReportKind, ReportRunStatus
from app.web.db.models.report_run import ReportRun
from app.web.services.market_data.supabase_client import SupabaseConnection
from app.web.services.reports.pipeline import run_pipeline
from app.web.utils.logger import get_logger

logger = get_logger("app.celery_app.tasks.report_tasks")


def _summary_for(market_summary: dict[str, Any]) -> dict[str, Any]:
    """Keep the durable headline numbers; drop the per-instrument tables."""
    return {
        key: value
        for key, value in market_summary.items()
        if key not in {"top_gainers", "top_losers"}
    }


@celery_app.task(name="app.celery_app.tasks.report_tasks.generate_report_task", bind=True)
def generate_report_task(self: Any, run_id: str, kind: str) -> dict[str, Any]:
    """Generate one report and update its ``report_runs`` row.

    Idempotent by row: re-running against a run already marked succeeded simply
    regenerates the artifact and rewrites the same fields.
    """
    settings = get_settings()
    report_kind = ReportKind(kind)
    session_factory = get_sync_session_factory()

    with session_factory() as session:
        run = session.get(ReportRun, uuid.UUID(run_id))
        if run is None:
            logger.error("report_run_missing", run_id=run_id)
            return {"run_id": run_id, "status": "missing"}

        run.status = ReportRunStatus.RUNNING
        session.commit()

        try:
            conn = SupabaseConnection(settings)
            result = run_pipeline(report_kind, settings, conn)
        except Exception as exc:
            # type name only: the message can carry a host or a key
            session.rollback()
            run = session.get(ReportRun, uuid.UUID(run_id))
            if run is not None:
                run.status = ReportRunStatus.FAILED
                run.error_message = type(exc).__name__
                session.commit()
            logger.exception("report_generation_failed", run_id=run_id, kind=kind)
            raise

        run.status = ReportRunStatus.SUCCEEDED
        run.output_path = str(result.report_path)
        run.instruments_analyzed = result.instruments_analyzed
        run.period_start = result.period_start
        run.period_end = result.period_end
        run.summary = _summary_for(result.market_summary)
        session.commit()

    logger.info(
        "report_generated",
        run_id=run_id,
        kind=kind,
        instruments=result.instruments_analyzed,
    )
    return {
        "run_id": run_id,
        "kind": kind,
        "status": ReportRunStatus.SUCCEEDED.value,
        "output_path": str(result.report_path),
        "instruments_analyzed": result.instruments_analyzed,
    }


def _scheduled(kind: ReportKind) -> dict[str, Any]:
    """Create a run row for a scheduled generation, then generate it."""
    session_factory = get_sync_session_factory()
    with session_factory() as session:
        run = ReportRun(kind=kind, triggered_by="celery-beat", status=ReportRunStatus.PENDING)
        session.add(run)
        session.commit()
        run_id = str(run.id)
    return generate_report_task(run_id, kind.value)


@celery_app.task(name="app.celery_app.tasks.report_tasks.scheduled_daily_report")
def scheduled_daily_report() -> dict[str, Any]:
    """Beat entry point. Inert unless CELERY_BEAT_ENABLED is set."""
    return _scheduled(ReportKind.DAILY)


@celery_app.task(name="app.celery_app.tasks.report_tasks.scheduled_weekly_report")
def scheduled_weekly_report() -> dict[str, Any]:
    """Beat entry point. Inert unless CELERY_BEAT_ENABLED is set."""
    return _scheduled(ReportKind.WEEKLY)


@celery_app.task(name="app.celery_app.tasks.report_tasks.scheduled_monthly_report")
def scheduled_monthly_report() -> dict[str, Any]:
    """Beat entry point. Inert unless CELERY_BEAT_ENABLED is set.

    Beat fires this on days 28-31; the guard keeps it to the true month end.
    """
    from calendar import monthrange
    from datetime import UTC, datetime

    now = datetime.now(tz=UTC)
    if now.day != monthrange(now.year, now.month)[1]:
        logger.info("monthly_report_skipped_not_month_end", day=now.day)
        return {"status": "skipped", "reason": "not the last day of the month"}
    return _scheduled(ReportKind.MONTHLY)


__all__ = [
    "generate_report_task",
    "scheduled_daily_report",
    "scheduled_monthly_report",
    "scheduled_weekly_report",
]
