"""Shared helpers for the dashboard services: the wire shape of a number, the
equity universe, and text hygiene for anything that leaves the process.

Every number the dashboard serves is ``{"value", "status", "reason"}`` - the same
triple ``ResearchProfile`` uses - so the client can never mistake missing for zero.

    codegraph explore "measure known unavailable equity_universe sanitise_text"
"""

from __future__ import annotations

import re
from datetime import date
from typing import Any

from app.web.services.analytics.classification.lookup import ClassificationIndex

#: Sector codes that are not equities and never belong in a stock list.
NON_EQUITY_SECTORS: frozenset[str] = frozenset({"indices", "etf"})

_PATH = re.compile(r"/(?:home|srv|tmp|var|usr)/\S+")


def measure(value: float | None, status: str, reason: str | None = None) -> dict[str, Any]:
    return {"value": value, "status": status, "reason": reason}


def known(value: float | int) -> dict[str, Any]:
    return measure(float(value), "known")


def unavailable(reason: str) -> dict[str, Any]:
    return measure(None, "unavailable", reason)


def missing(reason: str) -> dict[str, Any]:
    return measure(None, "missing", reason)


def from_optional(value: float | int | None, reason_if_none: str) -> dict[str, Any]:
    """A scraped field: known when present, unavailable (with the reason) when not."""
    if value is None:
        return unavailable(reason_if_none)
    try:
        return known(float(value))
    except (TypeError, ValueError):
        return unavailable(f"{reason_if_none} (unparseable: {value!r})")


def from_row(row: Any) -> dict[str, Any]:
    """A stored result row (``value``/``status``/``reason`` attributes) as a measure."""
    return measure(float(row.value) if row.value is not None else None, str(row.status), row.reason)


def absent(name: str, as_of: date | None) -> dict[str, Any]:
    day = as_of.isoformat() if as_of else "any date"
    return unavailable(f"{name}: not computed as of {day}")


def equity_universe(index: ClassificationIndex, as_of: date) -> list[str]:
    """Classified instruments that are equities on ``as_of`` (no indices, no ETFs)."""
    out: list[str] = []
    for ticker in index.tickers:
        if ticker.startswith("^"):
            continue
        assignment = index.sector_for(ticker, as_of)
        if assignment is not None and assignment.sector_code in NON_EQUITY_SECTORS:
            continue
        out.append(ticker)
    return out


def sanitise_text(text: str | None, *, limit: int = 300) -> str | None:
    """First line only, filesystem paths blanked, length bounded - for error strings
    and details that came from inside the process."""
    if not text:
        return None
    first = text.strip().splitlines()[0] if text.strip() else ""
    return _PATH.sub("<path>", first)[:limit] or None


def severity_counts(findings: list[Any]) -> dict[str, int]:
    counts = {"error": 0, "warning": 0, "info": 0}
    for f in findings:
        counts[str(f.severity)] = counts.get(str(f.severity), 0) + 1
    return counts


__all__ = [
    "NON_EQUITY_SECTORS",
    "absent",
    "equity_universe",
    "from_optional",
    "from_row",
    "known",
    "measure",
    "missing",
    "sanitise_text",
    "severity_counts",
    "unavailable",
]
