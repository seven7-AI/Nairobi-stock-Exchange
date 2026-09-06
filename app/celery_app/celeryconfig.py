"""Celery configuration.

**Beat is disabled by default.** The daily, weekly and monthly GitHub Actions
workflows already generate and commit those reports through the CLI. Turning
beat on without turning those workflows off double-generates every report, so
``CELERY_BEAT_ENABLED`` must be set deliberately.

    codegraph explore "celery_app celeryconfig beat_schedule report_tasks"
"""

from __future__ import annotations

from typing import Any

from celery.schedules import crontab

from app.web.config import get_settings

settings = get_settings()

broker_url = settings.celery_broker_url
result_backend = settings.celery_result_backend

task_serializer = "json"
result_serializer = "json"
accept_content = ["json"]
timezone = "UTC"
enable_utc = True

task_track_started = True
task_acks_late = True
task_reject_on_worker_lost = True
worker_prefetch_multiplier = 1
task_time_limit = 30 * 60
task_soft_time_limit = 25 * 60
result_expires = 60 * 60 * 24

task_default_queue = "default"

#: Reports are long and CPU-heavy; ingestion is I/O bound; email is short.
#: Separate queues keep a slow report from starving a verification email.
task_routes: dict[str, dict[str, str]] = {
    "app.celery_app.tasks.report_tasks.*": {"queue": "reports"},
    "app.celery_app.tasks.ingest_tasks.*": {"queue": "ingest"},
    "app.celery_app.tasks.email_tasks.*": {"queue": "email"},
}

#: Mirrors the cron times the GitHub Actions workflows use, so switching from
#: CI-driven to worker-driven reporting is a flag flip rather than a rewrite.
_BEAT_SCHEDULE: dict[str, dict[str, Any]] = {
    "daily-report": {
        "task": "app.celery_app.tasks.report_tasks.scheduled_daily_report",
        "schedule": crontab(hour=19, minute=0),
    },
    "weekly-report": {
        "task": "app.celery_app.tasks.report_tasks.scheduled_weekly_report",
        "schedule": crontab(hour=19, minute=0, day_of_week=5),
    },
    "monthly-report": {
        "task": "app.celery_app.tasks.report_tasks.scheduled_monthly_report",
        "schedule": crontab(hour=19, minute=0, day_of_month="28-31"),
    },
    "ingest-latest-prices": {
        "task": "app.celery_app.tasks.ingest_tasks.ingest_latest_prices",
        "schedule": crontab(hour=18, minute=30),
    },
}

beat_schedule: dict[str, dict[str, Any]] = (
    _BEAT_SCHEDULE if settings.celery_beat_enabled else {}
)

__all__ = ["beat_schedule", "broker_url", "result_backend", "task_routes"]
