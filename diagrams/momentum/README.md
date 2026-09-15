# diagrams/momentum/

One PNG per instrument: the stock and `^NASI` rebased to 100 on their first common
date (top) and the ratio of the two — **relative strength** — (bottom), on the dates both
have a close. Gaps in either series break the lines. The benchmark ends 2024-12-31 in the
archive, so the scraper era shows no relative strength until an index source exists.

Regenerate: `uv run nse-analysis analytics plot momentum --all`.
