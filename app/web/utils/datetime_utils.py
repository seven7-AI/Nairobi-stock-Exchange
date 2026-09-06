"""Datetime helpers shared by the cursor-paginated routers."""

from __future__ import annotations

from datetime import date as date_type
from datetime import datetime
from typing import Any

from app.web.core.exceptions import DataValidationError


def cursor_datetime(payload: dict[str, Any], key: str = "created_at") -> datetime:
    """Read a timestamp out of a decoded cursor."""
    raw = payload.get(key)
    if not isinstance(raw, str):
        raise DataValidationError("Malformed pagination cursor.")
    try:
        return datetime.fromisoformat(raw)
    except ValueError as exc:
        raise DataValidationError("Malformed pagination cursor.") from exc


def cursor_date(payload: dict[str, Any], key: str = "bar_date") -> date_type:
    """Read a date out of a decoded cursor."""
    raw = payload.get(key)
    if not isinstance(raw, str):
        raise DataValidationError("Malformed pagination cursor.")
    try:
        return date_type.fromisoformat(raw)
    except ValueError as exc:
        raise DataValidationError("Malformed pagination cursor.") from exc


def cursor_str(payload: dict[str, Any], key: str) -> str:
    """Read a plain string out of a decoded cursor."""
    raw = payload.get(key)
    if not isinstance(raw, str):
        raise DataValidationError("Malformed pagination cursor.")
    return raw


__all__ = ["cursor_date", "cursor_datetime", "cursor_str"]
