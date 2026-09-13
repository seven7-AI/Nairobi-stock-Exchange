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


---

## Visualizations — switched to matplotlib PNG  ✅ 2026-09-13

The plotly HTML charts (102 × ~200 KB + a 4.2 MB `plotly.min.js`) are replaced by static
matplotlib PNGs at 140 dpi, ~100–150 KB each, no JavaScript. They render inline on GitHub
and in any viewer; interactivity (hover/zoom) is dropped by choice. `plotly` is removed
from the dependencies; `matplotlib` was already one.

Nothing about the data or its honesty rules changed — `growth_series.py` is untouched.
The renderer draws the same things: a `NaN` breaks the line at each gap (matplotlib never
draws across it), `axvspan` shades the gap with "no data · N days", `axvline` marks each
suspected corporate action with its ratio and "unadjusted", first/last/high/low carry
their dates, and lineage (`traded as BBK → ABSA`) sits in the subtitle. The figure is
closed after rendering so `--all` does not accumulate 102 open figures.

`GET /api/v1/market-data/{ticker}/growth` now returns `image/png`. CLI unchanged.
Tests updated (NaN break + one span patch; one dashed line per corporate action; PNG
magic bytes and no leaked figures; API `image/png`). Reviewed `KCB.png` visually.

---

# Quantitative research engine

