"""Point-in-time view of the scraper's financial statements.

The scraper stores every version of every line item it has ever seen, with the
moment it first saw it (``first_seen_at``). This module answers the only question
the engines ask of that table: **what was known about a period on a given date?**

Two rules turn captures into availability dates:

1. A figure captured *live* is available from the day it was first seen.
2. A figure first captured long after its period ended - the 2026-09 backfill of
   FY2021-FY2025 - was obviously published earlier. Its availability is set to
   ``period_end + publication_lag`` (config; 90 d annual / 60 d interim, the CMA
   deadlines). This is an assumption and is recorded as one in the provenance.
   Only the *initial* capture of a (statement, period, line item) gets this
   treatment; a later capture is a restatement and is available from its own
   first-seen date, never earlier.

Values are scaled here, once, into base units: ``millions_kes`` -> KES,
``millions`` -> shares, ``percent`` -> fraction, ``kes``/``ratio`` unchanged.
A ``-`` on the site is a ``MISSING`` measure, never zero.

    codegraph explore "StatementRow load_statement_rows point_in_time statement_measure"
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from typing import Any

from app.web.services.analytics.config import AnalyticsConfig
from app.web.services.analytics.measure import Measure, Provenance

STATEMENTS_TABLE = "financial_statements"

#: Displayed unit -> multiplier into base units. Percent becomes a fraction so a
#: margin of 38.69% and a computed margin of 0.3869 compare directly.
UNIT_SCALE = {
    "millions_kes": 1_000_000.0,
    "thousands_kes": 1_000.0,
    "billions_kes": 1_000_000_000.0,
    "millions": 1_000_000.0,
    "thousands": 1_000.0,
    "percent": 0.01,
    "kes": 1.0,
    "ratio": 1.0,
}


@dataclass(frozen=True, slots=True)
class StatementRow:
    """One captured line-item value with the date it became usable."""

    id: int
    ticker_symbol: str
    statement: str
    period_type: str
    fiscal_period_end: date
    fiscal_label: str
    line_item: str
    label: str
    value: float | None
    value_raw: str
    unit: str
    currency: str
    first_seen_at: datetime
    available_from: date
    #: True when ``available_from`` came from the publication-lag assumption.
    availability_assumed: bool

    @property
    def key(self) -> tuple[str, str, date, str]:
        return (self.statement, self.period_type, self.fiscal_period_end, self.line_item)


def _parse_datetime(value: Any) -> datetime:
    parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)


def availability_date(
    first_seen_at: datetime,
    period_end: date,
    period_type: str,
    config: AnalyticsConfig,
    *,
    initial_capture: bool,
) -> tuple[date, bool]:
    """When a captured figure became usable, and whether that date is an assumption."""
    seen = first_seen_at.astimezone(UTC).date()
    if not initial_capture:
        return seen, False
    lag: timedelta = config.fundamentals.publication_lag(period_type)
    published = period_end + lag
    if published < seen:
        return published, True
    return seen, False


def load_statement_rows(
    raw_rows: Iterable[dict[str, Any]], config: AnalyticsConfig
) -> list[StatementRow]:
    """Apply the availability rules to the scraper's raw rows."""
    parsed: list[dict[str, Any]] = []
    for raw in raw_rows:
        parsed.append(
            {
                **raw,
                "_first_seen": _parse_datetime(raw["first_seen_at"]),
                "_period_end": date.fromisoformat(str(raw["fiscal_period_end"])[:10]),
            }
        )
    earliest: dict[tuple[str, str, date, str], datetime] = {}
    for row in parsed:
        key = (row["statement"], row["period_type"], row["_period_end"], row["line_item"])
        seen = row["_first_seen"]
        if key not in earliest or seen < earliest[key]:
            earliest[key] = seen

    rows: list[StatementRow] = []
    for row in parsed:
        key = (row["statement"], row["period_type"], row["_period_end"], row["line_item"])
        initial = row["_first_seen"] == earliest[key]
        available, assumed = availability_date(
            row["_first_seen"],
            row["_period_end"],
            row["period_type"],
            config,
            initial_capture=initial,
        )
        rows.append(
            StatementRow(
                id=int(row["id"]),
                ticker_symbol=str(row["ticker_symbol"]),
                statement=str(row["statement"]),
                period_type=str(row["period_type"]),
                fiscal_period_end=row["_period_end"],
                fiscal_label=str(row["fiscal_label"]),
                line_item=str(row["line_item"]),
                label=str(row.get("label") or row["line_item"]),
                value=None if row.get("value") is None else float(row["value"]),
                value_raw=str(row.get("value_raw") or "-"),
                unit=str(row.get("unit") or "ratio"),
                currency=str(row.get("currency") or "KES"),
                first_seen_at=row["_first_seen"],
                available_from=available,
                availability_assumed=assumed,
            )
        )
    rows.sort(key=lambda r: (r.fiscal_period_end, r.statement, r.line_item, r.first_seen_at))
    return rows


