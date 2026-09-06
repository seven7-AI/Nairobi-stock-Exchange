# Business services — `app/web/services/`

## Start here, every time

```bash
codegraph explore "fetcher.py calculator.py generator.py service call path"
```

The indicator and report services carry the real domain math and have the widest blast
radius in this repo — they are called from routers, from Celery tasks, **and** from the
CLI. CodeGraph shows all three caller sets in one query. Changing a return shape here
without checking that list is the most likely way to break this codebase.

## Rules

- This layer holds the domain logic: fetching, validating, computing, rendering.
- It is **framework-free**. No `HTTPException`, no `Request`, no `Depends` — services
  raise the custom exceptions in `app/web/core/exceptions.py` and let the router or task
  translate them into a response.
- It is **role-free**. Authorization already happened at the router. A service receives an
  authorized caller context, never a role to check.
- Functional and declarative. Prefer module-level functions over classes; use a class only
  when there is genuine state to hold (an open client, a connection pool).
- Type hints on every signature including the return type. Pydantic or dataclasses for
  structured payloads.
- `async def` for I/O. Pure computation (indicator math, formatting) stays sync `def` so
  it can be called from both async routers and sync Celery tasks.
- Callers pass data in. A service must not re-fetch something its caller already has —
  that pattern caused a duplicate Supabase round-trip in the previous architecture.

## Layout

```
redis/        cache client + key helpers
email/        transactional email (verify, invite, reset, report delivery)
storage/      report artifact storage
market_data/  Supabase client, fetcher, validator
indicators/   registry, feasibility, calculator
reports/      generator, templates, formatter
```
