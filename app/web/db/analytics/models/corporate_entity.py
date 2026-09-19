"""Legal entities and the ownership relationships between them.

``corporate_entities`` is one row per legal entity ever named by a report, GLEIF or
an announcement - listed groups, subsidiaries, associates, joint ventures,
branches. Identity is the normalised legal name plus jurisdiction (``ZZ`` when a
report names an entity without a country); an LEI or a registration number
resolves earlier in the ladder when present. Two entities that turn out to be one
are *merged* (``merged_into_id``), never deleted.

``corporate_relationships`` is bitemporal: one version per (parent, child, type)
per assertion, with the ownership percentage as a Measure triple and the child's
country of incorporation *as that report states it*.

    codegraph explore "CorporateEntity CorporateRelationship resolve append_and_close"
"""

from __future__ import annotations

from datetime import date as date_type
from datetime import datetime
from typing import Any

from sqlalchemy import JSON, Date, Float, ForeignKey, Index, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.web.db.analytics.base import AnalyticsBase
from app.web.db.analytics.models.corporate_bitemporal import BitemporalMixin
from app.web.db.analytics.models.mixins import IntIdMixin, UTCDateTime, utcnow

ENTITY_TYPES: tuple[str, ...] = (
    "listed",
    "parent",
    "subsidiary",
    "associate",
    "joint_venture",
    "branch",
    "representative_office",
    "franchise",
    "strategic_investment",
    "unknown",
)
RELATIONSHIP_TYPES: tuple[str, ...] = (
    "subsidiary",
    "associate",
    "joint_venture",
    "branch",
    "representative_office",
    "franchise",
    "strategic_investment",
)
RESOLUTION_METHODS: tuple[str, ...] = (
    "lei",
    "isin",
    "registration",
    "exchange_id",
    "legal_name_exact",
    "fuzzy",
    "provisional",
    "curated",
    "new",
)


class CorporateEntity(IntIdMixin, AnalyticsBase):
    __tablename__ = "corporate_entities"
    __table_args__ = (
        Index(
            "uq_corporate_entity_registration",
            "registration_number",
            "jurisdiction",
            unique=True,
        ),
    )

    entity_key: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    canonical_key: Mapped[str] = mapped_column(String(240), nullable=False)
    legal_name: Mapped[str] = mapped_column(String(200), nullable=False)
    display_name: Mapped[str] = mapped_column(String(200), nullable=False)
    jurisdiction: Mapped[str] = mapped_column(String(2), nullable=False, index=True)
    entity_type: Mapped[str] = mapped_column(String(24), nullable=False)
    lei: Mapped[str | None] = mapped_column(String(20), nullable=True, unique=True)
    registration_number: Mapped[str | None] = mapped_column(String(64), nullable=True)
    identifiers: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    #: Set when the entity *is* a listed company (its ticker).
    listed_ticker: Mapped[str | None] = mapped_column(String(24), nullable=True, index=True)
    #: The listed group the entity was first seen under; scopes fuzzy matching.
    group_ticker: Mapped[str | None] = mapped_column(String(24), nullable=True, index=True)
    resolution_method: Mapped[str] = mapped_column(String(16), nullable=False)
    confidence: Mapped[float] = mapped_column(Float, nullable=False)
    merged_into_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("corporate_entities.id"), nullable=True
    )
    evidence: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    first_seen_at: Mapped[datetime] = mapped_column(UTCDateTime(), nullable=False, default=utcnow)
    last_seen_at: Mapped[datetime] = mapped_column(UTCDateTime(), nullable=False, default=utcnow)

    def __repr__(self) -> str:
        return f"<CorporateEntity {self.id} {self.legal_name!r} {self.jurisdiction}>"


class CorporateRelationship(IntIdMixin, BitemporalMixin, AnalyticsBase):
    __tablename__ = "corporate_relationships"
    __table_args__ = (
        Index("ix_corporate_relationships_parent_current", "parent_entity_id", "superseded_at"),
    )

    parent_entity_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("corporate_entities.id"), nullable=False
    )
    child_entity_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("corporate_entities.id"), nullable=False, index=True
    )
    relationship_type: Mapped[str] = mapped_column(String(24), nullable=False)
    ownership_pct_value: Mapped[float | None] = mapped_column(Float, nullable=True)
    ownership_pct_status: Mapped[str] = mapped_column(String(16), nullable=False)
    ownership_pct_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    ownership_basis: Mapped[str] = mapped_column(String(16), nullable=False, default="unspecified")
    principal_activity: Mapped[str | None] = mapped_column(String(200), nullable=True)
    #: The child's country of incorporation as stated by *this* report.
    country: Mapped[str] = mapped_column(String(2), nullable=False)
    #: The report period that asserts the relationship.
    period_end: Mapped[date_type | None] = mapped_column(Date, nullable=True)
    page: Mapped[int | None] = mapped_column(Integer, nullable=True)
    table_ref: Mapped[str | None] = mapped_column(String(24), nullable=True)

    def __repr__(self) -> str:
        return (
            f"<CorporateRelationship {self.parent_entity_id}->{self.child_entity_id} "
            f"{self.relationship_type} {self.effective_from}..{self.effective_to}>"
        )


__all__ = [
    "ENTITY_TYPES",
    "RELATIONSHIP_TYPES",
    "RESOLUTION_METHODS",
    "CorporateEntity",
    "CorporateRelationship",
]
