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

## #11 Valuation metrics and dividend engine  ✅ 2026-09-14

`services/analytics/valuation_metrics/engine.py`, point-in-time: the last close on or
before the date × the latest fiscal-year figures known on it (TTM where the site
reports them):

- `market_cap` (price × diluted shares from the statement), `enterprise_value`
  (+ total debt − cash), `pe`, `pe_ttm`, `forward_pe` (`unavailable`: no estimates
  source), `pb`, `ps`, `ev_ebitda`, `ev_sales` (`not_applicable` for banks and
  insurers), `dividend_yield` / `dividend_yield_ttm`, `payout_ratio`, `fcf_yield`; a
  negative or zero denominator (loss-making EPS, negative EBITDA, negative equity) is
  `not_meaningful`, never a small multiple; a stale price (> 14 d) is `unavailable`;
- `pe_vs_history` / `pb_vs_history` against the median of the company's own
  fiscal-year multiples from the site's ratios page as known on the date (≥ 3 years);
- `*_vs_sector` / `*_vs_market` — own multiple over the median of peers with a
  positive multiple (≥ 3 peers), cross-sectional in the service;
- dividends — `dividend_years_paid`, `dividend_consistency`, `dividend_cut`,
  `fcf_dividend_coverage`, `dividend_class` (Reliable payer / Growing payer /
  High-yield / Potential dividend trap / Deteriorating / Non-payer as a code with the
  label in the reason). A missing dividend row is `missing`; only a reported zero is
  "paid nothing".

