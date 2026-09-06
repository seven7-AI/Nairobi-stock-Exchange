# NSE Analytics Backend — Full Project Context

## Overview

**`nse-be`** is a layered FastAPI service for Nairobi Securities Exchange market
analytics: it ingests NSE market data, computes financial indicators, serves them
over an authenticated REST API, and generates daily, weekly and monthly Markdown
market reports on a schedule.

The same business services are reachable three ways — the HTTP API, Celery
background tasks, and the `nse-analysis` CLI — so no entry path holds its own copy
of the logic.

**Service:** `nse-be` on port **8000**
**Author:** Kevin Kipkoech · **License:** Apache 2.0
**Python:** 3.11+ · **Package manager:** uv · **Build backend:** Hatchling
**Database:** PostgreSQL via asyncpg, SQLAlchemy 2.0 async, Alembic migrations
**Background tasks:** Celery + Redis
**Agent rules:** `CLAUDE.md` (root) plus layer-specific rules in five packages

> **Navigate with CodeGraph first.** This repo is indexed (`.codegraph/`).
> `codegraph explore "<symbols or question>"` returns verbatim source plus the
> callers and blast radius — which matters here because routers, Celery tasks and
> the CLI all reach the same services through edges grep cannot follow.

---

## Architecture

```
                    ┌───────────────── ENTRY PATHS ─────────────────┐
                    │                                               │
   HTTP :8000            Celery worker              nse-analysis CLI
   (FastAPI)             (Redis broker)             (Typer)
        │                      │                          │
        └──────────────────────┼──────────────────────────┘
                               ▼
              ┌────────── BUSINESS SERVICES ──────────┐
              │  market_data · indicators · reports   │
              │  redis · email · storage              │
              └───────────────┬───────────────────────┘
                              ▼
                     ┌── DB SERVICE LAYER ──┐
                     │  queries only        │
                     └──────────┬───────────┘
                                ▼
        ┌───────────────── ORM MODELS ─────────────────┐
        │  organizations · users · onboarding_state     │
        │  instruments · watchlists · watchlist_items   │
        │  price_bars · indicator_snapshots             │
        │  report_runs · connectors                     │
        │  ─────────────────────────────────────────    │
        │  stockanalysis_stocks  (READ-ONLY, external)  │
        └───────────────────┬───────────────────────────┘
                            ▼
                 PostgreSQL (Supabase) · Redis
```

**Layering rule:** Routers → Business Services → DB Services → ORM Models, one
direction only. A router never imports an ORM model; a service never raises
`HTTPException`; a DB service never holds a business rule.

### RBAC — 7 roles

`platform_admin`, `org_admin`, `analyst`, `portfolio_manager`, `trader`,
`research_viewer`, `client`.

Enforced by `require_roles(*roles)` **at the router**, never inside business
logic. Every protected endpoint declares the roles it admits.

### Onboarding — a 7-step state machine

1. Organization profile → 2. Team invitations → 3. Market coverage →
4. Watchlist setup → 5. **Data connectors (optional, skippable)** →
6. Report preferences → 7. Review & activate

Steps are strictly ordered; ordering is enforced in `onboarding_service` so the
rule holds for every caller. Completing step 7 activates the organization.

---

## Two Data Sources

### 1. Live Data: Supabase `stockanalysis_stocks` Table (Primary)

This is the **primary data source** used by the pipeline. A separate scraper (not in this repo) populates a Supabase PostgreSQL table called `stockanalysis_stocks` with current NSE stock data. Each row contains:

| Field | Description |
|---|---|
| `ticker_symbol` | Stock ticker code (e.g., `SCOM`, `EQTY`, `KCB`) |
| `company_name` | Full company name |
| `stock_price` | Current trading price (KES) |
| `stock_change` | Absolute price change from previous day |
| `market_cap` | Market capitalization in KES |
| `revenue` | Annual revenue in KES |
| `dividend_yield` | Dividend yield percentage |
| `pe_ratio` | Price-to-earnings ratio |
| `ps_ratio` | Price-to-sales ratio |
| `pb_ratio` | Price-to-book ratio |
| `week_52_low` | 52-week low price |
| `week_52_high` | 52-week high price |
| `price_history` | JSON array of historical price entries `[{"date": "...", "price": ...}, ...]` |
| `scraped_at` | UTC timestamp of when the data was scraped |

