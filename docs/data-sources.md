# Data sources

`nse-be` gets its raw NSE market data from **one** source: the daily output of the
separate **`~/nse-stock-scraper`** project.

```text
Data Sources
│
├── NSE Scraper                                    [ACTIVE]
│   └── ~/nse-stock-scraper
│       └── data/nse_scraper.sqlite3
│           └── daily scraped NSE market data
│
└── Supabase / stockanalysis_stocks                [registered, not used]
```

---

## Architecture

```text
                 ┌──────────────────────┐
                 │  NSE Scraper Project │
                 │ ~/nse-stock-scraper  │
                 └──────────┬───────────┘
                            │
                            │ Daily scrape — cron, 09:00 Africa/Nairobi
                            ▼
                 ┌──────────────────────┐
                 │  Scraped NSE Data    │
                 │  Existing Storage    │
                 └──────────┬───────────┘
                            │
                            │ Read / Pull  (SQLite mode=ro)
                            ▼
                 ┌──────────────────────┐
                 │      nse-be          │
                 │   NSE Data Source    │
                 └──────────┬───────────┘
                            │
                            ▼
                 ┌──────────────────────┐
                 │ Future Analytics     │
                 │ Indicators / Agents  │
                 │ Reports / AI         │
                 └──────────────────────┘
```

---

## What the scraper does

A separate repository, not part of `nse-be`. Its logic is **not** duplicated here.

| | |
|---|---|
| **Trigger** | cron, `0 09 * * *` Africa/Nairobi → `scripts/run_daily_with_git.sh` → `scripts/run_daily_job.sh` |
| **Spiders** | `stockanalysis_scraper` → `stockanalysis_stocks`; `afx_scraper` → `stock_data` |
| **Storage** | local SQLite, `data/nse_scraper.sqlite3` (`DB_BACKEND=sqlite`) |
| **Completion** | Scrapy exits 0 even on an empty crawl, so a quality gate writes `reports/stats/<spider>-latest.json` with a `quality_ok` flag |
| **Fallback** | rows whose database write threw are appended to `reports/local_fallback/<table>_fallback-<date>.jsonl` |

### Where the data lives

```text
~/nse-stock-scraper/
├── data/nse_scraper.sqlite3            ← the market data
│   ├── stockanalysis_stocks            ← ACTIVE: 64 tickers, full metrics + history
│   └── stock_data                      ← legacy, stale since 2026-08-18
├── reports/stats/<spider>-latest.json  ← did the last run actually succeed
└── reports/local_fallback/*.jsonl      ← rows that never reached the database
```

`stockanalysis_stocks` holds **one row per ticker**. History is not one row per day —
it lives in each row's `price_history` JSON array, appended only when a ticker's price
or change actually moves.

---

## How `nse-be` reads it

`app/web/services/market_data/sources/nse_scraper.py`.

- Opens the file with SQLite's `file:...?mode=ro` URI, which refuses every write, plus a
  busy timeout so a read waits out a concurrent scrape instead of failing.
- Decodes the JSON columns. SQLite has no JSONB, so the five metrics blobs and
  `price_history` are stored as TEXT. Decoding them **restores the exact shape the
  Supabase client used to return**, which is why nothing downstream had to change.
- That is the only transformation. Every scraper field is passed through as produced.

```text
NseScraperSource.fetch_latest_rows()
  → DataFetcher.merge_current_data()      latest row per ticker
  → DataFetcher.load_historical()         price_history → tidy frame
  → calculate_batch()                     indicators
  → reports / analytics
```

### Fields exposed

`ticker_symbol`, `company_name`, `rank`, `stock_price`, `stock_change`, `scraped_at`,
`created_at`, `updated_at`, and the JSON blobs `overview_metrics`,
`performance_metrics`, `dividends_metrics`, `price_metrics`, `profile_metrics`,
`price_history`.

---

## Configuration

Typed settings in `app/web/config.py`. Nothing reads `os.environ` directly, and no
machine-specific path appears in application code — only the root is configured and the
artifact paths are derived from it.

| Setting | Default | Purpose |
|---|---|---|
| `NSE_SCRAPER_PATH` | `~/nse-stock-scraper` | Root of the scraper project |
| `NSE_SCRAPER_DB_PATH` | *(derived)* | Override for the SQLite file |
| `NSE_SCRAPER_READ_TIMEOUT_SECONDS` | `5.0` | SQLite busy timeout |
| `NSE_SCRAPER_STALE_AFTER_HOURS` | `36` | Age at which data is reported stale |

