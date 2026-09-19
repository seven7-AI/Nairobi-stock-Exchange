"""Build + persist the universe: the one call the CLI and the jobs make.

Reads the scraper's instrument master, aliases, observation spans and profile
rows; fetches the NSE listed-companies page (unless told not to); records every
sighting; then runs the pure builder and upserts the result.

    codegraph explore "refresh_universe build_universe upsert_companies"
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from app.web.config import Settings
from app.web.db.analytics import analytics_session
from app.web.db.analytics.services.classifications import load_classifications
from app.web.db.analytics.services.corporate_companies import (
    SightingRow,
    last_sighting_per_ticker,
    load_companies,
    record_sightings,
    source_runs,
    upsert_companies,
)
from app.web.services.analytics.classification.lookup import ClassificationIndex
from app.web.services.corporate.config import DEFAULT_CORPORATE_CONFIG, CorporateConfig
from app.web.services.corporate.http import PoliteClient, polite_client_from_settings
from app.web.services.corporate.universe.builder import (
    PageHistory,
    PriorCompany,
    UniverseInputs,
    UniverseReport,
    build_universe,
    page_symbol_key,
)
from app.web.services.corporate.universe.nse_page import (
    LISTED_COMPANIES_URL,
    NseListing,
    dedupe_listings,
    parse_listed_companies,
)
from app.web.services.market_data.sources.nse_scraper import NseScraperSource
from app.web.utils.logger import get_logger

logger = get_logger("app.web.services.corporate.universe")

PAGE_SOURCE = "nse_listed_page"


@dataclass(frozen=True)
class UniverseResult:
    created: int
    updated: int
    unchanged: int
    companies: int
    status_changes: dict[str, tuple[str | None, str]]
    unmatched_listings: tuple[str, ...]
    page: str
    sightings_recorded: int
    warnings: tuple[str, ...] = field(default_factory=tuple)


def fetch_listings(
    client: PoliteClient, url: str = LISTED_COMPANIES_URL
) -> tuple[dict[str, NseListing], str]:
    """The page's listings by symbol, plus a one-line account of the fetch."""
    result = client.get(url, max_bytes=5_000_000)
    if not result.ok:
        return {}, f"{result.status}: {result.reason or 'no body'}"
    listings = parse_listed_companies(result.content.decode("utf-8", errors="replace"))
    if not listings:
        return {}, "fetched but no company blocks were found (page layout changed?)"
    return dedupe_listings(listings), f"fetched {len(listings)} blocks"


def _page_history(
    runs: list[datetime],
    last_seen: dict[str, datetime],
    tickers: set[str],
) -> dict[str, PageHistory]:
    """Per ticker: named on the latest page run? how many runs since it last was?

    The current fetch has already been recorded as a sighting, so "on the page" is
    "named on the latest run" whether that run happened now or on an earlier day
    (``--no-network`` reuses it).
    """
    total = len(runs)
    latest = runs[-1] if runs else None
    history: dict[str, PageHistory] = {}
    for ticker in tickers | set(last_seen):
        seen = last_seen.get(ticker)
        if latest is not None and seen == latest:
            history[ticker] = PageHistory(True, 0, total)
            continue
        missing = total if seen is None else sum(1 for run in runs if run > seen)
        history[ticker] = PageHistory(False, missing, total)
    return history