Rows go to `fundamental_metrics` next to #10's. `nse-analysis analytics compute
valuation-metrics`.

**Live** (`--as-of 2026-09-13`, 10 tickers with statements, 320 rows): P/E SCOM 14.7,
BAT 10.7, BRIT 9.6, SBIC 8.1, KEGN 7.0, DTK 5.5, EQTY 5.3, KCB 4.5 (94.0 / 20.8); P/B
SCOM 7.0 … KCB 0.91, KEGN 0.25; yields BAT 12.5 %, KEGN 8.2 %, SBIC 7.9 %, KCB 5.3 %;
dividend classes: DTK/EQTY/SBIC/SCOM Growing payer, BAT Potential dividend trap (payout
133 %), KEGN Potential dividend trap (yield 8.2 % with EPS falling), KCB Deteriorating
(paid 4 of 5 years — the FY2023 gap); BKG and SCBK `missing` — their captured statements
carry no EPS/DPS rows, so nothing is invented.

Tests (16): hand-computed multiples (P/E 120/10, P/B, P/S, EV/EBITDA, yield, payout, FCF
yield), market cap and EV from shares/debt/cash, negative denominators
`not_meaningful`, stale price `unavailable`, `vs_history` from the ratios page with the
minimum, `relative_to_group` median and minimum, reliable and growing payers, cut and
stopped dividends → Deteriorating, missing dividend row `missing` not zero, high yield
vs trap (payout > 100 % / falling EPS), FCF-coverage edge cases (nothing paid
`not_meaningful`, negative FCF stays negative), bank `not_applicable` rules, **real KCB**
(P/E 4.52 = 94.0 / 20.8, P/B 0.91 = 302.07 bn / 331.47 bn, yield 5.3 %, payout 24 %),
the job (cross-sectional medians), CLI.

## #12 Factor engine  ✅ 2026-09-14

`services/analytics/factors/engine.py` — cross-sectional factor scores from the metric
rows already stored for the date (`market_metrics` + `fundamental_metrics`, newest
computation wins). The universe is every instrument classified in an **operating
sector** on the date (indices, ETFs and REITs excluded). Per input: winsorise at the
5th/95th percentiles, z-score, flip the sign for "lower is better"; a factor's raw score
is the weight-averaged z of the inputs that are *known*, `coverage` is the share of
input weight known, and coverage below 50 % makes the factor `unavailable` rather than a
score built on one number. Percentile ranks (0–100) within industry, sector and market;
a group smaller than 3 yields no rank at that level.

Factor definitions live in `AnalyticsConfig.factors` (`FactorDefinition` /
`FactorInput(metric, source, direction, weight)`) and are part of the calc-version hash:

| factor | inputs (− = lower is better; ½ = half weight) |
|---|---|
| value | −pe, −pb, −ps½, −ev_ebitda½, fcf_yield½, dividend_yield½ |
| quality | roe, roa½, net_margin, operating_margin½, fcf_margin½, −debt_to_equity½, roe_trend½ |
| growth | revenue_growth_1y, eps_growth_1y, revenue_cagr_3y, eps_cagr_3y, fcf_growth_1y½ |
| momentum | momentum_12m_1m, momentum_6m½, relative_12m_vs_market, trend_strength_6m½, price_to_ma_200½, distance_from_52w_high½ |
| dividend | dividend_yield, dividend_consistency, dividend_cagr_3y½, fcf_dividend_coverage½, dividend_class½ |
| risk | −volatility_annualised, max_drawdown_36m (less negative is better), −beta_12m½, sharpe_12m |
| liquidity | liquidity_score, avg_daily_turnover½, trading_frequency½, −zero_volume_share½ |

`factor_scores` (Alembic `20260914_0007`) stores score, status, coverage, the three
percentiles, group sizes and the per-input breakdown (value, z, weight, status).
`nse-analysis analytics compute factors`.

**Live**: `--as-of 2024-12-31` — universe 85, 595 rows; momentum and risk known for 64,
liquidity 54, the fundamental factors for the 8 with statements known on the date;
momentum leaders ORCH, KPLC, IMH, PORT, KCB (P94, banking P92), SCBK, KEGN. `--as-of
2026-09-13` — universe 89, 623 rows; only value/quality/growth/dividend known (8/8/8/7):
every market-side input (12-1 momentum, 6M momentum, annualised volatility, liquidity
score) is `unavailable` across the 2025 gap or the seven-week scraper era, so the
market factors are honestly absent rather than computed on a stub.

Tests (9): winsorised z-scores (clipping, centring, < 3 values → 0, no dispersion → 0),
direction and weights (low P/E scores high), the coverage rule (33 % → `unavailable`
with the reason, a stricter minimum as configuration), group ranks and the minimum group
size, every factor reported for every ticker with group sizes; on the real fixture
(2024-12-31): the metric table only carries known values (delisted KENO excluded),
`compute_factors` universe = the eight operating-sector instruments listed on the date,
KCB momentum known with a banking percentile, KCB quality with no sector percentile
(only two banks have statements), one calc version, idempotent re-run, a changed factor
definition is a new calc version with both sets of rows kept, CLI.

## #13 Composite ranking, classification, value trap, compounder, explainability  ✅ 2026-09-14

`services/analytics/ranking/engine.py` over the stored factor scores and metric rows for
the date, `factor-model v1` (`AnalyticsConfig.ranking`, registered in `model_registry`
with its weights as `params`; the weights are part of the calc-version hash):

- `overall` (0–100) — weighted **market percentile** of the factors available for the
  stock, weights quality .25 / value .20 / growth .15 / momentum .15 / risk .10 /
  dividend .10 / liquidity .05 renormalised over what is available; below 50 % of the
  weight the stock is `unavailable` naming the missing factors. `confidence` = available
  weight share × mean input coverage;
- classification — Strong Candidate ≥ 80, Buy Candidate ≥ 65, Watch ≥ 50, Neutral ≥ 35,
  Weak ≥ 20, else Avoid; a liquidity score under 20, confidence under 0.5 or a HIGH
  value-trap risk caps the class at Watch (never lifts it), and the explanation says
  which gate bit;
- value-trap risk — "cheap" (P/E ≥ 25 % below the market median, P/B < 1, or yield ≥
  8 %) crossed with deterioration signals (revenue fell, EPS fell, ROE / margins
  deteriorating, leverage rising, negative FCF, 12-1 momentum < −10 %, liquidity score
  < 40, dividend cut): HIGH = cheap + ≥ 3 signals, MEDIUM = cheap + any signal or ≥ 4
  signals, LOW otherwise, `unavailable` when no multiple is known. Only *known*
  metrics can fire a signal;
- compounder score — share of applicable criteria met (revenue and EPS 3-y CAGR ≥ 8 %,
  revenue grew, ROE ≥ 15 %, ROA ≥ 5 % (1 % for financials), positive FCF, FCF margin ≥
  5 %, D/E ≤ 1 (not judged for financials), margins not deteriorating, dividend growing,
  positive momentum); `unavailable` when fewer than half can be judged;
- market / sector / industry ranks among the scored, and the explanation JSON
  (model, overall with provenance, confidence, every factor's percentiles / weight /
  coverage, positive and negative factors, the caps, value-trap signals, compounder
  criteria met, ranks, and a disclaimer that these are model outputs).

`stock_rankings` (Alembic `20260914_0008`) — one row per (ticker, date, model, calc
version). `nse-analysis analytics compute rankings`; `nse-analysis analytics rank
[--as-of] [--top N] [--ticker X]` prints the table or one explanation.

**Live** (`--as-of 2024-12-31`, universe 85): 8 scored — the eight with statements
known on the date; the other 77 have only momentum, risk and liquidity (30 % of the
weight) and are honestly `unavailable` until the scraper's statement rotation covers
them. SBIC 77.7 Buy Candidate (trap medium, compounder 71), BRIT 68.6 Buy, KEGN 67.0 Buy,
EQTY 62.8 Watch (trap HIGH), DTK 60.4 Watch, BAT 53.9 Watch (trap HIGH), SCOM 46.9
Neutral (compounder 88), KCB 45.8 Neutral — value trap HIGH on FY2023 statements: P/B
0.59 with EPS fell, ROE / margins deteriorating, leverage rising, negative FCF, dividend
cut (KCB did skip its FY2023 dividend). `--as-of 2026-09-13`: 8 scored on the fundamental
factors only (market factors `unavailable` across the gap), confidence 0.52–0.70: EQTY
78.7 Buy Candidate (compounder 100), BAT 63.4 Watch (trap HIGH), SCOM 61.1 Watch, BRIT
57.3 Watch, KEGN / DTK / SBIC / KCB Neutral.

Tests (10): renormalisation and confidence by hand, the minimum-weight rule with the
missing factors named, every band and the three caps (a cap only pulls down, and is
reported only when it bit), value trap HIGH with the exact signal list, MEDIUM / LOW /
`unavailable` / thin-liquidity cases, compounder for an industrial vs a bank
(applicability) and the minimum-known rule, `rank_universe` ranks per level and the full
explanation schema, custom weights = a new model hash; on the real fixture (2024-12-31)
the job scores the statement-bearing instruments, leaves delisted KENO `unavailable`
without a rank, orders market ranks by score, registers the model once, is idempotent;
CLI `compute rankings`, `rank --top`, `rank --ticker`, and the empty-store exit code.

## #14 Fair-value engine  ✅ 2026-09-14

`services/analytics/fair_value/engine.py` — independent per-share valuations by method,
applicability by sector, blended into a range. Every assumption used is written into the
row's `assumptions` JSON (`FairValueConfig`, part of the calc-version hash):

- cost of equity = risk-free 12 % + clamped `beta_12m` (0.5–1.5, default 1 when no beta)
  × equity risk premium 7 %; scenarios move the rate ±1 pp;
- **financials** (banking, insurance, investment services) — justified P/B
  `(ROE − g)/(r − g)` × book value per share with g = retention × ROE capped at 10 %
  (bear ROE ×0.85, bull ×1.10), and a Gordon dividend discount `DPS × (1+g)/(r − g)`
  with g from the dividend 3-y CAGR (else retention × ROE), capped at 10 %, ±2 pp;
- **other operating companies** — a 5-year FCF DCF (FCF = OCF − capex treated as cash
  flow to equity, base = mean of the last 3 fiscal years per share, growth = revenue
  3-y CAGR clamped to [−5 %, 15 %] ±5 pp, terminal 5 % (3 % / 6 %)), EV/EBITDA and P/E
  relative to the **sector median of peers with a positive multiple** (≥ 3 peers, else
  the market median), ±20 % on the multiple, net debt taken off the EV methods;
- indices, ETFs, REITs and unclassified instruments are `not_applicable`; negative
  earnings / EBITDA / FCF base / equity, ROE ≤ growth or rate ≤ growth are
  `not_meaningful`; missing inputs `unavailable` with the names;
- blend = equal-weight mean of the method base cases, range = mean of bears … mean of
  bulls, upside = intrinsic / price − 1, margin of safety = (intrinsic − price) /
  intrinsic;
- uncertainty (0–1) = 0.10 + 0.20 single method + 0.15 fewer than 3 fiscal years + 0.15
  deteriorating ROE / margins + 0.15 thin or unknown liquidity + 0.15 balance-sheet risk
  (D/E > 1.5 non-financial, or interest coverage < 2) + 0.05 no beta + 0.15 methods
  disagree (range > 50 % of the blend); at or above 0.6 the margin of safety is stored
  with `actionable = False` — it is a number, never a signal on its own.

`valuations` (Alembic `20260914_0009`): one row per method plus the `blended` row.
`nse-analysis analytics compute fair-value [--as-of] [--ticker …]`.

**Live** (10 tickers with statements): `--as-of 2024-12-31` — KCB (beta 0.92, r 18.4 %)
justified P/B 58.0 (ROE 16.9 % on FY2023, BVPS 70.8), DDM 26.1 (DPS 2.0, g 10 %), blend
42.1 vs price 41.6, upside +1 %, uncertainty 0.40 (deteriorating ROE, methods disagree);
SCOM DCF 6.7 (FCF/share 1.34, r 22.5 %) and P/E-relative 6.8 (market median 4.3×) vs
17.05 → −60 %; SBIC blend 266 vs 137 (+94 %, uncertainty 0.10); KEGN 12.0 vs 3.64.
`--as-of 2026-09-13` (no beta, no liquidity score across the gap → r 19 %, uncertainty
0.30–0.50): KCB justified P/B 138.0 (ROE 22.0 %, BVPS 103.2), DDM 61.1 (DPS 5.0), blend
99.6 vs 94.0 (+6 %); SCOM DCF 16.3 / P/E-rel 16.7 vs 35.2 (−53 %); EQTY 110.2 vs 102;
BAT 345.5 vs 560 (−38 %). EV/EBITDA is `unavailable` everywhere: fewer than three
non-financials carry an EBITDA multiple yet. BKG / SCBK `unavailable` — no book value,
ROE or DPS in their captured statements.

Tests (12): CAPM with clamped beta; justified P/B by hand (166.67 / 112.5 / 218.75,
sustainable growth, negative ROE / equity, missing inputs named, default retention, rate
≤ growth); DDM by hand (61.11 / 45.0 / 68.75, growth sources, no dividend); DCF by hand
(108.42 / 78.21 / 148.77, negative base, growth clamp); relative multiples by hand (EV
net of debt, P/E, loss-making, no peers, debt exceeding EV); blend, upside and margin;
`not_applicable` sectors, all-methods-unavailable with the reasons, no price; the
uncertainty ledger and the not-actionable flag; peer-median rule; on the real fixture
(2024-12-31) KCB gets P/B–ROE + DDM only and SCOM DCF + EV/EBITDA + P/E only, the
market-median fallback, idempotency; point-in-time at 2022-06-30 (FY2021 statements
visible, stored ROE absent → justified P/B says so, DDM alone → not actionable); CLI.

## #15 Forecast baselines, evaluation and walk-forward  ✅ 2026-09-14

`services/analytics/forecasting/engine.py` on **monthly log returns** of the segment
that contains the origin (never across a data gap; the origin month is the as-of
close), at 1 / 3 / 6 / 12 months:

- `naive` (zero drift, historical volatility), `mean` (60-month mean and volatility
  scaled by the horizon), `ewma` (half-life 12 months), `ar1` (AR(1) by least squares
  on the last 60 months — ARIMA(1,0,0) — with the exact closed-form mean and variance
  of the h-step sum; |φ| shrunk to 0.95). No `statsmodels`: four transparent
  estimators with hand-checkable maths, no opaque dependency;
- each forecast is a normal distribution in log space, stated as such: expected
  simple return, q05 / q25 / q50 / q75 / q95, P(positive), P(outperform `^NASI`) from
  the same model on the index and the monthly correlation, expected horizon
  volatility, and P(drawdown > 20 %) — the Brownian first-passage probability of losing
  more than the threshold from the origin at some point in the horizon;
- fewer than 36 contiguous monthly returns → `unavailable` with the count; a stale
  origin → `unavailable` with the age.

Evaluation writes a row **only once the horizon has elapsed in the data** and the
realised path neither crosses a gap nor ends more than 14 days short of the target:
error, directional hit, benchmark hit, inside the 90 % interval. `summarise` gives
MAE / RMSE / directional accuracy / benchmark hit rate / interval coverage per model
and horizon, stored on the `model_registry` rows (`performance`). Candidate models
(`ForecastConfig.candidate_models`, none registered) are admitted to `active` only
when they beat every baseline's MAE at every evaluated horizon and match the best
directional accuracy — the gate exists before any complex model does.

`forecasts` + `forecast_evaluations` (Alembic `20260914_0010`). CLI
`compute forecasts`, `forecast evaluate [--as-of]`, `forecast walk-forward --ticker …
--from --to` (monthly origins anchored to the start day, each seeing only its own past).

**Live** — `compute forecasts --as-of 2024-12-31`: universe 85, 1,360 rows, 228 known
per model (57 stocks with 36 contiguous months); KCB 12M: naive 0.0 / [−42 %, +72 %],
mean +0.2 %, AR(1) +3.8 % with P(positive) 0.47 and P(drawdown > 20 %) 0.58, EWMA +28 %
(the 2024 rally weighs on it). `--as-of 2026-09-13`: 1,424 rows, **0 known** — the
scraper era holds two monthly returns and the archive is 621 days stale, and every
row says which. **Walk-forward 2015-01-31 → 2024-12-31, KCB / EQTY / SCOM / KEGN /
ABSA**: 120 origins, 9,600 forecasts, 9,160 evaluated (440 pending — 2024 origins whose
horizons have not elapsed), none skipped:

| model | 1M MAE | 12M MAE | 12M dir. acc. | 12M bench. hit | 12M 90 % cov. |
|---|---|---|---|---|---|
| naive | 0.060 | 0.239 | 0.561 | 0.492 | 0.865 |
| mean | 0.060 | 0.246 | 0.528 | 0.600 | 0.861 |
| ewma | 0.061 | 0.276 | 0.467 | 0.575 | 0.837 |
| ar1 | 0.061 | 0.243 | 0.539 | 0.594 | 0.861 |

The honest reading: on NSE monthly returns the baselines are indistinguishable at
one month, the random walk has the lowest 12-month error, direction is close to a
coin flip, and the 90 % intervals hold 84–91 % of outcomes (slightly narrow at long
horizons). Nothing beats the naive baseline yet; that is what the registry says.

Tests (14): `shift_forward` clamps, naive / mean / EWMA by hand (lookback honoured),
AR(1) recovers c / φ / σ from a 4,000-point synthetic series and the 2-step moments by
hand, first-passage probability (zero-drift identity, limits, monotonicity, overflow-safe),
the distribution by hand (quantiles, P(positive), P(outperform) with correlation, no
dispersion → unavailable), evaluation math and the summary, the candidate gate; on the
real fixture: monthly series point-in-time and gap-aware (54.0 at 2019-12-31, stale
2025, two months after the gap → unavailable naming the count), KCB forecasts as of
2019-12-31 with ^NASI, realised-return rules (54.0 / 37.45 − 1, into the gap, across the
gap, not yet elapsed), compute-then-evaluate only when elapsed (1M / 3M at 2020-04-15,
all four by 2021-01-31, no duplicates, second run a no-op), quarterly walk-forward
2016–2019 with registry performance and per-origin provenance, an unregistered
candidate stays `unavailable` and `candidate`, CLI.

## #16 Monte Carlo, scenario and regime engines  ✅ 2026-09-15

**Monte Carlo** (`services/analytics/montecarlo/engine.py`) — seeded price paths from
the stock's own in-segment daily log returns over the 36M window ending at the origin
(≥ 250 returns): `bootstrap` (iid resampling) and `block_bootstrap` (21-day circular
blocks, keeps volatility clustering), 10,000 paths by default (`MonteCarloConfig`, seed
20260914 + horizon), horizons 21 / 63 / 126 / 252 days. Per run: terminal-return
quantiles q05–q95, mean, P(positive), P(return > −20 / −10 / 0 / +10 / +25 %),
P(max drawdown within the horizon > 10 / 20 / 30 %) measured on the paths, expected max
drawdown. The same inputs, config and seed reproduce the same numbers; nothing is
assumed about the distribution beyond "the sampled past". No `arch`/GARCH: the block
bootstrap is the volatility-clustering variant and is stated as such.

**Scenarios** (`services/analytics/scenarios/engine.py`) — `ScenarioConfig` states
bear / base / bull in full (NASI −25 % / +8 % / +25 %, multiples −20 / 0 / +15 %,
earnings −10 / +5 / +15 %, volatility ×1.5 / 1 / 0.8, a description). For each stock
the one-year implied price is computed on a **beta path** (price × (1 + β × market
move), β = stored `beta_12m` or the default 1, said which) and, when the stock has a
positive P/E on the date, a **fundamental path** (EPS × (1+g) × P/E × (1+Δmultiple));
the implied return is the mean of the paths used. The row stores the scenario's
assumptions verbatim next to the result. Arithmetic on stated assumptions, not a
forecast.

**Regime** (`services/analytics/regime/engine.py`) — on `^NASI` (falling back to
`^N20I` for dates NASI cannot cover; the row names its index): trend from the price
against its 200-day average and the 6-month return (Bull / Bear / Sideways, ±5 %
band), volatility from the 63-day annualised volatility against the median of the same
measure over the reference window (High-vol > 1.25×, Low-vol < 0.75×), risk-on /
risk-off / neutral, the evidence (every number) and the **proposed** factor-weight
overrides (`RegimeConfig.weight_overrides`, recorded for the backtester to evaluate —
applied nowhere by default). The reference window is the 36M span, or the whole segment
containing the date when the index is younger than that or the span would cross a data
gap; a stale end or a short post-gap segment yields no regime.

`simulations` (Monte Carlo rows and `method = "scenario"` rows) and `regimes` (Alembic
`20260914_0011`). CLI `compute montecarlo`, `compute scenarios`, `compute regime
[--as-of | --from --to]`.

**Live** — Monte Carlo `--as-of 2024-12-31`: 85 instruments, 680 rows, 248 known per
method (62 stocks with ≥ 250 in-window returns); KCB 1-year bootstrap: mean +1.8 %,
q05 −41 %, q95 +61 %, P(positive) 0.46, P(drawdown > 20 %) 0.79; block bootstrap wider
(q95 +82 %, P(dd > 20 %) 0.91). `--as-of 2026-09-13`: 712 rows, all `unavailable` (the
window crosses the 2025 gap). Scenarios 2024-12-31: KCB β 0.92 → bear 31.0 / base 44.2 /
bull 53.1 vs 41.6 (−26 % / +6 % / +28 %), SCOM β 1.76 → 10.9 / 18.7 / 23.6 vs 17.05;
2026-09-13: 180 rows on the default β (no stored beta across the gap). Regime, monthly
2008-01 → 2024-12 (204 dates): 2008-08 → 2009-05 **Bear**, High-vol from 2008-10 to
2009-01 (on `^N20I`, NASI starts 2008-02-25); 2020-03 → 2020-07 **Bear / High-vol /
Risk-off**; 2022-01 → 2022-08 `unavailable` (the NASI archive has no values between
2021-12-31 and 2022-06-02, then too short a segment); 2024-12-31 Bull / Normal /
Risk-on on the post-gap segment; 2026-09-13 `unavailable` (621-day-stale index). Bull
90 dates, Bear 60, Sideways 37, unavailable 17.

Tests (11): seeded and shaped paths (every step is a sampled return; unknown method
raises), block bootstrap keeps contiguous blocks, path statistics by hand, quantile
convergence in N (40k vs 500 paths, seed noise < 0.01, q05/q95 in the analytic
neighbourhood), KCB simulation (ordered quantiles, probability keys, monotone drawdown
probabilities, byte-identical re-run, month narrower than year, gap → unavailable,
N/seed as configuration), scenario arithmetic with verbatim assumptions (beta and
fundamental paths, default beta, loss-making, no price, custom scenario), regime weight
renormalisation, regime labels (young NASI → unavailable with the count, N20I 2008-12
Bear / High-vol, NASI 2020-04 Bear / High-vol / Risk-off with vol ratio > 1.25, 2017-12
Bull / Risk-on, the gap and the post-gap stale index → none, adaptive window, threshold
as configuration), the Monte Carlo and scenario jobs (index not a target, N from config,
idempotent, scenario rows with their assumptions), the regime job over 2008–2009 with
the N20I fallback and the 2025 gap, CLI.

## #17 Portfolio risk engine  ✅ 2026-09-15

`services/analytics/portfolio/engine.py` for a hypothetical weight set (validated:
positive, unique, summing to one within `PortfolioConfig.weight_tolerance`), from the
positions' own in-segment daily returns over the 36M window ending at the date, aligned
on common dates (≥ 100):

- historical expected return and volatility (annualised), Sharpe (risk-free 12 %), max
  drawdown of the constant-weight equity curve, beta to `^NASI`;
- the pairwise correlation matrix and the average pairwise correlation;
- concentration — HHI, effective positions (1 / HHI), top-3 weight; sector and
  industry exposure from the point-in-time classification;
- liquidity — days to liquidate each position at 20 % of its stored average daily
  turnover on a KES 10 m notional (`unavailable` per position without turnover data);
- warnings that say why: a single position over 25 %, a sector over 50 % ("N positions
  are one bet on the sector, not N independent ones"), HHI over 0.25, average
  correlation over 0.7, more than 10 days to liquidate, no turnover data.

Any position without enough history makes the return / risk block `unavailable`
naming it and the covered weight share; exposures, concentration and liquidity are
still reported for what is known. `portfolio_analyses` (Alembic `20260914_0012`) keeps
every analysis with its weights, metrics as Measure JSON, exposures, correlation,
liquidity, warnings. CLI `portfolio analyse --weights KCB=0.2,EQTY=0.3,... [--as-of]
[--name]`.

**Live** (`--as-of 2024-12-31`, 36M window): `core-five` (KCB 25 / EQTY 25 / SCOM 30 /
KEGN 10 / BAT 10): historical return −6.5 % a year, volatility 17.4 %, Sharpe −1.06 (at a
12 % risk-free), max drawdown −52 %, average pairwise correlation 0.09, HHI 0.235
(4.3 effective positions), 0.1–1.2 days to liquidate KES 10 m at 20 % of turnover,
warning "SCOM is 30 % (limit 25 %)"; **beta `unavailable`** — the `^NASI` archive has no
values between 2021-12-31 and 2022-06-02, so the 36M benchmark window crosses a gap and
the row says so. `all-banks` (KCB / EQTY / ABSA / NCBA / COOP at 20 % each): +11.3 %,
volatility 14.8 %, drawdown −25 %, correlation 0.15, and the warning "banking is 100 %
of the portfolio across 5 position(s) — one bet on the sector, not 5 independent ones".
`--as-of 2026-09-13`: every position "no series" for the window across the 2025 gap —
metrics `unavailable`, coverage 0 %, nothing invented.

Tests (7): the two-asset closed form (volatility, Sharpe, drawdown, correlation, HHI,
days to liquidate, the single-position warning), beta against a benchmark and a
single position, the all-bank portfolio (sector 100 %, five positions "one bet",
average correlation warning, no HHI warning at equal weights), partial coverage with
the missing names and observation counts, weight validation and parsing, the job on
real prices (KCB / EQTY / SCOM as of 2019-12-31 with turnover from the liquidity job,
a delisted KENO named as missing, invalid weights rejected), CLI.

## #18 Backtesting engine  ✅ 2026-09-15

`services/analytics/backtesting/engine.py` — a monthly-rebalanced top-N simulation
with the three classic mistakes handled explicitly:

- **look-ahead** — the signal is the live ranking pipeline recomputed in memory as of
  each rebalance date (`backtesting/signals.py`: returns, momentum, risk, liquidity,
  fundamentals, valuation multiples, factor scores, composite ranking on
  `PriceSeries.as_of(date)` slices and point-in-time statements; the fundamentals and
  valuation services were refactored into `fundamental_results` / `valuation_results`
  so the job and the backtester share one implementation). Nothing is read from stored
  metrics; the metric table per date is memoised so weight variants share it;
- **survivorship** — a stock is a candidate only while listed (first observation ≤ date
  ≤ last observation, last price within 14 days); a holding that delists is carried at
  its last price and sold at that price on the next rebalance (`action = "exit"`);
- **costs** — per-side fraction of traded value from `TransactionCosts` (brokerage
  1.5 %, levies 0.45 %, half-spread 0.5 %, slippage 0.25 % → 2.7 % per side, all
  configuration), buys scaled so costs come out of the cash deployed; a position is
  capped at 20 % × 5 days × the stock's average daily turnover on a KES 10 m book, the
  remainder stays in cash and the rebalance note says what was trimmed.

The trading calendar is the union of the universe's dates; a break longer than the gap
threshold ends a segment and the next one starts fresh — the 2025 gap is never
bridged, `linked` compounds segments and says it ignored the gap. Per segment and per
series (portfolio, `^NASI`, `^N20I`, and an equal-weight listed-universe run under the
same calendar with zero costs): total return, CAGR, annualised return and volatility,
Sharpe, Sortino, max drawdown, Calmar, monthly win rate, best / worst calendar year,
average monthly one-way turnover; alpha (annualised, with its t-statistic), beta,
information ratio and excess return against each benchmark from monthly returns (≥ 12).
`backtest_runs` / `backtest_results` / `backtest_positions` / `backtest_equity`
(Alembic `20260915_0013`). CLI `backtest run --from --to [--top-n] [--market-only]`,
`backtest compare`, `backtest weight-search --from --split --to --candidate name=…`
(in-sample pick by Sharpe, out-of-sample report, every run stored with its purpose).

`--market-only` is a documented **control** (momentum 0.5 / risk 0.3 / liquidity 0.2):
the model's fundamental factors only exist from 2022 (statements start FY2021), so
before that the default model has no stock above the 50 % weight floor and holds cash —
which the run reports rather than hides.

**Live** — `backtest run --from 2013-01-01 --to 2024-12-31`, top 10, 2.7 % per side,
KES 10 m, one segment (the union calendar has no gap before 2025), 144 rebalances;
benchmarks measured on their longest continuous stretch because both index archives
have a hole (N20I 2013-10/11 and both 2021-12-31 → 2022-06-02 — the rows say so):

| series | total | CAGR | vol | Sharpe | MDD | alpha vs NASI (t) | beta | turnover / m | costs |
|---|---|---|---|---|---|---|---|---|---|
| `factor-model-v1` | −18.2 % | −1.7 % | 4.8 % | −2.81 | −28.9 % | −11.7 % (−7.6) | 0.17 | 1.7 % | KES 1.12 m |
| `market-only` control | −56.6 % | −6.7 % | 12.0 % | −1.53 | −82.9 % | −13.9 % (−3.6) | 0.54 | 18.7 % | KES 10.9 m |
| equal-weight universe (no costs) | +4.3 % | +0.3 % | 5.5 % | −2.10 | −44.9 % | | | | 0 |
| `^NASI` (2013-01 → 2021-12 stretch) | +74.2 % | +6.3 % | 15.6 % | −0.29 | −36.8 % | | | | |
| `^N20I` (longest stretch) | −62.1 % | −11.2 % | 12.7 % | −1.83 | −68.7 % | | | | |

What the numbers say, honestly: the default model has nothing above the 50 % weight
floor until FY2021 statements become visible on 2022-03-31, so it holds cash for nine
years (return 0, Sharpe deeply negative against a 12 % risk-free) and then holds
10–13 names a year with 1.7 % monthly turnover; its first buys (BAT, DTK, EQTY, JUB at
10 %, CGEN trimmed to 0.9 % and HFCK to 2.7 % by the ADV cap) lose 18 % through 2024.
The market-only control trades from 2013 (758 buys, 942 sells, one delisting exit),
turns over 19 % a month and pays KES 10.9 m in costs on a KES 10 m book — more than
its −57 % result: at NSE retail costs a monthly momentum rotation is a cost machine,
which is the point of charging them. Neither beats holding NASI; the equal-weight
universe without costs is flat. The run took 1 h 37 min (default) and 55 min
(control) on the shared build box, 16–90 s per rebalance date depending on load.

Tests (13): calendar, month ends and gap segments; point-in-time listing; a single
stock's equity by hand with and without costs (first buy `notional / (1 + rate)`, no
cost while holding); switching positions pays both sides and reports one-way turnover
1.0; the ADV cap trims to `20 % × 5 d × turnover / equity` and leaves cash; a delisted
holding is carried at its frozen last price and exits at it; a gap splits segments
that each start fresh and link by compounding; metrics by hand (total return, CAGR,
zero-vol Sharpe not meaningful, best / worst year, alpha 0 / beta 1 against itself,
minimum months); **look-ahead mutation on the real fixture** — tripling every close
and volume after 2019-06-30 leaves every trade, target and equity value on or before
it byte-identical (and changes what follows); **survivorship on real data** — KENO,
delisted 2019-10-11, is held and exits at its last close on 2019-10-31; the stored run
(weights, costs, benchmarks, per-segment and linked results, positions with target
weights, equity with benchmark levels, the equal-weight companion); the weight search
(in-sample / out-of-sample runs by purpose, the ordering guard); CLI.

## #19 Job runner, cron and observability  ✅ 2026-09-15

`services/jobs/runner.py` — dependency-ordered pipelines of steps, each step calling the
same service the CLI command calls and recording a `job_runs` row `step:<name>` with a
**fingerprint** of its inputs: the source tables it reads (`NseScraperSource.
input_watermarks()` — `MAX(key):COUNT(*)` per table), the config hash, the date and the
fingerprints of the steps it depends on. A step whose fingerprint equals its last
succeeded run for the date is skipped ("inputs unchanged"); a failed step stops the
steps that depend on it, records the error, and the next run resumes from it; `--force`
re-runs everything and, because every service upserts on its natural key, yields the
same row counts. `services/jobs/pipelines.py` defines `daily` (data quality → returns →
momentum → risk → liquidity → valuation multiples → factors → rankings → fair value →
scenarios), `fundamentals` (fundamentals → multiples → factors → rankings → fair value;
skips itself unless statements changed) and `weekly` (regime → forecasts → forecast
evaluation, which always runs → Monte Carlo → factors → rankings).

`nse-analysis analytics jobs daily | fundamentals | weekly [--as-of] [--force]` and
`jobs status` (store revision, rows and last update per table, last run per job with
its counts, open data-quality findings, the model registry).
`scripts/install_analytics_cron.sh` appends (never rewrites) three entries after the
scraper's 09:00 Africa/Nairobi job — 09:40 daily, 10:10 fundamentals, Saturdays 10:30
weekly — running `scripts/run_analytics_jobs.sh`, which upgrades the store, runs the
pipeline and logs START / OK / FAILED to `reports/analytics-jobs.log`; `--print` shows
the entries, `--verify` exits 1 when one is missing. The same pipelines are Celery
tasks (`analytics_tasks.py`, queue `reports`), on beat only when `CELERY_BEAT_ENABLED`.
Analytics SQLite connections now wait up to 120 s for the writer (`BUSY_TIMEOUT_SECONDS`)
instead of failing "database is locked" while a job writes. `docs/quant-engine.md` is the
operator guide.

**Live** — cron installed (`crontab -l`: `CRON_TZ=Africa/Nairobi`, the scraper's `0 09`,
then `40 09 … daily`, `10 10 … fundamentals`, `30 10 * * 6 … weekly`; `--verify` passes;
the installed copy is `deployment/cron/analytics-cron.installed`) and the first runs
made through the cron runner on the shared build box (load 10–20):

| pipeline | wall | steps |
|---|---|---|
| `daily` (first) | 18 m 46 s | data quality 63 s (48 new info findings: `missing_fundamentals` for the instruments the statement rotation has not reached, `thin_history`), returns 77 s, momentum 89 s, **risk 407 s** (peer correlations for every sector), liquidity 81 s, valuation multiples 99 s, factors 3 s, rankings 1 s, fair value 112 s, scenarios 104 s — 7,458 rows |
| `fundamentals` | 6 m 12 s | fundamentals 66 s, multiples 88 s, factors, rankings, fair value 57 s |
| `weekly` | 6 m 18 s | regime 10 s, forecasts 50 s (1,424 rows), forecast evaluation 78 s (0 elapsed yet), Monte Carlo 138 s (712 rows), factors, rankings |
| `daily` (again) | 2 m 00 s | every step `skipped` — "inputs unchanged" (the second attempt recomputed the steps shared with the other pipelines; the fix — any prior succeeded run with the same fingerprint counts, not only the latest — is in this commit, and the third run skipped all ten) |

`jobs status` lists 26 tables with their row counts and last update, the last run of
every job and step (`pipeline:daily … succeeded`, `step:risk … succeeded`), 319 open
data-quality findings (1 error, 217 warning, 101 info) and the five registered models.
Every run is in `reports/analytics-jobs.log` as START / OK.

Tests (8): the daily pipeline on the real fixture twice — identical row counts, every
step skipped the second time with "inputs unchanged", `--force` reruns with the same
counts, the pipeline rows and the step rows carry the fingerprints; a new statement row
makes the `fundamentals` pipeline rerun; a simulated mid-run failure stops the
dependents, records the error, resumes without duplicates; `always_run` steps never
skip; `job_status` reports tables, jobs and models; CLI (`jobs fundamentals` twice,
`jobs status`, a failing pipeline exits 1); the Celery task runs the same pipeline
eagerly and skips on the second call; the cron script prints the chained entries.

## #20 Research diagrams  ✅ 2026-09-15

`app/web/services/visualizations/` gains one module per chart, each a pure `figure_for`
over a small dataclass plus a loader and a `write_*` (the `stock_growth.py` pattern), and
`diagrams.py` regenerates every folder. Price-based charts compute in-segment from the
canonical closes and draw a gap as a gap (a NaN breaks the line, a shaded span names the
hole); store-based charts read the analytics store, and a chart with nothing to show
says why instead of drawing an empty axis or a zero.

| folder | chart | source |
|---|---|---|
| `volatility/` | 63-day annualised volatility and drawdown from the running peak per instrument (window refills and peak resets after a gap) | prices |
| `momentum/` | stock and `^NASI` rebased to 100, relative strength | prices |
| `sector-analysis/` | median 12-month return per sector with member counts (indices / ETFs excluded) | `market_metrics` + classification |
| `factor-ranking/` | top 15 overall scores with classification, every factor's market percentile (a missing factor drawn empty) | `stock_rankings` |
| `valuation/` | fair-value range and intrinsic value relative to price, grey when not actionable | `valuations` |
| `forecasts/` | two years of closes and the AR(1) fan (q05–q95, q25–q75, median) at 1 / 3 / 6 / 12 months | prices + `forecasts` |
| `backtests/` | equity curve vs rebased benchmarks, drawdown, segments drawn apart | `backtest_equity` |
| `portfolio-risk/` | correlation heat map, risk / return scatter with the held positions highlighted | `portfolio_analyses` + `market_metrics` |

`nse-analysis analytics plot <kind> [--ticker … | --all] [--as-of] [--run-id] [--name]
[--out]`; `plot all` regenerates every folder (per-stock kinds for every instrument).
Each folder carries a README saying what its chart shows and leaves out.

**Live** — `analytics plot all` from the live store on the shared box: 284 PNGs, 36.9 MB,
12 m 38 s (93 instruments × volatility 16 MB, momentum 19 MB, forecasts 2.2 MB — every
forecast chart in the scraper era says "no known forecast", since the origin sits two
months after the gap; sector performance, the top 13 of `factor-model v1` as of
2026-09-15 (EQTY 79 Buy Candidate, then KEGN / BRIT / SCOM / BAT … Watch; momentum,
risk and liquidity drawn empty because the gap makes them `unavailable`), fair value vs
price for 8 instruments, the two model backtest runs (the equity curve shows the model
flat in cash until 2022 and both index archives' 2022 hole as a break, plus the
`^N20I` 2024-11-26 decimal slip the quality checks already reported, drawn as it is
stored), and the three portfolio analyses). The per-instrument folders are regenerated
locally and git-ignored; the summary charts are committed.

Tests (9): `broken_line` inserts one NaN per gap on the last day before it; the
volatility figure breaks at the gap, refills the window after it and resets the
drawdown peak, renders PNG; relative strength by hand (100 / 110 / 120 rebase, ratio),
no shared dates → a chart that says so; every empty figure names its reason and
renders; ranking and valuation figures from dataclasses (order, bar counts, upside
sort); the forecast fan (bands, median, 12M note) and the backtest figure (segment
break drawn as a gap) and the portfolio figure (heat map + scatter); the store loaders
on a populated fixture store (sector medians exclude indices, ranking order, KCB fan at
54.0 with four horizons) and `plot all` writing every folder with real PNGs; CLI.


## #21 Research API and profile  ✅ 2026-09-15

`services/analytics/research/profile.py` — `build_profile(settings, ticker, as_of)`
assembles everything the store holds about an instrument, from the store only:
identity (point-in-time sector / industry, classification source), the data as-of
per table, the score block (`stock_rankings`: overall with status, confidence,
classification, ranks, value-trap risk, compounder, the explanation JSON), the
factor scores with coverage and percentiles, eight metric blocks (returns, momentum,
risk, liquidity, quality, growth, value, dividend — each stored metric as its Measure
JSON `{value, status, reason}`, and a metric never computed for the date present as
`unavailable` with that reason), the blended and per-method valuation with
assumptions, forecasts per model and horizon, scenarios, simulations, the latest
market regime, the model registry, a disclaimer and notes ("no statements captured").
`render_profile` prints it one number per line with its status — the §46 profile —
via `nse-analysis analytics research TICKER [--as-of] [--json]`.

`app/web/api/routers/research/` (RBAC `RESEARCH_ROLES`: platform_admin, org_admin,
analyst, portfolio_manager, trader, research_viewer; `client` gets 403): `GET
/research/stocks` (every classified instrument with its latest ranking summary,
cursor-paginated by ticker), `/research/stocks/{ticker}` (the full profile),
`/{ticker}/metrics | valuation | forecast | risk | factors` (blocks of it),
`/{ticker}/history` (the stored ranking per evaluation date), `/research/rankings`
(a date's table, best first, unscored last with reasons, paginated),
`/research/sectors` (median of a stored metric per sector), `/research/backtests`
(stored runs with headline metrics). The store is read in the threadpool; nothing is
computed on request; an unknown ticker is 404 with a message.

Live (`nse-analysis analytics research KCB`, store as of 2026-09-15, 115 lines): KCB,
Banking / Commercial Banks, score 55.23 (factor-model v1, confidence 0.65) → **Watch**,
ranks market 7 · sector 3 · industry 3, value-trap risk medium (cheap on P/E −49 % vs the
market, P/B 0.89, negative FCF), compounder 77.8 (7/9 criteria). Returns 1d −1.86 %,
1w −6.35 %, 1m +5.73 %; every window of three months or more is `unavailable` naming
the 2024-12-31 → 2026-07-26 gap (572 d), as are MA50/200, volatility, beta, Sharpe and
the liquidity block; market cap KES 296.4 bn. Quality ROE 22.0 %, ROA 3.25 %, net margin
38.5 %, D/E 0.29, gross / operating margin, interest coverage and asset turnover
`not_applicable` (financial company); growth revenue +5.6 %, EPS +11.2 %, 3-y CAGR
revenue 14.2 % / EPS 18.1 %, 5-y `unavailable` (history starts FY2021). Value P/E 4.44
(TTM 4.15), P/B 0.89, P/S 1.71, P/E −36 % vs sector, −49 % vs market; dividend yield
5.42 % (TTM 6.50 %), payout 24 %, 4 years paid, 3-y dividend CAGR 35.7 %. Valuation
intrinsic 99.56 (range 67.55–126.21, DDM 61.11, P/B–ROE 138.01) vs price 92.25 → upside
+7.9 %, uncertainty 0.45, actionable. Forecasts `unavailable` for all four models (2
contiguous monthly returns, minimum 36); scenarios base +6.5 % / bear −26.5 % / bull
+28.6 %; regime `unavailable` (^NASI last observed 2024-12-31, 623 days stale). Models:
ar1 / ewma / mean / naive v1 active, factor-model v1 candidate. `--json` emits the same
profile as the API's `GET /research/stocks/KCB`.

Tests: integration — every allowed role reads all eleven endpoints, `client` is 403
everywhere, unknown tickers are 404, the KCB profile carries statuses and reasons
(momentum known, ROE `unavailable` with "not computed", the overall score
`unavailable` naming the 30 % weight share, forecasts and regime present), the block
endpoints, history, pagination of stocks / rankings, sectors, the empty backtest list,
a rejected metric name (422), unauthenticated 401; unit — `metric_block` marks missing
rows, the profile from a populated store (as-of dates, bank `not_applicable` margins,
5-y CAGR `unavailable`, valuation methods P/B–ROE + DDM, scenarios' assumptions,
forecasts absent from the daily pipeline, a delisted instrument's notes, an earlier
as-of with nothing stored), `render_profile`, CLI (`research KCB`, `--json`, unknown
ticker exits 1).

## #22 Production hardening  ✅ 2026-09-16

**Quality gate in the daily pipeline.** The `quality` step now reads back the
error-severity findings its own run created (`new_error_findings(session, run_id)`) and,
when `AnalyticsConfig.quality.halt_on_new_errors` (default 1) of them appear, raises
`DataQualityGateError` before any engine runs: the step row is `failed` with the first
three findings named, every dependent step is `skipped`, `jobs status` shows it, and
the next morning's run — whose findings are by then *known* — proceeds. The very
first run on a store has no baseline (every finding is new by construction), so it
reports and continues; known, open defects never halt the pipeline, each engine
already carries them in its reasons.
Override for one run with `jobs daily --ignore-quality-gate` (recorded in the run's
details), disable with `halt_on_new_errors = 0` (a config change, so a new calc
version). `JobContext.ignore_quality_gate`, `run_pipeline(..., ignore_quality_gate=)`;
the Celery wrapper and cron script call the same function unchanged.

**Failure-scenario tests** (`app/tests/unit/test_hardening.py`): a missing scraper
database is an `ExternalServiceError` before any job row exists; an empty universe runs
the daily and weekly pipelines to completion writing nothing (the regime step now
stores `missing` rows naming the absent index instead of raising); a ticker with only some statements gets
`missing` metrics naming the statement, not zeros; a store held by another writer
(`BUSY_TIMEOUT_SECONDS` shortened) waits and then fails the step cleanly with the
`database is locked` reason recorded; the quality gate halts when the next scrape lands a
broken row (day low above day high) and the override computes anyway; a step that raises is recorded as `failed` and its
dependents `skipped`; the analytics migration chain walks down and up one revision at a
time from head; no `os.environ` and no credential-shaped literal anywhere under
`app/web` / `app/cli`; keys set on `Settings` never reach a log line
(`redact_event`).

**Docs.** `docs/quant-engine.md` gains the end-to-end runbook (scrape → upgrade →
classify → jobs → read → backtest) with the measured timings, the quality-gate
semantics and a failure-mode table. The scraper repository's `docs/STATUS.md` gets a
"Phase 13" entry describing what the engine reads, the daily chain and the statement
coverage to date.

**Live runbook** (2026-09-16 07:25–07:46 EAT+0, this branch's CLI on the live scraper
DB — 287,978 observations, 102 instruments, statements for 17 tickers — and the live
analytics store; `nice 19` on a box at load average 10–12, so wall times include
~60 s of interpreter start-up per command):

| Step | Wall | Result |
|---|---|---|
| `analytics upgrade` | 60 s | store already at head `20260915_0013`, no-op |
| `analytics classify` | 43 s | 102 classifications rewritten identically |
| `jobs daily` (run 114) | 5 m 42 s | 10/10 succeeded — quality 41.6 s, 0 new findings (319 known open; gate silent), returns 1,020 rows / 46.6 s, momentum 2,346 / 36.2 s, risk 1,428 / 53.7 s, liquidity 1,122 / 29.3 s, valuation metrics 544 / 35.8 s, factors 623 / 0.7 s, rankings 89 (13 scored) / 0.4 s, fair value 58 (85 skipped) / 35.3 s, scenarios 180 / 23.3 s |
| `jobs fundamentals` (run 135) | 2 m 27 s | 5/5 — fundamentals 680 rows for 17 tickers / 31.2 s, then valuation metrics, factors, rankings, fair value recomputed because their inputs changed |
| `jobs weekly` (run 146) | 5 m 29 s | 6/6 — regime 1 (`unavailable`, ^NASI 624 days stale) / 13.1 s, forecasts 1,424 / 33.3 s, evaluation 0 (nothing matured) / 62.5 s, Monte Carlo 712 / 141.5 s, factors + rankings refreshed |
| `jobs status` | 2 m 2 s | revision = head, 20 tables (market_metrics 23,580 · forecasts 15,152 · factor_scores 3,087 · fundamental_metrics 3,844 · stock_rankings 352 · valuations 182 · regimes 207 · simulations 3,548), every job's last run `succeeded` as of 2026-09-16, 5 registry rows |
| `research KCB` | 2 m 16 s | the #21 profile with every as-of now 2026-09-16; score 55.23 Watch, ranks 7/3/3, intrinsic 99.56 vs 92.25 — unchanged, as the inputs are |
| `jobs daily` again (run 159) | 1 m 23 s | 10/10 `skipped — inputs unchanged`; no rows written |

The cron chain (`09:40` daily, `10:10` fundamentals, Saturday `10:30` weekly) stays as
installed in #19; a full morning costs about 14 minutes of compute on this box and the
second run of a day about a minute. The backtest is not part of the daily chain (the
2013–2024 run in #18 took hours) and its stored results are unchanged.

## #23 AI reasoning layer  ✅ 2026-09-16

`app/web/services/analytics/ai/narrative.py` — a research note written by Claude from
the stored profile, and nothing else. `build_context(profile)` reduces the #21 profile
to the numbers that are `known` (ratios rendered as percentages, the rest rounded to two
decimals) and the reasons of the `unavailable` ones — score, factors, the eight metric
blocks, valuation, forecasts, scenarios, regime — and `context_hash` fingerprints it.
`narrate(settings, ticker, as_of, client, force)` sends `SYSTEM_PROMPT` (prompt version
1: interpret only, cite only context numbers, never recommend, disclaim once) plus the
JSON context to `AnthropicNarrativeClient` (`anthropic` 1.5.0, `messages.create`, model
`AI_MODEL` default `claude-opus-5`, a refusal stop reason becomes `unavailable`), then
**`check_numbers`** scans the reply: every number in the prose must be one the context
contains (any formatting variant of it — `4.44`, `4.4`, `22.0%`, `296,441,944,684`);
small integers (≤ 36: horizons, counts) and years are allowed. A note that cites
anything else is stored with status `rejected` and its text is never served. One row per
(ticker, as-of, model, prompt version, context hash): a second call reuses it, `--force`
regenerates, a changed store means a new hash and a new note. Statuses: `known`,
`rejected`, `unavailable` (no key, API error, refusal, unknown ticker), `disabled`.

Feature-gated and secret-safe: `AI_NARRATIVES_ENABLED` (default false),
`ANTHROPIC_API_KEY` (Settings only; `sk-ant-…` values are redacted by the logger),
`AI_MODEL`. Table `research_narratives` (migration `20260915_0014`: ticker, as-of, model,
prompt version, context hash, status, reason, narrative, the context JSON, created at).
CLI `nse-analysis analytics narrate TICKER [--as-of] [--force]`; API
`GET /research/stocks/{ticker}/narrative` (`NarrativeOut`, `RESEARCH_ROLES`) returns the
latest row read-only — generation is never a request. `docs/quant-engine.md` gains the
section.

Tests (`app/tests/unit/test_ai_narrative.py`, fake clients only — no network): the
number check accepts context numbers in any variant and rejects `9.1%`, `23%`,
`173,395` from prose while allowing confidence 0.87, the score, horizons, counts and
years; the context is built from the profile only (KCB 2024-12-31 on the fixture:
score, P/E, ROE present, no raw statement rows); the store cycle — known → reused by
hash → `--force` with a fabricating client stored `rejected` naming the offending
numbers → a client that raises stored `unavailable` with the error → `latest_narrative`
is the newest row; disabled and keyless produce clean statuses and write nothing; API
keys never appear in log events; the CLI exits 1 naming the missing key. The research
API tests now sweep `/stocks/{ticker}/narrative` with every role (200 / 403 / 404) and
read `unavailable` with the feature-flag reason before anything is generated.

Live (2026-09-16): `analytics upgrade` migrated the live store `20260915_0013 →
20260915_0014` (`research_narratives`, 0 rows). `narrate KCB` with the flag off prints
`disabled — AI narratives are off (AI_NARRATIVES_ENABLED=false)` and writes nothing;
with `AI_NARRATIVES_ENABLED=true` and no key it prints `unavailable — no
ANTHROPIC_API_KEY configured` (as of 2026-09-16, the ranking date) and writes nothing.
No `ANTHROPIC_API_KEY` is configured on this machine, so no note has been generated
against the live API yet; the generation path is exercised by the fake clients in the
tests. To switch it on: set the two variables in `.env` and run `narrate TICKER` —
the first call stores the note, every later call reuses it until the store changes.

## Epic #24 — complete  ✅ 2026-09-16

Twenty-two issues merged in four days (nse-be PRs #25–#46, scraper PRs #3 and #4), every
one through the local gate with real-data validation recorded above. What exists now:

| Layer | Where | Live state (2026-09-16) |
|---|---|---|
| Raw data | `~/nse-stock-scraper` SQLite, read-only | 287,978 observations / 102 instruments (2007-01 → 2024-12, 2026-07 → today); statements for 17 of 63 tickers, 8 more a day |
| Store | `data/nse_analytics.sqlite3`, Alembic `20260915_0014`, 21 tables | market_metrics 23,580 · fundamental_metrics 3,844 · factor_scores 3,087 · stock_rankings 352 · valuations 182 · forecasts 15,152 · forecast_evaluations 9,160 · simulations 3,548 · regimes 207 · portfolio_analyses 4 · backtest_runs 4 · research_narratives 0 |
| Engines | `app/web/services/analytics/` — returns, momentum, risk, liquidity, fundamentals, valuation metrics, factors, ranking, fair value, forecasting, Monte Carlo, scenarios, regime, portfolio, backtesting, research profile, AI narrative | every row carries `calc_version_id`, `status`, `reason`; 15 calc versions registered |
| Jobs | `jobs daily` 09:40 · `fundamentals` 10:10 · Saturday `weekly` 10:30 (`CRON_TZ=Africa/Nairobi`), Celery wrappers | a morning costs ~14 min of compute here, a rerun ~1 min; the quality gate halts on new error findings |
| Surfaces | CLI `nse-analysis analytics …` (compute, rank, research, backtest, portfolio, forecast, plot, narrate, jobs, dq, classify, upgrade); API `/research/*` with RBAC | `research KCB`: score 55.2 Watch, ranks 7/3/3, intrinsic 99.56 vs 92.25 |
| Diagrams | `diagrams/{momentum,volatility,valuation,sector-analysis,factor-ranking,forecasts,backtests,portfolio-risk}/` | 284 PNGs from `plot all` |

What the numbers honestly say today: the 2024-12-31 → 2026-07-26 gap makes every
3-month-plus price window, volatility, beta, liquidity, MA50/200, forecasts and the
regime `unavailable` for the current date and will keep doing so until 2026-10 (3 m),
2027-01 (6 m) and 2027-07 (12 m) of continuous scraping exist; fundamentals, valuation
metrics, fair value, dividend and quality factors are live for the tickers with
statements; the ranking scores 13 instruments with confidence 0.65 and names the 30 %
of weight it cannot apply. The 2013–2024 backtest of `factor-model v1` returned
−18.2 % against NASI +74.2 % and a market-only control of −56.6 % after costs — the
model is registered as `candidate`, not `active`, on purpose. Known archive defects
(`^N20I` 2024-11-26 decimal slip, `^NASI` 2021-12 → 2022-06 hole, no index data after
2024) are open findings the engines carry in their reasons rather than patch.

**Found by the first unattended cron run (2026-09-16 09:40):** both pipelines failed
before starting — `Settings` demanded `SUPABASE_URL` / `SUPABASE_KEY`, which every
interactive run had supplied by hand and cron does not. The two fields now default to
empty (the `supabase` source and the API's client already handle "not configured"),
`test_hardening.py` runs `analytics upgrade` with both variables unset, and
`scripts/run_analytics_jobs.sh daily` / `fundamentals` were rerun under `env -i`
(cron's environment) — see the log lines below.

```
[2026-09-16T09:40:19+0200] START pipeline=daily args=          ← installed cron, before the fix
[2026-09-16T10:20:48+0200] FAILED pipeline=daily exit=1         ValidationError: SUPABASE_URL / SUPABASE_KEY Field required
[2026-09-16T10:34:52+0200] START pipeline=daily args=          ← env -i, after the fix
[2026-09-16T10:39:20+0200] OK pipeline=daily                    run 170: 10/10 succeeded — the 09:00 scrape had landed, so
                                                                quality wrote 41 new (non-error) findings and every step recomputed
[2026-09-16T10:39:20+0200] START pipeline=fundamentals args=
[2026-09-16T10:40:59+0200] OK pipeline=fundamentals             run 191: fundamentals 960 rows (the day's 7 new statement tickers),
                                                                valuation metrics 768, fair value 84, rankings 89
```

Operator guide: `docs/quant-engine.md`. Data sources and their defects:
`docs/data-sources.md`. The scraper's view of the hand-over: its `docs/STATUS.md`
Phase 13.

# Dashboard

Tracking epic: [#57](https://github.com/seven7-AI/Nairobi-stock-Exchange/issues/57). A
simple, live web dashboard over the engine, public on the server's IP. Decisions taken
with the user: a **public read-only** `/api/v1/dashboard/*` with no login (the single
documented exception to the RBAC rule; SQLite only); the dashboard on its **own port
4747** as a user systemd service (80/443 belong to another project's nginx); **React +
Vite** served by FastAPI; the geographic-exposure block stays `unavailable` until the
scraper captures the company page.

## #48 Dashboard API core: status, version, overview, market  ✅ 2026-09-17

`app/web/api/routers/dashboard/{views,schema}.py` — mounted behind `DASHBOARD_PUBLIC`
(default true), no `require_roles`, `GET` only, every read in the threadpool through
`app/web/services/dashboard/`. The layering rule is enforced by a test that greps both
packages for platform models, `SessionDep`, Redis or Supabase imports.

- **`cache.py`** — `StoreStamp` = the modification times of the analytics store and the
  scraper database (WAL-aware); `DashboardCache.get_or_compute(key, stamp, compute)`
  serves a cached payload while the stamp is unchanged and the entry is younger than
  `DASHBOARD_CACHE_MAX_AGE_SECONDS` (300). No `lru_cache` — it cannot see a file change.
  Every response carries `X-Store-Version`.
- **`status.py`** — `build_status` on top of `job_status` (the CLI's `jobs status`):
  store revision/head/`migrated`, tables and last-update stamps, each pipeline's last
  run and **last success** (`summaries.latest_runs`) with the step table from the run's
  details, every job's last run, the scraper's `health_check` (location removed), input
  watermarks, the cron chain (`CRON_SCHEDULE`, pinned to
  `scripts/install_analytics_cron.sh` by a unit test), the model registry.
  `build_version` is the cheap poll: stamps, `latest_trade_date()` and the latest
  ranking date. `JobRow` sanitises: first line of an error only, filesystem paths
  blanked, details whitelisted to `steps/counts/force/ignore_quality_gate`.
- **`market.py`** — `latest_quotes` (cached): one `Quote` per classified equity —
  scraped price, change, volume, 52-week range, market cap and profile facts from
  `stockanalysis_stocks` when the scraper has the ticker, the last canonical close from
  `stock_observations` always, and every scraped field `unavailable` with the reason
  ("not on stockanalysis; last observation 2019-10-11") when it does not.
  `build_market`: sector medians of `return_1d/1w/1m` from `market_metrics` — every
  sector listed, `unavailable` when no member has a known value — coverage counts per
  metric, top/bottom ten movers by scraped change, and the benchmark indices'
  availability (`^NASI`, `^N20I`: known within 14 days of the date, otherwise
  `unavailable` naming the last observation, with the last level).
- **`overview.py`** — counts and dates: tracked / scraped / classified instruments, the
  latest trade date and how many have it (`latest_trade_date_coverage()`), per result
  table the status counts on its latest date and `latest_known_as_of`
  (`summaries.status_counts_on_latest`, `latest_known_as_of`), open findings by
  severity, the pipelines block.
- `NseScraperSource.latest_trade_date()` / `latest_trade_date_coverage()`;
  `app/web/db/analytics/services/summaries.py`; `Settings.dashboard_public`,
  `dashboard_cache_max_age_seconds`; CLAUDE.md §2 exception paragraph;
  `docs/quant-engine.md` section.

Tests (no Postgres needed): every endpoint 200 without a token and free of filesystem
paths; the version poll (`ETag`, 304, changes when the store file is touched); status
(migrated store, pipelines daily/fundamentals with steps, weekly never run, schedule and
timezone, watermarks, cron order, models); overview on the fixture store as of
2024-12-31 (8 instruments on the newest scrape day 2026-09-13, 10 equities, 8 scraped,
point-in-time ranking counts, no forecasts → `latest_known_as_of` None); market (KCB
price 94.00 and volume 375,298 from the scrape, founded 1896; KENO present with
`unavailable` reasons and no zeros; Banking median known; indices known on their last
day 2024-12-31 and stale with the reason after the gap); 404 on an empty store; the
router switched off by `DASHBOARD_PUBLIC=false`; unit tests for the stamp, the cache
(hit/miss/age/bound/threads), the cron pin, error sanitising, the equity universe and
the no-platform-imports rule; a `realdata` test on the live store.

Live (2026-09-17, the real store and scraper DB through the app in-process, box at load
30): `/status/version` → `latest_market_date 2026-09-16`, `latest_analytics_date
2026-09-16`, `ETag` honoured (304); `/overview` → 92 tracked (63 scraped by
stockanalysis, 92 classified equities), 63 instruments with a row on 2026-09-16,
findings error 1 / warning 217 / info 94, store `20260915_0014` migrated, rankings
known 19 / unavailable 70, forecasts 1,424 `unavailable` with `latest_known_as_of
2024-12-31`, pipelines daily/fundamentals/weekly all `succeeded` as of 2026-09-16;
`/market` (94 kB, 0.8 s cached / 6.3 s cold) → ^NASI and ^N20I `unavailable` ("last
observation 2024-12-31 is 624 days before 2026-09-16", last levels 123.48 / 2,010.65),
coverage `return_1d` known 50 / zero 13 / unavailable 39, sector 1-day medians led by
Telecommunication +1.81 % (1 of 2 known), top movers SKL +7.51 %, EGAD +5.35 %, bottom
TCL −6.67 %; KCB price 90.00, change −2.44 %, volume 375,298, 52-week 52.50–101.00,
market cap KES 289.2 bn, industry Commercial Banks, founded 1896, 11,253 employees;
29 classified equities have no stockanalysis row (ACCS, ARM, BAUM, …) and appear with
`unavailable` reasons. No string leaving the API contains a filesystem path.
