"""The returns engine: trailing, year-to-date, rolling and cumulative returns.

All windows are resolved on the instrument's own observations, never by calendar
arithmetic alone:

* the **end** of a window is the last observation on or before ``as_of``; if that
  observation is older than the gap threshold the return is ``unavailable`` - an
  ``as_of`` inside the 2025 hole must not report December-2024 numbers as current;
* the **start** is the last observation on or before ``end - window`` (for ``1D``,
  the previous observation);
* start and end must lie in the same segment - a window that crosses a data gap is
  ``unavailable`` with the gap in the reason, never bridged;
* a newly listed instrument has no start observation for long windows, a delisted
  one has a stale end: both ``unavailable`` with the reason.

Returns are simple fractions (0.10 = +10 %), unadjusted for corporate actions - the
row is marked when the window contains a flagged observation so a consumer can
discount it.

    codegraph explore "trailing_returns window_return ytd_return PriceSeries"
"""

from __future__ import annotations

import calendar
from dataclasses import dataclass
from datetime import date, timedelta

import pandas as pd

from app.web.services.analytics.measure import Measure, Provenance
from app.web.services.analytics.series import PriceSeries

#: Window name -> (days, months). ``1D`` is "the previous observation".
WINDOWS: dict[str, tuple[int, int] | None] = {
    "1D": None,
    "1W": (7, 0),
    "1M": (0, 1),
    "3M": (0, 3),
    "6M": (0, 6),
    "12M": (0, 12),
    "24M": (0, 24),
    "36M": (0, 36),
}


def shift_back(day: date, days: int, months: int) -> date:
    """``day`` minus a calendar span; month arithmetic clamps to the month's last day."""
    year, month = day.year, day.month - months
    while month <= 0:
        month += 12
        year -= 1
    last = calendar.monthrange(year, month)[1]
    return date(year, month, min(day.day, last)) - timedelta(days=days)


#: Metric names as stored in ``market_metrics``.
METRIC_NAMES = {window: f"return_{window.lower()}" for window in WINDOWS} | {
    "YTD": "return_ytd",
    "YOY": "return_yoy",
}


@dataclass(frozen=True, slots=True)
class WindowResult:
    measure: Measure
    start: date | None
    end: date | None
    #: True when an observation inside the window carries a corporate-action flag.
    contains_flagged: bool


def _end_position(series: PriceSeries, as_of: date, name: str) -> tuple[int | None, Measure | None]:
    if series.is_empty:
        return None, Measure.unavailable(f"{name}: no observations")
    position = series.position_on_or_before(as_of)
    if position is None:
        return None, Measure.unavailable(f"{name}: no observation on or before {as_of}")
    end_day = series.dates[position].date()
    if (as_of - end_day).days > series.gap_threshold_days:
        return None, Measure.unavailable(
            f"{name}: last observation {end_day} is {(as_of - end_day).days} days before "
            f"{as_of} (limit {series.gap_threshold_days})"
        )
    return position, None


def _return_between(
    series: PriceSeries, start_position: int, end_position: int, name: str
) -> WindowResult:
    start_day = series.dates[start_position].date()
    end_day = series.dates[end_position].date()
    if not series.same_segment(start_position, end_position):
        gaps = series.gaps_between(start_day, end_day)
        described = ", ".join(f"{g.after}->{g.before} ({g.days} d)" for g in gaps) or "unknown"
        return WindowResult(
            Measure.unavailable(
                f"{name}: window {start_day}..{end_day} crosses data gap {described}"
            ),
            start_day,
            end_day,
            False,
        )
    start_close = float(series.close.iloc[start_position])
    end_close = float(series.close.iloc[end_position])
    flagged = bool(series.flagged.iloc[start_position + 1 : end_position + 1].any())
    provenance = Provenance(
        table="stock_observations",
        ticker=series.ticker_symbol,
        start=start_day,
        end=end_day,
        note=f"{name}: {start_close} -> {end_close}"
        + (" (window contains a flagged observation)" if flagged else ""),
    )
    return WindowResult(
        Measure.known(end_close / start_close - 1.0, provenance), start_day, end_day, flagged
    )


