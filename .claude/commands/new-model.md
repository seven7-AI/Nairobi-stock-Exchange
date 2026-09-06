---
description: Add a SQLAlchemy model plus its Alembic migration, safely
---

Add a new database model for `$ARGUMENTS`.

## Step 1 — CodeGraph first (mandatory, do not skip)

```
codegraph_explore "UUIDMixin TimestampMixin base.py models declarative"
codegraph_explore "StockAnalysisStock external include_object env.py"
```

The first query gives you the mixins and the declarative base to inherit. The second shows
the read-only external model and the Alembic exclusion hook — read it so you understand
which tables this repo owns before you generate a migration.

## Step 2 — Write the model

- One file per table in `app/web/db/models/`, named for the singular table.
- Inherit `UUIDMixin` and `TimestampMixin`.
- SQLAlchemy 2.0 style only: `Mapped[...]` annotations and `mapped_column()`. No legacy
  `Column()`.
- Type every column. Declare FKs and relationships explicitly with `back_populates`.
- Register it in `app/web/db/models/__init__.py` so Alembic sees it.

## Step 3 — Generate the migration

```
uv run alembic revision --autogenerate -m "add <table>"
```

**Read the generated migration before applying it.** It must contain only your table. If
it contains any operation against `stockanalysis_stocks`, stop — the `include_object` hook
in `app/alembic/env.py` is broken. Fix the hook and regenerate; never hand-edit the
migration to work around it.

## Step 4 — Apply and verify the round trip

```
uv run alembic upgrade head
uv run alembic downgrade -1
uv run alembic upgrade head
```

## Step 5 — Resync

```
make graph
```
