"""Persist and query legal entities and relationships. No resolution rules here.

codegraph explore "find_entity create_entity entities_for_group relationships_current"
"""

from __future__ import annotations

import hashlib
from collections.abc import Iterable
from datetime import date, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.web.db.analytics.models.corporate_entity import CorporateEntity, CorporateRelationship
from app.web.db.analytics.models.mixins import utcnow
from app.web.services.corporate.bitemporal import as_of, current


def entity_key_for(canonical_key: str) -> str:
    return hashlib.sha256(canonical_key.encode("utf-8")).hexdigest()[:24]


def find_by_lei(session: Session, lei: str) -> CorporateEntity | None:
    return session.execute(
        select(CorporateEntity).where(CorporateEntity.lei == lei.upper())
    ).scalar_one_or_none()


def find_by_registration(
    session: Session, registration_number: str, jurisdiction: str
) -> CorporateEntity | None:
    return session.execute(
        select(CorporateEntity).where(
            CorporateEntity.registration_number == registration_number,
            CorporateEntity.jurisdiction == jurisdiction.upper(),
        )
    ).scalar_one_or_none()


def find_by_canonical_key(session: Session, canonical_key: str) -> CorporateEntity | None:
    return session.execute(
        select(CorporateEntity).where(CorporateEntity.canonical_key == canonical_key)
    ).scalar_one_or_none()


def find_listed(session: Session, ticker_symbol: str) -> CorporateEntity | None:
    return session.execute(
        select(CorporateEntity).where(
            CorporateEntity.listed_ticker == ticker_symbol.upper(),
            CorporateEntity.merged_into_id.is_(None),
        )
    ).scalar_one_or_none()


def candidates_in(
    session: Session, jurisdiction: str, group_ticker: str | None
) -> list[CorporateEntity]:
    """Entities a fuzzy match may consider: same jurisdiction, same group, not merged."""
    stmt = select(CorporateEntity).where(
        CorporateEntity.jurisdiction == jurisdiction.upper(),
        CorporateEntity.merged_into_id.is_(None),
    )
    if group_ticker is not None:
        stmt = stmt.where(CorporateEntity.group_ticker == group_ticker.upper())
    return list(session.execute(stmt).scalars())


def create_entity(
    session: Session,
    *,
    canonical_key: str,
    legal_name: str,
    jurisdiction: str,
    entity_type: str,
    resolution_method: str,
    confidence: float,
    evidence: dict[str, Any],
    lei: str | None = None,
    registration_number: str | None = None,
    identifiers: dict[str, Any] | None = None,
    listed_ticker: str | None = None,
    group_ticker: str | None = None,
    now: datetime | None = None,
) -> CorporateEntity:
    stamp = now or utcnow()
    row = CorporateEntity(
        entity_key=entity_key_for(canonical_key),
        canonical_key=canonical_key,
        legal_name=legal_name.strip(),
        display_name=legal_name.strip(),
        jurisdiction=jurisdiction.upper(),
        entity_type=entity_type,
        lei=lei.upper() if lei else None,
        registration_number=registration_number,
        identifiers=dict(identifiers or {}),
        listed_ticker=listed_ticker.upper() if listed_ticker else None,
        group_ticker=group_ticker.upper() if group_ticker else None,
        resolution_method=resolution_method,
        confidence=confidence,
        evidence=dict(evidence),
        first_seen_at=stamp,
        last_seen_at=stamp,
    )
    session.add(row)
    session.flush()
    return row


def entities_for_group(session: Session, group_ticker: str) -> list[CorporateEntity]:
    return list(
        session.execute(
            select(CorporateEntity)
            .where(CorporateEntity.group_ticker == group_ticker.upper())
            .order_by(CorporateEntity.jurisdiction, CorporateEntity.legal_name)
        ).scalars()
    )


def load_entities(session: Session, ids: Iterable[int]) -> dict[int, CorporateEntity]:
    wanted = list(ids)
    if not wanted:
        return {}
    rows = session.execute(select(CorporateEntity).where(CorporateEntity.id.in_(wanted))).scalars()
    return {row.id: row for row in rows}


def relationships_current(
    session: Session, parent_entity_id: int, *, on: date | None = None
) -> list[CorporateRelationship]:
    """The current belief about a parent's relationships, optionally valid on a day."""
    stmt = current(
        select(CorporateRelationship).where(
            CorporateRelationship.parent_entity_id == parent_entity_id
        ),
        CorporateRelationship,
    )
    if on is not None:
        stmt = as_of(stmt, CorporateRelationship, on)
    return list(session.execute(stmt.order_by(CorporateRelationship.id)).scalars())


def relationship_versions(session: Session, version_key: str) -> list[CorporateRelationship]:
    return list(
        session.execute(
            select(CorporateRelationship)
            .where(CorporateRelationship.version_key == version_key)
            .order_by(CorporateRelationship.recorded_at)
        ).scalars()
    )


__all__ = [
    "candidates_in",
    "create_entity",
    "entities_for_group",
    "entity_key_for",
    "find_by_canonical_key",
    "find_by_lei",
    "find_by_registration",
    "find_listed",
    "load_entities",
    "relationship_versions",
    "relationships_current",
]
