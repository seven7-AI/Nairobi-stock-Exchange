"""``Measure`` - a number that knows whether it exists.

Every engine in ``app/web/services/analytics`` returns these instead of bare
floats, because the difference between *known*, *missing*, *unavailable*,
*zero*, *not applicable* and *not meaningful* is investment information:

    missing dividend         != dividend of 0
    negative-earnings P/E    != a very low P/E
    12M return across a gap  != a 12M return

A ``Measure`` also carries where it came from (``Provenance``), so a score can be
traced back to the observations and statement rows behind it.

    codegraph explore "Measure MeasureStatus Provenance safe_div"
"""

from __future__ import annotations

import math
from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import date
from enum import StrEnum
from typing import Any, Self


class MeasureStatus(StrEnum):
    """Why a value is, or is not, there."""

    #: A real number computed from real inputs.
    KNOWN = "known"
    #: The source explicitly says zero (a company that paid no dividend, zero volume).
    ZERO = "zero"
    #: The source should carry the input but this row/cell is absent.
    MISSING = "missing"
    #: Cannot be computed: insufficient history, a data gap, no source at all.
    UNAVAILABLE = "unavailable"
    #: The metric does not apply to this kind of instrument (interest coverage of a bank).
    NOT_APPLICABLE = "not_applicable"
    #: Inputs exist but the result would mislead (P/E on negative earnings).
    NOT_MEANINGFUL = "not_meaningful"


@dataclass(frozen=True, slots=True)
class Provenance:
    """A pointer at the source rows behind a value.

    Either explicit row ids or a (ticker, start, end) range over a table - ranges
    keep the record small for windowed calculations over thousands of rows.
    """

    table: str
    ids: tuple[int, ...] = ()
    ticker: str | None = None
    start: date | None = None
    end: date | None = None
    note: str | None = None

    def as_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {"table": self.table}
        if self.ids:
            payload["ids"] = list(self.ids)
        if self.ticker is not None:
            payload["ticker"] = self.ticker
        if self.start is not None:
            payload["start"] = self.start.isoformat()
        if self.end is not None:
            payload["end"] = self.end.isoformat()
        if self.note is not None:
            payload["note"] = self.note
        return payload


@dataclass(frozen=True, slots=True)
class Measure:
    """A value plus its status, reason and provenance. Immutable."""

    value: float | None
    status: MeasureStatus
    reason: str | None = None
    provenance: tuple[Provenance, ...] = field(default_factory=tuple)

    def __post_init__(self) -> None:
        if self.status in (MeasureStatus.KNOWN, MeasureStatus.ZERO):
            if self.value is None or not math.isfinite(self.value):
                raise ValueError(f"{self.status} measure needs a finite value, got {self.value!r}")
        elif self.value is not None:
            raise ValueError(f"{self.status} measure must not carry a value, got {self.value!r}")

    # -- constructors ------------------------------------------------------
    @classmethod
    def known(cls, value: float, *provenance: Provenance, reason: str | None = None) -> Self:
        """A finite number. Exactly zero is recorded as ZERO, not KNOWN."""
        if value == 0:
            return cls(0.0, MeasureStatus.ZERO, reason, tuple(provenance))
        return cls(float(value), MeasureStatus.KNOWN, reason, tuple(provenance))

    @classmethod
    def zero(cls, *provenance: Provenance, reason: str | None = None) -> Self:
        return cls(0.0, MeasureStatus.ZERO, reason, tuple(provenance))

    @classmethod
    def missing(cls, reason: str, *provenance: Provenance) -> Self:
        return cls(None, MeasureStatus.MISSING, reason, tuple(provenance))

    @classmethod
    def unavailable(cls, reason: str, *provenance: Provenance) -> Self:
        return cls(None, MeasureStatus.UNAVAILABLE, reason, tuple(provenance))

    @classmethod
    def not_applicable(cls, reason: str, *provenance: Provenance) -> Self:
        return cls(None, MeasureStatus.NOT_APPLICABLE, reason, tuple(provenance))

    @classmethod
    def not_meaningful(cls, reason: str, *provenance: Provenance) -> Self:
        return cls(None, MeasureStatus.NOT_MEANINGFUL, reason, tuple(provenance))

    # -- queries -----------------------------------------------------------
    @property
    def is_known(self) -> bool:
        """True for KNOWN and ZERO - the two statuses that carry a usable number."""
        return self.status in (MeasureStatus.KNOWN, MeasureStatus.ZERO)

    @property
    def is_positive(self) -> bool:
        return self.is_known and self.value is not None and self.value > 0

    def as_dict(self) -> dict[str, Any]:
        """The JSON shape stored in the analytics tables and served by the API."""
        return {
            "value": self.value,
            "status": self.status.value,
            "reason": self.reason,
            "provenance": [p.as_dict() for p in self.provenance],
        }

    def with_provenance(self, *provenance: Provenance) -> Measure:
        return Measure(self.value, self.status, self.reason, self.provenance + tuple(provenance))


