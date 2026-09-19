"""Persist and query the company universe. No business rules here.

codegraph explore "upsert_companies load_companies record_sightings page_sightings"
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Iterable, Mapping
from dataclasses import asdict, dataclass
from datetime import date, datetime
from typing import Any, Literal

from sqlalchemy import func, select
from sqlalchemy.dialects.sqlite import insert
from sqlalchemy.orm import Session

from app.web.db.analytics.models.corporate_company import CorporateCompany, CorporateSighting
from app.web.db.analytics.models.mixins import utcnow

UpsertOutcome = Literal["created", "updated", "unchanged"]

#: Columns compared on upsert; the timestamps and id are not.
_COMPARED = (
    "canonical_name",
    "legal_name",
    "instrument_type",
    "sector_code",
    "home_country",
    "isin",
    "lei",
    "registration_number",
    "exchange_ids",
    "website",
    "ir_url",
    "listing_status",
    "status_reason",
    "first_listed",
    "delisted_on",
    "name_history",
    "status_history",
    "field_sources",
    "confidence",
)


@dataclass(frozen=True)
class SightingRow:
    ticker_symbol: str
    source: str
    payload: Mapping[str, Any]


def _json_ready(value: Any) -> Any:
    if isinstance(value, tuple):
        return [_json_ready(v) for v in value]
    if isinstance(value, dict):
        return {k: _json_ready(v) for k, v in value.items()}
    if isinstance(value, date):
        return value
    return value


def upsert_companies(
    session: Session, records: Iterable[Any], *, now: datetime | None = None
) -> dict[str, UpsertOutcome]:
    """Insert new companies, update changed ones field by field, leave the rest alone.

    ``records`` are ``CompanyRecord`` dataclasses (or anything ``asdict`` accepts with
    the same field names). Returns ticker -> outcome.
    """
    stamp = now or utcnow()
    existing = {
        row.ticker_symbol: row for row in session.execute(select(CorporateCompany)).scalars()
    }
    outcomes: dict[str, UpsertOutcome] = {}
    for record in records:
        values = {k: _json_ready(v) for k, v in asdict(record).items()}
        ticker = values["ticker_symbol"]
        row = existing.get(ticker)
        if row is None:
            session.add(
                CorporateCompany(
                    **values, first_seen_at=stamp, last_seen_at=stamp, updated_at=stamp
                )
            )
            outcomes[ticker] = "created"
            continue
        changed = False
        for column in _COMPARED:
            new = values.get(column)
            if getattr(row, column) != new:
                setattr(row, column, new)
                changed = True
        row.last_seen_at = stamp
        if changed:
            row.updated_at = stamp
        outcomes[ticker] = "updated" if changed else "unchanged"
    session.flush()
    return outcomes


def load_companies(
    session: Session, *, status: str | None = None, tickers: Iterable[str] | None = None
) -> list[CorporateCompany]:
    stmt = select(CorporateCompany).order_by(CorporateCompany.ticker_symbol)
    if status is not None:
        stmt = stmt.where(CorporateCompany.listing_status == status)
    if tickers is not None:
        stmt = stmt.where(CorporateCompany.ticker_symbol.in_([t.upper() for t in tickers]))
    return list(session.execute(stmt).scalars())


def load_company(session: Session, ticker_symbol: str) -> CorporateCompany | None:
    return session.execute(
        select(CorporateCompany).where(CorporateCompany.ticker_symbol == ticker_symbol.upper())
    ).scalar_one_or_none()


def payload_hash(payload: Mapping[str, Any]) -> str:
    text = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def record_sightings(session: Session, rows: Iterable[SightingRow], *, seen_at: datetime) -> int:
    """Append one sighting per row for this run; re-recording the same run is a no-op."""
    payload = [
        {
            "ticker_symbol": r.ticker_symbol.upper(),
            "source": r.source,
            "seen_at": seen_at,
            "payload_hash": payload_hash(r.payload),
            "payload": dict(r.payload),
        }
        for r in rows
    ]
    if not payload:
        return 0
    statement = (
        insert(CorporateSighting)
        .values(payload)
        .on_conflict_do_nothing(
            index_elements=["ticker_symbol", "source", "payload_hash", "seen_at"]
        )
    )
    before = session.execute(
        select(func.count())
        .select_from(CorporateSighting)
        .where(CorporateSighting.seen_at == seen_at)
    ).scalar_one()
    session.execute(statement)
    session.flush()
    after = session.execute(
        select(func.count())
        .select_from(CorporateSighting)
        .where(CorporateSighting.seen_at == seen_at)
    ).scalar_one()
    return int(after - before)


def source_runs(session: Session, source: str) -> list[datetime]:
    """Distinct run timestamps recorded for a source, oldest first."""
    rows = session.execute(
        select(CorporateSighting.seen_at)
        .where(CorporateSighting.source == source)
        .group_by(CorporateSighting.seen_at)
        .order_by(CorporateSighting.seen_at)
    ).scalars()
    return list(rows)


def last_sighting_per_ticker(session: Session, source: str) -> dict[str, datetime]:
    rows = session.execute(
        select(CorporateSighting.ticker_symbol, func.max(CorporateSighting.seen_at))
        .where(CorporateSighting.source == source)
        .group_by(CorporateSighting.ticker_symbol)
    ).all()
    return {str(ticker): seen for ticker, seen in rows}


def sightings_for(session: Session, ticker_symbol: str) -> list[CorporateSighting]:
    return list(
        session.execute(
            select(CorporateSighting)
            .where(CorporateSighting.ticker_symbol == ticker_symbol.upper())
            .order_by(CorporateSighting.seen_at.desc(), CorporateSighting.source)
        ).scalars()
    )


__all__ = [
    "SightingRow",
    "UpsertOutcome",
    "last_sighting_per_ticker",
    "load_companies",
    "load_company",
    "payload_hash",
    "record_sightings",
    "sightings_for",
    "source_runs",
    "upsert_companies",
]
