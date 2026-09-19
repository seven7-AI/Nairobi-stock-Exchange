"""Parser for the NSE's listed-companies page.

``https://www.nse.co.ke/listed-companies/`` is server-rendered WordPress: one block
per company with the name in an ``<h6>``, a ``Trading Symbol:`` and an
``ISIN CODE:`` line, an optional website link, under an ``<h3>`` sector heading.
The page is a *name and identifier* source: it still lists companies that no longer
trade, so it never delists on its own and never lists on its own.

Pure: the caller fetches, this parses.

    codegraph explore "parse_listed_companies NseListing"
"""

from __future__ import annotations

import html as html_lib
import re
from dataclasses import dataclass

LISTED_COMPANIES_URL = "https://www.nse.co.ke/listed-companies/"

_BLOCK_SPLIT = re.compile(r'(?=<div\s+class="vc_col-sm-3)')
_H3 = re.compile(r"<h3[^>]*>(.*?)</h3>", re.S)
_H6 = re.compile(r"<h6[^>]*>(.*?)</h6>", re.S)
_TAGS = re.compile(r"<[^>]+>")
_SYMBOL = re.compile(r"Trading Symbol\s*:?\s*([A-Z0-9&.\-]+)")
_ISIN = re.compile(r"ISIN CODE\s*:?\s*([A-Z]{2}[A-Z0-9]{9}[0-9])")
_WEBSITE = re.compile(r'<a href="(https?://[^"]+)"[^>]*>\s*<img', re.S)
#: Par-value and market-segment suffixes the page appends to names.
_NAME_SUFFIX = re.compile(
    r"\s*(?:[0O]rd\.?\s*\d+(?:\.\d+)?|Ord\s+Ord\s+\d+(?:\.\d+)?|\d+\.\d+|AIMS|GEMS)\s*$",
    re.I,
)
_SPACES = re.compile(r"\s+")


@dataclass(frozen=True)
class NseListing:
    """One company block as the page shows it."""

    name_raw: str
    name: str
    symbol: str | None
    isin: str | None
    website: str | None
    sector_heading: str | None


def clean_name(raw: str) -> str:
    """Strip the par-value suffix: ``KCB Group Ltd Ord 1.00`` -> ``KCB Group Ltd``."""
    text = _SPACES.sub(" ", html_lib.unescape(_TAGS.sub("", raw))).strip()
    previous = None
    while previous != text:
        previous = text
        text = _NAME_SUFFIX.sub("", text).strip()
    return text


def parse_listed_companies(page: str) -> list[NseListing]:
    """Every company block, in page order, duplicates included (the page repeats some)."""
    listings: list[NseListing] = []
    sector: str | None = None
    for fragment in _BLOCK_SPLIT.split(page):
        text = html_lib.unescape(_TAGS.sub(" ", fragment))
        block_heading = _H6.search(fragment)
        if block_heading is not None:
            symbol = _SYMBOL.search(text)
            isin = _ISIN.search(text)
            website = _WEBSITE.search(fragment)
            raw = _SPACES.sub(" ", html_lib.unescape(_TAGS.sub("", block_heading.group(1)))).strip()
            listings.append(
                NseListing(
                    name_raw=raw,
                    name=clean_name(raw),
                    symbol=symbol.group(1).strip().upper() if symbol else None,
                    isin=isin.group(1) if isin else None,
                    website=website.group(1) if website else None,
                    sector_heading=sector,
                )
            )
        # Sector headings sit at the tail of the previous block's fragment or on
        # their own; whichever heading was seen last applies to what follows.
        for heading in _H3.findall(fragment):
            label = _SPACES.sub(" ", html_lib.unescape(_TAGS.sub("", heading))).strip()
            if label and label.upper() == label and "QUICK" not in label:
                sector = label
    return listings


def dedupe_listings(listings: list[NseListing]) -> dict[str, NseListing]:
    """Symbol -> listing; the page repeats blocks, the first occurrence wins."""
    by_symbol: dict[str, NseListing] = {}
    for listing in listings:
        if listing.symbol and listing.symbol not in by_symbol:
            by_symbol[listing.symbol] = listing
    return by_symbol


__all__ = [
    "LISTED_COMPANIES_URL",
    "NseListing",
    "clean_name",
    "dedupe_listings",
    "parse_listed_companies",
]
