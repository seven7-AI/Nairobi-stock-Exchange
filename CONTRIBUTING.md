# Contributing to the NSE Analytics Backend

## Navigating this codebase with CodeGraph

**Read this before you read any source file.**

This repository is indexed by [CodeGraph](https://github.com/) — a SQLite knowledge graph
of every symbol, edge, and file in the tree, living in `.codegraph/`. It returns the
**verbatim, line-numbered source** of the symbols you ask about, plus **who calls them**
and **what depends on them**.

That last part is the point. This codebase has three separate entry paths into the same
business services — the HTTP routers, the Celery tasks, and the `nse-analysis` CLI — so
"who calls this?" is genuinely not obvious from reading a file. CodeGraph answers it in
one call. Grep does not, because it cannot follow FastAPI `Depends`, Celery task
registration, or SQLAlchemy relationship resolution.

### Use it first, every time

```bash
codegraph explore "require_roles rbac.py jwt.py"              # how RBAC is enforced
codegraph explore "how does onboarding step validation work"  # the 7-step machine
codegraph explore "calculate_for_row price_bar.py"            # indicator math + inputs
codegraph explore "get_async_session AppState lifespan"       # DI wiring
codegraph explore "report_tasks.py write_daily_report"        # Celery -> service path

make explore Q="StockAnalysisStock external read-only"        # same thing via make
make graph                                                    # resync after edits
make graph-status                                             # index health
```

If you use an agent (Claude Code or similar), the rules in `CLAUDE.md` already require it
to query CodeGraph before reading, editing, or planning — and there are layer-specific
`CLAUDE.md` files in `app/web/api/routers/`, `app/web/db/`, `app/web/services/`,
`app/celery_app/`, and `app/tests/` with the right query for each area.

The pull request template asks which queries you ran and what the blast radius showed.
That is not a formality — it is the review signal that a change was made with its callers
in view.

## Setup

```bash
make install                     # dependencies + git hooks
cp deployment/env.example .env   # then fill in real values
uv run alembic upgrade head
make api                         # http://localhost:8000/docs
```

Requires Python 3.11+, and **uv** — not pip, not poetry, not pipenv.
`pyproject.toml` is the single source of truth for dependencies. There is no
`requirements.txt`, and there should never be one.

## Before you push

**This repository runs its checks locally. There is no hosted CI.** Nothing on the
server will catch a regression for you.

```bash
make install   # installs dependencies AND the git hooks
make ci        # the full gate — identical to what pre-push runs
```

`make install` (or `make hooks`) points `core.hooksPath` at `.githooks/`:

| Hook | Runs |
|---|---|
| `pre-commit` | ruff check + format — fast enough to not notice |
| `pre-push` | secret scan, ruff, format, mypy, the full pytest suite against a disposable PostgreSQL, and the Alembic drift probe |

`git push --no-verify` skips the gate. If you use it, you are the only thing standing
between a regression and `main`.

The secret scan matters most: a credential-shaped literal that reaches the remote can
only be removed by rewriting history. Catching it locally costs nothing.

## Commit messages

`<type>(<scope>): <description>`

**Types:** `feat | fix | docs | style | refactor | perf | test | build | ci | chore | revert`

**Scopes:** `auth, onboarding, orgs, users, instruments, market-data, indicators,
analytics, reports, connectors, celery, db, models, config, api, ci, docker, cli`

```
feat(auth): add JWT refresh token endpoint
fix(reports): exclude NaN changes from gainer and loser rankings
refactor(onboarding): extract step validators to dedicated module
```

## Architecture rules you will be held to

Read `CLAUDE.md` in full — it is the contract, for humans as much as for agents. The
short version:

- **Layering:** Routers → Business Services → DB Services → ORM Models. One direction only.
  A router never imports an ORM model; a service never raises `HTTPException`.
- **RBAC at the router.** Every protected route declares `Depends(require_roles(...))`.
  Business logic never inspects a role.
- **Lifespan, never `@app.on_event()`.**
- **`stockanalysis_stocks` is not ours.** An external scraper owns it. It is read-only and
  excluded from Alembic autogenerate. A migration touching it is a bug.
- **Never log a credential.** Supabase keys, JWTs, password hashes, connector API keys.
- **The CLI is a thin wrapper.** Logic reachable from `nse-analysis` but not from the API
  is in the wrong place.
