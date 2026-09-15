# diagrams/

Visualizations of the NSE data. Every diagram here is drawn from the **canonical
`stock_observations` timeline** in the scraper's database — the 2007–2024 archive plus
every daily scrape — read through `NseScraperSource`. There is no second source of
prices for charts.

```text
NSE_DATA archive  +  daily scraper  →  stock_observations  →  app/web/services/visualizations/  →  diagrams/<kind>/
```

| Folder | What | Regenerate |
|---|---|---|
| `stock-growth/` | one PNG chart per instrument, 2007 → latest scrape | `uv run nse-analysis plot-stock --all` |
| `volatility/` | rolling 63-day volatility and drawdown per instrument | `uv run nse-analysis analytics plot volatility --all` |
| `momentum/` | stock vs `^NASI` rebased, relative strength | `uv run nse-analysis analytics plot momentum --all` |
| `sector-analysis/` | median 12-month return per sector | `uv run nse-analysis analytics plot sector-analysis` |
| `factor-ranking/` | top 15 by the factor model, factor percentiles | `uv run nse-analysis analytics plot factor-ranking` |
| `valuation/` | fair-value range vs price | `uv run nse-analysis analytics plot valuation` |
| `forecasts/` | AR(1) forecast fan per instrument | `uv run nse-analysis analytics plot forecasts --all` |
| `backtests/` | equity curve vs benchmarks, drawdown | `uv run nse-analysis analytics plot backtests` |
| `portfolio-risk/` | correlation matrix, risk / return scatter | `uv run nse-analysis analytics plot portfolio-risk` |
| everything above | | `uv run nse-analysis analytics plot all` |

The per-instrument folders (`volatility/`, `momentum/`, `forecasts/` — ~90 PNGs each) are
regenerated locally and not committed; the summary charts are.

The research diagrams (everything but `stock-growth/`) are drawn from the **analytics
store** (`data/nse_analytics.sqlite3`) and the same price series; each folder's README
says what its chart shows and what it leaves out. Charts are static PNGs (matplotlib): they render inline on GitHub, need no JavaScript,
and are ~100–150 KB each. The same figure is served as `image/png` at
`GET /api/v1/market-data/{ticker}/growth`.

## Adding a new kind of diagram

1. Add a module under `app/web/services/visualizations/` that turns rows from
   `NseScraperSource` into a matplotlib `Figure`. Keep it pure: no I/O beyond the
   source, no interpolation, no second price source.
2. Give it a `write_*` function that renders with `render_png` and writes to
   `diagrams/<new-kind>/`.
3. Add a CLI command beside `plot-stock` and, if it should be served, a route in the
   matching router.
4. Add a `README.md` in the new folder saying how to read it and where the data comes from.

Planned siblings: `sector-performance/`, `market-index/`, `comparison/`.