def window_return(series: PriceSeries, as_of: date, window: str) -> WindowResult:
    """Trailing return for one of ``WINDOWS`` as of a date."""
    if window not in WINDOWS:
        raise ValueError(f"unknown window {window!r}; expected one of {sorted(WINDOWS)}")
    name = f"return {window}"
    end_position, blocked = _end_position(series, as_of, name)
    if blocked is not None or end_position is None:
        return WindowResult(blocked or Measure.unavailable(name), None, None, False)
    end_day = series.dates[end_position].date()
    length = WINDOWS[window]
    if length is None:
        start_position = end_position - 1
        if start_position < 0:
            return WindowResult(
                Measure.unavailable(f"{name}: no previous observation"), None, end_day, False
            )
    else:
        target = shift_back(end_day, *length)
        maybe = series.position_on_or_before(target)
        if maybe is None:
            first = series.first_date
            return WindowResult(
                Measure.unavailable(
                    f"{name}: history starts {first}, after the window start {target}"
                ),
                None,
                end_day,
                False,
            )
        start_position = maybe
        # The start observation must itself be reasonably close to the target date,
        # otherwise a thin listing would report a "1M" return over a much longer span.
        start_day = series.dates[start_position].date()
        if (target - start_day).days > series.gap_threshold_days:
            crossed = series.gaps_between(start_day, end_day)
            if crossed:
                described = ", ".join(f"{g.after}->{g.before} ({g.days} d)" for g in crossed)
                reason = f"{name}: window {target}..{end_day} crosses data gap {described}"
            else:
                reason = (
                    f"{name}: no observation within {series.gap_threshold_days} days before "
                    f"{target} (nearest {start_day})"
                )
            return WindowResult(Measure.unavailable(reason), start_day, end_day, False)
    return _return_between(series, start_position, end_position, name)


def ytd_return(series: PriceSeries, as_of: date) -> WindowResult:
    """From the last observation of the previous calendar year to the end observation."""
    name = "return YTD"
    end_position, blocked = _end_position(series, as_of, name)
    if blocked is not None or end_position is None:
        return WindowResult(blocked or Measure.unavailable(name), None, None, False)
    end_day = series.dates[end_position].date()
    year_start = date(end_day.year, 1, 1)
    start_position = series.position_on_or_before(year_start - timedelta(days=1))
    if start_position is None:
        return WindowResult(
            Measure.unavailable(
                f"{name}: no observation before {year_start} (history starts {series.first_date})"
            ),
            None,
            end_day,
            False,
        )
    start_day = series.dates[start_position].date()
    if (year_start - start_day).days > series.gap_threshold_days:
        return WindowResult(
            Measure.unavailable(f"{name}: last observation before {year_start} is {start_day}"),
            start_day,
            end_day,
            False,
        )
    return _return_between(series, start_position, end_position, name)


def trailing_returns(series: PriceSeries, as_of: date) -> dict[str, WindowResult]:
    """Every trailing window plus YTD and YoY (== 12M), keyed by metric name."""
    results = {METRIC_NAMES[window]: window_return(series, as_of, window) for window in WINDOWS}
    results[METRIC_NAMES["YTD"]] = ytd_return(series, as_of)
    results[METRIC_NAMES["YOY"]] = results[METRIC_NAMES["12M"]]
    return results


def cumulative_return(series: PriceSeries, start: date, end: date) -> WindowResult:
    """Return from the last observation on/before ``start`` to the one on/before ``end``."""
    name = f"cumulative return {start}..{end}"
    if series.is_empty:
        return WindowResult(Measure.unavailable(f"{name}: no observations"), None, None, False)
    start_position = series.position_on_or_before(start)
    end_position = series.position_on_or_before(end)
    if start_position is None or end_position is None or end_position <= start_position:
        return WindowResult(
            Measure.unavailable(f"{name}: fewer than two observations in range"), None, None, False
        )
    return _return_between(series, start_position, end_position, name)


def rolling_returns(series: PriceSeries, window: str) -> pd.Series:
    """The trailing ``window`` return at every observation date; NaN where unavailable.

    Vectorised for diagrams and backtests; the per-date semantics are exactly
    ``window_return`` (same segment, start within the gap threshold of the target).
    """
    if window not in WINDOWS or series.is_empty:
        return pd.Series(dtype=float, index=series.dates)
    length = WINDOWS[window]
    closes = series.close
    if length is None:
        out = closes.pct_change()
        out[series.segment.diff().fillna(1) != 0] = float("nan")
        return out
    values: list[float] = []
    for position, stamp in enumerate(series.dates):
        end_day = stamp.date()
        target = shift_back(end_day, *length)
        start_position = series.position_on_or_before(target)
        if (
            start_position is None
            or (target - series.dates[start_position].date()).days > series.gap_threshold_days
            or not series.same_segment(start_position, position)
        ):
            values.append(float("nan"))
            continue
        values.append(float(closes.iloc[position] / closes.iloc[start_position] - 1.0))
    return pd.Series(values, index=series.dates, dtype=float)


__all__ = [
    "METRIC_NAMES",
    "WINDOWS",
    "WindowResult",
    "cumulative_return",
    "rolling_returns",
    "shift_back",
    "trailing_returns",
    "window_return",
    "ytd_return",
]
