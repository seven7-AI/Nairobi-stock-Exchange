# stock-growth/

One chart per instrument: **how has this stock performed from 2007 until the latest
scrape?** Open any `<TICKER>.html` in a browser.

## What the chart shows

- **The line** is the unadjusted daily close from `stock_observations`, oldest first.
  Hover for the date, close, source (`nse_archive:<year>` or `nse_scraper`) and the
  ticker the source used that day.
- **Gaps are gaps.** Consecutive observations more than 14 days apart (the archive's
  widest holiday gap is 9) break the line and get a shaded "no data · N days" band.
  Nothing is interpolated. Every stock has a gap from 2025-01-01 to 2026-07-25 — there is
  no data from any source for that stretch.
- **first / last / high / low** are marked and labelled.
- **Suspected corporate actions** — a close-to-close step of more than 2.5× within one
  trading window — get a dashed vertical line. Prices in the archive are **not adjusted**
  for splits (its `Adjust` column is too sparse to use), so KCB's 10:1 split on
  2007-04-03 (212 → 22.5) appears as a cliff and is marked as one, not smoothed away.
  Treat the "overall %" in the subtitle accordingly.
- **Lineage** — when the archive used an older code, the subtitle says so
  (`traded as BBK → ABSA`).

## Where the data comes from

`~/nse-stock-scraper/data/nse_scraper.sqlite3` → `stock_observations`, read-only, via
`NseScraperSource.fetch_observations()`. New scraper rows appear the next time the
chart is regenerated.

```bash
uv run nse-analysis plot-stock KCB      # one
uv run nse-analysis plot-stock --all    # every instrument
```
