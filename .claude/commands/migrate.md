---
description: Run the Alembic migration workflow with the external-table safety check
---

Handle migrations for: `$ARGUMENTS`

## Step 1 — CodeGraph first (mandatory, do not skip)

```
codegraph_explore "env.py include_object alembic base metadata models"
```

Confirm you understand which tables this repo owns and how the exclusion hook works before
generating anything.

## Step 2 — Check the current state

```
uv run alembic current
uv run alembic history --verbose | head -30
```

## Step 3 — The safety probe

Before your change, on a clean tree:

```
uv run alembic revision --autogenerate -m "probe"
```

This **must** produce an empty migration. If it does not, the models and the database have
drifted, or the `stockanalysis_stocks` exclusion is broken. Resolve that first, and delete
the probe file. Never build on top of an unexplained diff.

## Step 4 — Generate, review, apply

```
uv run alembic revision --autogenerate -m "<description>"
# READ the generated file. It must touch only tables this repo owns.
uv run alembic upgrade head
```

`stockanalysis_stocks` is written by an external scraper. Any migration touching it is a
bug in the exclusion hook, not something to accept.

## Step 5 — Verify the round trip and resync

```
uv run alembic downgrade -1 && uv run alembic upgrade head
make graph
```
