# CLAUDE.md — NSE Analytics Backend (`nse-be`)

You are an expert in Python, FastAPI, and scalable API development, working on the
**NSE Analytics Backend** — a Nairobi Securities Exchange market-analytics platform.

---

## 0. CODEGRAPH FIRST — THE RULE THAT COMES BEFORE EVERY OTHER RULE

This repository is indexed by **CodeGraph** (`.codegraph/` at the repo root). CodeGraph is a
pre-built knowledge graph of every symbol, edge, and file here. It returns **verbatim,
line-numbered source** plus **who calls it** and **what breaks if you change it**.

**Before you grep. Before you find. Before you Read. Before you edit. Before you plan.**

| How | Command |
|---|---|
| MCP tool (preferred) | `codegraph_explore` with a question or a bag of symbol names |
| Shell (always works) | `codegraph explore "<symbols or question>"` |
| Make target | `make explore Q="require_roles rbac.py"` |

### Non-negotiables

1. **Never open a file cold.** Query CodeGraph for the symbol first — one call returns the
   source *and* the callers, which is what you actually need to change it safely.
2. **Never edit without the blast radius.** CodeGraph's "what depends on these" section is
   the list of things your change can break. Read it. Act on it. Say what you found.
3. **Never re-Read a file CodeGraph already returned.** Its output is byte-for-byte the
   current on-disk source. Treat it as a Read you already performed.
4. **Never delegate a lookup to a grep/read sub-agent.** CodeGraph already did that work.
   A direct query is 1-3 calls; a grep loop is dozens, and it misses dynamic-dispatch hops
   (FastAPI `Depends`, Celery task registration, SQLAlchemy relationship resolution) that
   CodeGraph follows and grep cannot.
5. **Sync after structural edits.** `make graph` (`codegraph sync`) — the watcher lags
   writes by ~1s. `make graph-status` shows index health.

### Query shapes that work in this repo

```bash
codegraph explore "require_roles rbac.py jwt.py"              # how is RBAC enforced
codegraph explore "how does onboarding step validation work"  # the 7-step machine
codegraph explore "calculate_for_row price_bar.py"            # indicator math + its inputs
codegraph explore "get_async_session AppState lifespan"       # DI wiring
codegraph explore "report_tasks.py write_daily_report"        # Celery -> service path
codegraph explore "StockAnalysisStock external read-only"     # the scraper-owned table
```

### It is not optional in your reporting either

When you finish a task, state which CodeGraph queries you ran and what the blast radius
told you. "I explored X, it showed N callers in Y, so I also updated Z" is the expected
shape of a completion report here.

---

## 1. Project identity

**Project:** NSE Analytics Backend
**Domain:** Kenyan capital-markets analytics — market data ingestion, technical and
fundamental indicators, sector analytics, watchlists, and scheduled market reporting for
the Nairobi Securities Exchange.

**Service:** `nse-be` (port **8000**) — the single service. Auth, organizations, users,
instruments, market data, indicators, analytics, reports, connectors.

**Stack:** Python 3.11+, FastAPI, SQLAlchemy 2.0, Pydantic v2, Celery, Redis
**Package manager:** **uv** (by Astral) — NOT pip, poetry, or pipenv
**Build backend:** Hatchling
**Database:** PostgreSQL (Supabase) via asyncpg
**Migrations:** Alembic
**Background tasks:** Celery + Redis

All commands use uv:

```bash
uv sync                       # install deps from lockfile
uv add <package>              # add a dependency
uv run uvicorn ...            # run inside the venv
uv run pytest                 # run tests
uv run alembic upgrade head   # apply migrations
```

`pyproject.toml` is the single source of truth for dependencies. **No requirements.txt.**

---

## 2. RBAC — roles & permissions

Seven platform roles. **Every protected endpoint must declare which roles are allowed.**
Never expose another organization's data to a role that does not require it.

