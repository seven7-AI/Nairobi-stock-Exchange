"""Build the company universe from evidence. Pure apart from its inputs.

One :class:`CompanyRecord` per listed company (ordinary shares, REITs, ETFs;
preference shares fold into their parent; indices and rights are not companies).
Every field is chosen from a hierarchy of sources and carries the source, its
confidence and the evidence in ``field_sources`` - a later, better source (GLEIF in
C2) replaces a field by out-ranking it, never by overwriting silently.

    codegraph explore "build_universe CompanyRecord UniverseReport listing_status"
"""

from __future__ import annotations

import re
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import date
from typing import Any

from app.web.services.analytics.classification.lookup import ClassificationIndex
from app.web.services.corporate.config import CorporateConfig
from app.web.services.corporate.countries import HOME_COUNTRY, to_iso2
from app.web.services.corporate.universe.nse_page import NseListing
from app.web.services.corporate.universe.rules import (
    Announcement,
    StatusEvidence,
    listing_status,
)

#: Instrument types that are companies (or funds) in their own right.
COMPANY_TYPES: frozenset[str] = frozenset({"ordinary", "reit", "etf"})

_SHARE_CLASS_SUFFIX = re.compile(r"\.[A-Z]\d{4}$")
_ISIN = re.compile(r"^[A-Z]{2}[A-Z0-9]{9}\d$")
_NON_WORD = re.compile(r"[^a-z0-9 ]+")
_STOP = frozenset({"ltd", "limited", "plc", "co", "company", "the", "group", "holdings", "of"})


@dataclass(frozen=True)
class FieldSource:
    source: str
    confidence: float
    evidence: str

    def as_dict(self) -> dict[str, Any]:
        return {"source": self.source, "confidence": self.confidence, "evidence": self.evidence}


@dataclass(frozen=True)
class PageHistory:
    """What the NSE page sightings say about one ticker."""

    on_page: bool
    runs_missing: int
    runs_total: int


@dataclass(frozen=True)
class PriorCompany:
    """The stored row, as far as the builder needs it."""

    listing_status: str
    delisted_on: date | None
    name_history: tuple[dict[str, Any], ...]
    status_history: tuple[dict[str, Any], ...]
    field_sources: dict[str, dict[str, Any]]
    lei: str | None = None
    legal_name: str | None = None
    registration_number: str | None = None


@dataclass(frozen=True)
class CompanyRecord:
    ticker_symbol: str
    canonical_name: str
    legal_name: str | None
    instrument_type: str
    sector_code: str | None
    home_country: str
    isin: str | None
    lei: str | None
    registration_number: str | None
    exchange_ids: dict[str, str]
    website: str | None
    ir_url: str | None
    listing_status: str
    status_reason: str
    first_listed: date | None
    delisted_on: date | None
    name_history: tuple[dict[str, Any], ...]
    status_history: tuple[dict[str, Any], ...]
    field_sources: dict[str, dict[str, Any]]
    confidence: float


@dataclass(frozen=True)
class UniverseReport:
    records: tuple[CompanyRecord, ...]
    #: Page listings that matched no instrument, with the reason.
    unmatched_listings: tuple[tuple[NseListing, str], ...] = field(default_factory=tuple)
    #: ticker -> (previous status, new status) where the status moved.
    status_changes: dict[str, tuple[str | None, str]] = field(default_factory=dict)


@dataclass(frozen=True)
class UniverseInputs:
    instruments: Sequence[Mapping[str, Any]]
    aliases: Sequence[Mapping[str, Any]]
    spans: Mapping[str, tuple[date, date, int]]
    #: ticker -> stockanalysis ``profile_metrics`` (from the scraper's database).
    profiles: Mapping[str, Mapping[str, Any]]
    #: NSE page listings by (normalised) symbol; empty when the page was not fetched.
    listings: Mapping[str, NseListing]
    page_history: Mapping[str, PageHistory]
    prior: Mapping[str, PriorCompany]
    sectors: ClassificationIndex | None
    today: date
    announcements: Sequence[Announcement] = ()


def page_symbol_key(symbol: str) -> str:
    """``SKL.O0000`` -> ``SKL``: the page appends a share-class code to some symbols."""
    return _SHARE_CLASS_SUFFIX.sub("", symbol.strip().upper())


def _tokens(name: str) -> frozenset[str]:
    text = _NON_WORD.sub(" ", name.lower().replace("&", " and "))
    return frozenset(t for t in text.split() if t and t not in _STOP)


def _name_similarity(a: str, b: str) -> float:
    ta, tb = _tokens(a), _tokens(b)
    if not ta or not tb:
        return 0.0
    return len(ta & tb) / len(ta | tb)


