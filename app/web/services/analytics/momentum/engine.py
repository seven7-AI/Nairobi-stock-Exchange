"""The momentum engine: absolute, relative and trend measures on a ``PriceSeries``.

Momentum here means *sustained relative strength*, not "the price went up":

* ``momentum_{1m,3m,6m,12m,24m}`` - the trailing return (same resolution rules as
  the returns engine: same segment, start within the gap threshold of its target);
* ``momentum_12m_1m`` - the classic 12-1: the return from twelve months ago to one
  month ago, which skips the short-term reversal month;
* ``relative_{w}_vs_market`` - the stock's window return minus the benchmark
  index's over the same window; ``relative_{w}_vs_sector`` - minus the equal-weighted
  mean of its sector peers' returns (needs ``min_peers`` peers with a known return);
* ``ma_{short,long}`` (simple moving averages over the last N observations, all in
  one segment), ``price_to_ma_{short,long}`` and ``ma_short_over_long``;
* ``trend_strength_{w}`` - R² of log-price on time over the window, signed by the
  slope, so +0.9 is a clean uptrend, -0.9 a clean downtrend, ~0 noise;
* ``momentum_persistence_12m`` - the share of the last twelve calendar months with a
  positive month-over-month close;
* ``distance_from_52w_high`` / ``distance_from_52w_low`` - where the close sits in
  its trailing 12-month range.

Every value is a ``Measure``; anything that cannot be computed honestly says why.

    codegraph explore "momentum_metrics relative_return moving_average trend_strength"
"""

from __future__ import annotations

import math
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date

import numpy as np

from app.web.services.analytics.config import AnalyticsConfig
from app.web.services.analytics.measure import Measure, Provenance
from app.web.services.analytics.returns.engine import WindowResult, shift_back, window_return
from app.web.services.analytics.series import PriceSeries

MOMENTUM_WINDOWS = ("1M", "3M", "6M", "12M", "24M")
RELATIVE_WINDOWS = ("1M", "3M", "6M", "12M")


@dataclass(frozen=True, slots=True)
class MetricResult:
    measure: Measure
    window_start: date | None = None
    window_end: date | None = None
    contains_flagged: bool = False


def _from_window(result: WindowResult) -> MetricResult:
    return MetricResult(result.measure, result.start, result.end, result.contains_flagged)


# --- absolute --------------------------------------------------------------------


def momentum_12_1(series: PriceSeries, as_of: date) -> MetricResult:
    """Return from the observation ~12 months before ``as_of`` to the one ~1 month before."""
    name = "momentum 12-1"
    if series.is_empty:
        return MetricResult(Measure.unavailable(f"{name}: no observations"))
    end_position = series.position_on_or_before(shift_back(as_of, 0, 1))
    if end_position is None:
        return MetricResult(Measure.unavailable(f"{name}: no observation one month before {as_of}"))
    end_day = series.dates[end_position].date()
    if (shift_back(as_of, 0, 1) - end_day).days > series.gap_threshold_days:
        return MetricResult(
            Measure.unavailable(f"{name}: nearest observation to one month ago is {end_day}")
        )
    truncated = series.as_of(end_day)
    return _from_window(window_return(truncated, end_day, "12M"))


def absolute_momentum(series: PriceSeries, as_of: date) -> dict[str, MetricResult]:
    out = {
        f"momentum_{w.lower()}": _from_window(window_return(series, as_of, w))
        for w in MOMENTUM_WINDOWS
    }
    out["momentum_12m_1m"] = momentum_12_1(series, as_of)
    return out


# --- relative --------------------------------------------------------------------


def relative_return(
    own: WindowResult, reference: Measure, *, name: str, reference_note: str
) -> MetricResult:
    """``own - reference`` when both are known; otherwise the first blocker's status."""
    if not own.measure.is_known:
        return MetricResult(
            Measure(
                None, own.measure.status, f"{name}: {own.measure.reason}", own.measure.provenance
            ),
            own.start,
            own.end,
            own.contains_flagged,
        )
    if not reference.is_known:
        return MetricResult(
            Measure(
                None,
                reference.status,
                f"{name}: {reference_note} {reference.reason}",
                own.measure.provenance,
            ),
            own.start,
            own.end,
            own.contains_flagged,
        )
    assert own.measure.value is not None and reference.value is not None
    provenance = own.measure.provenance + tuple(
        p for p in reference.provenance if p not in own.measure.provenance
    )
    return MetricResult(
        Measure.known(own.measure.value - reference.value, *provenance),
        own.start,
        own.end,
        own.contains_flagged,
    )


def relative_to_market(
    series: PriceSeries, benchmark: PriceSeries | None, as_of: date, benchmark_name: str
) -> dict[str, MetricResult]:
    out: dict[str, MetricResult] = {}
    for window in RELATIVE_WINDOWS:
        metric = f"relative_{window.lower()}_vs_market"
        own = window_return(series, as_of, window)
        if benchmark is None or benchmark.is_empty:
            reference = Measure.unavailable(f"benchmark {benchmark_name} has no observations")
        else:
            reference = window_return(benchmark, as_of, window).measure
        out[metric] = relative_return(
            own, reference, name=metric, reference_note=f"benchmark {benchmark_name}:"
        )
    return out