The pipeline connects using `SUPABASE_URL` and `SUPABASE_KEY` environment variables (stored in `.env` locally, GitHub Secrets in CI).

### 2. Historical Archive: `NSE_DATA/` Folder (Reference / Legacy)

This folder contains **18 CSV files** (one per year, 2007-2024) with daily trading data for all NSE-listed stocks, plus **5 sector classification files**. These CSVs are currently marked as **deprecated** in the codebase - the pipeline now pulls historical data from the `price_history` field in Supabase rather than from these files. However, they remain a valuable reference dataset.

#### Stock Price CSV Structure (18 files)

Files: `NSE_data_all_stocks_2007.csv` through `NSE_data_all_stocks_2024.csv`

| Column | Description |
|---|---|
| `DATE` | Trading date (format varies: `1/2/2007` in older files, `2-Jan-24` in newer) |
| `CODE` | Stock ticker code |
| `NAME` | Company name |
| `12m Low` | 12-month low price |
| `12m High` | 12-month high price |
| `Day Low` | Intraday low |
| `Day High` | Intraday high |
| `Day Price` | Closing price for the day |
| `Previous` | Previous day's closing price |
| `Change` | Absolute price change |
| `Change%` | Percentage change |
| `Volume` | Number of shares traded |
| `Adjust` / `Adjusted Price` | Adjusted price (column name varies across years) |

**Example rows:**

2007 data:
```
1/2/2007, EGAD, Eaagads, 22, 57, 52, 52, 52, 52, -, -, 300, 26
1/2/2007, BBK, Barclays Bank, 11.75, 18.5, 74, 84.5, 83.5, 76, 7.5, 8.98%, 398300, 20.88
```

2024 data:
```
2-Jan-24, EGAD, Eaagads Ltd, 10.35, 14.5, 12.8, 12.8, 12.8, 13.95, -1.15, -8.24%, 100, -
2-Jan-24, SCOM, Safaricom PLC, 14.3, 22.75, 17.2, 17.75, 17.5, 17.15, 0.35, 2.04%, 24889900, -
```

**Scale:** Files range from ~10,600 rows (2007) to ~18,100 rows (2024), reflecting the growing number of listed companies and trading days.

#### Sector Classification CSV Structure (5 files)

Files: `NSE_data_stock_market_sectors_2013.csv` through `NSE_data_stock_market_sectors_2023_2024.csv`

| Column | Description |
|---|---|
| `Sector` | Market sector (e.g., Agricultural, Banking, Insurance) |
| `Stock_code` | Ticker code |
| `Stock_name` | Full company name |

---

## Stocks Tracked (59 Active as of February 2026)

The pipeline currently tracks **59 stocks** across these NSE sectors:

### Agricultural (6)
| Ticker | Company |
|---|---|
| EGAD | Eaagads Limited |
| KUKZ | Kakuzi Plc |
| KAPC | Kapchorua Tea Kenya Plc |
| LIMT | Limuru Tea Plc |
| SASN | Sasini PLC |
| WTK | Williamson Tea Kenya Plc |

### Banking (12)
| Ticker | Company |
|---|---|
| ABSA | Absa Bank Kenya PLC |
| BKG | BK Group PLC |
| COOP | Co-operative Bank of Kenya |
| DTK | Diamond Trust Bank Kenya |
| EQTY | Equity Group Holdings Plc |
| HFCK | HF Group Plc |
| IMH | I&M Group PLC |
| KCB | KCB Group PLC |
| NBK | National Bank of Kenya |
| NCBA | NCBA Group PLC |
| SBIC | Stanbic Holdings Plc |
| SCBK | Standard Chartered Bank Kenya |

### Commercial & Services (12)
| Ticker | Company |
|---|---|
| DCON | Deacons (East Africa) Plc |
| EVRD | Eveready East Africa PLC |
| XPRS | Express Kenya PLC |
| HBE | Homeboyz Entertainment Plc |
| KQ | Kenya Airways Plc |
| LKL | Longhorn Publishers Plc |
| NBV | Nairobi Business Ventures |
| NMG | Nation Media Group PLC |
| SCAN | WPP Scangroup Plc |
| SGL | Standard Group PLC |
| SMER | Sameer Africa PLC |
| TPSE | TPS Eastern Africa (Serena Hotels) |

