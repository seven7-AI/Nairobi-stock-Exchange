# diagrams/portfolio-risk/

`<name>.png`: the pairwise correlation matrix of a stored portfolio analysis (left) and a
risk / return scatter of every stock with a known annualised volatility and 12-month
return on the latest metrics date, the held positions highlighted (right), from
`portfolio_analyses` and `market_metrics`. Warnings from the analysis are printed
under the chart.

Regenerate: `uv run nse-analysis analytics plot portfolio-risk [--name NAME]`.
