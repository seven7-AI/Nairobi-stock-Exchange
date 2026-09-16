# The NSE quantitative research engine

A live, continuously updating research system over the Nairobi Securities Exchange:
the canonical price timeline (2007 → today) and point-in-time financial statements go
in; versioned, explainable analytics come out — returns, momentum, risk, liquidity,
fundamental quality and growth, valuation multiples, factor scores, a composite
ranking with value-trap and compounder detection, fair values, forecasts, Monte Carlo
paths, scenarios, market regimes, portfolio risk and a look-ahead-safe backtester.

Everything here obeys four rules:

1. **Missing is not zero.** Every stored number is a `Measure` with a `status`
   (`known`, `zero`, `missing`, `unavailable`, `not_applicable`, `not_meaningful`)
   and a `reason`. Nothing is interpolated, back-filled or defaulted.
2. **Point in time.** A calculation as of date *T* sees prices on or before *T* and
   statements that were captured by *T* (or, for back-filled captures, published by
   period end + lag). Restatements are never back-dated.
3. **Versioned and reproducible.** Every row carries a `calc_version_id` — a hash of
   the whole `AnalyticsConfig` — so any historical number can be recomputed.
4. **Gaps are gaps.** The 2025-01 → 2026-07 hole in the price archive (and every hole
   longer than 14 days) blocks any window that would cross it; backtests and regimes
   segment around it.

## Where things live

```text
~/nse-stock-scraper/data/nse_scraper.sqlite3   raw truth, read-only from here
    instruments, stock_observations (prices), financial_statements (append-only,
    first_seen_at), fundamental_snapshots (daily overview metrics)

data/nse_analytics.sqlite3                     everything derived (Alembic -n analytics)
    job_runs, calc_versions, model_registry, classifications, data_quality_findings,
    market_metrics, correlations, fundamental_metrics, factor_scores, stock_rankings,
    valuations, forecasts, forecast_evaluations, simulations, regimes,
    portfolio_analyses, backtest_runs / _results / _positions / _equity
```

Code: `app/web/services/analytics/<engine>/engine.py` is pure (data in, `Measure`s
out); `<engine>/service.py` reads the sources, runs the engine for a date and writes
rows through `app/web/db/analytics/services/`. The CLI (`nse-analysis analytics …`) and
the Celery tasks call the same services.

## The pipelines

| Pipeline | When | Steps |
|---|---|---|
| `daily` | after the 09:00 scrape (cron 09:40) | data quality → returns → momentum → risk → liquidity → valuation multiples → factors → rankings → fair value → scenarios |
| `fundamentals` | daily 10:10; skips itself unless statements changed | fundamentals → valuation multiples → factors → rankings → fair value |
| `weekly` | Saturdays 10:30 | regime → forecasts → forecast evaluation → Monte Carlo → factors → rankings |

```bash
uv run nse-analysis analytics jobs daily [--as-of YYYY-MM-DD] [--force]
uv run nse-analysis analytics jobs fundamentals
uv run nse-analysis analytics jobs weekly
uv run nse-analysis analytics jobs status
```

Each step records a `job_runs` row (`step:<name>`) with a **fingerprint** of its
inputs — the source tables it reads (`MAX(key):COUNT(*)`), the config hash, the date
and the fingerprints of the steps it depends on. A step whose fingerprint matches its
last succeeded run for the date is skipped, so a second run on unchanged data writes
nothing; a failed step stops what depends on it, and the next run resumes there. Every
service upserts on its natural key, so `--force` re-runs yield the same row counts.

Install the cron entries once (appends; never rewrites the crontab):

```bash
scripts/install_analytics_cron.sh            # 09:40 daily, 10:10 fundamentals, Sat 10:30 weekly
scripts/install_analytics_cron.sh --verify   # exit 1 when an entry is missing
tail -f reports/analytics-jobs.log
```

The same three pipelines are Celery tasks (`app/celery_app/tasks/analytics_tasks.py`)
scheduled by beat only when `CELERY_BEAT_ENABLED=true`; cron is the deployed path.

## Reading the results

```bash
uv run nse-analysis analytics rank --top 20                # latest ranking table
uv run nse-analysis analytics rank --ticker KCB            # one explanation JSON
uv run nse-analysis analytics research KCB                 # the full profile (#21)
uv run nse-analysis analytics forecast evaluate            # score elapsed forecasts
uv run nse-analysis analytics backtest run --from 2013-01-01 --to 2024-12-31
uv run nse-analysis analytics backtest compare
uv run nse-analysis analytics portfolio analyse --weights KCB=0.4,EQTY=0.3,SCOM=0.3
uv run nse-analysis analytics plot all                     # diagrams/<kind>/ (#20)
uv run nse-analysis analytics narrate KCB                  # AI research note (#23)
```