### Construction & Allied (5)
| Ticker | Company |
|---|---|
| ARM | ARM Cement |
| BAMB | Bamburi Cement Plc |
| CABL | East African Cables PLC |
| CRWN | Crown Paints Kenya PLC |
| PORT | East African Portland Cement |

### Energy & Petroleum (4+)
| Ticker | Company |
|---|---|
| KEGN | KenGen (Kenya Electricity Generating) |
| KPLC | Kenya Power and Lighting |
| TOTL | TotalEnergies Marketing Kenya |
| UMME | Umeme Limited (Uganda) |

### Insurance (6)
| Ticker | Company |
|---|---|
| BRIT | Britam Holdings Plc |
| CIC | CIC Insurance Group Plc |
| JUB | Jubilee Holdings Limited |
| KNRE | Kenya Reinsurance Corporation |
| LBTY | Liberty Kenya Holdings |
| SLAM | Sanlam Allianz Holdings (Kenya) |

### Investment (5)
| Ticker | Company |
|---|---|
| CTUM | Centum Investment Company |
| HAFR | Home Afrika Limited |
| KURV | Kurwitu Ventures Limited |
| OCH | Olympia Capital Holdings |
| TCL | TransCentury PLC |

### Investment Services (1)
| Ticker | Company |
|---|---|
| NSE | Nairobi Securities Exchange Plc |

### Manufacturing & Allied (8)
| Ticker | Company |
|---|---|
| BAT | British American Tobacco Kenya |
| BOC | BOC Kenya Plc |
| CARB | Carbacid Investments Plc |
| EABL | East African Breweries PLC |
| FTGH | FTG Holdings Ltd (Flame Tree) |
| MSC | Mumias Sugar |
| ORCH | Kenya Orchards |
| UNGA | Unga Group Plc |

### Telecommunication (1)
| Ticker | Company | Market Cap (Feb 2026) |
|---|---|---|
| SCOM | Safaricom PLC | KES 1.33 Trillion (largest on NSE) |

### Other
| Ticker | Company | Type |
|---|---|---|
| CGEN | Car & General (Kenya) Plc | Automobiles |
| GLD | ABSA NewGold ETF | ETF |
| LAPR | Laptrust Imara I-REIT | REIT |
| AMAC | Africa Mega Agricorp Plc | Other |
| SKL | Shri Krishana Overseas PLC | Other |

---

## How the Pipeline Works

All three report pipelines share one implementation:
`app/web/services/reports/pipeline.py`. The Celery task and the CLI both call it.

1. **Fetch** — `DataFetcher.fetch_daily_window()` pulls the latest rows from the
   upstream `stockanalysis_stocks` table.
2. **Merge** — the newest row per `ticker_symbol` is kept (~59 instruments).
3. **Validate** — `validate_merged_rows()` produces a completeness summary.
4. **Load history** — `load_historical_from_supabase(merged_rows)`. The merged
   rows are *passed in*; this method used to re-fetch them itself, doubling every
   run's upstream reads.
5. **Calculate** — 1D/1W/1M change, 20/50/200-day moving averages, RSI(14), CAGR,
   all-time high/low, distance from ATH.
6. **Classify** — `_classify_market()` ranks gainers and losers. Instruments whose
   change could not be computed are **excluded from the ranking**, not coerced to
   0.00%, and the exclusion count is reported.
7. **Render** — Markdown to `reports/{daily,weekly,monthly}/`.
8. **Record** — a `report_runs` row captures status, output path, instrument count
   and the headline summary.

Weekly uses a 7-day window and top-10 tables; monthly uses the calendar month and
top-15 tables. Both need enough history per ticker (≥5 and ≥22 observations),
which is what the `price_bars` backfill provides.

---

## Report Examples

### Daily Report Example (2026-02-19)