```
platform_admin     — full access across all organizations
org_admin          — full access within their organization
analyst            — research, indicator runs, custom report generation
portfolio_manager  — watchlists, holdings, allocation views
trader             — live prices, signals, latest quotes
research_viewer    — read-only reports and dashboards
client             — own watchlists and own statements only
```

Implement RBAC via FastAPI dependencies:

```python
require_roles(*roles) -> Depends()   # validates JWT claims against allowed roles
```

**Scope checks happen at the router level, not inside business logic.** A service function
must never inspect a role; it receives an already-authorized caller context.

> Before touching auth: `codegraph explore "require_roles get_current_user jwt.py rbac.py"`

---

## 3. Architecture patterns

### Layered architecture

```
Routers (views.py) → Business Services → DB Services → ORM Models
```

Each arrow is one-directional. A router never touches an ORM model. A DB service never
holds business rules. A business service never builds an HTTP response.

### Router-per-domain

Every domain gets its own folder under `app/web/api/routers/` containing exactly:

```
views.py    # route handlers
schema.py   # Pydantic request/response models
```

### Dependency injection

A central `AppState` dataclass is initialized at startup via the **lifespan context
manager**. Services (Redis, Storage, DB sessions, Email, Supabase) are injected through
FastAPI `Depends()`.

**NEVER use `@app.on_event()` — use lifespan only.**

### Onboarding state machine

Organization onboarding is a **7-step stateful wizard**:

1. Organization profile
2. Team & role invitations
3. Market coverage (exchanges, sectors)
4. Watchlist setup (tickers)
5. **Data connectors — optional, may be skipped**
6. Report preferences (cadence, delivery)
7. Review & activate

`OnboardingState` tracks `org_id, current_step, completed_steps[], status`. Each step
endpoint validates that prior steps are complete before accepting data. Step 5 is optional
and can be skipped.

### Data-handling rules (credentials & licensed market data)

- **Never log credentials or secrets** — Supabase keys, JWT secrets and tokens, password
  hashes, connector API keys — at any level.
- Use structured logging; **redact sensitive fields before emission** (see
  `app/web/utils/logger.py`).
- Organization data is isolated per `org_id`; cross-org reads require `platform_admin`.
- Secrets at rest: environment or secret manager, never committed. In transit: HTTPS only.

---

## 4. Python / FastAPI coding standards

**Key principles**

- Concise, technical code with accurate type annotations everywhere.
- Functional, declarative programming; avoid classes where possible.
- Descriptive variable names with auxiliary verbs (`is_active`, `has_permission`).
- Lowercase with underscores for all directories and filenames.
- **RORO** — Receive an Object, Return an Object.

**Functions**

- `def` for pure functions, `async def` for I/O.
- Type hints on **all** signatures, including return types.
- Pydantic models over raw dicts for all input validation.

**Error handling**

- Early returns for error conditions — no deep nesting.
- Happy path last.
- `HTTPException` with specific status codes and user-facing messages.
- Custom exception classes in `app/web/core/exceptions.py`.
- **Never expose stack traces or internal details in 4xx/5xx responses.**

**Validation**

- Pydantic v2 `BaseModel` for all request/response schemas.
- `Field`, `model_validator`, `field_validator` for complex rules.
- Separate `schema.py` per router domain.

**Performance**

- Async for all DB calls and external API requests.
- Redis caching for instrument lists, indicator snapshots, and org settings.
- **Paginated responses for all list endpoints** — cursor-based preferred.
- Background tasks via Celery for: email sending, price ingestion, report generation,
  historical backfill.

---

## 5. Database conventions

ORM: **SQLAlchemy 2.0 async** (asyncpg driver).
Sessions: `AsyncSession` via `Depends(get_async_session)`.
Sync engine for **Alembic and Celery tasks only**.

All models use:

- `UUIDMixin` — uuid primary key (uuid4)
- `TimestampMixin` — `created_at`, `updated_at` (server-side UTC)

