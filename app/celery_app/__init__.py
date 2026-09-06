"""Celery application.

Tasks are thin: each resolves its inputs, calls a business service in
``app/web/services/``, and records the outcome. Domain logic never lives in a
task body, so the API, the worker and the CLI all execute the same code.

    codegraph explore "celery_app report_tasks ingest_tasks email_tasks"
"""

from __future__ import annotations

from celery import Celery

celery_app = Celery("nse_be")
celery_app.config_from_object("app.celery_app.celeryconfig")
celery_app.autodiscover_tasks(
    [
        "app.celery_app.tasks.report_tasks",
        "app.celery_app.tasks.ingest_tasks",
        "app.celery_app.tasks.email_tasks",
    ],
    force=True,
)

__all__ = ["celery_app"]