def as_measure(value: Measure | float | None, *, reason: str = "input missing") -> Measure:
    """Lift a raw number (or None) into a ``Measure`` so helpers accept both."""
    if isinstance(value, Measure):
        return value
    if value is None or (isinstance(value, float) and not math.isfinite(value)):
        return Measure.missing(reason)
    return Measure.known(float(value))


def merge_provenance(*measures: Measure) -> tuple[Provenance, ...]:
    seen: list[Provenance] = []
    for measure in measures:
        for item in measure.provenance:
            if item not in seen:
                seen.append(item)
    return tuple(seen)


def first_unusable(*measures: Measure) -> Measure | None:
    """The first input that cannot feed a calculation, or None if all are usable."""
    for measure in measures:
        if not measure.is_known:
            return measure
    return None


def _propagate(name: str, *inputs: Measure) -> Measure | None:
    """If any input is unusable, the result inherits its status with a fuller reason."""
    blocker = first_unusable(*inputs)
    if blocker is None:
        return None
    reason = f"{name}: input {blocker.status.value}" + (
        f" ({blocker.reason})" if blocker.reason else ""
    )
    return Measure(None, blocker.status, reason, merge_provenance(*inputs))


def safe_div(
    numerator: Measure | float | None,
    denominator: Measure | float | None,
    *,
    name: str = "ratio",
    require_positive_denominator: bool = True,
) -> Measure:
    """``numerator / denominator`` that never produces a misleading number.

    A zero denominator is NOT_MEANINGFUL; a negative one too when the ratio only
    makes sense over a positive base (P/E, P/B, payout) - pass
    ``require_positive_denominator=False`` for ratios like growth where sign is fine.
    """
    top = as_measure(numerator, reason=f"{name}: numerator missing")
    bottom = as_measure(denominator, reason=f"{name}: denominator missing")
    blocked = _propagate(name, top, bottom)
    if blocked is not None:
        return blocked
    assert top.value is not None and bottom.value is not None
    provenance = merge_provenance(top, bottom)
    if bottom.value == 0:
        return Measure.not_meaningful(f"{name}: denominator is zero", *provenance)
    if require_positive_denominator and bottom.value < 0:
        return Measure.not_meaningful(f"{name}: denominator is negative", *provenance)
    return Measure.known(top.value / bottom.value, *provenance)


def pct_change(
    new: Measure | float | None, old: Measure | float | None, *, name: str = "change"
) -> Measure:
    """``(new - old) / |old|`` as a fraction; NOT_MEANINGFUL when the base is zero."""
    after = as_measure(new, reason=f"{name}: current value missing")
    before = as_measure(old, reason=f"{name}: base value missing")
    blocked = _propagate(name, after, before)
    if blocked is not None:
        return blocked
    assert after.value is not None and before.value is not None
    provenance = merge_provenance(after, before)
    if before.value == 0:
        return Measure.not_meaningful(f"{name}: base value is zero", *provenance)
    return Measure.known((after.value - before.value) / abs(before.value), *provenance)


def cagr(
    end: Measure | float | None, start: Measure | float | None, years: float, *, name: str = "cagr"
) -> Measure:
    """Compound annual growth; NOT_MEANINGFUL when either end is non-positive."""
    last = as_measure(end, reason=f"{name}: end value missing")
    first = as_measure(start, reason=f"{name}: start value missing")
    blocked = _propagate(name, last, first)
    if blocked is not None:
        return blocked
    assert last.value is not None and first.value is not None
    provenance = merge_provenance(last, first)
    if years <= 0:
        return Measure.unavailable(f"{name}: period must be positive, got {years}", *provenance)
    if first.value <= 0 or last.value <= 0:
        return Measure.not_meaningful(f"{name}: needs positive start and end values", *provenance)
    return Measure.known((last.value / first.value) ** (1.0 / years) - 1.0, *provenance)


def all_known(measures: Iterable[Measure]) -> bool:
    return all(measure.is_known for measure in measures)


__all__ = [
    "Measure",
    "MeasureStatus",
    "Provenance",
    "all_known",
    "as_measure",
    "cagr",
    "first_unusable",
    "merge_provenance",
    "pct_change",
    "safe_div",
]
