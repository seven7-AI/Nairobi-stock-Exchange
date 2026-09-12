# STATUS — historical NSE data unification (this repository's side)

The canonical ticker+date timeline lives in the **scraper's** database
(`~/nse-stock-scraper`, see its `docs/STATUS.md` and `docs/CANONICAL_SCHEMA.md`). This
file records what was inspected here, what was selected, and what changed here.
Updated 2026-09-12.

## What was inspected

- The 18 yearly price files and 5 sector files under `NSE_DATA/`, row by row — headers,
  date layouts, placeholders, sign, duplicates, index/rights/preference codes.
- `research/01_data_foundation.ipynb` and the parquet artifacts it produced.
- The scraper repository's storage, pipelines, Alembic setup and daily job, through
  CodeGraph, before any decision.

## Historical datasets selected

`NSE_data_all_stocks_2007.csv` … `2024.csv` — the primary historical source.
285,889 rows, 103 source codes, two date layouts, four header variants.

## How the sector files were evaluated

`NSE_data_stock_market_sectors_{2013,2020,2021,2022,2023_2024}.csv` are pure
`SECTOR, CODE, NAME` maps with **no price data**, so they cannot overlap with the price
history and were used **only** to classify instruments. They carry the official NSE
sector labels and agree with each other except for three defects, each corrected with
evidence:

| Defect | Evidence | Handling |
|---|---|---|
| `2023_2024` line 39: `Construction and Allied,Energy and Petroleum,` — a section header in the CODE column; KEGN, KPLC, KPLC-P4, KPLC-P7, TOTL, UMME inherit the wrong sector | 2022 file has them under Energy and Petroleum | row dropped, six stocks corrected |
| `Telecommunication and Technology` → `Telecommunication` | exchange rename in 2022 | normalised to the current label |
| 2013 index rows carry their own code as sector | `^NASI,^NASI,…` | normalised to `Indices` |

## Data-cleaning decisions

| Decision | Why |
|---|---|
| **`-` is missing only when it is the whole cell** | 91,276 `Change` cells are negative numbers; the notebook stripped every `-` and corrupted them |
| Ticker lineage resolved to the current code, original kept in `source_ticker` | eight aliases verified by date span with zero overlap; `CFCI→LBTY` and the scraper-side `HFCB→HFCK` found, `CFCI→CIC` rejected |
| Three 2009 dates and one 2017 date repaired | each misdated block sits exactly in the gap of a missing weekday; repairs are flagged and the raw date kept |
| 2017-03-24 second block quarantined, not repaired | no positional evidence for another date |
| Indices, rights and preference shares kept, typed | benchmarks are useful; excluded from equity aggregates by type |
| Unknown sector stays NULL | never guessed — 10 pre-2013 delisted companies and `^NBDI` |
| `change_pct` stored as given, never recomputed | the source's number is the fact; a consistency rate is *reported* |

## Intentionally excluded, and why

- **`research/data/canonical_nse_prices.parquet`** — sign-corrupted (above). The
  `backfill_price_bars_from_parquet` task that read it is now marked deprecated; the
  correct history is in the scraper database's `stock_observations`.
- **`research/data/ticker_master.parquet`** — derived by the same notebook; the instrument
  master is rebuilt from the sector files instead.
- **`CFCI → CIC`** as a lineage alias — overlapping spans prove two different companies.
- **`stock_data`** (scraper's AFX table) as a history source — stale since 2026-08-18.

## What was implemented here

- `NseScraperSource.fetch_observations(ticker, start, end)` — one instrument's full
  timeline, oldest first, JSON flags decoded, canonical ticker with `source_ticker`
  preserved. `fetch_instruments(sector=…)` for the master. `has_observations()` for a
  scraper database that predates the tables. Health reports the timeline's span.
- Five unit tests against a synthetic timeline database (28 in the module, up from 23).
- `docs/data-sources.md` gains the timeline section; `PROJECT_CONTEXT.md` marks the
  parquet path deprecated.

## Validation results (from the scraper repository's `reports/historical_validation.md`)

PASS — 28 checks, 0 failures, 13 informational. 285,819 archive rows + 63 scraper rows
for 2026-09-12 coexist; 0 duplicate `(ticker, trade_date)`; `close − previous == change`
for 100.00% of 179,040 rows; KCB reads 2007-01-02 → 2026-09-12 unbroken; all seven
spot checks match their CSV line byte-for-byte.


---

## Visualizations — stock-growth diagrams  ✅ 2026-09-12

**What.** `diagrams/stock-growth/<TICKER>.html`: one interactive plotly chart per
instrument, 2007 → latest scrape, plus `GET /api/v1/market-data/{ticker}/growth` serving
the same figure. `nse-analysis plot-stock KCB` / `--all` regenerate them.

**Where and why here.** nse-be is the analytics side and already reads the canonical
timeline read-only through `NseScraperSource.fetch_observations()`; the scraper only
produces data. Chart logic is a business service (`app/web/services/visualizations/`),
so the CLI and the API share it and future sector/market/comparison charts are siblings
of `stock_growth.py` writing to siblings of `diagrams/stock-growth/`.

**Data path.** `stock_observations` → `build_growth_series()` (pure) → `figure_for()` →
HTML. No second price source. New scraper rows are included on the next regeneration.

**Honesty rules baked in.**
- Gaps > 14 days break the line and are shaded; nothing is interpolated. The
  2025-01-01 → 2026-07-25 stretch is a gap for every instrument.
- Prices are unadjusted (the archive's `Adjust` column covers 37,513 of 285,819 rows —
  too sparse to build an adjusted series). Close-to-close steps > 2.5× are marked as
  suspected corporate actions instead: KCB 10:1 (2007-04-03), Barclays 4:1 (2011-05-31),
  Equity 2007 and 2009 — all real events, none smoothed.
- `traded as BBK → ABSA` appears in the subtitle where the archive used a retired code.

**Prerequisite done in the scraper repo.** The 1,907 real 2026 points that lived only in
`price_history` JSON were replayed into `stock_observations`, so the 2026 end of each
chart has 36 points rather than one (scraper `docs/STATUS.md`, phase 11).

**Why plotly, why one shared JS file.** Interactive hover/zoom was chosen over static
PNG. `plotly.min.js` (4.2 MB) is written once to `diagrams/assets/`; each chart
references it relatively and is ~200 KB, so the folder works offline and stays small.

**Tests.** 9 unit tests on the pure series/figure (gaps vs holidays, split detection,
lineage, empty/unusable rows, no inlined JS) and 3 API tests (200 HTML, 404, 403/401).