## The AI narrative layer

`app/web/services/analytics/ai/narrative.py` turns the stored profile into a short
research note with Claude. It is **off by default** and reads only the store:

- `AI_NARRATIVES_ENABLED=true`, `ANTHROPIC_API_KEY=…` (never logged; the value pattern
  is redacted), `AI_MODEL` (default `claude-opus-5`).
- `build_context(profile)` keeps only `known` numbers (plus the reasons of the
  `unavailable` ones) and is hashed; the note is generated once per
  (ticker, as-of, model, prompt version, context hash) and reused after that.
- `check_numbers` rejects a note that cites any number not present in the context —
  the row is stored with status `rejected` and the text is never served. Statuses:
  `known`, `rejected`, `unavailable` (no key, API error, refusal), `disabled`.
- `GET /research/stocks/{ticker}/narrative` returns the latest stored row; generation
  is a CLI / job action, never a request.

## Configuration

`app/web/services/analytics/config.py` — `AnalyticsConfig` — holds every assumption:
publication lags, windows, the risk-free rate, factor definitions and weights,
classification bands, valuation assumptions, forecast horizons, simulation size and
seed, scenario sets, regime thresholds, transaction costs. It is frozen, validated and
hashed; the hash is the `calc_version`. Change a number and every downstream row is a
new version — the old rows stay.

## Operational notes

- The analytics store is SQLite in WAL mode; a job holds the single writer while it
  writes, and connections wait up to 120 s for it (`BUSY_TIMEOUT_SECONDS`). The
  backtester simulates with no lock held and writes at the end.
- `docs/STATUS.md` records every phase with its live numbers; `docs/data-sources.md`
  describes the raw sources and their known defects.

## End-to-end runbook

The order below is what cron runs; the timings are from the run recorded in
`docs/STATUS.md` (#22) on the shared build machine — expect faster on a quiet host.

```bash
# 1. raw data (scraper repo): prices + statements, once a day at 09:00 Nairobi
cd ~/nse-stock-scraper && bash scripts/run_daily_with_git.sh

# 2. the analytics store, created or migrated in place
uv run nse-analysis analytics upgrade

# 3. one-off / rarely: point-in-time classification
uv run nse-analysis analytics classify

# 4. the pipelines (each skips unchanged steps; each records job_runs rows)
uv run nse-analysis analytics jobs daily          # quality gate → metrics → factors → rankings → fair value
uv run nse-analysis analytics jobs fundamentals   # only when statements changed
uv run nse-analysis analytics jobs weekly         # regime, forecasts (+ evaluation), Monte Carlo

# 5. read
uv run nse-analysis analytics jobs status
uv run nse-analysis analytics research KCB
uv run nse-analysis analytics plot all

# 6. when the ranking model changes: the backtest (hours on a loaded box)
uv run nse-analysis analytics backtest run --from 2013-01-01 --to 2024-12-31
```

### The quality gate

`jobs daily` starts with the data-quality checks. If that run creates **new**
error-severity findings (a decimal slip, an impossible OHLC, a broken scrape), the
pipeline stops before computing and the step row says which findings and why
(`DataQualityGateError`). The first run on a store has no baseline — every finding is
new — so it reports and continues. Known, still-open defects never halt it — they are reported
in `jobs status` and every engine handles them (windows containing a flagged
observation say so in their reason). Override for one run with
`jobs daily --ignore-quality-gate`, or disable with
`AnalyticsConfig.quality.halt_on_new_errors = 0` (a config change, so a new
calc version).

### Failure modes and what you see

| Scenario | Behaviour |
|---|---|
| Scraper database missing or unreadable | `ExternalServiceError` before any job row is written; cron logs FAILED |
| Analytics store held by another writer | connections wait up to 120 s, then `database is locked` — the step records it and the next run resumes |
| A ticker with only some statements | the missing statement's metrics are `missing` with the item named; the others compute |
| Empty universe (fresh scraper DB) | every pipeline succeeds with zero rows; profiles are 404 / `None` |
| `^NASI` (or the fallback) absent from the source | regime rows are `missing` naming the index; profiles and diagrams show it as such |
| New error-severity findings | the daily pipeline halts at the quality gate (above) |
| A step crashes mid-run | its row is `failed` with the exception; dependents are skipped; rerun resumes |
