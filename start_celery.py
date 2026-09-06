#!/usr/bin/env python
"""Celery entry point: worker, beat, or flower.

    uv run python start_celery.py worker
    uv run python start_celery.py beat
    uv run python start_celery.py flower
"""

from __future__ import annotations

import sys

from app.celery_app import celery_app
from app.web.config import get_settings

USAGE = "usage: start_celery.py [worker|beat|flower]"


def main(argv: list[str]) -> int:
    mode = argv[1] if len(argv) > 1 else "worker"
    settings = get_settings()

    if mode == "worker":
        celery_app.worker_main(
            ["worker", "--loglevel=INFO", "--queues=default,reports,ingest,email"]
        )
    elif mode == "beat":
        if not settings.celery_beat_enabled:
            print(
                "CELERY_BEAT_ENABLED is false, so the beat schedule is empty.\n"
                "The daily/weekly/monthly GitHub Actions workflows already generate\n"
                "those reports through the CLI. Enable beat only after disabling them,\n"
                "or every report will be generated twice.",
                file=sys.stderr,
            )
            return 1
        celery_app.start(["beat", "--loglevel=INFO"])
    elif mode == "flower":
        celery_app.start(["flower", "--port=5555"])
    else:
        print(USAGE, file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
