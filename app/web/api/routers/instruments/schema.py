"""Instrument schemas."""

from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict

from app.web.db.models.enums import InstrumentStatus


class InstrumentRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    ticker_symbol: str
    company_name: str
    sector: str | None
    exchange: str
    currency: str
    status: InstrumentStatus
    is_active: bool
    created_at: datetime


class SectorList(BaseModel):
    sectors: list[str]
    count: int


__all__ = ["InstrumentRead", "SectorList"]
