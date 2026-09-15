# diagrams/sector-analysis/

`sector-performance-<date>.png`: the **median 12-month return** of each sector's members
with a known value on that date (member count after the value), from `market_metrics`
and the point-in-time classification. Indices and ETFs are excluded. A sector with no
known member value on the date does not appear — it is not drawn as zero.

Regenerate: `uv run nse-analysis analytics plot sector-analysis [--as-of YYYY-MM-DD]`.
