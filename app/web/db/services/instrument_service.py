"""Instrument, price bar, and indicator snapshot persistence."""

from __future__ import annotations

import uuid
from datetime import date as date_type

from sqlalchemy import Select, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.web.db.models.indicator_snapshot import IndicatorSnapshot
from app.web.db.models.instrument import Instrument
from app.web.db.models.price_bar import PriceBar


def _instrument_filters(
    stmt: Select[tuple[Instrument]],
    *,
    sector: str | None,
    is_active: bool | None,
    search: str | None,
) -> Select[tuple[Instrument]]:
    if sector is not None:
        stmt = stmt.where(Instrument.sector == sector)
    if is_active is not None:
        stmt = stmt.where(Instrument.is_active.is_(is_active))
    if search:
        pattern = f"%{search.upper()}%"
        stmt = stmt.where(
            func.upper(Instrument.ticker_symbol).like(pattern)
            | func.upper(Instrument.company_name).like(pattern)
        )
    return stmt


async def list_instruments(
    session: AsyncSession,
    *,
    limit: int,
    after_ticker: str | None = None,
    sector: str | None = None,
    is_active: bool | None = None,
    search: str | None = None,
) -> list[Instrument]:
    stmt = _instrument_filters(
        select(Instrument), sector=sector, is_active=is_active, search=search
    )
    if after_ticker is not None:
        stmt = stmt.where(Instrument.ticker_symbol > after_ticker)
    stmt = stmt.order_by(Instrument.ticker_symbol.asc()).limit(limit)
    result = await session.execute(stmt)
    return list(result.scalars().all())


async def get_instrument_by_ticker(session: AsyncSession, ticker_symbol: str) -> Instrument | None:
    result = await session.execute(
        select(Instrument).where(Instrument.ticker_symbol == ticker_symbol.upper())
    )
    return result.scalar_one_or_none()


async def list_sectors(session: AsyncSession) -> list[str]:
    result = await session.execute(
        select(Instrument.sector)
        .where(Instrument.sector.is_not(None))
        .distinct()
        .order_by(Instrument.sector.asc())
    )
    return [sector for sector in result.scalars().all() if sector]


# --- price bars -------------------------------------------------------------
async def list_price_bars(
    session: AsyncSession,
    instrument_id: uuid.UUID,
    *,
    limit: int,
    before_date: date_type | None = None,
    start_date: date_type | None = None,
) -> list[PriceBar]:
    """Most recent first, so a cursor walks backwards through history."""
    stmt = select(PriceBar).where(PriceBar.instrument_id == instrument_id)
    if before_date is not None:
        stmt = stmt.where(PriceBar.bar_date < before_date)
    if start_date is not None:
        stmt = stmt.where(PriceBar.bar_date >= start_date)
    stmt = stmt.order_by(PriceBar.bar_date.desc()).limit(limit)
    result = await session.execute(stmt)
    return list(result.scalars().all())


async def get_latest_price_bar(session: AsyncSession, instrument_id: uuid.UUID) -> PriceBar | None:
    result = await session.execute(
        select(PriceBar)
        .where(PriceBar.instrument_id == instrument_id)
        .order_by(PriceBar.bar_date.desc())
        .limit(1)
    )
    return result.scalar_one_or_none()


async def count_price_bars(session: AsyncSession, instrument_id: uuid.UUID) -> int:
    result = await session.execute(
        select(func.count()).select_from(PriceBar).where(PriceBar.instrument_id == instrument_id)
    )
    return int(result.scalar_one())


# --- indicator snapshots ----------------------------------------------------
async def get_snapshot(
    session: AsyncSession, instrument_id: uuid.UUID, as_of_date: date_type
) -> IndicatorSnapshot | None:
    result = await session.execute(
        select(IndicatorSnapshot).where(
            IndicatorSnapshot.instrument_id == instrument_id,
            IndicatorSnapshot.as_of_date == as_of_date,
        )
    )
    return result.scalar_one_or_none()


async def get_latest_snapshot(
    session: AsyncSession, instrument_id: uuid.UUID
) -> IndicatorSnapshot | None:
    result = await session.execute(
        select(IndicatorSnapshot)
        .where(IndicatorSnapshot.instrument_id == instrument_id)
        .order_by(IndicatorSnapshot.as_of_date.desc())
        .limit(1)
    )
    return result.scalar_one_or_none()


async def latest_snapshot_date(session: AsyncSession) -> date_type | None:
    result = await session.execute(select(func.max(IndicatorSnapshot.as_of_date)))
    return result.scalar_one_or_none()


async def list_snapshots_for_date(
    session: AsyncSession, as_of_date: date_type, *, limit: int = 1000
) -> list[tuple[IndicatorSnapshot, Instrument]]:
    """Snapshots joined to their instrument — the input to market analytics."""
    result = await session.execute(
        select(IndicatorSnapshot, Instrument)
        .join(Instrument, Instrument.id == IndicatorSnapshot.instrument_id)
        .where(IndicatorSnapshot.as_of_date == as_of_date)
        .limit(limit)
    )
    return [(snapshot, instrument) for snapshot, instrument in result.all()]


__all__ = [
    "count_price_bars",
    "get_instrument_by_ticker",
    "get_latest_price_bar",
    "get_latest_snapshot",
    "get_snapshot",
    "latest_snapshot_date",
    "list_instruments",
    "list_price_bars",
    "list_sectors",
    "list_snapshots_for_date",
]
