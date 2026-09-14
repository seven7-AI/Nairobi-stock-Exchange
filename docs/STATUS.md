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

## #5 Data-quality framework  ✅ 2026-09-13

`data_quality_findings` (Alembic `20260913_0003`): a finding is identified by
`(check, ticker, trade_date, sha256(detail))`; the first run that sees it creates the
row, later runs move `last_seen_at`, the first run that no longer sees it sets
`resolved_at`. Nothing is deleted, so the table is today's list *and* the history.
`nse-analysis analytics dq [--fail-on error|warning|never]` runs the checks, records a
`job_runs` row, writes `reports/data_quality/<date>.md` + `latest.md` (gitignored) and
exits 1 on errors by default.

Checks (`services/analytics/quality/checks.py`, pure functions, thresholds in
`AnalyticsConfig.quality`): `duplicate_observations`, `impossible_values` (non-positive
close, low > high, close outside the day's range, 52-week low > high, negative volume),
`price_jumps` (> 50 % vs the previous observation, **not** across a data gap; INFO when
the row is flagged as a corporate action, WARNING otherwise), `missing_periods` (> 14
days), `universe_gap` (a gap shared by ≥ ⅓ of the universe collapses into one ERROR),
`zero_volume_streaks` (≥ 20 days), `thin_history` (< 20 observations), `stale_data`,
`broken_scrape` (the scraper's own quality gate), `unclassified_instruments`,
`balance_sheet_consistency` (assets vs liabilities + equity, 2 %),
`missing_fundamentals`.

**Live run** (102 instruments): 332 findings — 1 error, 217 warnings, 114 info.
Genuine defects it surfaced, now on record:

| Finding | What it is |
|---|---|
| `universe_gap` 57 instruments, 2024-12-31 → 2026-07-26 | the known 2025 hole, as one ERROR |
| `impossible_values` × 9 — BAMB/KCB 2022-07-26; BRIT/CIC/COOP/NCBA/SCBK 2022-12-13; EVRD 2018-11-28 | two archive dates where the close sits outside a zero-width day range: the source's day low/high on those days are wrong, not the close |
| `price_jumps` ^N20I 2024-11-26 +900 % then −90 % | a decimal slip in the NSE 20 archive (18,845 between 1,884 and 1,881) |
| `price_jumps` DTK-R 2012-07-23/24 (48.5 → 2.3 → 25.0) | a decimal slip on a rights issue |
| `price_jumps` KCB 2007-04-03, EQTY 2007-04-10 & 2009-03-26, ABSA 2011-05-31, KENO 2010-06-02, NCBA 2007-12-07, ARM 2013-01-02 … | unflagged share splits — the archive never marked them; the growth diagrams already draw them as "suspected corporate action" and the returns engine will treat them the same way |
| `missing_fundamentals` × 59 | statements captured for 4 tickers so far; the rotation covers the rest over the coming week |
| `zero_volume_streaks` × 45, `thin_history` × 10 | the illiquid tail of the market, as expected |

Tests (`test_data_quality.py`, 17 + 1 realdata): each check on injected rows, the
open → still-open → resolved lifecycle (a resolved finding that reappears is a new
row), the runner on the real-data fixture asserting **its** genuine defects (KCB
2022-07-26, NCBA 2022-12-13, the ^N20I slip) and nothing spurious, injected defects
(×10 slip, zero close, doubled balance-sheet assets) found and then resolved when the
data is fixed with zero duplicate rows, CLI exit codes, and the live database.

Also in this issue: `UTCDateTime` on every analytics timestamp column so SQLite hands
back aware UTC datetimes.

## #6 Trading calendar, PriceSeries and the returns engine  ✅ 2026-09-14

First Phase-2 engine. `services/analytics/series.py` turns an instrument's rows into a
`PriceSeries` (closes + volumes on a `DatetimeIndex`, **segments** split at every break
longer than `gap_threshold_days`, source-ticker lineage, flagged rows, provenance) with
`as_of(day)` as the single point-in-time operation. `services/analytics/returns/engine.py`
computes 1D · 1W · 1M · 3M · 6M · 12M · 24M · 36M · YTD · YoY trailing returns, plus
cumulative and rolling series, on the instrument's own observations:

- the end is the last observation on/before `as_of`; older than the threshold →
  `unavailable` (an `as_of` inside the 2025 hole never reports December-2024 numbers);
- the start is the last observation on/before `end − window` (1D: the previous one);
  a start more than the threshold before its target, or in another segment, is
  `unavailable` **naming the gap** — windows are never bridged across the hole;
- new listings (no start), delistings (stale end) and thin listings each get the reason;
- prices are unadjusted; a window containing a flagged observation is marked
  `contains_flagged` so the factor engine can discount it.

`market_metrics` (Alembic `20260913_0004`): one row per
`(ticker, as_of_date, metric, calc_version_id)` with `value`, `status`, `reason`,
`window_start/end`, `contains_flagged`, `provenance`; upsert on the natural key so a
re-run rewrites identical rows. `nse-analysis analytics compute returns [--as-of] [--ticker]`
records a `job_runs` row with per-metric known counts.

**Live** (`--as-of 2024-12-31`, 102 instruments, 1,020 rows, 0 skipped): 12M known for
60, zero for 12 (unchanged closes on thin names), unavailable for 30 (delisted before
2024, or listed after). Top 2024 12M returns: PORT +282 %, ORCH +259 %, KPLC +239 %,
IMH +107 %; worst SGL −35 %, KNRE −32 %, NMG −28 %.

Tests (`test_returns_engine.py`, 24 + 1 realdata): series ordering/dedupe/non-positive
closes, gaps and segments, `as_of` truncation, every window incl. weekend `as_of`,
insufficient history, gap-crossing and in-gap `as_of`, delisting, thin listing,
flagged window, YTD, tiny prices, cumulative/rolling; **hand-computed KCB** at
2019-12-31 (12M 54.0/37.45−1 = 44.19 %, 6M vs 2019-06-28, 3M vs 2019-09-30, 1W vs
2019-12-24, 1D vs 2019-12-30, YTD); KCB windows crossing the 2025 gap unavailable;
the 2007 split visible; a **look-ahead test** (appending or tampering rows after T
leaves every metric byte-identical); the compute job idempotent (upsert, not append)
with unavailable rows carrying reasons; CLI.

## #7 Momentum engine  ✅ 2026-09-14

`services/analytics/momentum/engine.py`, on the same `PriceSeries` and window rules as
the returns engine: `momentum_{1m,3m,6m,12m,24m}`, `momentum_12m_1m` (12-1, skipping
the reversal month), `relative_{1m,3m,6m,12m}_vs_market` (minus `^NASI`, fallback
`^N20I`), `relative_{…}_vs_sector` (minus the equal-weighted mean of the point-in-time
sector peers from `classifications`; needs ≥ `min_peers` = 2 known), `ma_50`/`ma_200`
over the last N observations **inside one segment**, `price_to_ma_*`,
`ma_short_over_long`, `trend_strength_6m` (R² of log-price on time, signed by the
slope), `momentum_persistence_12m` (share of positive month-ends), and
`distance_from_52w_{high,low}`. Parameters in `AnalyticsConfig.momentum`.
`nse-analysis analytics compute momentum` writes to `market_metrics`.

**Live** (`--as-of 2024-12-31`): 102 instruments, 2,346 rows. `^NASI` returned
+34.1 % in 2024; strongest 12M relative to it: PORT +248 pp, ORCH +225 pp, KPLC +205 pp;
cleanest 6M uptrends SCBK 0.91, KPLC 0.86, GLD 0.84. Sector-relative known for 67
(the rest lack peers or history); market-relative for 72.

Tests (19): synthetic constant-growth series (12-1 equals 12M by construction),
benchmark subtraction and the missing-benchmark reason, equal-weighted peer mean with
the minimum-peer rule, the stock's own blocker winning, MAs and price-to-MA, an MA that
would span a gap refused, signed R² (up ≈ +1, down ≈ −1, flat = zero, zig-zag ≈ 0),
persistence, 52-week range; **hand-computed KCB at 2019-12-31**: relative 12M vs
`^NASI` = (54.0/37.45−1) − (166.41/140.43−1), 6M likewise, 12-1 = 50.0/39.25−1 with the
start on 2018-11-29, at its 52-week high (54.0), sector-relative vs EQTY/ABSA/NCBA; the
post-gap `as_of` keeps only short windows and reports `^NASI` ending in 2024;
look-ahead; the job resolves peers through the classification index and rewrites rows in
place; CLI.

## #8 Risk engine  ✅ 2026-09-14

`services/analytics/risk/engine.py`, on trailing in-segment windows: `volatility_daily`
/ `_weekly` / `_monthly` (sample std of daily, week-end and month-end returns over 12M),
`volatility_annualised` (daily × √252), `volatility_rolling_3m`; `drawdown_current`,
`max_drawdown_36m` (peak and trough dates as the window bounds; falls back to the whole
current segment when 36M of history is not there), `drawdown_recovery_days`
(`unavailable` while not recovered, `not_applicable` when there was no drawdown);
`beta_12m` / `beta_36m` and `correlation_market_12m` on daily returns inner-joined on
date with `^NASI` (≥ 100 pairs), `correlation_sector_12m` against the equal-weighted
daily return of the sector peers; `sharpe_12m` / `sortino_12m` on the configured
risk-free rate (12 %, `AnalyticsConfig.market.risk_free_rate`, versioned — a changed
rate is a new `calc_version` and the old rows stay). The stock-to-stock matrix goes to
`correlations` (Alembic `20260914_0005`, upper triangle per as-of/window/version).
`nse-analysis analytics compute risk [--no-matrix]`.

**Live** (`--as-of 2024-12-31`): 96 instruments (6 listed after that date), 3,297
metric rows + 1,953 correlation pairs. Betas vs `^NASI`: SCOM 1.76, IMH 1.03; deepest
36M drawdowns TCL −78 % (2022-01 → 2024-08), CGEN −75 %; best Sharpe ORCH 3.27. The
`^N20I` −90 % "drawdown" (2024-11-26 → 12-05) and 9.1 annualised volatility are the
decimal-slip defect `analytics dq` already reports — the engine computes what the
archive says; the repair belongs at the source (noted for the hardening issue).

Tests (19): volatility vs numpy with annualisation, constant price → zero volatility and
not-meaningful Sharpe, minimum observations, drawdown peak/trough/recovery on a
constructed path and an unrecovered one, short-history fallback, beta of a 2× copy = 2
and of an inverse = −1 (correlation ±1), benchmark missing/short/flat, sector
correlation of affine copies = 1 and the minimum-peer rule, correlation matrix upper
triangle with ±1 checks and the observation minimum, Sharpe against a hand-formula and a
higher risk-free rate lowering it, always-rising series has no downside deviation;
**hand-computed KCB 2019**: daily vol 0.01484, annualised 0.2355, beta 0.639,
correlation 0.380 vs `^NASI`; `^NASI` 2008-06-09 → 2009-03-09 drawdown −56.27 %;
post-gap `as_of` unavailable naming the gap; look-ahead; the job writes metrics and the
matrix idempotently; a changed risk-free rate keeps both versions; CLI.

## #9 Liquidity engine and liquidity score  ✅ 2026-09-14

`services/analytics/liquidity/engine.py`, over the 6M in-segment window:
`avg_daily_volume`, `avg_daily_turnover` (close × volume, KES), `trading_frequency`
(observations / business days), `zero_volume_days`, `zero_volume_share`, `volume_cv`,
`turnover_cv`, `market_cap` (latest `fundamental_snapshots` overview on/before the
date — from 2026-09-13 only), `free_float` (`unavailable`: no source). A volume that is
not reported is **not** zero: fewer than 20 reported volumes in the window →
`unavailable` with the count, which is the scraper era for all but the rotating
enrichment slice.

`liquidity_score` (0–100) is cross-sectional: percentile ranks (ties take the top rank,
so every stock trading daily is at the top for frequency) of turnover 50 %, frequency
20 %, non-zero-volume share 20 %, steadiness 10 % (`AnalyticsConfig.liquidity`), mapped
to Highly liquid ≥ 80 / Liquid ≥ 60 / Moderately liquid ≥ 40 / Illiquid ≥ 20 / Very
illiquid (`liquidity_bucket` stores 5…1 with the label as the reason). Instruments with
no volume data get `unavailable`, never a low score. `nse-analysis analytics compute
liquidity`.

**Live** (`--as-of 2024-12-31`): 102 instruments, 1,122 rows; 54 scored (the rest
have no volume in the window — indices, delisted, or the archive's sparse-volume tail):
SCOM 99.3, KCB 95.9, EQTY 94.4, COOP 91.3, KPLC 90.9, EABL 90.2 (16 Highly liquid, 24
Liquid, 14 Moderately liquid); thinnest scored XPRS 43.3, OCH 45.9.

Tests (14): steady stock, missing volume unavailable (not zero) with the count, zero
days and thin trading frequency, gap-crossing window, point-in-time market cap,
cross-sectional ranking with the silent instrument unavailable, bucket bounds
(config), weights and window as configuration; **hand-checked KCB / SCOM H2-2024**
(ADV 920,560 / 7,109,197 shares; KCB turnover KES 32.0 m; no zero days), the scraper
era (prices but no volume; the 6M window crossing the gap), KCB market cap from the
2026-09-13 snapshot (KES 302.07 bn), look-ahead, the job scoring the universe with SCOM
≥ KCB and Highly liquid, CLI.

## #10 Fundamental quality and growth engine  ✅ 2026-09-14

`services/analytics/fundamentals/engine.py`, point-in-time from the statements known
on the date (`statements.py` availability rules), by **concept** rather than label
(banks print `diluted_shares_outstanding`, industrials `shares_outstanding_diluted`;
`net_income_to_common` before `net_income`; a label present but all `-` falls through
to the next):

- quality for the latest fiscal year — `roe` and `roa` on the average of the year's and
  the prior year's balance sheet, `net_margin`, `gross_margin`, `operating_margin`,
  `ebitda_margin`, `fcf`, `ocf`, `fcf_margin`, `total_debt`, `net_debt`,
  `debt_to_equity`, `interest_coverage` (operating income over |interest expense|),
  `asset_turnover`; for banks and insurers the gross/operating/EBITDA margins, interest
  coverage and asset turnover are `not_applicable`; negative earnings and negative FCF
  stay negative; negative equity makes leverage `not_meaningful`;
- trends — `roe_trend`, `roa_trend`, `net_margin_trend`, `operating_margin_trend`,
  `gross_margin_trend`, `fcf_trend`, `debt_to_equity_trend` (rising leverage is
  deteriorating): least-squares slope over ≥ 3 fiscal years relative to the mean level,
  ±5 % per year is stable; stored as +1 / 0 / −1 with the label and slope in the reason;
- growth — `revenue/eps/net_income/fcf/dividend_growth_1y`, `*_cagr_3y`, `*_cagr_5y`
  (`unavailable` until six fiscal years exist; `not_meaningful` across a sign change);
- sector-relative growth (`*_vs_sector`, own minus the sector median, ≥ 3 peers).

`fundamental_metrics` (Alembic `20260914_0006`) carries the fiscal period each value
describes. `nse-analysis analytics compute fundamentals`.

**Live** (`--as-of 2026-09-13`, statements now captured for 10 tickers by the
scraper's rotation): ROE SCOM 50.5 %, BAT 33.6 %, EQTY 26.5 %, KCB 22.0 %, SBIC 17.6 %,
BRIT 17.2 %, DTK 10.3 %, KEGN 3.6 %; ROE trends BRIT/KEGN/SBIC/DTK improving, KCB/EQTY/SCOM
stable, BAT deteriorating; 3-y revenue CAGR BRIT 28 %, EQTY 16 %, KCB 14 %, BAT −5 %.
Sector-relative growth known for the 4 banks.

Tests (19): hand-computed quality metrics on a synthetic industrial, bank rules,
negative earnings / negative FCF / negative equity / missing items, `-` cells and label
fall-through, no statements at all, trend labels and the minimum-period rule, growing
revenue with deteriorating margins, hand-computed growth and CAGRs (5-y unavailable with
the reason), growth edge cases (zero base, sign change, single year), sector-relative
median; point-in-time (a live capture is visible from its capture day, a backfilled one
from period end + 90 d — leap year included), a restatement invisible until captured;
**real KCB FY2025**: ROE 66,819 / avg(331,466, 274,888) = 22.0 % (the site's 20.9 %
averages quarterly equity), ROA within 0.2 pp of the site's 3.17 %, net margin, FCF
−130,880 m kept negative, D/E, revenue growth 5.6 %, EPS growth, 3-y CAGR, dividend
growth 5.0/3.0; the FY2023 dividend gap is `missing`, not zero; **real SCOM FY2026**
industrial margins and interest coverage; an `as_of` of 2023-03-30 sees FY2021 only;
the job with sector-relative growth; CLI.
