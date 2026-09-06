# Background tasks — `app/celery_app/`

## Start here, every time

```bash
codegraph explore "celeryconfig.py report_tasks.py ingest_tasks.py task registration"
```

Celery task registration is dynamic dispatch — `.delay()` and `.apply_async()` calls do
not appear as ordinary call edges to grep. CodeGraph follows those hops, so its blast
radius is the only reliable answer to "who triggers this task".

## Rules

- Tasks are **thin**. A task resolves its inputs, calls a business service in
  `app/web/services/`, and records the outcome. Domain logic never lives in a task body.
- Tasks are **sync**. Use the sync SQLAlchemy engine, never `get_async_session`.
- Every task is idempotent and safe to retry. Assume it will run twice.
- Never pass an ORM object through a task argument — pass an id and re-load it.
- Never put a credential or a raw payload in a task argument; those are serialized into
  the broker and appear in Flower.
- Queues are declared in `celeryconfig.py`. A new task names its queue explicitly.

## Beat is off by default

`CELERY_BEAT_ENABLED` defaults to **false**. The three GitHub Actions report workflows
already generate and commit daily/weekly/monthly reports through the CLI. Enabling beat
without disabling those workflows double-generates every report. If you turn beat on, say
so and turn the workflows off in the same change.