**Tables we own (Alembic-managed):**

```
organizations       — clinic/fund/desk entities subscribing to the platform
users               — platform users with role + org_id FK
onboarding_state    — wizard progress per organization
instruments         — NSE-listed tickers with sector classification
watchlists          — per-org / per-user ticker lists
watchlist_items     — instruments in a watchlist
price_bars          — canonical daily OHLCV history per ticker
indicator_snapshots — computed indicator payloads per ticker per date
report_runs         — daily/weekly/monthly report execution records
connectors          — data-source integration config per org
```

**Table we do NOT own:**

`stockanalysis_stocks` is populated by an **external scraper outside this repo**. It is
mapped read-only in `app/web/db/models/external/stockanalysis_stock.py` and is **excluded
from Alembic autogenerate**. Never write to it. Never emit a migration against it. If
`alembic revision --autogenerate` produces a diff for it, the exclusion hook in
`app/alembic/env.py` is broken — fix the hook, do not accept the migration.

**Migrations**

```bash
uv run alembic revision --autogenerate -m "description"
uv run alembic upgrade head
uv run alembic downgrade -1
```

> Before adding a model: `codegraph explore "UUIDMixin TimestampMixin base.py models"`

---

## 6. Tooling & code quality

**Ruff:** line-length 100, Python 3.11, rules `E/W/F/I/N/UP/B/C4/SIM/PTH/RUF`
**mypy:** `python_version 3.11`, `check_untyped_defs true`
**pytest:** markers `unit`/`integration`/`slow`, coverage on `app/`

```bash
uv run ruff check .
uv run ruff format .
uv run mypy app/
uv run pytest
make check          # codegraph sync + all of the above
```

---

## 7. Git conventional commits

Format: `<type>(<scope>): <description>`

**Types:** `feat | fix | docs | style | refactor | perf | test | build | ci | chore | revert`

**Scopes:**

```
auth, onboarding, orgs, users, instruments, market-data, indicators,
analytics, reports, connectors, celery, db, models, config, api, ci, docker, cli
```

**Examples:**

```
feat(auth): add JWT refresh token endpoint
feat(onboarding): implement 7-step org wizard state machine
fix(reports): exclude NaN changes from gainer and loser rankings
feat(analytics): add sector performance aggregation endpoint
feat(market-data): add nightly price ingestion via Celery
refactor(onboarding): extract step validators to dedicated module
```

---

## 8. Deployment & infrastructure

**Docker Compose services:**

```
api            — FastAPI on port 8000
celery-worker  — background task consumer
celery-beat    — scheduler (gated by CELERY_BEAT_ENABLED, default false)
celery-flower  — task monitor on port 5555
nginx          — reverse proxy + SSL
certbot        — Let's Encrypt auto-renewal
```

**GitHub Actions:**

```
test.yml            — uv sync + ruff + mypy + pytest on PR/push
deploy.yml          — SSH -> EC2, git pull, docker compose up --build
daily-report.yml    — 19:00 UTC, runs the CLI, commits reports/daily/
weekly-report.yml   — Fridays 19:00 UTC, commits reports/weekly/
monthly-report.yml  — last day of month, commits reports/monthly/
```

The three report workflows drive the **CLI**, not the API. `CELERY_BEAT_ENABLED` defaults
to `false` so the deployed stack does not double-generate the same reports.

**Monitoring:** `/health` endpoint (Docker healthcheck), Prometheus via
`prometheus-fastapi-instrumentator`.

---

## 9. The CLI is a thin wrapper — not a second implementation

`app/cli/main.py` exposes the `nse-analysis` console script. It calls **the same business
services the routers call**. If you add logic to the CLI that the API cannot reach, you
have made a mistake — move it into `app/web/services/` and have both call it.

> Before changing the CLI: `codegraph explore "app/cli/main.py run_daily_pipeline"`
