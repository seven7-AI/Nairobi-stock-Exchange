# NSE Analytics Backend (`nse-be`)

Market data, indicators, analytics and scheduled reporting for the **Nairobi
Securities Exchange** — a FastAPI service on port **8000**, with a Celery worker,
PostgreSQL, Redis, and a `nse-analysis` CLI that shares its business logic.

```
Routers (views.py) → Business Services → DB Services → ORM Models
```

---

## Navigating this codebase with CodeGraph

**Do this before you read a file.**

This repository is indexed by [CodeGraph](https://github.com/) (`.codegraph/`) — a
knowledge graph of every symbol and edge in the tree. It returns the verbatim,
line-numbered source of what you ask about, **plus who calls it and what depends on it.**

That last part matters here more than in most repos: three separate entry paths
(HTTP routers, Celery tasks, and the CLI) reach the same business services, so
"who calls this?" is not answerable by reading a file. Grep cannot follow FastAPI
`Depends`, Celery task registration, or SQLAlchemy relationship resolution. CodeGraph can.

```bash
codegraph explore "require_roles rbac.py jwt.py"              # how RBAC is enforced
codegraph explore "how does onboarding step validation work"  # the 7-step machine
codegraph explore "run_daily_pipeline report_tasks app/cli"   # the three entry paths
codegraph explore "StockAnalysisStock include_object env.py"  # the table we do not own

make explore Q="calculate_for_row price_bar.py"               # same, via make
make graph                                                    # resync after edits
make graph-status                                             # index health
```

Agent rules live in [`CLAUDE.md`](CLAUDE.md), with layer-specific rules in
`app/web/api/routers/`, `app/web/db/`, `app/web/services/`, `app/celery_app/` and
`app/tests/`. Contributor guidance is in [`CONTRIBUTING.md`](CONTRIBUTING.md).

---

## Setup

Requires **Python 3.11+** and **uv** — not pip, poetry or pipenv.
`pyproject.toml` is the single source of truth for dependencies; there is no
`requirements.txt`.

```bash
uv sync --dev                     # or: make install
cp deployment/env.example .env    # then fill in real values
uv run alembic upgrade head
make api                          # http://localhost:8000/docs
```

## Project layout

```
app/
├── cli/            nse-analysis CLI — a thin wrapper over the services below
├── web/
│   ├── main.py     app factory, lifespan (never @app.on_event)
│   ├── config.py   Pydantic Settings
│   ├── api/        routers (views.py + schema.py per domain), middleware
│   ├── core/       dependencies (AppState), security (JWT, RBAC), exceptions
│   ├── db/         engines, ORM models, DB service layer
│   ├── services/   business logic: market_data, indicators, reports, redis, email, storage
│   └── utils/      structured logging with credential redaction
├── celery_app/     worker config and tasks (report, ingest, email)
├── alembic/        migrations
└── tests/          unit/ and integration/
```

## RBAC — 7 roles

| Role | Scope |
|---|---|
| `platform_admin` | full access across all organizations |
| `org_admin` | full access within their organization |
| `analyst` | research, indicator runs, report generation |
| `portfolio_manager` | watchlists, holdings, allocation views |
| `trader` | live prices, signals, latest quotes |
| `research_viewer` | read-only reports and dashboards |
| `client` | own watchlists and statements only |

Every protected route declares `Depends(require_roles(...))` at the router.
Business services never inspect a role.

## API

43 endpoints under `/api/v1`, plus `/health`, `/health/ready` and `/metrics`.
Interactive docs at `/docs`.

```
auth/          register, login, refresh, verify-email, password reset, me
onboarding/    the 7-step organization wizard (step 5 is skippable)
organizations/ list (platform_admin), read, update
users/         list, create, read, change role, change status
instruments/   NSE tickers and sectors
market-data/   latest quote, price history, history coverage
indicators/    per-ticker snapshots, feasibility catalogue
analytics/     market summary and sector performance (1d / 1w / 1m)
reports/       list runs, read artifacts, queue generation
connectors/    per-org data source configuration
```

## CLI

The CLI calls the same services the API does.

```bash
uv run nse-analysis run-daily                 # full daily pipeline
uv run nse-analysis generate-weekly-report
uv run nse-analysis generate-monthly-report
uv run nse-analysis check-feasibility         # which indicators are computable
uv run nse-analysis inspect-metadata          # upstream table structure
uv run nse-analysis seed-instruments          # from research/data/ticker_master.parquet
uv run nse-analysis backfill-prices           # 18 years from the canonical archive
```

Reports land in `reports/{daily,weekly,monthly}/`.

## Data sources

**`stockanalysis_stocks`** is the live upstream table. **It is written by an
external scraper outside this repo.** It is mapped read-only and excluded from
Alembic autogenerate — a migration touching it is a bug in the exclusion hook,
and CI fails the build if one appears.

**`research/`** holds the cleaned 18-year archive built from `NSE_DATA/`:
`canonical_nse_prices.parquet` (267,310 rows, 2007-01-02 → 2024-12-31) and
`ticker_master.parquet` (88 tickers with sectors). `backfill-prices` loads it
into `price_bars`, which is what gives weekly and monthly indicators the ≥5 and
≥22 observations they need.

## Background tasks

```bash
make worker      # Celery worker (queues: default, reports, ingest, email)
make flower      # task monitor on :5555
```

`CELERY_BEAT_ENABLED` defaults to **false**. The daily, weekly and monthly
GitHub Actions workflows already generate those reports through the CLI;
enabling beat without disabling them double-generates every report.

## Quality gates

```bash
make check       # codegraph sync + ruff + mypy + pytest
./scripts/run_tests.sh   # same, starting a disposable PostgreSQL for integration tests
```

Ruff (line-length 100, `E/W/F/I/N/UP/B/C4/SIM/PTH/RUF`), mypy
(`check_untyped_defs`), pytest with `unit`/`integration`/`slow` markers and
coverage on `app/`.

## Deployment

```bash
cd deployment && cp env.example .env    # fill in, then:
docker compose up --build -d            # api, worker, flower, nginx, postgres, redis
docker compose --profile beat up -d     # ... and the scheduler
```

`deploy.yml` ships to EC2 over SSH on push to `main`; `test.yml` runs the gates
on every PR, including a migration drift probe.

## Automation

| Workflow | Schedule | Output |
|---|---|---|
| `daily-report.yml` | 19:00 UTC daily | `reports/daily/YYYY-MM-DD.md` |
| `weekly-report.yml` | Fridays 19:00 UTC | `reports/weekly/YYYY-MM-DD.md` |
| `monthly-report.yml` | last day of month | `reports/monthly/YYYY-MM.md` |
| `test.yml` | PR / push | quality gates |
| `deploy.yml` | push to `main` | production |

Repository secrets: `SUPABASE_URL`, `SUPABASE_KEY`, and for deployment
`DEPLOY_HOST`, `DEPLOY_USER`, `DEPLOY_SSH_KEY`, `DEPLOY_PATH`.

## License

Apache 2.0 — see [LICENSE](LICENSE).
