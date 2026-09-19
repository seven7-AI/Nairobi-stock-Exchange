"""Listed-company entities and GLEIF enrichment: the calls the CLI and jobs make.

codegraph explore "sync_gleif ensure_listed_entities GleifClient resolve"
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from sqlalchemy.orm import Session

from app.web.config import Settings
from app.web.db.analytics import analytics_session
from app.web.db.analytics.models.corporate_company import CorporateCompany
from app.web.db.analytics.models.corporate_entity import CorporateEntity
from app.web.db.analytics.services.corporate_companies import load_companies
from app.web.db.analytics.services.corporate_entities import find_by_lei, find_listed, load_entities
from app.web.services.corporate.config import DEFAULT_CORPORATE_CONFIG, CorporateConfig
from app.web.services.corporate.entities.gleif import GleifClient, LeiRecord
from app.web.services.corporate.entities.normalise import (
    distinguishing_difference,
    normalise,
    token_set_ratio,
)
from app.web.services.corporate.entities.resolver import EntityMention, resolve
from app.web.services.corporate.http import PoliteClient, polite_client_from_settings
from app.web.utils.logger import get_logger

logger = get_logger("app.web.services.corporate.entities")

#: GLEIF registration statuses that still identify a real entity.
_LIVE_STATUSES = frozenset({"ISSUED", "LAPSED", "PENDING_TRANSFER", "PENDING_ARCHIVAL"})


@dataclass(frozen=True)
class GleifSyncResult:
    companies: int
    matched: int
    unmatched: int
    unchanged: int
    ambiguous: tuple[str, ...] = field(default_factory=tuple)
    errors: tuple[str, ...] = field(default_factory=tuple)
    requests: int = 0
    cache_hits: int = 0
    entities_created: int = 0


def ensure_listed_entities(
    session: Session,
    companies: list[CorporateCompany],
    *,
    config: CorporateConfig = DEFAULT_CORPORATE_CONFIG,
    now: datetime | None = None,
) -> tuple[dict[str, CorporateEntity], int]:
    """One ``listed`` entity per company via the ladder. Returns (by ticker, created)."""
    stamp = now or datetime.now(UTC)
    created = 0
    by_ticker: dict[str, CorporateEntity] = {}
    for company in companies:
        existing = find_listed(session, company.ticker_symbol)
        if existing is not None:
            by_ticker[company.ticker_symbol] = existing
            continue
        resolution = resolve(
            session,
            EntityMention(
                name=company.legal_name or company.canonical_name,
                jurisdiction=company.home_country,
                lei=company.lei,
                isin=company.isin,
                registration_number=company.registration_number,
                exchange_id=("NSE", company.ticker_symbol),
                entity_type="listed",
                group_ticker=company.ticker_symbol,
                source_ref={"table": "corporate_companies", "ticker": company.ticker_symbol},
            ),
            config,
            now=stamp,
        )
        row = load_entities(session, [resolution.entity_id])[resolution.entity_id]
        row.listed_ticker = company.ticker_symbol
        row.entity_type = "listed"
        row.identifiers = {**row.identifiers, "exchange": {"NSE": company.ticker_symbol}}
        if company.isin:
            row.identifiers = {**row.identifiers, "isin": company.isin}
        created += int(resolution.created)
        by_ticker[company.ticker_symbol] = row
    session.flush()
    return by_ticker, created


def _search_names(company: CorporateCompany) -> list[str]:
    names: list[str] = []
    seen: set[str] = set()
    for candidate in (company.legal_name, company.canonical_name):
        if not candidate:
            continue
        key = normalise(candidate)
        if key and key not in seen:
            seen.add(key)
            names.append(candidate)
    return names


def match_record(name: str, records: tuple[LeiRecord, ...]) -> tuple[LeiRecord | None, str, float]:
    """Pick the GLEIF record for a company name: exact normalised name, else a fenced near match."""
    live = [r for r in records if r.registration_status in _LIVE_STATUSES]
    target = normalise(name)
    for record in live:
        aliases = {normalise(record.legal_name), *(normalise(o) for o in record.other_names)}
        if target in aliases:
            return record, "exact", 1.0
    scored = sorted(
        ((token_set_ratio(name, r.legal_name), r) for r in live), key=lambda x: x[0], reverse=True
    )
    if (
        scored
        and scored[0][0] >= 0.95
        and not distinguishing_difference(name, scored[0][1].legal_name)
        and (len(scored) == 1 or scored[1][0] < 0.8)
    ):
        return scored[0][1], "near", 0.85
    return None, "none", 0.0


def _apply_match(
    session: Session,
    company: CorporateCompany,
    entity: CorporateEntity,
    record: LeiRecord,
    how: str,
    confidence: float,
    today: str,
) -> bool:
    """Write the LEI onto the company and its entity. Returns whether anything changed."""
    evidence = (
        f"GLEIF {record.lei} {record.legal_name!r} registered as {record.registered_as or '-'} "
        f"({record.registration_status}, {how} name match, checked {today})"
    )
    other = find_by_lei(session, record.lei)
    if other is not None and other.id != entity.id:
        logger.warning(
            "gleif_lei_already_on_another_entity",
            ticker=company.ticker_symbol,
            entity_id=other.id,
        )
        return False
    changed = False
    sources = dict(company.field_sources)
    if company.lei != record.lei:
        company.lei = record.lei
        changed = True
    sources["lei"] = {"source": "gleif", "confidence": confidence, "evidence": evidence}
    if how == "exact" and company.legal_name != record.legal_name:
        company.legal_name = record.legal_name
        changed = True
    if how == "exact":
        sources["legal_name"] = {"source": "gleif", "confidence": 1.0, "evidence": evidence}
    if record.registered_as and company.registration_number != record.registered_as:
        company.registration_number = record.registered_as
        sources["registration_number"] = {
            "source": "gleif",
            "confidence": confidence,
            "evidence": evidence,
        }
        changed = True
    if sources != company.field_sources:
        company.field_sources = sources
        changed = True
    if entity.lei != record.lei:
        entity.lei = record.lei
        entity.registration_number = record.registered_as or entity.registration_number
        entity.legal_name = record.legal_name if how == "exact" else entity.legal_name
        entity.resolution_method = "lei"
        entity.confidence = max(entity.confidence, confidence)
        entity.identifiers = {
            **entity.identifiers,
            "gleif": {
                "lei": record.lei,
                "registered_as": record.registered_as,
                "registration_status": record.registration_status,
                "entity_status": record.entity_status,
                "last_update": record.last_update,
            },
            "gleif_checked_at": today,
        }
        changed = True
    return changed


def sync_gleif(
    settings: Settings,
    *,
    tickers: list[str] | None = None,
    client: PoliteClient | None = None,
    gleif: GleifClient | None = None,
    config: CorporateConfig = DEFAULT_CORPORATE_CONFIG,
    now: datetime | None = None,
) -> GleifSyncResult:
    """Look every company up on GLEIF; write LEIs, legal names and registration numbers."""
    stamp = now or datetime.now(UTC)
    today = stamp.date().isoformat()
    own_client = client is None and gleif is None
    http = client or polite_client_from_settings(settings)
    api = gleif or GleifClient(
        http,
        settings.corporate_cache_dir / "gleif",
        base_url=settings.corporate_gleif_base_url,
        now=lambda: stamp,
    )
    matched = unmatched = unchanged = 0
    ambiguous: list[str] = []
    errors: list[str] = []
    try:
        with analytics_session(settings) as session:
            companies = load_companies(session, tickers=tickers)
            entities, created = ensure_listed_entities(session, companies, config=config, now=stamp)
            for company in companies:
                entity = entities[company.ticker_symbol]
                record: LeiRecord | None = None
                how, confidence = "none", 0.0
                failed = False
                for name in _search_names(company):
                    response = api.search(fulltext=normalise(name), country=company.home_country)
                    if response.status == "error":
                        errors.append(f"{company.ticker_symbol}: {response.reason}")
                        failed = True
                        break
                    record, how, confidence = match_record(name, response.records)
                    if record is not None:
                        break
                if failed:
                    continue
                if record is None:
                    unmatched += 1
                    shown = company.legal_name or company.canonical_name
                    note = {
                        "source": "gleif",
                        "confidence": 0.0,
                        "evidence": (
                            f"no LEI record matches {shown!r} in {company.home_country} "
                            f"(checked {today})"
                        ),
                    }
                    if company.field_sources.get("lei") != note:
                        company.field_sources = {**company.field_sources, "lei": note}
                    entity.identifiers = {**entity.identifiers, "gleif_checked_at": today}
                    continue
                if how == "near":
                    ambiguous.append(
                        f"{company.ticker_symbol}: {record.legal_name!r} ({record.lei})"
                    )
                if _apply_match(session, company, entity, record, how, confidence, today):
                    matched += 1
                else:
                    unchanged += 1
    finally:
        if own_client:
            http.close()
    logger.info(
        "gleif_synced",
        companies=len(companies),
        matched=matched,
        unmatched=unmatched,
        unchanged=unchanged,
        requests=api.requests_made,
        cache_hits=api.cache_hits,
    )
    return GleifSyncResult(
        companies=len(companies),
        matched=matched,
        unmatched=unmatched,
        unchanged=unchanged,
        ambiguous=tuple(ambiguous),
        errors=tuple(errors),
        requests=api.requests_made,
        cache_hits=api.cache_hits,
        entities_created=created,
    )


def entity_summary(session: Session, ticker_symbol: str) -> dict[str, Any] | None:
    listed = find_listed(session, ticker_symbol)
    if listed is None:
        return None
    return {
        "id": listed.id,
        "legal_name": listed.legal_name,
        "jurisdiction": listed.jurisdiction,
        "lei": listed.lei,
        "registration_number": listed.registration_number,
        "identifiers": listed.identifiers,
        "resolution_method": listed.resolution_method,
        "confidence": listed.confidence,
    }


__all__ = [
    "GleifSyncResult",
    "ensure_listed_entities",
    "entity_summary",
    "match_record",
    "sync_gleif",
]
