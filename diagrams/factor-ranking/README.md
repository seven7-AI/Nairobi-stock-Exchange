# diagrams/factor-ranking/

`top-ranking-<date>.png`: the top 15 by `factor-model v1` overall score (left, with the
classification) and every factor's market percentile per stock (right), from
`stock_rankings`. A factor the model could not score is drawn as an empty bar (0), not
as an average.

Regenerate: `uv run nse-analysis analytics plot factor-ranking [--as-of YYYY-MM-DD]`.
