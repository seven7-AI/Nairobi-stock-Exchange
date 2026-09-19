"""Persist and query document sources, document versions and extraction runs.

codegraph explore "latest_document_for upsert_source record_source_health"
"""

from __future__ import annotations

from collections.abc import Iterable
from datetime import datetime
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.web.db.analytics.models.corporate_document import (
    CorporateDocument,
    CorporateExtraction,
    CorporateSource,
)
from app.web.db.analytics.models.mixins import utcnow


def upsert_source(
    session: Session,
    *,
    name: str,
    kind: str,
    base_url: str,
    ticker_symbol: str | None = None,
    rules_path: str | None = None,
    enabled: bool = True,
    notes: str | None = None,
    now: datetime | None = None,
) -> CorporateSource:
    row = session.execute(
        select(CorporateSource).where(CorporateSource.name == name)
    ).scalar_one_or_none()
    stamp = now or utcnow()
    if row is None:
        row = CorporateSource(
            name=name,
            kind=kind,
            base_url=base_url,
            ticker_symbol=ticker_symbol,
            rules_path=rules_path,
            enabled=enabled,
            notes=notes,
            updated_at=stamp,
        )
        session.add(row)
        session.flush()
        return row
    changed = False
    for column, value in (
        ("kind", kind),
        ("base_url", base_url),
        ("ticker_symbol", ticker_symbol),
        ("rules_path", rules_path),
        ("enabled", enabled),
        ("notes", notes),
    ):
        if getattr(row, column) != value:
            setattr(row, column, value)
            changed = True
    if changed:
        row.updated_at = stamp
    return row


def record_source_health(
    session: Session, name: str, *, status: str, detail: str, now: datetime
) -> CorporateSource | None:
    row = session.execute(
        select(CorporateSource).where(CorporateSource.name == name)
    ).scalar_one_or_none()
    if row is None:
        return None
    row.health = status
    row.updated_at = now
    if status in ("ok", "degraded"):
        row.last_ok_at = now
        row.consecutive_failures = 0 if status == "ok" else row.consecutive_failures
        row.last_error = detail if status == "degraded" else None
        if status == "degraded":
            row.last_error_at = now
    elif status in ("down", "blocked"):
        row.last_error_at = now
        row.last_error = detail[:2000]
        row.consecutive_failures += 1
    return row


def load_sources(session: Session) -> list[CorporateSource]:
    return list(session.execute(select(CorporateSource).order_by(CorporateSource.name)).scalars())


def latest_document_for(session: Session, source: str, url: str) -> CorporateDocument | None:
    """The newest version at an identity (highest ``version_no``)."""
    return session.execute(
        select(CorporateDocument)
        .where(CorporateDocument.source == source, CorporateDocument.url == url)
        .order_by(CorporateDocument.version_no.desc())
        .limit(1)
    ).scalar_one_or_none()


def document_by_sha(session: Session, sha256: str) -> CorporateDocument | None:
    return session.execute(
        select(CorporateDocument).where(CorporateDocument.sha256 == sha256).limit(1)
    ).scalar_one_or_none()


def add_document_version(
    session: Session, *, previous: CorporateDocument | None, values: dict[str, Any]
) -> CorporateDocument:
    row = CorporateDocument(**values, version_no=(previous.version_no + 1) if previous else 1)
    session.add(row)
    session.flush()
    if previous is not None:
        previous.superseded_by_id = row.id
    return row


def load_documents(
    session: Session,
    *,
    ticker_symbol: str | None = None,
    source: str | None = None,
    kind: str | None = None,
    parse_status: str | None = None,
    current_only: bool = True,
) -> list[CorporateDocument]:
    stmt = select(CorporateDocument).order_by(
        CorporateDocument.ticker_symbol, CorporateDocument.fiscal_year, CorporateDocument.title
    )
    if ticker_symbol is not None:
        stmt = stmt.where(CorporateDocument.ticker_symbol == ticker_symbol.upper())
    if source is not None:
        stmt = stmt.where(CorporateDocument.source == source)
    if kind is not None:
        stmt = stmt.where(CorporateDocument.kind == kind)
    if parse_status is not None:
        stmt = stmt.where(CorporateDocument.parse_status == parse_status)
    if current_only:
        stmt = stmt.where(CorporateDocument.superseded_by_id.is_(None))
    return list(session.execute(stmt).scalars())


def document_counts(session: Session) -> dict[str, Any]:
    by_status: dict[str, int] = {}
    for status, count in session.execute(
        select(CorporateDocument.parse_status, func.count())
        .where(CorporateDocument.superseded_by_id.is_(None))
        .group_by(CorporateDocument.parse_status)
    ).all():
        by_status[str(status)] = int(count)
    by_kind: dict[str, int] = {}
    for kind, count in session.execute(
        select(CorporateDocument.kind, func.count())
        .where(CorporateDocument.superseded_by_id.is_(None))
        .group_by(CorporateDocument.kind)
    ).all():
        by_kind[str(kind)] = int(count)
    total_bytes = session.execute(
        select(func.coalesce(func.sum(CorporateDocument.bytes), 0))
    ).scalar_one()
    tickers = session.execute(
        select(func.count(func.distinct(CorporateDocument.ticker_symbol))).where(
            CorporateDocument.ticker_symbol.is_not(None)
        )
    ).scalar_one()
    return {
        "by_parse_status": by_status,
        "by_kind": by_kind,
        "bytes": int(total_bytes),
        "tickers": int(tickers),
    }


def add_extraction(session: Session, **values: Any) -> CorporateExtraction:
    row = CorporateExtraction(**values)
    session.add(row)
    session.flush()
    return row


def extractions_for(session: Session, document_ids: Iterable[int]) -> list[CorporateExtraction]:
    wanted = list(document_ids)
    if not wanted:
        return []
    return list(
        session.execute(
            select(CorporateExtraction)
            .where(CorporateExtraction.document_id.in_(wanted))
            .order_by(CorporateExtraction.started_at)
        ).scalars()
    )


__all__ = [
    "add_document_version",
    "add_extraction",
    "document_by_sha",
    "document_counts",
    "extractions_for",
    "latest_document_for",
    "load_documents",
    "load_sources",
    "record_source_health",
    "upsert_source",
]
