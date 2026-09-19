"""The bitemporal columns every versioned corporate fact table carries.

Two time axes: *valid time* (``effective_from`` inclusive / ``effective_to``
exclusive - when the fact was true in the world) and *transaction time*
(``recorded_at`` / ``superseded_at`` - when we believed it). A row is never
updated in place: the only mutation an old row ever receives is the closing of its
transaction time (``superseded_at``, ``superseded_by_id``, ``supersession_reason``)
by ``app.web.services.corporate.bitemporal.append_and_close``.

``version_key`` hashes the row's natural identity without its values;
``content_hash`` hashes the values. Same key + same content + same source is the
same assertion (a re-extraction is a no-op); same key + different content is a
restatement or a correction.

    codegraph explore "BitemporalMixin append_and_close as_of as_known_on"
"""

from __future__ import annotations

from datetime import date as date_type
from datetime import datetime
from typing import TYPE_CHECKING, Any

from sqlalchemy import JSON, Date, Float, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, declared_attr, mapped_column

from app.web.db.analytics.models.mixins import UTCDateTime, utcnow

SUPERSESSION_REASONS: tuple[str, ...] = (
    "restated",
    "corroborated",
    "closed",
    "merged_entity",
    "retracted",
)
SOURCE_KINDS: tuple[str, ...] = ("document", "gleif", "announcement", "event", "curated")


class BitemporalMixin:
    if TYPE_CHECKING:
        __tablename__: str
        id: Mapped[int]

    effective_from: Mapped[date_type] = mapped_column(Date, nullable=False, index=True)
    effective_to: Mapped[date_type | None] = mapped_column(Date, nullable=True)
    recorded_at: Mapped[datetime] = mapped_column(
        UTCDateTime(), nullable=False, default=utcnow, index=True
    )
    superseded_at: Mapped[datetime | None] = mapped_column(UTCDateTime(), nullable=True, index=True)

    @declared_attr
    def superseded_by_id(cls) -> Mapped[int | None]:  # noqa: N805 - SQLAlchemy convention
        return mapped_column(Integer, ForeignKey(f"{cls.__tablename__}.id"), nullable=True)

    supersession_reason: Mapped[str | None] = mapped_column(String(16), nullable=True)
    version_key: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    #: ``corporate_documents.id`` (table arrives in C3; the reference is by value until
    #: then). NULL only when ``source_kind`` is not ``document``.
    source_id: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)
    source_kind: Mapped[str] = mapped_column(String(12), nullable=False)
    confidence: Mapped[float] = mapped_column(Float, nullable=False)
    provenance: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)


__all__ = ["SOURCE_KINDS", "SUPERSESSION_REASONS", "BitemporalMixin"]