Tracking epic: [#24](https://github.com/seven7-AI/Nairobi-stock-Exchange/issues/24). One
issue per component, one branch per issue, local gate only. Decisions taken with the
user before the first line was written:

- **Fundamentals** are crawled from stockanalysis.com statement pages into append-only,
  point-in-time tables in the scraper (`nse-stock-scraper#2`).
- **Derived analytics** live in an nse-be-owned SQLite file with its own Alembic chain;
  the scraper database stays the read-only raw source of truth.
- **Jobs** run from cron + `nse-analysis analytics ...` chained after the 09:00 scrape.
- The **2025-01 → 2026-07 price gap** is missing data, flagged, never filled.

## #2 Analytics store  ✅ 2026-09-13

`data/nse_analytics.sqlite3` (gitignored; `Settings.analytics_db_path`, env
`ANALYTICS_DB_PATH`) holds every derived result. It is a second SQLAlchemy metadata
(`AnalyticsBase`, `app/web/db/analytics/`) and a second Alembic chain
(`app/alembic_analytics/`, `uv run alembic -n analytics ...`, batch mode for SQLite),
deliberately disjoint from the Postgres platform chain. WAL + `foreign_keys=ON` on every
connection.

First revision `20260913_0001`: `job_runs` (job state, watermark, counts, error, details),
`calc_versions` (name + sha256 of the canonical config JSON, unique — every later table
points here so a number can always be tied to the configuration that produced it),
`model_registry` (name/version/kind/status, features, params, training and backtest
periods, performance).

CLI: `nse-analysis analytics upgrade` (idempotent; creates or migrates) and
`analytics status` (revision vs head, row counts; exit 1 when behind). `make
migrate-analytics`, `make migration-analytics M="..."`. Pre-push gained a second drift
probe that migrates a throwaway file and autogenerates against it.

Tests (`app/tests/unit/test_analytics_store.py`, 13): real migrations on a temp file,
idempotent upgrade, downgrade→upgrade round trip, in-process autogenerate diff is empty,
pragmas, status without side effects, JSON/date round trips, unique constraints,
rollback on error, plain-sqlite readability, CLI upgrade/status.

CodeGraph: `get_settings` has 26 callers — the new field has a default so none change;
`Base`/`get_sync_session_factory` (13/11 callers) untouched — the analytics base is a
separate class so no Postgres model can accidentally land in the SQLite chain.

## #3 Measure type, provenance, point-in-time fundamentals read path  ✅ 2026-09-13

Depends on `nse-stock-scraper#2` (merged as its PR #3): the scraper now appends
`financial_statements` (10,765 rows for KCB/SCOM/KEGN/EQTY after the first live run;
8 rotating tickers a day from tomorrow) and `fundamental_snapshots`.

- `services/analytics/measure.py` — `Measure(value, status, reason, provenance)` with
  statuses `known · zero · missing · unavailable · not_applicable · not_meaningful`;
  `safe_div` (negative/zero denominators → not meaningful), `pct_change`, `cagr`, all
  propagating the first unusable input with its reason. `Provenance` points at table
  rows or ranges.
- `services/analytics/config.py` — `AnalyticsConfig` (frozen pydantic; publication
  lags 90/60 d, gap threshold 14 d, risk-free 12 % *to be reviewed*, benchmark
  `^NASI`), sha256 `config_hash()`, `register_calc_version()` get-or-create on
  `(name, hash)`.
- `NseScraperSource` — `fetch_financial_statements(first_seen_before=…)`,
  `fetch_fundamental_snapshots(end=…)`, `fetch_observations_bulk(tickers)`,
  `has_financial_statements()`; all `mode=ro`.
- `services/analytics/fundamentals/statements.py` — availability rule (live capture →
  first-seen day; backfilled initial capture → `period_end + lag`, flagged as assumed;
  restatements never backdated), `point_in_time(rows, as_of)`, `line_item_series`,
  `latest_line_item`, unit scaling, `-` → MISSING.
- Real-data fixture: `scripts/build_test_fixture.py` slices the live DB (KCB, EQTY,
  SCOM, KEGN, ABSA, NCBA, KENO delisted 2019, ACCS delisted 2012, KPC/SKL thin,
  `^NASI`, `^N20I`; 39,647 observations, 10,765 statement rows) into
  `app/tests/fixtures/nse_fixture.sqlite3.gz` (2.4 MB) with a manifest; `conftest`
  fixtures `fixture_source` (always) and `live_source` (`@pytest.mark.realdata`, skips
  when the DB is absent).

Tests: 46 new (measure 20, config 5, read path + PIT 21 incl. 1 realdata) — e.g. FY2021
KCB is visible from 2022-03-31 not before, the `Current` ratios column keeps its real
capture date, a restatement captured 2026-11-01 is invisible on 2026-10-31, KCB FY2025
revenue scales to 173,395,000,000 KES, a `-` cell is MISSING.

CodeGraph: `NseScraperSource` has 28 callers; only methods were added, no signature
changed. `fetch_observations` (4 callers, `stock_growth.py`) untouched — the bulk
variant sits beside it.

## #4 Classification layer — point-in-time industry and sector  ✅ 2026-09-13

`classifications` (analytics store, Alembic `20260913_0002`): one row per instrument
per validity range — `sector_code` (normalised taxonomy: banking, energy, telecommunication
…), the official `sector_label` as printed at the time, `industry` (stockanalysis
profile, e.g. "Commercial Banks"), `valid_from`/`valid_to`, `source`, `evidence`.

**Sources, in order of authority**

1. The five `NSE_DATA/NSE_data_stock_market_sectors_*.csv` files (2013, 2020, 2021,
   2022, 2023/24) read by `classification/sector_files.py`. Two defects repaired with
   the repair recorded on every affected row: the 2023/24 file's *section-header* row
   (`Construction and Allied,Energy and Petroleum,`) — KEGN, KPLC, KPLC-P4/P7, TOTL,
   UMME are Energy and Petroleum, not Construction; and the 2013 file labelling
   indices with their own code. "Telecommunication and Technology" → "Telecommunication"
   is a spelling change, one code. The 2013 membership is carried back to each
   instrument's first observation (the assumption is written on the row).
2. `CURATED` — the **16 instruments no sector file lists** (contrary to the earlier
   note in this file, they are in none of the five): ten delisted before 2013 (ACCS,
   BAUM, BERG, CITY, CMC, ICDC, MASH, PAFR, REA, UTK) and six listed after the 2023/24
   file (KPC, FMLY, AMAC, SKL, TRFC, ALP), each with its evidence.
3. The scraper's instrument master — rights issues inherit their parent's sector
   (`CFC-R`, `KCB-R` …), `^NBDI` by instrument type.

Scraper-era listings with no `first_seen_date` start at their first observation (KPC,
ALP … 2026-07-26), never at 2007. Lineage resolves through `instrument_aliases`
(`BBK` rows become `ABSA` stints).

**Live**: `nse-analysis analytics classify` → **102 rows for 102 instruments, 0
unclassified**: banking 19, commercial services 17, agricultural 9, energy 9, indices 9,
manufacturing 9, investment 8, insurance 7, construction 5, automobiles 3, REIT 3,
telecommunication 2, ETF 1, investment services 1; industry filled for 61 (the
stockanalysis-covered universe). Sources: sector files 75, curated 16, instrument master
11. Rebuild is a wholesale replace inside one transaction — idempotent by construction.

`ClassificationIndex.sector_for(ticker, as_of)` / `peers_for` / `members` are the
point-in-time lookups the factor and valuation engines will use. 18 tests: defect
repair on the real files, taxonomy refusal of unknown labels, lineage, curated coverage,
industry from the profile snapshot, a synthetic reclassification producing two ranges
that are invisible before they happened, persistence idempotency, CLI.