```markdown
# NSE Daily Market Report - 2026-02-19

- Generated At (UTC): `2026-02-19T18:14:06.367242+00:00`
- Data Sources: `stockanalysis_stocks`
- Stocks Analyzed: `59`

## Executive Summary

- Market Trend: **bearish**
- Mean Daily Change: **-6.88%**
- Data Completeness: **100.00%**

## Top Gainers

| Ticker | 1D Change |
|---|---:|
| SLAM | 219.05% |
| EGAD | 38.19% |
| UMME | 27.54% |
| NSE | 14.62% |
| CRWN | 9.24% |

## Top Losers

| Ticker | 1D Change |
|---|---:|
| EVRD | -85.70% |
| CIC | 0.00% |
| UCHM | 0.00% |

## Valuation Snapshot

| Ticker | Price | Market Cap | Revenue | Dividend Yield | 52W Low | 52W High |
|---|---:|---:|---:|---:|---:|---:|
| SCOM | 32.15 | 1,326,165,666,800 | 399,964,500,000 | 4.53% | 17.00 | 34.20 |
| EQTY | 74.25 | 282,082,191,450 | 176,545,609,000 | 5.69% | 41.20 | 78.00 |
| KCB | 74.75 | 241,009,711,125 | 180,683,048,000 | 5.33% | 35.00 | 76.50 |
...
```

### Weekly Report Example (Week Ending 2026-02-19)

```markdown
# NSE Weekly Market Report - Week Ending 2026-02-19

- Week Period: `2026-02-13` to `2026-02-19`
- Stocks Analyzed: `59`

## Executive Summary
- Market Trend: **flat**
- Mean Weekly Change: **0.00%**

## Top Weekly Gainers
| Ticker | Company | Weekly Change | Current Price |
|---|---:|---:|---:|
| SCOM | Safaricom PLC | 0.00% | 32.15 |
| EQTY | Equity Group Holdings Plc | 0.00% | 74.25 |
...

## Weekly Performance Overview
| Ticker | Company | Price | Weekly Change | Market Cap |
|---|---:|---:|---:|---:|
| SCOM | Safaricom PLC | 32.15 | N/A | 1,326,165,666,800 |
...
```

### Monthly Report Example (February 2026)

```markdown
# NSE Monthly Market Report - February 2026

- Month: `February 2026`
- Stocks Analyzed: `59`

## Executive Summary
- Market Trend: **flat**
- Mean Monthly Change: **0.00%**

## Monthly Performance Overview
| Ticker | Company | Price | Monthly Change | Market Cap | PE Ratio |
|---|---:|---:|---:|---:|---:|
| SCOM | Safaricom PLC | 32.15 | N/A | 1,326,165,666,800 | N/A |
...
```

**Note:** The weekly and monthly reports currently show 0.00% changes and N/A for many metrics. This is because the `price_history` JSON field in Supabase doesn't yet have enough accumulated historical data points (the scraper needs to have been running for at least 5 days for weekly and 22 days for monthly calculations to work).

---

## Financial Indicators

### Currently Calculable (22 of 280+)

The pipeline defines **280+ financial indicators** across 21 categories in `indicators.txt`, but only **22 are currently calculable** with available Supabase data:

| Indicator | Source |
|---|---|
| Stock Price | Direct from `stock_price` field |
| Price Change 1D (%) | Calculated from `stock_change` / previous price |
| Price Change 1W (%) | From 5-day historical lookback |
| Price Change 1M (%) | From 22-day historical lookback |
| Market Cap | From the `overview_metrics` JSONB blob |
| Revenue | From the `overview_metrics` JSONB blob |
| PE Ratio | From the `overview_metrics` JSONB blob |
| PS Ratio | From the `overview_metrics` JSONB blob |
| PB Ratio | From the `overview_metrics` JSONB blob |
| Dividend Yield | From the `dividends_metrics` JSONB blob |
| 52-Week High | From the `price_metrics` JSONB blob |
| 52-Week Low | From the `price_metrics` JSONB blob |
| Distance from ATH (%) | Latest price against the all-time high |
| 20-Day Moving Average | Calculated from 20 data points of history |
| 50-Day Moving Average | Calculated from 50 data points of history |
| 200-Day Moving Average | Calculated from 200 data points of history |
| RSI (14-day) | Calculated from 15+ data points of history |
| CAGR | Calculated from historical start/end prices + time span |
| All-Time High | Max of all historical prices |
| All-Time Low | Min of all historical prices |
| Total Return 1M / 1Y | Direct from `performance_metrics` |
| Company Name | Direct from `company_name` field |

