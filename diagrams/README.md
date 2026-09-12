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
| `stock-growth/` | one interactive chart per instrument, 2007 → latest scrape | `uv run nse-analysis plot-stock --all` |
| `assets/` | `plotly.min.js`, written once and shared by every chart | automatic |

Charts are standalone HTML — open one in a browser. They reference
`../assets/plotly.min.js` relatively, so the folder works offline and each chart stays
small. The same figure is served live at `GET /api/v1/market-data/{ticker}/growth`.

## Adding a new kind of diagram

1. Add a module under `app/web/services/visualizations/` that turns rows from
   `NseScraperSource` into a plotly figure. Keep it pure: no I/O beyond the source, no
   interpolation, no second price source.
2. Give it a `write_*` function that writes to `diagrams/<new-kind>/` and reuses
   `assets/plotly.min.js`.
3. Add a CLI command beside `plot-stock` and, if it should be served, a route in the
   matching router.
4. Add a `README.md` in the new folder saying how to read it and where the data comes from.

Planned siblings: `sector-performance/`, `market-index/`, `comparison/`.