def sector_average_return(
    peers: Mapping[str, PriceSeries], as_of: date, window: str, *, min_peers: int
) -> Measure:
    """Equal-weighted mean of the peers' known window returns."""
    values: list[float] = []
    used: list[str] = []
    for ticker, peer in peers.items():
        result = window_return(peer, as_of, window)
        if result.measure.is_known and result.measure.value is not None:
            values.append(result.measure.value)
            used.append(ticker)
    if len(values) < min_peers:
        return Measure.unavailable(
            f"only {len(values)} peer(s) with a known {window} return (minimum {min_peers})"
        )
    return Measure.known(
        float(np.mean(values)),
        Provenance(
            table="market_metrics",
            note=(
                f"equal-weighted {window} return of {len(used)} sector peers: "
                f"{', '.join(sorted(used))}"
            ),
        ),
    )


def relative_to_sector(
    series: PriceSeries, peers: Mapping[str, PriceSeries], as_of: date, *, min_peers: int
) -> dict[str, MetricResult]:
    out: dict[str, MetricResult] = {}
    for window in RELATIVE_WINDOWS:
        metric = f"relative_{window.lower()}_vs_sector"
        own = window_return(series, as_of, window)
        reference = sector_average_return(peers, as_of, window, min_peers=min_peers)
        out[metric] = relative_return(own, reference, name=metric, reference_note="sector peers:")
    return out


# --- trend -----------------------------------------------------------------------


def _recent_same_segment(
    series: PriceSeries, as_of: date, count: int, name: str
) -> tuple[int, int] | None | Measure:
    """Positions (start, end) of the last ``count`` observations if they share a segment."""
    end = series.position_on_or_before(as_of)
    if end is None:
        return Measure.unavailable(f"{name}: no observation on or before {as_of}")
    end_day = series.dates[end].date()
    if (as_of - end_day).days > series.gap_threshold_days:
        return Measure.unavailable(f"{name}: last observation {end_day} is stale at {as_of}")
    start = end - count + 1
    if start < 0:
        return Measure.unavailable(f"{name}: needs {count} observations, has {end + 1}")
    if not series.same_segment(start, end):
        return Measure.unavailable(f"{name}: the last {count} observations span a data gap")
    return start, end


def moving_average(series: PriceSeries, as_of: date, count: int) -> MetricResult:
    name = f"MA{count}"
    located = _recent_same_segment(series, as_of, count, name)
    if isinstance(located, Measure):
        return MetricResult(located)
    assert located is not None
    start, end = located
    window = series.close.iloc[start : end + 1]
    value = float(window.mean())
    start_day, end_day = series.dates[start].date(), series.dates[end].date()
    return MetricResult(
        Measure.known(
            value,
            Provenance(
                table="stock_observations",
                ticker=series.ticker_symbol,
                start=start_day,
                end=end_day,
                note=f"{name} over {count} observations",
            ),
        ),
        start_day,
        end_day,
        bool(series.flagged.iloc[start : end + 1].any()),
    )


def price_to_ma(series: PriceSeries, as_of: date, ma: MetricResult, name: str) -> MetricResult:
    if not ma.measure.is_known:
        return MetricResult(Measure(None, ma.measure.status, f"{name}: {ma.measure.reason}"))
    if ma.measure.value is None or ma.measure.value <= 0:
        return MetricResult(Measure.not_meaningful(f"{name}: moving average is not positive"))
    located = series.close_on_or_before(as_of)
    assert located is not None
    _, close = located
    return MetricResult(
        Measure.known(close / ma.measure.value - 1.0, *ma.measure.provenance),
        ma.window_start,
        ma.window_end,
        ma.contains_flagged,
    )


def trend_strength(series: PriceSeries, as_of: date, window: str) -> MetricResult:
    """Signed R² of a least-squares line through log(close) over the trailing window."""
    name = f"trend strength {window}"
    result = window_return(series, as_of, window)
    if not result.measure.is_known or result.start is None or result.end is None:
        return MetricResult(
            Measure(None, result.measure.status, f"{name}: {result.measure.reason}")
        )
    part = series.between(result.start, result.end)
    if len(part) < 10:
        return MetricResult(
            Measure.unavailable(f"{name}: only {len(part)} observations in the window")
        )
    y = np.log(part.close.to_numpy(dtype=float))
    x = np.arange(len(y), dtype=float)
    if float(np.ptp(y)) == 0.0:  # every close identical: no trend, not a division by ~0
        return MetricResult(
            Measure.zero(part.provenance(result.start, result.end)),
            result.start,
            result.end,
            result.contains_flagged,
        )
    slope, intercept = np.polyfit(x, y, 1)
    fitted = slope * x + intercept
    ss_res = float(np.sum((y - fitted) ** 2))
    ss_tot = float(np.sum((y - y.mean()) ** 2))
    r_squared = 1.0 - ss_res / ss_tot if ss_tot > 0 else 0.0
    value = math.copysign(r_squared, slope) if slope != 0 else 0.0
    provenance = part.provenance(result.start, result.end)
    measure = Measure.known(value, provenance) if value != 0 else Measure.zero(provenance)
    return MetricResult(measure, result.start, result.end, result.contains_flagged)


