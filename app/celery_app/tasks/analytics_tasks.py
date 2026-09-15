"""Analytics pipeline tasks - the same ``run_pipeline`` the CLI and cron call.

codegraph explore "run_pipeline_task run_pipeline PIPELINES"
"""

from __future__ import annotations

from datetime import date
from typing import Any

from app.celery_app import celery_app
from app.web.config import get_settings
from app.web.services.jobs import run_pipeline
from app.web.services.market_data.sources import NseScraperSource, build_market_data_source
from app.web.utils.logger import get_logger

logger = get_logger("app.celery_app.tasks.analytics_tasks")


def _result_payload(result: Any) -> dict[str, Any]:
    return {
        "pipeline": result.pipeline,
        "as_of": result.as_of.isoformat(),
        "run_id": result.run_id,
        "succeeded": result.succeeded,
        "counts": result.counts,
        "steps": [
            {"name": s.name, "status": s.status, "rows": s.rows_written, "reason": s.reason}
            for s in result.steps
        ],
    }


@celery_app.task(name="app.celery_app.tasks.analytics_tasks.run_pipeline_task", bind=True)
def run_pipeline_task(
    self: Any, pipeline: str, as_of: str | None = None, force: bool = False
) -> dict[str, Any]:
    """Run one pipeline (daily, fundamentals, weekly) and return its step outcomes."""
    settings = get_settings()
    source = build_market_data_source(settings)
    if not isinstance(source, NseScraperSource):
        raise RuntimeError("the analytics pipelines need the nse_scraper market-data source")
    day = date.fromisoformat(as_of) if as_of else None
    result = run_pipeline(settings, source, pipeline, as_of=day, force=force)
    logger.info("analytics_pipeline_task", pipeline=pipeline, counts=result.counts)
    return _result_payload(result)


@celery_app.task(name="app.celery_app.tasks.analytics_tasks.scheduled_daily_analytics")
def scheduled_daily_analytics() -> dict[str, Any]:
    return run_pipeline_task.apply(args=("daily",)).get()


@celery_app.task(name="app.celery_app.tasks.analytics_tasks.scheduled_fundamentals_analytics")
def scheduled_fundamentals_analytics() -> dict[str, Any]:
    return run_pipeline_task.apply(args=("fundamentals",)).get()


@celery_app.task(name="app.celery_app.tasks.analytics_tasks.scheduled_weekly_analytics")
def scheduled_weekly_analytics() -> dict[str, Any]:
    return run_pipeline_task.apply(args=("weekly",)).get()


__all__ = [
    "run_pipeline_task",
    "scheduled_daily_analytics",
    "scheduled_fundamentals_analytics",
    "scheduled_weekly_analytics",
]
