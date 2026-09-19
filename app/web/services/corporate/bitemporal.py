"""Append-only versioning for the corporate fact tables.

``append_and_close`` is the only writer. A new assertion with the same
``version_key`` and the same ``content_hash`` from the same source is a no-op; a
different content (a restatement or correction) or a different source (a
corroboration) inserts a new version and closes the current one's transaction
time. No value column of an old row is ever updated.

Queries compose ``as_of`` (valid time) and ``as_known_on`` (transaction time) so
"where did KCB operate on 2018-12-31?" and "what did we believe about that on
2019-06-30?" are both one select.

    codegraph explore "append_and_close as_of as_known_on VersionedWrite"
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date, datetime
from typing import Any, Literal, TypeVar

from sqlalchemy import Select, inspect, or_, select
from sqlalchemy.orm import Session

from app.web.db.analytics.models.corporate_bitemporal import BitemporalMixin

ModelT = TypeVar("ModelT", bound=BitemporalMixin)
WriteOutcome = Literal["inserted", "noop", "superseded"]


def version_key(*parts: object) -> str:
    """Hash of a row's natural identity (no values): sha256 of the joined parts, 24 hex."""
    text = "|".join("" if p is None else str(p) for p in parts)
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:24]


def content_hash(values: Mapping[str, Any]) -> str:
    """Hash of the value-bearing columns, order-independent."""
    text = json.dumps(values, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class VersionedWrite:
    """One assertion: identity, content, and the full row payload to insert."""

    version_key: str
    content_hash: str
    #: Every column of the row except the transaction-time ones; must include
    #: ``effective_from``, ``source_kind``, ``confidence`` and (when known) ``source_id``.
    values: dict[str, Any]
    #: Why the current version (if any) is closed: ``restated`` when the content
    #: differs, ``corroborated`` when only the source differs.
    reason_if_superseding: str = "restated"


def append_and_close(
    session: Session, model: type[ModelT], write: VersionedWrite, *, now: datetime
) -> tuple[WriteOutcome, ModelT]:
    """Insert ``write`` as the current version unless it is already the current version."""
    current_row = session.execute(
        select(model).where(model.version_key == write.version_key, model.superseded_at.is_(None))
    ).scalar_one_or_none()
    if (
        current_row is not None
        and current_row.content_hash == write.content_hash
        and current_row.source_id == write.values.get("source_id")
        and current_row.source_kind == write.values.get("source_kind")
    ):
        return "noop", current_row
    payload: dict[str, Any] = {
        **write.values,
        "version_key": write.version_key,
        "content_hash": write.content_hash,
        "recorded_at": now,
    }
    row = model(**payload)
    session.add(row)
    session.flush()
    if current_row is None:
        return "inserted", row
    reason = write.reason_if_superseding
    if current_row.content_hash == write.content_hash and reason == "restated":
        reason = "corroborated"
    current_row.superseded_at = now
    current_row.superseded_by_id = row.id
    current_row.supersession_reason = reason
    session.flush()
    return "superseded", row


def as_of(stmt: Select[Any], model: type[BitemporalMixin], day: date) -> Select[Any]:
    """Valid time: rows whose ``[effective_from, effective_to)`` covers ``day``."""
    return stmt.where(
        model.effective_from <= day,
        or_(model.effective_to.is_(None), model.effective_to > day),
    )


def as_known_on(stmt: Select[Any], model: type[BitemporalMixin], at: datetime) -> Select[Any]:
    """Transaction time: rows believed at ``at`` (recorded by then, not yet superseded)."""
    return stmt.where(
        model.recorded_at <= at,
        or_(model.superseded_at.is_(None), model.superseded_at > at),
    )


def current(stmt: Select[Any], model: type[BitemporalMixin]) -> Select[Any]:
    """The current belief: versions never superseded."""
    return stmt.where(model.superseded_at.is_(None))


def close_valid_time(
    session: Session,
    model: type[ModelT],
    row: ModelT,
    *,
    effective_to: date,
    now: datetime,
    source_kind: str,
    source_id: int | None,
    confidence: float,
    provenance: dict[str, Any] | None,
) -> ModelT:
    """ "It ended on ``effective_to``": a new version with the end date, the old one closed.

    Never an UPDATE of the old row's ``effective_to``.
    """
    mapper = inspect(model)
    assert mapper is not None
    values = {
        column.name: getattr(row, column.name)
        for column in mapper.columns
        if column.name
        not in {
            "id",
            "recorded_at",
            "superseded_at",
            "superseded_by_id",
            "supersession_reason",
            "version_key",
            "content_hash",
        }
    }
    values.update(
        effective_to=effective_to,
        source_kind=source_kind,
        source_id=source_id,
        confidence=confidence,
        provenance=provenance,
    )
    hashed = {
        k: v
        for k, v in values.items()
        if k not in {"source_id", "source_kind", "confidence", "provenance"}
    }
    write = VersionedWrite(row.version_key, content_hash(hashed), values, "closed")
    _, new_row = append_and_close(session, model, write, now=now)
    return new_row


__all__ = [
    "VersionedWrite",
    "WriteOutcome",
    "append_and_close",
    "as_known_on",
    "as_of",
    "close_valid_time",
    "content_hash",
    "current",
    "version_key",
]
