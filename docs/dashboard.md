# The dashboard

A single-page React app (`dashboard/`, Vite + TypeScript, four runtime dependencies:
react, react-dom, react-router-dom, recharts) served by the FastAPI app itself on the
public port — `http://194.195.87.62:4747`. It is a window onto the engine, not a second
implementation: every number on it comes from `/api/v1/dashboard/*` (see
`docs/quant-engine.md`), which reads only the analytics store and the scraper's
database.

## Pages

| Route | Shows |
|---|---|
| `/` Overview | tracked / scraped / classified counts, latest market date and coverage, ranked stocks, forecasts (or why none), open findings by severity, the data source, each pipeline's last run and last success, per-table status counts |
| `/market` | benchmark indices with their staleness reason, sector medians for 1d / 1w / 1m, top and bottom movers, every classified equity's quote |
| `/stocks` | the universe: price, change, volume, market cap, P/E, P/B, yield, four factor percentiles, composite score, class, rank — searchable, sortable (unknown values always last) |
| `/stocks/:ticker` | the research profile: price history with gaps shaded, eight metric blocks, factor scores with percentiles, valuation range against price, forecast distributions, scenarios, regime, sector comparison, company facts (geographic exposure honestly `unavailable`), fiscal-year statements, models and notes |
| `/analytics` | the ranked universe on a date (as-of selector) with factor percentiles and relative metrics |
| `/forecasts` | per ticker and model: quantile bands and probabilities per horizon (a fan chart when known), scenarios, regime, the models' walk-forward accuracy — and a button to jump to the last date with known forecasts |
| `/signals` | Buy / Watch / Neutral-Weak-Avoid, value traps with their signals, compounders with their criteria, valuation upside and downside, factor combinations, risk flags, the not-scored list with reasons |
| `/backtests` | stored runs; equity vs benchmarks rebased to 100, drawdown, headline metrics, benchmark metrics, weights and costs |
| `/system` | store revision and tables, pipelines with their steps, every job's last run, scraper health, the cron chain, the model registry |

## Missing is never zero

Every number arrives as `{value, status, reason}` and is rendered by one component,
`Measure`: a known value is formatted; an explicit zero is "0" with a title saying so;
`missing`, `unavailable`, `not_applicable` and `not_meaningful` render as a labelled
chip whose tooltip is the reason. Forecast views show ranges and probabilities with a
disclaimer and never a single target price. Price charts break at every gap the API
lists and shade it — the 572-day hole (2024-12-31 → 2026-07-26) is drawn, not bridged.

## Live

The shell polls `GET /status/version` every 60 s (paused while the tab is hidden).
The version is the modification stamp of the two SQLite files; when it changes, every
mounted view refetches. The header shows the latest market date, when analytics and
the scrape last wrote, and turns red when the API cannot be reached.

## Development

```bash
. ~/.nvm/nvm.sh                        # Node 20 lives in nvm on this host
cd dashboard && npm ci                 # once
npm run dev                            # Vite on :5173, /api proxied to :4747 (VITE_API_TARGET to change)
npm run check                          # oxlint + tsc + vitest
npm run build                          # dashboard/dist (gitignored) - what the server mounts
npm run capture-fixtures               # refresh src/test/fixtures/*.json from a running API
```

Tests render the pages from **payloads captured from the live API**
(`src/test/fixtures/`, with a `manifest.json` naming the endpoint, time and store
version) — never from invented data. `Measure` has a test per status; `useVersion` is
tested for refetch-on-change and no-refetch-on-same-version.

## Deploying

`scripts/install_dashboard_service.sh --build` builds `dashboard/dist` and restarts the
`nse-dashboard` user service (see `docs/quant-engine.md`, "Serving the dashboard on
port 4747"). The pre-push gate runs the dashboard's own checks whenever `dashboard/`
changed (`DASHBOARD_GATE=always|strict` to force or require it); `make dashboard-check`
and `make dashboard-build` are the manual equivalents.
