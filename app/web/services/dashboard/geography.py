"""Geographic exposure from the scraper's company page.

The page carries a home ``country`` and a business ``description`` that, for the
groups that operate regionally, names the countries they work in. That is what we
have - an observation from prose, not a revenue split - and the block says so. A
ticker whose profile predates the company-page capture is ``unavailable`` with the
reason; nothing is inferred.

    codegraph explore "geographic_block operating_countries COUNTRY_NAMES"
"""

from __future__ import annotations

import re
from typing import Any

from app.web.services.dashboard.common import measure

#: Countries an NSE-listed group plausibly names; matched as whole words in the
#: description. Kept short and explicit - a miss is an omission, never an invention.
COUNTRY_NAMES: tuple[str, ...] = (
    "Kenya",
    "Uganda",
    "Tanzania",
    "Rwanda",
    "Burundi",
    "South Sudan",
    "Ethiopia",
    "Somalia",
    "Democratic Republic of Congo",
    "Democratic Republic of the Congo",
    "DR Congo",
    "Zambia",
    "Zimbabwe",
    "Malawi",
    "Mozambique",
    "Botswana",
    "Namibia",
    "South Africa",
    "Mauritius",
    "Seychelles",
    "Madagascar",
    "Nigeria",
    "Ghana",
    "Egypt",
    "Morocco",
    "Angola",
    "Eritrea",
    "Djibouti",
    "Sudan",
    "Cameroon",
    "Ivory Coast",
    "Côte d'Ivoire",
    "Senegal",
    "Togo",
    "Benin",
    "Mali",
    "Niger",
    "United Kingdom",
    "United States",
    "India",
    "China",
    "United Arab Emirates",
    "Dubai",
    "Germany",
    "France",
    "Netherlands",
    "Switzerland",
)
_ALIASES = {
    "Democratic Republic of the Congo": "Democratic Republic of Congo",
    "DR Congo": "Democratic Republic of Congo",
    "Côte d'Ivoire": "Ivory Coast",
    "Dubai": "United Arab Emirates",
}
NOT_CAPTURED = (
    "no company page captured for this instrument yet (the scraper adds it on its "
    "rotating slice); the quote page carries industry, founding year and headcount only"
)
NOTE = (
    "countries are the ones named in the company's business description on "
    "stockanalysis.com - an observation from prose, not a revenue or asset split, "
    "which the source does not publish"
)


def operating_countries(description: str | None) -> list[str]:
    """Country names that appear in the description, in order of first mention."""
    if not description:
        return []
    hits: list[tuple[int, str]] = []
    text = description
    # longest names first, blanking each match so "South Sudan" never also yields "Sudan"
    for name in sorted(COUNTRY_NAMES, key=len, reverse=True):
        pattern = re.compile(r"(?<![A-Za-z])" + re.escape(name) + r"(?![A-Za-z])")
        match = pattern.search(text)
        if match:
            hits.append((match.start(), _ALIASES.get(name, name)))
            text = pattern.sub(" " * len(name), text)
    found: list[str] = []
    for _, canonical in sorted(hits):
        if canonical not in found:
            found.append(canonical)
    return found


def geographic_block(profile: dict[str, Any] | None) -> dict[str, Any]:
    """The dashboard's geographic block from a scraped profile view."""
    profile = profile or {}
    country = profile.get("country")
    description = profile.get("description")
    if not country and not description:
        return {
            "status": "unavailable",
            "reason": NOT_CAPTURED,
            "home_country": None,
            "operating_countries": [],
            "description": None,
            "note": NOTE,
            "segments": [],
        }
    countries = operating_countries(description)
    if country and country not in countries:
        countries.insert(0, country)
    return {
        "status": "known",
        "reason": None,
        "home_country": country,
        "operating_countries": countries,
        "description": description,
        "note": NOTE,
        "segments": [],  # no revenue / asset split exists at the source
        "coverage": measure(float(len(countries)), "known", None),
    }


__all__ = ["COUNTRY_NAMES", "NOTE", "NOT_CAPTURED", "geographic_block", "operating_countries"]
