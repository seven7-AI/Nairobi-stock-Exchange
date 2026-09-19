"""The NSE's announcements and circulars pages.

Server-rendered WordPress: each item is a ``<h3>`` title next to a ``box-link``
anchor to a PDF under ``/wp-content/uploads/``. The page shows the current year;
earlier years sit behind a JavaScript year filter that is not followed here
(recorded as a limitation). Titles name the company in prose, so the ticker is
resolved by name against the universe - unresolved items are kept unattributed,
never guessed.

    codegraph explore "NseAnnouncementsSource parse_nse_items attribute_ticker"
"""

from __future__ import annotations

import html as html_lib
import re
from collections.abc import Mapping

from app.web.services.corporate.collect.base import (
    DocumentCandidate,
    FetchedDocument,
    SourceHealth,
    fetch_document,
    fiscal_year_of,
    text_of,
)
from app.web.services.corporate.entities.normalise import token_set_ratio, tokens
from app.web.services.corporate.http import PoliteClient

ANNOUNCEMENTS_URL = "https://www.nse.co.ke/listed-company-announcements/"
CIRCULARS_URL = "https://www.nse.co.ke/circulars/"

_ITEM = re.compile(
    r"<h3>(?P<title>.*?)</h3>.*?<a[^>]+href=\"(?P<url>https://www\.nse\.co\.ke/[^\"]+)\"[^>]*class=\"box-link\"",
    re.S,
)
_RESULTS = re.compile(r"\b(audited|unaudited|financial|results|statements)\b", re.I)
# Titles separate the company from the subject with a hyphen, an en dash or an em dash.
_SPLIT = re.compile(
    r"\s*[-\u2013\u2014]\s*|\s+(?:Audited|Unaudited|Financial|Consolidated|Results)\b", re.I
)


def parse_nse_items(page: str) -> list[tuple[str, str]]:
    """(title, url) for every announcement block, in page order."""
    items: list[tuple[str, str]] = []
    seen: set[str] = set()
    for match in _ITEM.finditer(page):
        url = html_lib.unescape(match.group("url").strip())
        title = text_of(match.group("title"))
        if url in seen or not title:
            continue
        seen.add(url)
        items.append((title, url))
    return items


def attribute_ticker(title: str, names: Mapping[str, str]) -> str | None:
    """The ticker whose company name the title starts with, or None.

    ``names`` maps ticker -> canonical name. The leading clause of the title (before a
    dash or a results word) must match one company clearly better than any other.
    """
    lead = _SPLIT.split(title, maxsplit=1)[0].strip()
    if not lead:
        return None
    scored = sorted(
        ((token_set_ratio(lead, name), ticker) for ticker, name in names.items()), reverse=True
    )
    if not scored or scored[0][0] < 0.6:
        return None
    if len(scored) > 1 and scored[1][0] >= scored[0][0] - 0.05 and scored[1][0] >= 0.6:
        return None  # two companies fit about equally: do not guess
    # The lead's own tokens must be mostly present in the company name.
    lead_tokens = tokens(lead)
    name_tokens = tokens(names[scored[0][1]])
    if lead_tokens and len(lead_tokens & name_tokens) / len(lead_tokens) < 0.5:
        return None
    return scored[0][1]


class NseAnnouncementsSource:
    kind = "exchange"
    ticker_symbol: str | None = None

    def __init__(self, names: Mapping[str, str], *, name: str = "nse") -> None:
        self.name = name
        self.base_url = "https://www.nse.co.ke"
        self._names = dict(names)

    def discover(self, client: PoliteClient) -> tuple[list[DocumentCandidate], SourceHealth]:
        found: list[DocumentCandidate] = []
        failures: list[str] = []
        for page_url, default_kind in (
            (ANNOUNCEMENTS_URL, "announcement"),
            (CIRCULARS_URL, "circular"),
        ):
            result = client.get(page_url, max_bytes=5_000_000)
            if not result.ok:
                failures.append(f"{page_url}: {result.status} {result.reason or ''}".strip())
                continue
            for title, url in parse_nse_items(result.content.decode("utf-8", errors="replace")):
                kind = (
                    "results"
                    if default_kind == "announcement" and _RESULTS.search(title)
                    else default_kind
                )
                ticker = (
                    attribute_ticker(title, self._names) if default_kind == "announcement" else None
                )
                found.append(
                    DocumentCandidate(
                        ticker_symbol=ticker,
                        source=self.name,
                        kind=kind,
                        title=title[:300],
                        url=url,
                        page_url=page_url,
                        fiscal_year=fiscal_year_of(title),
                        hints={"attributed": ticker is not None},
                    )
                )
        if failures and not found:
            return [], SourceHealth(self.name, "down", "; ".join(failures)[:500])
        if failures:
            return found, SourceHealth(self.name, "degraded", "; ".join(failures)[:500])
        return found, SourceHealth(self.name, "ok", f"{len(found)} items (current year only)")

    def fetch(
        self,
        candidate: DocumentCandidate,
        client: PoliteClient,
        *,
        etag: str | None,
        last_modified: str | None,
    ) -> FetchedDocument:
        return fetch_document(candidate, client, etag=etag, last_modified=last_modified)


__all__ = [
    "ANNOUNCEMENTS_URL",
    "CIRCULARS_URL",
    "NseAnnouncementsSource",
    "attribute_ticker",
    "parse_nse_items",
]
