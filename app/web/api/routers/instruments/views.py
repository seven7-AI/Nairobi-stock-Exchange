"""Instrument reference data — NSE tickers and their sectors.

Reference data is shared across organizations, so these routes are open to
every research role rather than org-scoped.

    codegraph explore "instruments views.py list_instruments Instrument"
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query

from app.web.api.deps import CurrentUser, SessionDep
from app.web.api.pagination import Cursor, CursorPage, PageSize, decode_cursor
from app.web.api.routers.instruments.schema import InstrumentRead, SectorList
from app.web.core.exceptions import ResourceNotFoundError
from app.web.core.security import RESEARCH_ROLES, require_roles
from app.web.db.services import instrument_service
from app.web.utils.datetime_utils import cursor_str

router = APIRouter(prefix="/instruments", tags=["instruments"])

ResearchUser = Depends(require_roles(*RESEARCH_ROLES))


@router.get("", response_model=CursorPage[InstrumentRead])
async def list_instruments(
    session: SessionDep,
    page_size: PageSize = 50,
    cursor: Cursor = None,
    sector: str | None = Query(default=None, description="Filter by sector"),
    is_active: bool | None = Query(default=None, description="Filter by listing status"),
    search: str | None = Query(default=None, description="Match ticker or company name"),
    current_user: CurrentUser = ResearchUser,
) -> CursorPage[InstrumentRead]:
    """Paginated instrument list, ordered by ticker."""
    after_ticker = cursor_str(decode_cursor(cursor), "ticker_symbol") if cursor else None
    rows = await instrument_service.list_instruments(
        session,
        limit=page_size + 1,
        after_ticker=after_ticker,
        sector=sector,
        is_active=is_active,
        search=search,
    )
    items = [InstrumentRead.model_validate(row) for row in rows]
    return CursorPage.build(
        items,
        page_size=page_size,
        cursor_for=lambda item: {"ticker_symbol": item.ticker_symbol},
    )


@router.get("/sectors", response_model=SectorList)
async def list_sectors(session: SessionDep, current_user: CurrentUser = ResearchUser) -> SectorList:
    """Every distinct sector present in the instrument master."""
    sectors = await instrument_service.list_sectors(session)
    return SectorList(sectors=sectors, count=len(sectors))


@router.get("/{ticker_symbol}", response_model=InstrumentRead)
async def read_instrument(
    ticker_symbol: str, session: SessionDep, current_user: CurrentUser = ResearchUser
) -> InstrumentRead:
    """Fetch one instrument by ticker."""
    instrument = await instrument_service.get_instrument_by_ticker(session, ticker_symbol)
    if instrument is None:
        raise ResourceNotFoundError(f"No instrument found for ticker {ticker_symbol.upper()}.")
    return InstrumentRead.model_validate(instrument)


__all__ = ["router"]