def point_in_time(
    rows: Iterable[StatementRow], as_of: date
) -> dict[tuple[str, str, date, str], StatementRow]:
    """The latest version of each line item that was available on ``as_of``.

    A restatement captured after ``as_of`` is invisible; the original stays in force.
    """
    chosen: dict[tuple[str, str, date, str], StatementRow] = {}
    for row in rows:
        if row.available_from > as_of:
            continue
        current = chosen.get(row.key)
        if current is None or row.first_seen_at > current.first_seen_at:
            chosen[row.key] = row
    return chosen


def periods_available(
    rows: Iterable[StatementRow], as_of: date, *, statement: str, period_type: str = "annual"
) -> list[date]:
    """Period ends of one statement known on ``as_of``, oldest first."""
    ends = {
        row.fiscal_period_end
        for row in point_in_time(rows, as_of).values()
        if row.statement == statement and row.period_type == period_type
    }
    return sorted(ends)


def statement_measure(
    row: StatementRow | None, *, reason_if_absent: str = "line item not reported"
) -> Measure:
    """A row as a base-unit ``Measure`` with provenance; ``-`` on the site is MISSING."""
    if row is None:
        return Measure.missing(reason_if_absent)
    provenance = Provenance(
        table=STATEMENTS_TABLE,
        ids=(row.id,),
        ticker=row.ticker_symbol,
        end=row.fiscal_period_end,
        note=(
            f"{row.statement}/{row.fiscal_label} {row.label} = {row.value_raw} {row.unit}; "
            f"available {row.available_from.isoformat()}"
            + (" (publication-lag assumption)" if row.availability_assumed else "")
        ),
    )
    if row.value is None:
        return Measure.missing(
            f"{row.label} shown as '{row.value_raw}' for {row.fiscal_label}", provenance
        )
    scale = UNIT_SCALE.get(row.unit)
    if scale is None:
        return Measure.unavailable(f"unknown unit {row.unit!r} for {row.label}", provenance)
    return Measure.known(row.value * scale, provenance)


def line_item_series(
    rows: Iterable[StatementRow],
    as_of: date,
    *,
    statement: str,
    line_item: str,
    period_type: str = "annual",
) -> list[tuple[date, Measure]]:
    """One line item across periods as known on ``as_of``, oldest first."""
    snapshot = point_in_time(rows, as_of)
    series: list[tuple[date, Measure]] = []
    by_period: dict[date, StatementRow] = {}
    for key, row in snapshot.items():
        if key[0] == statement and key[1] == period_type and key[3] == line_item:
            by_period[row.fiscal_period_end] = row
    for period_end in sorted(by_period):
        series.append((period_end, statement_measure(by_period[period_end])))
    return series


def latest_line_item(
    rows: Iterable[StatementRow],
    as_of: date,
    *,
    statement: str,
    line_item: str,
    period_type: str = "annual",
) -> Measure:
    series = line_item_series(
        rows, as_of, statement=statement, line_item=line_item, period_type=period_type
    )
    if not series:
        return Measure.missing(
            f"{line_item} not reported in any {period_type} {statement} known on {as_of}"
        )
    return series[-1][1]


def group_by_ticker(rows: Iterable[StatementRow]) -> dict[str, list[StatementRow]]:
    grouped: dict[str, list[StatementRow]] = defaultdict(list)
    for row in rows:
        grouped[row.ticker_symbol].append(row)
    return dict(grouped)


__all__ = [
    "STATEMENTS_TABLE",
    "UNIT_SCALE",
    "StatementRow",
    "availability_date",
    "group_by_ticker",
    "latest_line_item",
    "line_item_series",
    "load_statement_rows",
    "periods_available",
    "point_in_time",
    "statement_measure",
]