def momentum_persistence(series: PriceSeries, as_of: date, months: int = 12) -> MetricResult:
    """Share of the last ``months`` month-ends with a close above the previous month-end."""
    name = f"momentum persistence {months}M"
    result = window_return(series, as_of, f"{months}M")
    if not result.measure.is_known or result.start is None or result.end is None:
        return MetricResult(
            Measure(None, result.measure.status, f"{name}: {result.measure.reason}")
        )
    part = series.between(result.start, result.end)
    month_end = part.close.groupby([part.dates.year, part.dates.month]).last()
    if len(month_end) < months + 1:
        return MetricResult(
            Measure.unavailable(f"{name}: only {len(month_end)} month-ends in the window")
        )
    changes = np.diff(month_end.to_numpy(dtype=float))[-months:]
    positive = int((changes > 0).sum())
    value = positive / months
    measure = (
        Measure.known(value, part.provenance(result.start, result.end))
        if value
        else Measure.zero(part.provenance(result.start, result.end))
    )
    return MetricResult(measure, result.start, result.end, result.contains_flagged)


def range_position(series: PriceSeries, as_of: date) -> dict[str, MetricResult]:
    """Distance of the close from its trailing-12M high and low."""
    result = window_return(series, as_of, "12M")
    if not result.measure.is_known or result.start is None or result.end is None:
        blocked = Measure(None, result.measure.status, f"52-week range: {result.measure.reason}")
        return {
            "distance_from_52w_high": MetricResult(blocked),
            "distance_from_52w_low": MetricResult(blocked),
        }
    part = series.between(result.start, result.end)
    high, low = float(part.close.max()), float(part.close.min())
    close = float(part.close.iloc[-1])
    provenance = part.provenance(result.start, result.end)

    def measure(value: float) -> Measure:
        return Measure.known(value, provenance) if value != 0 else Measure.zero(provenance)

    return {
        "distance_from_52w_high": MetricResult(
            measure(close / high - 1.0), result.start, result.end, result.contains_flagged
        ),
        "distance_from_52w_low": MetricResult(
            measure(close / low - 1.0), result.start, result.end, result.contains_flagged
        ),
    }


# --- everything ------------------------------------------------------------------


def momentum_metrics(
    series: PriceSeries,
    as_of: date,
    *,
    benchmark: PriceSeries | None,
    peers: Mapping[str, PriceSeries],
    config: AnalyticsConfig,
) -> dict[str, MetricResult]:
    m = config.momentum
    out: dict[str, MetricResult] = {}
    out.update(absolute_momentum(series, as_of))
    out.update(relative_to_market(series, benchmark, as_of, config.market.benchmark_index))
    out.update(relative_to_sector(series, peers, as_of, min_peers=m.min_peers))
    short = moving_average(series, as_of, m.ma_short)
    long = moving_average(series, as_of, m.ma_long)
    out[f"ma_{m.ma_short}"] = short
    out[f"ma_{m.ma_long}"] = long
    out[f"price_to_ma_{m.ma_short}"] = price_to_ma(series, as_of, short, f"price to MA{m.ma_short}")
    out[f"price_to_ma_{m.ma_long}"] = price_to_ma(series, as_of, long, f"price to MA{m.ma_long}")
    if short.measure.is_known and long.measure.is_known and long.measure.value:
        assert short.measure.value is not None
        out["ma_short_over_long"] = MetricResult(
            Measure.known(short.measure.value / long.measure.value - 1.0, *long.measure.provenance),
            long.window_start,
            long.window_end,
            long.contains_flagged,
        )
    else:
        blocker = long if not long.measure.is_known else short
        out["ma_short_over_long"] = MetricResult(
            Measure(
                None,
                blocker.measure.status,
                f"MA{m.ma_short}/MA{m.ma_long}: {blocker.measure.reason}",
            )
        )
    out[f"trend_strength_{m.trend_window.lower()}"] = trend_strength(series, as_of, m.trend_window)
    out["momentum_persistence_12m"] = momentum_persistence(series, as_of)
    out.update(range_position(series, as_of))
    return out


__all__ = [
    "MOMENTUM_WINDOWS",
    "RELATIVE_WINDOWS",
    "MetricResult",
    "absolute_momentum",
    "momentum_12_1",
    "momentum_metrics",
    "momentum_persistence",
    "moving_average",
    "price_to_ma",
    "range_position",
    "relative_return",
    "relative_to_market",
    "relative_to_sector",
    "sector_average_return",
    "trend_strength",
]