> Two entries previously listed here - **Volume** and **Annualized Volatility** -
> were never produced by `calculate_for_row()`. They have been replaced above with
> metrics the calculator does emit. Query the live figure rather than trusting this
> table: `GET /api/v1/indicators/feasibility`, or `uv run nse-analysis check-feasibility`.

### Not Yet Calculable (216)

These require data sources or field mappings not currently available: EPS, EBITDA,
Free Cash Flow, debt ratios, Beta, Forward PE, balance sheet and cash flow items.
The full list appears in every daily report under "Indicators Not Calculable", and
at `GET /api/v1/indicators/feasibility`.

### Indicator Categories (from `indicators.txt`)

1. Basic Information (11 indicators)
2. Price and Volume (7)
3. Valuation Ratios (16)
4. Performance Metrics (15)
5. Price Levels (12)
6. Company Information (10)
7. Revenue and Growth (7)
8. Profitability (6)
9. Earnings (8)
10. Cash Flow (9)
11. Balance Sheet (12)
12. Margins and Ratios (10)
13. Debt and Leverage (12)
14. Efficiency and Turnover (3)
15. Dividends and Shareholder Returns (14)
16. Market and Technical Indicators (16)
17. Shares and Ownership (8)
18. Earnings and Dividend Dates (5)
19. Return on Investment (8)
20. Employee and Revenue Metrics (3)
21. Miscellaneous (8)

---

## Automation & Scheduling

| Workflow | Schedule | Purpose |
|---|---|---|
| `.github/workflows/daily-report.yml` | 19:00 UTC daily | CLI → `reports/daily/` |
| `.github/workflows/weekly-report.yml` | Fridays 19:00 UTC | CLI → `reports/weekly/` |
| `.github/workflows/monthly-report.yml` | last day of month | CLI → `reports/monthly/` |

**Quality checks and deployment do not run on GitHub.** The gate lives in
`.githooks/` (installed by `make install`): pre-commit runs ruff and format,
pre-push runs a secret scan, ruff, format, mypy, the full pytest suite against a
disposable PostgreSQL, and the Alembic drift probe. `make ci` runs the same thing
on demand. Deployment is `docker compose` from a machine. Nothing on the server
catches a regression, so `--no-verify` is the only thing between a mistake and
the remote.

Celery beat mirrors the same cron times but **`CELERY_BEAT_ENABLED` defaults to
`false`**: the report workflows above already generate those reports, and running
both would double-generate every one. `start_celery.py beat` refuses to launch
while the flag is false.

Local schedulers (`scripts/run_*_task.{sh,ps1,cmd}`, `scripts/setup_*.{sh,ps1}`)
are retained and still drive the same CLI commands.

---

## Project Structure

```
Nairobi-stock-Exchange/
├── CLAUDE.md                 agent rules — CodeGraph first
├── CONTRIBUTING.md
├── pyproject.toml            single source of truth for dependencies
├── uv.lock  alembic.ini  Makefile  start_celery.py
├── indicators.txt            280+ indicator catalogue
├── .claude/                  settings.json + /new-router /new-model /new-task /migrate
├── deployment/               Dockerfile, docker-compose.yml, nginx.conf, env.example
├── scripts/                  start_api.sh, start_worker.sh, run_tests.sh, schedulers
├── NSE_DATA/                 2007-2024 CSV archive (source for research/)
├── research/                 notebook + canonical parquet artifacts
├── reports/{daily,weekly,monthly}/
└── app/
    ├── cli/main.py           nse-analysis — a thin wrapper over the services
    ├── web/
    │   ├── main.py           app factory + lifespan (never @app.on_event)
    │   ├── config.py         Pydantic Settings
    │   ├── api/
    │   │   ├── routers/      10 domains, each views.py + schema.py
    │   │   ├── middleware/   request id, access logging
    │   │   ├── deps.py  pagination.py  error_handlers.py
    │   ├── core/
    │   │   ├── dependencies.py   AppState
    │   │   ├── exceptions.py
    │   │   └── security/         tokens.py, rbac.py, password.py
    │   ├── db/
    │   │   ├── base.py           async engine + sync engine (Alembic/Celery only)
    │   │   ├── models/           one file per table; external/ is read-only
    │   │   └── services/         queries only
    │   ├── services/         market_data, indicators, reports, redis, email, storage
    │   └── utils/            logger with credential redaction
    ├── celery_app/           celeryconfig.py + tasks/{report,ingest,email}_tasks.py
    ├── alembic/              env.py (include_object hook), versions/
    └── tests/                unit/, integration/, conftest.py
```

