"""Formatting helpers for markdown report output."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any


def fmt_number(value: Any, digits: int = 2) -> str:
    if value is None:
        return "N/A"
    try:
        return f"{float(value):,.{digits}f}"
    except (TypeError, ValueError):
        return str(value)


def fmt_percent(value: Any, digits: int = 2) -> str:
    if value is None:
        return "N/A"
    try:
        return f"{float(value):.{digits}f}%"
    except (TypeError, ValueError):
        return str(value)


def now_utc_iso() -> str:
    return datetime.now(tz=timezone.utc).isoformat()
