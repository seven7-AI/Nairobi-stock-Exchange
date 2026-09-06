---
description: Scaffold a new domain router (views.py + schema.py) following the established pattern
---

Create a new router domain named `$ARGUMENTS` under `app/web/api/routers/`.

## Step 1 — CodeGraph first (mandatory, do not skip)

```
codegraph_explore "views.py schema.py require_roles router APIRouter main.py mounts"
```

Read the returned source of an existing router and its schema module. The new router must
match that pattern exactly — same imports, same dependency style, same response shapes.
Do not invent a new convention. Note the blast radius on `app/web/main.py`; you will be
editing it to mount the new router.

## Step 2 — Create the folder

```
app/web/api/routers/<domain>/
├── __init__.py
├── views.py     # handlers only
└── schema.py    # Pydantic v2 request/response models
```

## Step 3 — Write the handlers

- `router = APIRouter(prefix="/api/v1/<domain>", tags=["<domain>"])`
- **Every protected route declares `Depends(require_roles(...))`.** Pick the narrowest set
  of the seven roles that genuinely need it — see the RBAC table in the root `CLAUDE.md`.
- `async def` for anything touching the DB, Redis, or the network.
- RORO: a Pydantic model in, a Pydantic model out. Never a bare dict.
- List endpoints are cursor-paginated.
- Call business services in `app/web/services/`. **Never import an ORM model here.**
- Early returns for errors; happy path last; `HTTPException` with a message that leaks
  nothing internal.
- Derive `org_id` from the token, never from a client-supplied body field.

## Step 4 — Mount it

Add the router to `app/web/main.py` alongside the existing mounts.

## Step 5 — Test it

Add an RBAC matrix test in `app/tests/integration/`: allowed roles get 2xx, at least one
disallowed role gets 403.

## Step 6 — Resync

```
make graph
```

Then report which CodeGraph queries you ran and what the blast radius showed.
