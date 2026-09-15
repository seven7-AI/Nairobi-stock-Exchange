# diagrams/forecasts/

One PNG per instrument with a known forecast: the last two years of closes and the
**AR(1) forecast fan** from the origin — the q25–q75 and q05–q95 bands and the median at
1 / 3 / 6 / 12 months, as prices, from `forecasts`. The distribution is normal in log
returns and the title says so. An instrument without a known forecast (too little
contiguous history, or a stale origin) gets a chart that says why.

Regenerate: `uv run nse-analysis analytics plot forecasts --all`.
