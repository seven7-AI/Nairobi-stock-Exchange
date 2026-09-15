# diagrams/volatility/

One PNG per instrument: **63-day annualised volatility** (top) and **drawdown from the
running peak** (bottom), both computed from the canonical `stock_observations` close
series, in-segment only. A data gap (the 2025 gap, or any hole longer than 14 days) is
shaded and labelled; the volatility window refills after it and the drawdown peak resets,
so no value ever spans a hole.

Regenerate: `uv run nse-analysis analytics plot volatility --all` (or `--ticker KCB`).
