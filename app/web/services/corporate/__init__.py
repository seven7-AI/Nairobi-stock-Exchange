"""Corporate expansion & geographic intelligence layer.

Which legal entities each NSE-listed company owns, in which countries it operates,
what those operations earn, and how that footprint changes over time - collected
from free public sources (company IR sites, the NSE, CBK, GLEIF, the World Bank),
extracted deterministically from annual reports, and stored bitemporally so that
history is never overwritten.

Every fact carries provenance, a confidence, and a disclosure status
(``disclosed`` / ``regional_only`` / ``not_disclosed`` / ``not_extractable``); a
missing number is never a zero. See ``docs/corporate-intelligence.md``.

    codegraph explore "CorporateConfig PoliteClient to_iso2 corporate"
"""
