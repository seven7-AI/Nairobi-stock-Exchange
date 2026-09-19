"""The shapes every document source produces.

A source *discovers* candidates (what documents a page offers) and *fetches* one.
Discovery is a list of :class:`DocumentCandidate`; identity for a signed download
link is the page it came from plus the link text, so the credential-bearing URL is
never persisted.

    codegraph explore "DocumentCandidate DocumentSource SourceHealth"
"""

from __future__ import annotations

import hashlib
import html as html_lib
import re
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass, field
from datetime import date
from typing import Any, Protocol
from urllib.parse import urljoin, urlsplit

from app.web.services.corporate.http import FetchResult, PoliteClient

_TAGS = re.compile(r"<[^>]+>")
_SPACES = re.compile(r"\s+")
_ANCHOR = re.compile(r"<a\b([^>]*)>(.*?)</a>", re.S | re.I)
_HREF = re.compile(r'href\s*=\s*"([^"]+)"|href\s*=\s*\'([^\']+)\'', re.I)
_SIGNED = re.compile(r"[?&](signature|token|expires|sig|x-amz-signature)=", re.I)
_YEAR = re.compile(r"\b(20\d{2})\b")
#: Markers of a bot-protection challenge served with HTTP 200 instead of the page.
_CHALLENGE = re.compile(r"_Incapsula_Resource|cf-chl|cf_chl_|captcha|Just a moment", re.I)


@dataclass(frozen=True)
class DocumentCandidate:
    ticker_symbol: str | None
    source: str
    kind: str
    title: str
    #: The link as the page gives it (may be signed).
    url: str
    page_url: str
    fiscal_year: int | None = None
    period_end: date | None = None
    published_on: date | None = None
    signed: bool = False
    hints: dict[str, Any] = field(default_factory=dict)

    @property
    def identity_url(self) -> str:
        """Stable across runs: the URL itself, or page + link text for signed links."""
        if not self.signed:
            return self.url
        digest = hashlib.sha256(self.title.strip().lower().encode("utf-8")).hexdigest()[:12]
        return f"{self.page_url}#{digest}"


@dataclass(frozen=True)
class FetchedDocument:
    content: bytes
    content_type: str | None
    etag: str | None
    last_modified: str | None
    final_host: str | None
    status: (
        str  # ok | not_modified | too_large | disallowed | budget_exhausted | http_error | error
    )
    reason: str | None = None


@dataclass(frozen=True)
class SourceHealth:
    name: str
    status: str  # ok | degraded | down | blocked | disabled | untested
    detail: str


class DocumentSource(Protocol):
    name: str
    kind: str
    base_url: str
    ticker_symbol: str | None

    def discover(self, client: PoliteClient) -> tuple[list[DocumentCandidate], SourceHealth]: ...

    def fetch(
        self,
        candidate: DocumentCandidate,
        client: PoliteClient,
        *,
        etag: str | None,
        last_modified: str | None,
    ) -> FetchedDocument: ...


def text_of(fragment: str) -> str:
    return _SPACES.sub(" ", html_lib.unescape(_TAGS.sub(" ", fragment))).strip()


def anchors(page: str, base_url: str) -> list[tuple[str, str, str]]:
    """(absolute href, link text, raw anchor attributes) for every anchor on the page."""
    found: list[tuple[str, str, str]] = []
    for attrs, inner in _ANCHOR.findall(page):
        href = _HREF.search(attrs)
        if not href:
            continue
        raw = href.group(1) or href.group(2) or ""
        found.append((urljoin(base_url, html_lib.unescape(raw.strip())), text_of(inner), attrs))
    return found


def is_signed(url: str) -> bool:
    return bool(_SIGNED.search(url))


def fiscal_year_of(title: str, *, pattern: str | None = None) -> int | None:
    """The fiscal year a title names: the first 20xx, or a custom named-group pattern."""
    if pattern:
        match = re.search(pattern, title)
        if match and match.groupdict().get("fy"):
            return int(match.group("fy"))
        return None
    match = _YEAR.search(title)
    return int(match.group(1)) if match else None


def period_end_for(fiscal_year: int | None, month: int, day: int) -> date | None:
    if fiscal_year is None:
        return None
    return date(fiscal_year, month, day)


def fetch_document(
    candidate: DocumentCandidate,
    client: PoliteClient,
    *,
    etag: str | None,
    last_modified: str | None,
) -> FetchedDocument:
    """The default fetch: a conditional GET through the polite client."""
    result: FetchResult = client.get(candidate.url, etag=etag, last_modified=last_modified)
    return FetchedDocument(
        content=result.content,
        content_type=result.content_type,
        etag=result.etag,
        last_modified=result.last_modified,
        final_host=result.final_host,
        status=result.status,
        reason=result.reason,
    )


def is_challenge_page(page: str) -> bool:
    """A JavaScript / CAPTCHA challenge returned in place of the content."""
    return bool(_CHALLENGE.search(page)) and len(page) < 20_000


def host_of(url: str) -> str:
    return urlsplit(url).netloc.lower()


Matcher = Callable[[str, str], bool]


def select_links(
    page: str,
    page_url: str,
    *,
    href_pattern: str | None,
    text_pattern: str | None,
    exclude_text: str | None = None,
) -> Iterable[tuple[str, str]]:
    """Anchors whose href / text match the patterns (case-insensitive), de-duplicated."""
    href_re = re.compile(href_pattern, re.I) if href_pattern else None
    text_re = re.compile(text_pattern, re.I) if text_pattern else None
    exclude_re = re.compile(exclude_text, re.I) if exclude_text else None
    seen: set[tuple[str, str]] = set()
    for href, text, _ in anchors(page, page_url):
        if href_re and not href_re.search(href):
            continue
        if text_re and not text_re.search(text):
            continue
        if exclude_re and exclude_re.search(text):
            continue
        if not text:
            continue
        key = (href if not is_signed(href) else text.lower(), text.lower())
        if key in seen:
            continue
        seen.add(key)
        yield href, text


def candidate_from(
    *,
    source: str,
    ticker_symbol: str | None,
    kind: str,
    page_url: str,
    href: str,
    text: str,
    fiscal_year_pattern: str | None = None,
    period_end_month: int | None = None,
    period_end_day: int | None = None,
    hints: Mapping[str, Any] | None = None,
) -> DocumentCandidate:
    fiscal_year = fiscal_year_of(text, pattern=fiscal_year_pattern)
    period_end = (
        period_end_for(fiscal_year, period_end_month, period_end_day)
        if period_end_month and period_end_day
        else None
    )
    return DocumentCandidate(
        ticker_symbol=ticker_symbol,
        source=source,
        kind=kind,
        title=text[:300],
        url=href,
        page_url=page_url,
        fiscal_year=fiscal_year,
        period_end=period_end,
        signed=is_signed(href),
        hints=dict(hints or {}),
    )


__all__ = [
    "DocumentCandidate",
    "DocumentSource",
    "FetchedDocument",
    "SourceHealth",
    "anchors",
    "candidate_from",
    "fetch_document",
    "fiscal_year_of",
    "host_of",
    "is_challenge_page",
    "is_signed",
    "period_end_for",
    "select_links",
    "text_of",
]