def match_listings(
    listings: Mapping[str, NseListing],
    instruments: Sequence[Mapping[str, Any]],
    aliases: Sequence[Mapping[str, Any]],
) -> tuple[dict[str, tuple[NseListing, FieldSource]], list[tuple[NseListing, str]]]:
    """Page listing -> instrument ticker: by symbol, then alias, then a unique name match."""
    tickers = {str(i["ticker_symbol"]).upper() for i in instruments}
    alias_to_canonical = {
        str(a["source_ticker"]).upper(): str(a["canonical_ticker"]).upper() for a in aliases
    }
    names = {str(i["ticker_symbol"]).upper(): str(i["company_name"]) for i in instruments}
    matched: dict[str, tuple[NseListing, FieldSource]] = {}
    unmatched: list[tuple[NseListing, str]] = []
    for symbol, listing in listings.items():
        key = page_symbol_key(symbol)
        if key in tickers:
            matched[key] = (
                listing,
                FieldSource("nse_listed_page", 1.0, f"trading symbol {symbol}"),
            )
            continue
        if key in alias_to_canonical:
            canonical = alias_to_canonical[key]
            matched[canonical] = (
                listing,
                FieldSource(
                    "nse_listed_page", 0.95, f"trading symbol {symbol} aliased to {canonical}"
                ),
            )
            continue
        scored = sorted(
            ((_name_similarity(listing.name, name), ticker) for ticker, name in names.items()),
            reverse=True,
        )
        if scored and scored[0][0] >= 0.9 and (len(scored) == 1 or scored[1][0] < 0.9):
            ticker = scored[0][1]
            matched[ticker] = (
                listing,
                FieldSource(
                    "nse_listed_page", 0.8, f"name '{listing.name}' matched {names[ticker]!r}"
                ),
            )
            continue
        unmatched.append((listing, f"symbol {symbol} is not a scraper instrument or alias"))
    return matched, unmatched


def _putter(sources: dict[str, dict[str, Any]]) -> Callable[[str, FieldSource], None]:
    def put(name: str, source: FieldSource) -> None:
        sources[name] = source.as_dict()

    return put


def _history_entry(**values: Any) -> dict[str, Any]:
    return {k: (v.isoformat() if isinstance(v, date) else v) for k, v in values.items()}