Under Docker the project is bind-mounted read-only at `/srv/scraper`
(`NSE_SCRAPER_HOST_PATH` on the host, `NSE_SCRAPER_PATH` inside the container).

---

## Using it

```bash
uv run nse-analysis inspect-source        # path, freshness, quality gate, history depth
uv run nse-analysis backfill-from-scraper # copy price_history into price_bars
uv run nse-analysis run-daily             # daily report from scraped data

GET /api/v1/market-data/source            # source info + health
GET /api/v1/market-data/scraped           # raw latest rows, cursor-paginated
GET /health/ready                         # includes market_data_source
```

`GET /api/v1/market-data/source` reports four states, and the distinction matters:

| Status | Meaning |
|---|---|
| `ok` | readable, fresh, last scrape passed its own quality gate |
| `stale` | readable, but not refreshed within `NSE_SCRAPER_STALE_AFTER_HOURS` |
| `degraded` | fresh, but the scraper's quality gate **failed** on the last run |
| `unreachable` | the database could not be read at all |

---

## The canonical timeline (2007 → today)

Since 2026-09-12 the scraper's database also holds **one row per ticker per trading
day** in `stock_observations`: the 2007–2024 NSE archive (285,819 rows, imported from
this repository's `NSE_DATA/`) plus every daily scrape, with `instruments` (official NSE
sector, instrument type) and `instrument_aliases` (`BBK → ABSA` and seven more).

```text
NSE_DATA/*.csv  ──import──▶  stock_observations  ◀──append daily──  stockanalysis_scraper
                             instruments · instrument_aliases
                                        │
                                        │  NseScraperSource.fetch_observations("KCB")
                                        ▼
                             2007-01-02 … 2024-12-31 (archive) … 2026-09-12 (scraper)
```

```python
source.fetch_observations("ABSA")             # includes the years it traded as BBK
source.fetch_observations("KCB", start=date(2020, 1, 1))
source.fetch_instruments(sector="Banking")
```

**Visualized:** `diagrams/stock-growth/<TICKER>.png` and
`GET /api/v1/market-data/{ticker}/growth` draw this timeline — gaps as gaps, prices
unadjusted with suspected splits marked. See `diagrams/README.md`.

The schema, lineage evidence, the four repaired source dates and the idempotency
mechanics are documented in the scraper repository's `docs/CANONICAL_SCHEMA.md`.
This repository's `docs/STATUS.md` records what was selected and excluded and why.

> `research/data/canonical_nse_prices.parquet` is **sign-corrupted** (its cleaning
> stripped every `-`, flipping 91,276 negative changes) and is no longer a data source.

## Why Supabase is no longer used

`nse-be` previously read a Supabase `stockanalysis_stocks` table. That path was dead:

- the scraper now runs with `DB_BACKEND=sqlite`;
- `reports/local_fallback/` holds a failed-write file for **every day from 2026-07-26 to
  2026-09-06**, and those files are only written when a database write throws.

Nothing had successfully written to that table since July. It is also why weekly and
monthly reports rendered `0.00%`: those windows need ≥5 and ≥22 observations per ticker
and the Supabase `price_history` was empty. The scraper's SQLite copy carries 29–32.

The Supabase adapter (`sources/supabase.py`) is kept and registered so the connectors
API can still describe and test a Supabase link, and so restoring it later is a registry
change rather than a rewrite.

---

## Building on this

This integration deliberately stops at *making the data available*. Market analysis,
technical indicators, fundamental analysis, agents, AI research and signals all consume
`MarketDataSource` — they do not need to know it is SQLite, and swapping the source will
not require touching them.

```text
NSE Scraped Data
       │
       ├── Market analysis
       ├── Technical indicators
       ├── Fundamental analysis
       ├── Agent analysis
       ├── AI research
       ├── Signals
       └── Reports
```

## Known limitations

- **`stock_data` is stale.** `afx_scraper` scraped 0 items on its last run and that table
  has not moved since 2026-08-18. Read for completeness; not used for analytics.
- **Same filesystem.** `nse-be` reads the scraper's file directly, so both must see the
  same path — hence the setting and the Docker mount.
- **History depth varies.** 56 of 64 tickers carry the ≥5 observations weekly needs and
  55 carry the ≥22 monthly needs. The rest are reported as `N/A`, never as `0.00%`.
