# Corporate expansion & geographic intelligence layer

Which legal entities each NSE-listed company owns, in which countries it operates,
what those operations earn, how that footprint changes over time, and — eventually —
whether regional expansion is creating or destroying value. Built on the quant engine
(`docs/quant-engine.md`), tracked by epic #70, delivered one phase per issue.

This document is the design record **and** the status trail: no earlier research
document existed in either repository, so the specification (the user's 18-phase
brief) and the decisions below are the starting point. Every phase updates the
[status](#status) section.

## Decisions

| Decision | Choice | Why |
|---|---|---|
| Ownership source | Annual-report subsidiary and segment notes are primary; GLEIF enriches identifiers only | GLEIF holds ~306 Kenyan LEIs; KCB Group PLC and Equity Group have none; its relationship records for the ones that exist return `NO_LEI`. The reports are the only complete source. |
| Document sources | Company IR sites + NSE announcements + CBK supervision reports now; CMA as a stub | The CMA resource centre returns 502; `cma.or.ke` has no issuer filings. Bank of Tanzania publishes usable PDFs; Bank of Uganda is a JS application and is registered disabled. |
| Extraction | PyMuPDF → pdfplumber → Camelot → OCR → LLM, all built; Camelot/OCR run only when `gs` / `tesseract` / `pdftoppm` exist; the LLM stage is gated off until a key exists | Deterministic text is the source of truth. A stage that cannot run is recorded as such on the extraction row — a scanned page is `ocr_pending`, never silently empty. |
| Storage | Corporate tables in the analytics SQLite Alembic chain (`app/alembic_analytics/`, from `20260919_0015`); PDFs on disk under `CORPORATE_DOCUMENTS_DIR` | One store, one migration chain, one backup. Documents are large binaries and are never served by the API. |
| History | Append-only versions; the only mutation of an old row is closing its transaction time | A restated figure must remain queryable as it was known at the time. |
| Configuration | Ingestion thresholds in `CorporateConfig` with its own hash and its own `calc_versions` row (`name="corporate"`); analytics thresholds and the factor definition join `AnalyticsConfig` once, in A3 | `AnalyticsConfig.config_hash()` is part of every job fingerprint; nesting the corporate thresholds there would force a recompute of every pipeline. |
| Factor | `expansion_quality` is scored and backtestable but is **not** in the composite weights until ≥ 2 stable reporting cycles are observed (earliest ≈ Q2 2027) | Missing disclosure would otherwise be ranked as a bad score. |

## Layers

```text
L1 country presence      the company says it operates there          (business description, segment note headings)
L2 legal entities        subsidiaries / associates / JVs / branches   (subsidiaries note, GLEIF cross-check)
L3 operations            branches, employees, customers by country    (operations tables)
L4 country revenue       segment note by geography                    (segment note)
L5 country profit        PBT / net profit by geography                (segment note)
L6 country assets etc.   assets, liabilities, capex, capital injected (segment note, subsidiary statements)
L7 derived               shares, growth, HHI, expansion quality       (computed; Part B)
```

Each layer is stored on its own row with its own disclosure status; a company can
be at L2 (we know the subsidiaries) and have nothing at L4 (no geographic split
disclosed). Nothing from a lower layer is spread upward.

## Disclosure statuses

A `Measure.status` says whether a *number exists for a computation* and is shared
by every engine. The corporate layer adds a second, independent word on each fact
row — `disclosure` — that describes the *company's reporting*:

| `disclosure` | Meaning | Example |
|---|---|---|
| `disclosed` | The report states this value for this country | KCB: revenue for Tanzania |
| `regional_only` | The report groups countries ("Rest of East Africa") — the value is known for the region, unknown per country | Equity: "Regional subsidiaries" |
| `not_disclosed` | The report has a segment note but it is not geographic (business lines only), or the item is absent | Safaricom segments by product |
| `not_extractable` | The page exists but could not be read (scanned, no OCR, broken table) | Pre-2015 scanned reports |

A `regional_only` fact carries a `known` value under a region key; a
`not_disclosed` fact is stored as `status=unavailable` with the page in the
reason, so the absence is itself recorded and countable ("companies missing
disclosure" in the status). A missing number is never a zero: `ZERO` is written
only when the report prints an explicit nil.

## Bitemporal semantics

Every versioned row (relationships, presence, segment facts, operational facts)
carries two time axes:

- **Valid time** — `effective_from` (inclusive) / `effective_to` (exclusive, `NULL`
  = still valid as far as we know). *When was this true in the world?*
- **Transaction time** — `recorded_at` / `superseded_at` (`NULL` = current belief).
  *When did we believe it?*

plus `version_key` (a hash of the row's natural identity without its values),
`content_hash` (a hash of the values), `superseded_by_id` and
`supersession_reason` (`restated`, `corroborated`, `closed`, `merged_entity`,
`retracted`). The single writer, `append_and_close`, inserts a new version and
closes the previous one; it never updates a value column.

- **Restatement.** FY2023 segment revenue appears in the FY2023 report (A) and as a
  comparative in the FY2024 report (B ≠ A). Same `version_key`, different
  `content_hash` → a new row from the FY2024 document; the old row is closed with
  `restated`. Asking "what did we know on 2024-06-01?" returns A; asking today
  returns B.
- **Corroboration.** The same value from a later document → a new row with its own
  provenance; the older is closed with `corroborated`, so the current belief always
  points at the latest evidence while the original stays queryable.
- **Closing valid time.** "KCB disposed of X in 2021" is a *new version* of the
  relationship with `effective_to = 2021-…`, never an update of the old row.
- **The KCB-2018 question.** "Where did KCB operate on 2018-12-31?" =
  `current(as_of(presence, 2018-12-31))`: rows whose valid time covers that day,
  taken from the current belief. It must not list TMB (DRC, acquired 2022) or BPR
  (Rwanda, 2021). "What did we believe about 2018 on 2019-06-30?" adds
  `as_known_on(2019-06-30)`. Both are tested once relationship facts exist (C6).
- **Point-in-time for analytics.** Period facts also carry `available_from` (the
  document's publication date when known, else `period_end + publication lag`,
  flagged `availability_assumed`), the same rule the fundamentals engine applies to
  statements, so a backtest as of *T* sees only facts available by *T*.

## Provenance

Every fact, relationship and presence row stores a provenance JSON:

```json
{"schema": 1, "document_id": 12, "sha256": "…", "url": "https://…", "source": "ir:KCB",
 "kind": "integrated_report", "period_end": "2024-12-31", "published_on": "2025-03-27",
 "page": 214, "table_ref": "p214.t1", "section": "Note 6 Segment information",
 "row_label": "Kenya", "column_label": "Total income", "method": "pdfplumber",
 "parser_version": "2026.09.1", "extracted_at": "2026-09-20T02:10:00Z", "confidence": 0.9,
 "unit_raw": "KShs million", "scale": 1000000, "currency": "KES",
 "assumptions": ["availability: period_end + 90d"],
 "cross_checks": [{"check": "gleif_name", "result": "match"}]}
```

`document_id`, `page`, `table_ref`, `extraction_method` and `confidence` are also
plain columns for indexing. The filesystem path of a PDF is never part of
provenance; the dashboard exposes only `{document, period, page, table, method,
confidence}`. Signed download links are credentials: they are logged with the query
string stripped and are never persisted (a signed document's identity is the page
it was linked from plus the link text).

## Sources and their hierarchy

| Field | Order of authority |
|---|---|
| Ticker, listing history | scraper `instruments` / `instrument_aliases`, NSE listed-companies page |
| Legal name, LEI, registration number | GLEIF (exact normalised-name match) → NSE page → scraper |
| Subsidiaries, ownership %, country of incorporation | annual-report subsidiaries note (primary) → subsidiary financial statements → announcements (candidates only) |
| Country revenue / profit / assets | annual-report segment note; subsidiary statements for local-currency figures |
| Operations (branches, staff, customers) | annual-report operations tables; regulator reports (CBK, BoT) as cross-checks |
| Country macro (GDP growth, inflation, FX, lending rate) | World Bank API; IMF DataMapper is 403 from this host and stays `unavailable` |
| Events (acquisitions, disposals, entries) | NSE announcements, IR news pages, RSS — **candidates until an authoritative document confirms them**; news never mutates structure |

The collector is polite by construction (`PoliteClient`): per-host spacing (3 s),
backoff on 429/5xx honouring `Retry-After`, `robots.txt`, conditional GET, a byte
cap, and a per-run request budget (300) whose exhaustion ends a run as a recorded
outcome, not a failure. It never touches stockanalysis (already rate-limited,
nse-stock-scraper#7); profile data is read from the scraper's database.

## Extraction ladder

```text
PyMuPDF text  → locate sections (segment note, subsidiaries, operations) by headings + table vocabulary
pdfplumber    → tables on the located pages
Camelot       → only when pdfplumber finds nothing and ghostscript exists
OCR           → tesseract over pdftoppm renders, only when CORPORATE_OCR_ENABLED and the binaries exist; else ocr_pending
LLM clean-up  → gated off; when on, may only re-shape text a deterministic stage extracted (numbers absent from the raw text are rejected)
```

`nse-analysis corporate capabilities` prints which stages this box can run and why
the others cannot; the same snapshot is stored on every extraction row.
Validation is a labelled set of real reports (KCB, Equity, Safaricom, Jubilee,
EABL) with thresholds: ≥ 95 % of labelled subsidiary rows recovered with country
and %; every labelled segment revenue within 0.5 %; sum of segments within 1 % of
the consolidated statement or a finding is raised. Tests skip with a reason when a
report has not been collected; they never run on invented PDFs.

## Configuration

`Settings` (`app/web/config.py`): `CORPORATE_DOCUMENTS_DIR`, `CORPORATE_CACHE_DIR`,
`CORPORATE_HTTP_DELAY_SECONDS`, `CORPORATE_HTTP_TIMEOUT_SECONDS`,
`CORPORATE_USER_AGENT`, `CORPORATE_CONTACT_EMAIL`, `CORPORATE_MAX_DOCUMENT_BYTES`,
`CORPORATE_MAX_DOCUMENTS_PER_RUN`, `CORPORATE_MAX_REQUESTS_PER_RUN`,
`CORPORATE_OCR_ENABLED`, `CORPORATE_LLM_CLEANUP_ENABLED` (forced off without the
AI layer and a key), `CORPORATE_GLEIF_BASE_URL`, `CORPORATE_WORLDBANK_BASE_URL`.

`CorporateConfig` (`app/web/services/corporate/config.py`): fuzzy-match acceptance
and margin, the low-confidence threshold, segment-sum tolerance, universe status
windows, event de-duplication / verification / expiry windows. `nse-analysis
corporate config` prints them with their hash.

## Commands

```bash
uv run nse-analysis corporate config          # thresholds and their hash
uv run nse-analysis corporate capabilities    # which extraction stages this box can run
```

Later phases add `universe`, `collect`, `documents`, `sources`, `extract`,
`structure`, `validate`, `review`, `macro`, `events`, `status`, `metrics`,
`evaluate`, `promote`, `coverage`.

## Status

| Phase | Issue | State | Notes |
|---|---|---|---|
| C0 skeleton, settings, config, countries, polite client, CLI, this document | #71 | done 2026-09-19 | `httpx`, `pymupdf`, `pdfplumber` added; Camelot/OCR need `gs` / `tesseract` / `pdftoppm` (not installed on this box yet) |
| C1 canonical company universe | — | planned | |
| C2 GLEIF, entities, resolver, bitemporal helpers | — | planned | |
| C3 document collector | — | planned | |
| C4 PDF text/tables, subsidiaries parser, labels v1 | — | planned | |
| C5 segment/operations parsers, disclosure statuses, labels v2 | — | planned | |
| C6 bitemporal writers, PIT queries | — | planned | |
| C7 validation, provenance, review queue | — | planned | |
| C8 World Bank macro, regulator documents | — | planned | |
| C9 event candidates and verification | — | planned | |
| C10 pipelines, cron, Celery, status | — | planned | |
| A1–A9 analytics, factor, API, dashboard, diagrams, AI, coverage, docs | — | planned | see epic #70 |

Coverage numbers (companies, documents, facts by disclosure, extraction pass rate)
appear here from C3 onwards.
