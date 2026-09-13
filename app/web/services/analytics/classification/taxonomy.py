"""The sector taxonomy: normalised codes for the official NSE labels.

The NSE has re-spelt labels over the years ("Telecommunication and Technology"
became "Telecommunication" in 2022) without moving any company; those are one
code here. Anything not in this table is a label the engine has not seen and is
refused rather than guessed - add it with evidence.

    codegraph explore "sector_code SECTORS LABEL_ALIASES"
"""

from __future__ import annotations

#: code -> canonical display label (the current official spelling).
SECTORS: dict[str, str] = {
    "agricultural": "Agricultural",
    "automobiles": "Automobiles and Accessories",
    "banking": "Banking",
    "commercial_services": "Commercial and Services",
    "construction": "Construction and Allied",
    "energy": "Energy and Petroleum",
    "insurance": "Insurance",
    "investment": "Investment",
    "investment_services": "Investment Services",
    "manufacturing": "Manufacturing and Allied",
    "telecommunication": "Telecommunication",
    "reit": "Real Estate Investment Trusts",
    "etf": "Exchange Traded Funds",
    "indices": "Indices",
}

#: Lower-cased label as printed in a source -> code. Includes historical spellings.
LABEL_ALIASES: dict[str, str] = {
    **{label.lower(): code for code, label in SECTORS.items()},
    "telecommunication and technology": "telecommunication",
    "telecommunications": "telecommunication",
    "automobiles & accessories": "automobiles",
    "commercial & services": "commercial_services",
    "construction & allied": "construction",
    "energy & petroleum": "energy",
    "manufacturing & allied": "manufacturing",
    "real estate investment trust": "reit",
    "reits": "reit",
    "exchange traded fund": "etf",
    "etf": "etf",
    "etfs": "etf",
    "index": "indices",
}

#: Sectors whose members are companies with equity that can be valued. Indices,
#: ETFs and REITs are handled separately by the valuation engine.
OPERATING_SECTORS = frozenset(SECTORS) - {"indices", "etf", "reit"}

#: Banks and insurers: no gross profit, interest coverage / asset turnover not
#: applicable, valued on book value and dividends rather than EV/EBITDA.
FINANCIAL_SECTORS = frozenset({"banking", "insurance", "investment_services"})


def sector_code(label: str | None) -> str | None:
    """Normalise a printed sector label; None when the label is unknown or empty."""
    if label is None:
        return None
    key = " ".join(label.replace("&amp;", "&").split()).strip().lower()
    if not key:
        return None
    return LABEL_ALIASES.get(key)


def sector_label(code: str) -> str:
    return SECTORS[code]


__all__ = [
    "FINANCIAL_SECTORS",
    "LABEL_ALIASES",
    "OPERATING_SECTORS",
    "SECTORS",
    "sector_code",
    "sector_label",
]