Each of `app/web/api/routers/`, `app/web/db/`, `app/web/services/`,
`app/celery_app/` and `app/tests/` carries its own `CLAUDE.md` opening with the
CodeGraph query to run before working there.

---

## Key Dependencies

**Web:** fastapi, uvicorn[standard], prometheus-fastapi-instrumentator
**Security:** pyjwt, bcrypt (not passlib — see below), email-validator
**Database:** sqlalchemy[asyncio], asyncpg, psycopg2-binary, alembic, supabase
**Tasks:** celery[redis], redis
**Config:** pydantic, pydantic-settings, python-dotenv
**Analytics:** pandas, numpy, scipy, pyarrow, matplotlib
**CLI:** typer, rich
**Dev:** ruff, mypy, pytest, pytest-asyncio, pytest-cov, httpx

> passlib 1.7.4 (its final release, 2020) probes its backend with a secret longer
> than 72 bytes, which bcrypt ≥ 4.1 refuses outright, so `CryptContext.hash()`
> raises before hashing anything. The `bcrypt` library is used directly instead.

---

## Configuration

All settings are typed in `app/web/config.py` and loaded from `.env`. Nothing
reads `os.environ` directly. See `deployment/env.example` for the full list.

Two production guards refuse to boot a misconfigured deployment:

- `JWT_SECRET_KEY` still at the development default in `ENVIRONMENT=production`;
- `BCRYPT_ROUNDS` below 12 in production (tests lower it to 4 for speed).

---

## Current State & Known Limitations

1. **`stockanalysis_stocks` is not ours.** An external scraper outside this repo
   creates and writes it. It is mapped read-only, excluded from Alembic
   autogenerate by the `include_object` hook, and CI fails the build if a
   migration ever touches it.

2. **Historical depth drives which indicators are computable.** Weekly and monthly
   changes need ≥5 and ≥22 observations per ticker. The upstream `price_history`
   field does not yet carry that depth, which is why
   `nse-analysis backfill-prices` loads the 18-year canonical archive into
   `price_bars`.

3. **~22 of 280+ catalogued indicators are computable.** The rest need financial
   statement data (EPS, EBITDA, free cash flow, debt ratios, beta) that no current
   source provides. `GET /api/v1/indicators/feasibility` reports the live count.

4. **1D change has no unit-drift guard.** `price_change_1d_pct` derives the
   previous close as `price - stock_change`, assuming `stock_change` is an
   absolute delta. Implausible daily moves in historical reports (e.g. SLAM
   +219.05% on 2026-02-19) suggest the upstream field is sometimes a percentage.
   Deliberately not "fixed" — it needs a decision on what counts as a plausible
   daily move, not a guess.

5. **No yearly report.** Daily, weekly and monthly exist; yearly does not.

6. **The scraper is external.** The component populating `stockanalysis_stocks`
   is not part of this repository.

---

## CLI Commands Reference

```bash
# Full daily pipeline (fetch + validate + calculate + report)
uv run nse-analysis run-daily

# Generate just a report (same as run-daily)
uv run nse-analysis generate-report

# Weekly report (best run on Fridays)
uv run nse-analysis generate-weekly-report

# Monthly report (best run on last day of month)
uv run nse-analysis generate-monthly-report

# Just fetch data without generating a report
uv run nse-analysis pull-data

# Calculate indicators without generating a report
uv run nse-analysis calculate-indicators --limit 100

# Check which of the 280+ indicators can be calculated
uv run nse-analysis check-feasibility

# Inspect Supabase table structure
uv run nse-analysis inspect-metadata

# Seed the instrument master from research/data/ticker_master.parquet
uv run nse-analysis seed-instruments

# Backfill price_bars from the 18-year canonical archive
uv run nse-analysis backfill-prices

# Inspect price_history field structure
uv run nse-analysis inspect-price-history --limit 5
```
