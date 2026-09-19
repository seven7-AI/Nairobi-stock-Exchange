"""The entity-resolution ladder: strongest identifier first, fuzzy last and fenced.

1. LEI            exact                                   -> 1.00
2. ISIN           exact, on the listed company            -> 1.00
3. registration   (number, jurisdiction) exact            -> 0.98
4. exchange id    (exchange, code) in ``identifiers``     -> 0.98
5. canonical key  normalised legal name + jurisdiction    -> 0.95
6. fuzzy          same jurisdiction AND same group, score >= accept, runner-up <=
                  margin, no distinguishing token differs -> score x 0.9
7. otherwise      a near miss becomes a *provisional* entity (0.6) with the
                  candidates recorded for review; a clean miss is a new entity (0.85)

A mention without a jurisdiction is keyed ``ZZ`` and always queued - never
defaulted to Kenya.

    codegraph explore "resolve EntityMention Resolution candidates_in"
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.web.db.analytics.models.corporate_company import CorporateCompany
from app.web.db.analytics.models.corporate_entity import CorporateEntity
from app.web.db.analytics.services.corporate_entities import (
    candidates_in,
    create_entity,
    find_by_canonical_key,
    find_by_lei,
    find_by_registration,
    find_listed,
)
from app.web.services.corporate.config import CorporateConfig
from app.web.services.corporate.countries import UNDISCLOSED_JURISDICTION, jurisdiction_from_name
from app.web.services.corporate.entities.normalise import (
    canonical_key,
    distinguishing_difference,
    token_set_ratio,
)


@dataclass(frozen=True)
class EntityMention:
    """An entity as a source names it."""

    name: str
    jurisdiction: str | None
    lei: str | None = None
    registration_number: str | None = None
    isin: str | None = None
    exchange_id: tuple[str, str] | None = None
    entity_type: str = "unknown"
    group_ticker: str | None = None
    source_ref: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class Resolution:
    entity_id: int
    method: str
    confidence: float
    created: bool
    #: Ambiguous: the mention was given a provisional entity and needs review.
    queued: bool
    #: (entity id, score) near misses, best first.
    candidates: tuple[tuple[int, float], ...] = ()
    jurisdiction: str = UNDISCLOSED_JURISDICTION


def _jurisdiction_for(mention: EntityMention) -> str | None:
    if mention.jurisdiction:
        return mention.jurisdiction.upper()
    return jurisdiction_from_name(mention.name)


def _touch(row: CorporateEntity, now: datetime) -> None:
    row.last_seen_at = now


def resolve(
    session: Session, mention: EntityMention, config: CorporateConfig, *, now: datetime
) -> Resolution:
    """Find or create the entity a mention refers to."""
    # 1. LEI
    if mention.lei:
        row = find_by_lei(session, mention.lei)
        if row is not None:
            _touch(row, now)
            return Resolution(row.id, "lei", 1.0, False, False, jurisdiction=row.jurisdiction)

    # 2. ISIN -> the listed company's own entity
    if mention.isin:
        company = session.execute(
            select(CorporateCompany).where(CorporateCompany.isin == mention.isin.upper())
        ).scalar_one_or_none()
        if company is not None:
            listed = find_listed(session, company.ticker_symbol)
            if listed is not None:
                _touch(listed, now)
                return Resolution(
                    listed.id, "isin", 1.0, False, False, jurisdiction=listed.jurisdiction
                )

    jurisdiction = _jurisdiction_for(mention)

    # 3. registration number
    if mention.registration_number and jurisdiction:
        row = find_by_registration(session, mention.registration_number, jurisdiction)
        if row is not None:
            _touch(row, now)
            return Resolution(row.id, "registration", 0.98, False, False, jurisdiction=jurisdiction)

    # 4. exchange id
    if mention.exchange_id:
        exchange, code = mention.exchange_id
        for row in session.execute(select(CorporateEntity)).scalars():
            if (row.identifiers.get("exchange") or {}).get(exchange) == code:
                _touch(row, now)
                return Resolution(
                    row.id, "exchange_id", 0.98, False, False, jurisdiction=row.jurisdiction
                )

    # No jurisdiction at all: keyed ZZ and queued, never assumed.
    if jurisdiction is None:
        key = canonical_key(mention.name, UNDISCLOSED_JURISDICTION)
        row = find_by_canonical_key(session, key)
        if row is None:
            row = create_entity(
                session,
                canonical_key=key,
                legal_name=mention.name,
                jurisdiction=UNDISCLOSED_JURISDICTION,
                entity_type=mention.entity_type,
                resolution_method="provisional",
                confidence=0.5,
                evidence={"reason": "no jurisdiction disclosed", "source": mention.source_ref},
                group_ticker=mention.group_ticker,
                now=now,
            )
            return Resolution(row.id, "provisional", 0.5, True, True)
        _touch(row, now)
        return Resolution(row.id, "provisional", 0.5, False, True)

    # 5. exact canonical key
    key = canonical_key(mention.name, jurisdiction)
    row = find_by_canonical_key(session, key)
    if row is not None:
        _touch(row, now)
        return Resolution(row.id, "legal_name_exact", 0.95, False, False, jurisdiction=jurisdiction)

    # 6. controlled fuzzy within the same jurisdiction and group
    scored: list[tuple[float, CorporateEntity]] = []
    for candidate in candidates_in(session, jurisdiction, mention.group_ticker):
        score = token_set_ratio(mention.name, candidate.legal_name)
        if score > 0:
            scored.append((score, candidate))
    scored.sort(key=lambda item: item[0], reverse=True)
    best = scored[0] if scored else None
    runner_up = scored[1][0] if len(scored) > 1 else 0.0
    if (
        best is not None
        and best[0] >= config.fuzzy_accept
        and runner_up <= config.fuzzy_margin_below
        and not distinguishing_difference(mention.name, best[1].legal_name)
    ):
        _touch(best[1], now)
        return Resolution(
            best[1].id,
            "fuzzy",
            round(best[0] * 0.9, 4),
            False,
            False,
            tuple((c.id, round(s, 4)) for s, c in scored[:5]),
            jurisdiction,
        )

    # 7. near miss -> provisional + candidates; clean miss -> new
    near = tuple((c.id, round(s, 4)) for s, c in scored[:5] if s >= config.fuzzy_margin_below)
    if near:
        row = create_entity(
            session,
            canonical_key=key,
            legal_name=mention.name,
            jurisdiction=jurisdiction,
            entity_type=mention.entity_type,
            resolution_method="provisional",
            confidence=0.6,
            evidence={
                "reason": "near miss against existing entities",
                "candidates": [list(c) for c in near],
                "source": mention.source_ref,
            },
            group_ticker=mention.group_ticker,
            now=now,
        )
        return Resolution(row.id, "provisional", 0.6, True, True, near, jurisdiction)
    row = create_entity(
        session,
        canonical_key=key,
        legal_name=mention.name,
        jurisdiction=jurisdiction,
        entity_type=mention.entity_type,
        resolution_method="new",
        confidence=0.85,
        evidence={"source": mention.source_ref},
        lei=mention.lei,
        registration_number=mention.registration_number,
        group_ticker=mention.group_ticker,
        now=now,
    )
    return Resolution(row.id, "new", 0.85, True, False, jurisdiction=jurisdiction)


__all__ = ["EntityMention", "Resolution", "resolve"]
