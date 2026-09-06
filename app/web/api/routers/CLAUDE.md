# Routers layer — `app/web/api/routers/`

## Start here, every time

```bash
codegraph explore "views.py schema.py require_roles router mounts main.py"
```

That one query returns an existing router's handlers, its schemas, the RBAC dependency,
and where routers are mounted — everything you need to add a new one consistently.
Before editing an existing route: `codegraph explore "<handler_name>"` and read the blast
radius; handlers are referenced by tests and sometimes by the CLI.

## Rules

- Every domain is a folder with exactly `views.py` (handlers) and `schema.py` (Pydantic
  request/response models). No other module names.
- **Every protected route declares `Depends(require_roles(...))` explicitly.** No route
  inherits its authorization implicitly, and no handler inspects a role in its body.
- Routers call **business services** (`app/web/services/`). A router must never import an
  ORM model or build a SQLAlchemy query.
- **RORO** — take a Pydantic model in, return a Pydantic model out. No bare dicts.
- Every list endpoint is paginated, cursor-based by preference. No unbounded list returns.
- Early returns for error conditions; happy path last; raise `HTTPException` with a
  specific status and a user-facing message that leaks no internals.
- `async def` for anything that touches the DB, Redis, or the network.
- Org scoping: derive `org_id` from the caller's token, never from a request body field a
  client can forge. Cross-org access requires `platform_admin`.

## Adding a router

Use `/new-router` — it runs the CodeGraph query first so the new folder matches the
established pattern rather than inventing a new one. Then mount it in `app/web/main.py`.
