# diagrams/backtests/

`run-<id>-<name>.png`: the daily equity curve of a stored backtest run against its
benchmarks rebased at each segment start (top) and the portfolio drawdown (bottom),
from `backtest_equity`. Segments are separated by data gaps and drawn as separate
lines; nothing is bridged. The subtitle carries the first segment's return, CAGR,
Sharpe and max drawdown.

Regenerate: `uv run nse-analysis analytics plot backtests [--run-id N | --name NAME]`.
