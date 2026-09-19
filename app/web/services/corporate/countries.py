"""Country and region normalisation for corporate facts.

Annual reports name countries inconsistently ("DRC", "DR Congo", "Democratic
Republic of the Congo", "Congo (Kinshasa)") and often disclose regions rather than
countries ("Rest of East Africa", "International"). A country becomes an ISO-3166
alpha-2 code; a region becomes a stable slug and the fact that carries it is
``regional_only`` - never spread across the countries it might contain.

A name this module does not know returns ``None``; callers record the raw label
with ``disclosure="not_disclosed"`` or queue it for review. Nothing is guessed.

    codegraph explore "to_iso2 region_slug classify_segment_label"
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from typing import Literal

#: Jurisdiction used when a report names an entity without a country.
UNDISCLOSED_JURISDICTION = "ZZ"

#: Home market of every NSE primary listing unless a profile says otherwise.
HOME_COUNTRY = "KE"

#: ISO2 -> display name, for the countries an NSE-listed group plausibly operates in.
COUNTRY_NAMES: dict[str, str] = {
    "KE": "Kenya",
    "UG": "Uganda",
    "TZ": "Tanzania",
    "RW": "Rwanda",
    "BI": "Burundi",
    "SS": "South Sudan",
    "ET": "Ethiopia",
    "SO": "Somalia",
    "CD": "Democratic Republic of the Congo",
    "ZM": "Zambia",
    "ZW": "Zimbabwe",
    "MW": "Malawi",
    "MZ": "Mozambique",
    "BW": "Botswana",
    "NA": "Namibia",
    "ZA": "South Africa",
    "MU": "Mauritius",
    "SC": "Seychelles",
    "DJ": "Djibouti",
    "ER": "Eritrea",
    "SD": "Sudan",
    "EG": "Egypt",
    "NG": "Nigeria",
    "GH": "Ghana",
    "MA": "Morocco",
    "AE": "United Arab Emirates",
    "GB": "United Kingdom",
    "US": "United States",
    "IN": "India",
    "CN": "China",
    "FR": "France",
    "NL": "Netherlands",
    "JE": "Jersey",
    "KY": "Cayman Islands",
}

#: Alternative spellings, in normalised form (see :func:`_norm`).
_ALIASES: dict[str, str] = {
    "drc": "CD",
    "dr congo": "CD",
    "democratic republic of congo": "CD",
    "democratic republic of the congo": "CD",
    "congo kinshasa": "CD",
    "congo drc": "CD",
    "the democratic republic of the congo": "CD",
    "south sudan": "SS",
    "republic of south sudan": "SS",
    "tanzania": "TZ",
    "united republic of tanzania": "TZ",
    "zanzibar": "TZ",
    "kenya": "KE",
    "republic of kenya": "KE",
    "uganda": "UG",
    "republic of uganda": "UG",
    "rwanda": "RW",
    "republic of rwanda": "RW",
    "burundi": "BI",
    "republic of burundi": "BI",
    "ethiopia": "ET",
    "federal democratic republic of ethiopia": "ET",
    "somalia": "SO",
    "somaliland": "SO",
    "mauritius": "MU",
    "republic of mauritius": "MU",
    "south africa": "ZA",
    "republic of south africa": "ZA",
    "uk": "GB",
    "united kingdom": "GB",
    "england": "GB",
    "england and wales": "GB",
    "britain": "GB",
    "great britain": "GB",
    "usa": "US",
    "united states": "US",
    "united states of america": "US",
    "uae": "AE",
    "dubai": "AE",
    "united arab emirates": "AE",
    "cayman": "KY",
    "cayman islands": "KY",
    "the netherlands": "NL",
    "holland": "NL",
}


#: Region labels a segment note may use instead of countries. Normalised label -> slug.
#: ``home_included`` says whether the region can contain the home market, which
#: decides whether "foreign" aggregates may use it.
@dataclass(frozen=True)
class Region:
    slug: str
    label: str
    home_included: bool


_REGIONS: dict[str, Region] = {
    "rest of east africa": Region("rest_of_east_africa", "Rest of East Africa", False),
    "rest of africa": Region("rest_of_africa", "Rest of Africa", False),
    "rest of the world": Region("rest_of_world", "Rest of the world", False),
    "rest of world": Region("rest_of_world", "Rest of the world", False),
    "international": Region("international", "International", False),
    "international business": Region("international", "International", False),
    "regional": Region("regional", "Regional subsidiaries", False),
    "regional subsidiaries": Region("regional", "Regional subsidiaries", False),
    "regional businesses": Region("regional", "Regional subsidiaries", False),
    "regional operations": Region("regional", "Regional subsidiaries", False),
    "other countries": Region("other_countries", "Other countries", False),
    "other": Region("other", "Other", True),
    "others": Region("other", "Other", True),
    "east africa": Region("east_africa", "East Africa", True),
    "eastern africa": Region("east_africa", "East Africa", True),
    "africa": Region("africa", "Africa", True),
    "sub saharan africa": Region("africa", "Africa", True),
    "europe": Region("europe", "Europe", False),
    "asia": Region("asia", "Asia", False),
    "middle east": Region("middle_east", "Middle East", False),
    "group": Region("group", "Group", True),
    "consolidated": Region("group", "Group", True),
    "total": Region("group", "Group", True),
    "eliminations": Region("eliminations", "Eliminations", True),
    "unallocated": Region("unallocated", "Unallocated", True),
    "head office": Region("head_office", "Head office", True),
}

_PAREN = re.compile(r"\((?:the )?[^)]*\)")
_NON_ALNUM = re.compile(r"[^a-z0-9 ]+")
_SPACES = re.compile(r"\s+")


def _norm(label: str) -> str:
    text = unicodedata.normalize("NFKD", label).encode("ascii", "ignore").decode("ascii")
    text = text.lower().replace("&", " and ")
    text = _NON_ALNUM.sub(" ", text)
    return _SPACES.sub(" ", text).strip()


def to_iso2(label: str | None) -> str | None:
    """Country label -> ISO-3166 alpha-2, or ``None`` when the label is not a known country.

    Accepts codes ("KE"), display names ("Kenya"), and the spellings reports use
    ("DRC", "Congo (Kinshasa)", "Republic of Uganda"). Never guesses.
    """
    if label is None:
        return None
    raw = label.strip()
    if not raw:
        return None
    if len(raw) == 2 and raw.upper() in COUNTRY_NAMES:
        return raw.upper()
    norm = _norm(raw)
    if norm in _ALIASES:
        return _ALIASES[norm]
    # "Congo (Kinshasa)" -> "congo kinshasa" is handled above; strip other parentheticals.
    stripped = _norm(_PAREN.sub(" ", raw))
    if stripped in _ALIASES:
        return _ALIASES[stripped]
    for code, name in COUNTRY_NAMES.items():
        if _norm(name) == stripped:
            return code
    return None


def region_for(label: str | None) -> Region | None:
    """Region label -> :class:`Region`, or ``None`` when it is not a known region."""
    if label is None:
        return None
    norm = _norm(_PAREN.sub(" ", label))
    return _REGIONS.get(norm)


SegmentKind = Literal["country", "region", "unknown"]


@dataclass(frozen=True)
class SegmentLabel:
    """What a row label in a segment note refers to."""

    kind: SegmentKind
    key: str
    label: str
    disclosure: Literal["disclosed", "regional_only", "not_disclosed"]
    home_included: bool


def classify_segment_label(label: str, *, home_country: str = HOME_COUNTRY) -> SegmentLabel:
    """Country rows are ``disclosed``; regions are ``regional_only``; the rest is unknown.

    A region that may contain the home market (``East Africa``, ``Other``) is flagged
    so that foreign aggregates never count it as foreign.
    """
    code = to_iso2(label)
    if code is not None:
        return SegmentLabel("country", code, COUNTRY_NAMES[code], "disclosed", code == home_country)
    region = region_for(label)
    if region is not None:
        return SegmentLabel(
            "region", region.slug, region.label, "regional_only", region.home_included
        )
    key = _norm(label).replace(" ", "_")[:48]
    return SegmentLabel("unknown", key, label.strip(), "not_disclosed", True)


def country_name(code: str) -> str:
    """Display name for a code; unknown codes come back unchanged rather than invented."""
    return COUNTRY_NAMES.get(code, code)


#: Tokens that, when present in a legal name, name its jurisdiction.
COUNTRY_TOKENS: frozenset[str] = frozenset(
    {_norm(name) for name in COUNTRY_NAMES.values()}
    | {alias for alias in _ALIASES if " " not in alias}
)


def jurisdiction_from_name(name: str) -> str | None:
    """Infer a jurisdiction from a country word inside a legal name, else ``None``.

    "KCB Bank Tanzania Limited" -> "TZ"; "Equity Bank (Uganda) Ltd" -> "UG";
    "Jubilee Holdings Limited" -> None (nothing is assumed from an absence).
    """
    norm = _norm(name)
    # Longest alias first so "south sudan" wins over "sudan".
    for alias in sorted(_ALIASES, key=len, reverse=True):
        if re.search(rf"\b{re.escape(alias)}\b", norm):
            return _ALIASES[alias]
    for code, display in COUNTRY_NAMES.items():
        if re.search(rf"\b{re.escape(_norm(display))}\b", norm):
            return code
    return None


__all__ = [
    "COUNTRY_NAMES",
    "COUNTRY_TOKENS",
    "HOME_COUNTRY",
    "UNDISCLOSED_JURISDICTION",
    "Region",
    "SegmentLabel",
    "classify_segment_label",
    "country_name",
    "jurisdiction_from_name",
    "region_for",
    "to_iso2",
]