def refresh_universe(
    settings: Settings,
    source: NseScraperSource,
    *,
    client: PoliteClient | None = None,
    network: bool = True,
    config: CorporateConfig = DEFAULT_CORPORATE_CONFIG,
    now: datetime | None = None,
) -> UniverseResult:
    """Rebuild ``corporate_companies`` from the evidence available today."""
    stamp = now or datetime.now(UTC)
    today = stamp.date()
    warnings: list[str] = []

    instruments = source.fetch_instruments()
    aliases = source.fetch_instrument_aliases()
    spans = source.fetch_observation_spans()
    profiles: dict[str, dict[str, Any]] = {}
    for row in source.fetch_latest_rows(limit=5000):
        profile = row.get("profile_metrics") or {}
        if profile:
            profiles[str(row["ticker_symbol"]).upper()] = dict(profile)

    listings: dict[str, NseListing] = {}
    page_note = "not fetched (--no-network)"
    if network:
        own_client = client is None
        http = client or polite_client_from_settings(settings)
        try:
            listings, page_note = fetch_listings(http)
        finally:
            if own_client:
                http.close()
        if not listings:
            warnings.append(f"NSE listed-companies page: {page_note}")

    with analytics_session(settings) as session:
        sightings: list[SightingRow] = []
        for instrument in instruments:
            sightings.append(
                SightingRow(
                    str(instrument["ticker_symbol"]),
                    "scraper_instruments",
                    {
                        "company_name": instrument.get("company_name"),
                        "instrument_type": instrument.get("instrument_type"),
                        "sector": instrument.get("sector"),
                        "last_seen_date": instrument.get("last_seen_date"),
                    },
                )
            )
        for ticker, profile in profiles.items():
            if profile.get("country") or profile.get("website"):
                sightings.append(
                    SightingRow(
                        ticker,
                        "stockanalysis_profile",
                        {"country": profile.get("country"), "website": profile.get("website")},
                    )
                )
        known_tickers = {str(i["ticker_symbol"]).upper() for i in instruments}
        alias_map = {
            str(a["source_ticker"]).upper(): str(a["canonical_ticker"]).upper() for a in aliases
        }
        current_page: set[str] = set()
        for symbol, listing in listings.items():
            key = page_symbol_key(symbol)
            ticker = key if key in known_tickers else alias_map.get(key, key)
            current_page.add(ticker)
            sightings.append(
                SightingRow(
                    ticker,
                    PAGE_SOURCE,
                    {
                        "name": listing.name_raw,
                        "symbol": listing.symbol,
                        "isin": listing.isin,
                        "website": listing.website,
                        "sector_heading": listing.sector_heading,
                    },
                )
            )
        recorded = record_sightings(session, sightings, seen_at=stamp)

        runs = source_runs(session, PAGE_SOURCE)
        last_seen = last_sighting_per_ticker(session, PAGE_SOURCE)
        page_history = _page_history(runs, last_seen, known_tickers | current_page)

        prior = {
            row.ticker_symbol: PriorCompany(
                listing_status=row.listing_status,
                delisted_on=row.delisted_on,
                name_history=tuple(row.name_history),
                status_history=tuple(row.status_history),
                field_sources=dict(row.field_sources),
                lei=row.lei,
                legal_name=row.legal_name,
                registration_number=row.registration_number,
            )
            for row in load_companies(session)
        }
        classifications = load_classifications(session)
        sectors = ClassificationIndex(classifications) if classifications else None
        if sectors is None:
            warnings.append("no classifications in the store; sector_code left empty")

        report: UniverseReport = build_universe(
            UniverseInputs(
                instruments=instruments,
                aliases=aliases,
                spans=spans,
                profiles=profiles,
                listings=listings,
                page_history=page_history,
                prior=prior,
                sectors=sectors,
                today=today,
            ),
            config,
        )
        outcomes = upsert_companies(session, report.records, now=stamp)

    counts = {"created": 0, "updated": 0, "unchanged": 0}
    for outcome in outcomes.values():
        counts[outcome] += 1
    logger.info(
        "corporate_universe_refreshed",
        companies=len(report.records),
        page=page_note,
        status_changes=len(report.status_changes),
        **counts,
    )
    return UniverseResult(
        created=counts["created"],
        updated=counts["updated"],
        unchanged=counts["unchanged"],
        companies=len(report.records),
        status_changes=dict(report.status_changes),
        unmatched_listings=tuple(
            f"{listing.symbol or '?'} {listing.name!r}: {why}"
            for listing, why in report.unmatched_listings
        ),
        page=page_note,
        sightings_recorded=recorded,
        warnings=tuple(warnings),
    )


__all__ = ["PAGE_SOURCE", "UniverseResult", "fetch_listings", "refresh_universe"]
