# diagrams/valuation/

`fair-value-vs-price-<date>.png`: for every instrument with a blended fair value on the
date, the range (mean of the bear cases … mean of the bull cases) and the intrinsic
value (dot), all relative to the price on the date, from `valuations`. Grey means the
uncertainty score is at or above the threshold: the margin of safety is a number, not a
signal.

Regenerate: `uv run nse-analysis analytics plot valuation [--as-of YYYY-MM-DD]`.