def build_universe(inputs: UniverseInputs, config: CorporateConfig) -> UniverseReport:
    """One record per company, every field sourced, statuses decided by the rules."""
    matched, unmatched = match_listings(inputs.listings, inputs.instruments, inputs.aliases)
    aliases_for: dict[str, list[Mapping[str, Any]]] = {}
    for alias in inputs.aliases:
        aliases_for.setdefault(str(alias["canonical_ticker"]).upper(), []).append(alias)
    parents_of_preference: dict[str, list[str]] = {}
    for instrument in inputs.instruments:
        if instrument.get("instrument_type") == "preference" and instrument.get("parent_ticker"):
            parents_of_preference.setdefault(str(instrument["parent_ticker"]).upper(), []).append(
                str(instrument["ticker_symbol"])
            )

    records: list[CompanyRecord] = []
    changes: dict[str, tuple[str | None, str]] = {}
    today_text = inputs.today.isoformat()
    for instrument in inputs.instruments:
        kind = str(instrument.get("instrument_type") or "ordinary")
        if kind not in COMPANY_TYPES:
            continue
        ticker = str(instrument["ticker_symbol"]).upper()
        prior = inputs.prior.get(ticker)
        sources: dict[str, dict[str, Any]] = dict(prior.field_sources) if prior else {}
        put = _putter(sources)

        scraper_name = str(instrument["company_name"]).strip()
        put("ticker_symbol", FieldSource("scraper_instruments", 1.0, "instrument master"))
        canonical_name = scraper_name
        put("canonical_name", FieldSource("scraper_instruments", 0.9, "instrument master"))

        listing = matched.get(ticker)
        page = listing[0] if listing else None

        # Legal name: GLEIF (C2, 1.0) beats the page (0.7) beats the scraper (0.6).
        legal_name: str | None
        prior_legal = sources.get("legal_name", {})
        if prior and prior.lei and prior_legal.get("source") == "gleif":
            legal_name = prior.legal_name
        elif page is not None:
            legal_name = page.name
            put("legal_name", FieldSource("nse_listed_page", 0.7, f"page name {page.name_raw!r}"))
        else:
            legal_name = scraper_name
            put("legal_name", FieldSource("scraper_instruments", 0.6, "instrument master"))

        # Sector from the classification stints the rest of the engine uses.
        sector_code: str | None = None
        if inputs.sectors is not None:
            stint = inputs.sectors.sector_for(ticker, inputs.today)
            if stint is not None:
                sector_code = stint.sector_code
                put("sector_code", FieldSource("classifications", 0.95, stint.source))
        if sector_code is None and page is not None and page.sector_heading:
            put(
                "sector_code",
                FieldSource(
                    "nse_listed_page", 0.0, f"unclassified; page heading {page.sector_heading!r}"
                ),
            )

        # Home country: the stockanalysis profile, else the exchange's country - assumed.
        profile = inputs.profiles.get(ticker) or {}
        home = to_iso2(str(profile.get("country") or "")) if profile.get("country") else None
        if home is not None:
            put(
                "home_country",
                FieldSource(
                    "stockanalysis_profile", 0.8, f"profile country {profile['country']!r}"
                ),
            )
        else:
            home = HOME_COUNTRY
            put(
                "home_country",
                FieldSource("assumed", 0.5, "primary NSE listing; no profile country captured"),
            )

        isin: str | None = None
        if page is not None and page.isin and _ISIN.match(page.isin):
            isin = page.isin
            put("isin", FieldSource("nse_listed_page", 0.9, f"ISIN CODE line for {page.symbol}"))

        website: str | None = None
        if profile.get("website"):
            website = str(profile["website"])
            put("website", FieldSource("stockanalysis_profile", 0.8, "profile website"))
        elif page is not None and page.website:
            website = page.website
            put(
                "website",
                FieldSource("nse_listed_page", 0.7, "logo link on the listed-companies page"),
            )

        exchange_ids = {"NSE": ticker}
        for pref in parents_of_preference.get(ticker, []):
            exchange_ids[f"NSE:{pref}"] = pref

        # Name history: ticker lineage the scraper resolved, appended once each.
        history = list(prior.name_history) if prior else []
        known = {(h.get("ticker"), h.get("reason")) for h in history}
        for alias in aliases_for.get(ticker, []):
            key = (str(alias["source_ticker"]), str(alias["reason"]))
            if key not in known:
                history.append(
                    _history_entry(
                        ticker=alias["source_ticker"],
                        reason=alias["reason"],
                        evidence=alias["evidence"],
                        source="scraper_instrument_aliases",
                        recorded=today_text,
                    )
                )
                known.add(key)

        span = inputs.spans.get(ticker)
        page_history = inputs.page_history.get(ticker)
        first_seen = None
        if instrument.get("first_seen_date"):
            first_seen = date.fromisoformat(str(instrument["first_seen_date"]))
        decision = listing_status(
            StatusEvidence(
                ticker_symbol=ticker,
                today=inputs.today,
                on_page=page_history.on_page if page_history else page is not None,
                page_runs_missing=page_history.runs_missing if page_history else 0,
                page_runs_total=page_history.runs_total
                if page_history
                else (1 if inputs.listings else 0),
                first_observation=span[0] if span else first_seen,
                last_observation=span[1]
                if span
                else (
                    date.fromisoformat(str(instrument["last_seen_date"]))
                    if instrument.get("last_seen_date")
                    else None
                ),
                previous_status=prior.listing_status if prior else None,
                previous_delisted_on=prior.delisted_on if prior else None,
                announcements=tuple(a for a in inputs.announcements if a.ticker_symbol == ticker),
            ),
            config,
        )
        status_history = list(prior.status_history) if prior else []
        previous_status = prior.listing_status if prior else None
        if previous_status != decision.status:
            status_history.append(
                _history_entry(
                    status=decision.status,
                    from_status=previous_status,
                    reason=decision.reason,
                    recorded=today_text,
                )
            )
            changes[ticker] = (previous_status, decision.status)
        put("listing_status", FieldSource("rules", 1.0, decision.reason))

        identity = ("ticker_symbol", "canonical_name", "legal_name", "home_country")
        confidence = min(float(sources[f]["confidence"]) for f in identity)
        records.append(
            CompanyRecord(
                ticker_symbol=ticker,
                canonical_name=canonical_name,
                legal_name=legal_name,
                instrument_type=kind,
                sector_code=sector_code,
                home_country=home,
                isin=isin,
                lei=prior.lei if prior else None,
                registration_number=prior.registration_number if prior else None,
                exchange_ids=exchange_ids,
                website=website,
                ir_url=None,
                listing_status=decision.status,
                status_reason=decision.reason,
                first_listed=decision.first_listed,
                delisted_on=decision.delisted_on,
                name_history=tuple(history),
                status_history=tuple(status_history),
                field_sources=sources,
                confidence=confidence,
            )
        )
    return UniverseReport(tuple(records), tuple(unmatched), changes)


__all__ = [
    "COMPANY_TYPES",
    "CompanyRecord",
    "FieldSource",
    "PageHistory",
    "PriorCompany",
    "UniverseInputs",
    "UniverseReport",
    "build_universe",
    "match_listings",
    "page_symbol_key",
]
