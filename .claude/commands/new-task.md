---
description: Add a Celery background task wired to an existing business service
---

Add a Celery task for `$ARGUMENTS`.

## Step 1 — CodeGraph first (mandatory, do not skip)

```
codegraph_explore "celeryconfig.py report_tasks.py ingest_tasks.py shared_task queues"
```

Task registration and `.delay()` dispatch are dynamic — grep cannot follow them, CodeGraph
can. Use the blast radius to see what already triggers tasks in this repo before adding
another entry point.

## Step 2 — Write the task

- Put it in the right module under `app/celery_app/tasks/`.
- Keep it **thin**: resolve inputs, call a business service in `app/web/services/`, record
  the outcome. No domain logic in the task body.
- **Sync only.** Use the sync SQLAlchemy engine — never `get_async_session`.
- Idempotent and retry-safe; assume it runs twice.
- Pass ids, not ORM objects. Never pass a credential or a raw payload — task arguments are
  serialized into the broker and visible in Flower.
- Name its queue explicitly in `celeryconfig.py`.

## Step 3 — Decide about scheduling

If this task needs a schedule, add it to the beat schedule in `celeryconfig.py` — but note
that `CELERY_BEAT_ENABLED` defaults to **false** because the GitHub Actions report
workflows already run on a schedule through the CLI. If enabling beat would duplicate an
existing workflow, say so explicitly rather than silently creating double runs.

## Step 4 — Test and resync

Add a unit test that asserts the task delegates to the service (mock the service). Then:

```
make graph
```
