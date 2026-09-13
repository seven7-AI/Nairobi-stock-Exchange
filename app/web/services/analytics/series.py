"""``PriceSeries`` - one instrument's observations as an ordered, gap-aware series.

Every market engine (returns, momentum, risk, liquidity, backtesting) consumes
this rather than raw rows. It keeps:

* closes and volumes as pandas Series on a ``DatetimeIndex`` (unique, ascending);
* the **segments** the observations fall into - a break longer than
  ``MarketConfig.gap_threshold_days`` starts a new segment, so a window that
  spans two segments can be refused instead of silently bridged;
* the source tickers the rows were recorded under (``BBK`` rows inside ``ABSA``),
  the row-id range for provenance, and which rows the scraper flagged.

``as_of(day)`` returns the series truncated to observations on or before ``day`` -
the one operation that makes every calculation point-in-time.

    codegraph explore "PriceSeries build_price_series find_gaps"
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import date, timedelta
from itertools import pairwise
from typing import Any

import numpy as np
import pandas as pd

from app.web.services.analytics.config import AnalyticsConfig
from app.web.services.analytics.measure import Provenance

OBSERVATIONS_TABLE = "stock_observations"


@dataclass(frozen=True, slots=True)
class Gap:
    """A break in observations: the last day before it and the first day after."""

    after: date
    before: date

    @property
    def days(self) -> int:
        return (self.before - self.after).days


def find_gaps(dates: Iterable[date], threshold_days: int) -> list[Gap]:
    """Breaks longer than ``threshold_days`` between consecutive observation dates."""
    ordered = sorted(set(dates))
    threshold = timedelta(days=threshold_days)
    return [
        Gap(previous, current)
        for previous, current in pairwise(ordered)
        if current - previous > threshold
    ]


@dataclass(frozen=True)
class PriceSeries:
    ticker_symbol: str
    close: pd.Series
    volume: pd.Series
    #: Segment id per observation (0-based, increasing); a gap starts a new one.
    segment: pd.Series
    gaps: tuple[Gap, ...]
    source_tickers: tuple[str, ...]
    row_ids: pd.Series
    flagged: pd.Series
    gap_threshold_days: int

    # -- shape ----------------------------------------------------------------
    def __len__(self) -> int:
        return len(self.close)

    @property
    def is_empty(self) -> bool:
        return len(self.close) == 0

    @property
    def dates(self) -> pd.DatetimeIndex:
        return pd.DatetimeIndex(self.close.index)

    @property
    def first_date(self) -> date | None:
        return None if self.is_empty else self.dates[0].date()

    @property
    def last_date(self) -> date | None:
        return None if self.is_empty else self.dates[-1].date()

    # -- point in time --------------------------------------------------------
    def as_of(self, day: date) -> PriceSeries:
        """Observations on or before ``day``. The only way engines see history."""
        if self.is_empty:
            return self
        mask = self.dates <= pd.Timestamp(day)
        if bool(mask.all()):
            return self
        return PriceSeries(
            ticker_symbol=self.ticker_symbol,
            close=self.close[mask],
            volume=self.volume[mask],
            segment=self.segment[mask],
            gaps=tuple(g for g in self.gaps if g.before <= day),
            source_tickers=self.source_tickers,
            row_ids=self.row_ids[mask],
            flagged=self.flagged[mask],
            gap_threshold_days=self.gap_threshold_days,
        )

    def between(self, start: date, end: date) -> PriceSeries:
        series = self.as_of(end)
        if series.is_empty:
            return series
        mask = series.dates >= pd.Timestamp(start)
        return PriceSeries(
            ticker_symbol=series.ticker_symbol,
            close=series.close[mask],
            volume=series.volume[mask],
            segment=series.segment[mask],
            gaps=tuple(g for g in series.gaps if g.after >= start),
            source_tickers=series.source_tickers,
            row_ids=series.row_ids[mask],
            flagged=series.flagged[mask],
            gap_threshold_days=series.gap_threshold_days,
        )

    # -- lookups --------------------------------------------------------------
    def position_on_or_before(self, day: date) -> int | None:
        """Index of the last observation on or before ``day``; None if there is none."""
        if self.is_empty:
            return None
        position = int(self.dates.searchsorted(pd.Timestamp(day), side="right")) - 1
        return position if position >= 0 else None

    def close_on_or_before(self, day: date) -> tuple[date, float] | None:
        position = self.position_on_or_before(day)
        if position is None:
            return None
        return self.dates[position].date(), float(self.close.iloc[position])

    def same_segment(self, start_position: int, end_position: int) -> bool:
        return int(self.segment.iloc[start_position]) == int(self.segment.iloc[end_position])

    def gaps_between(self, start: date, end: date) -> list[Gap]:
        return [g for g in self.gaps if g.after >= start and g.before <= end]

    def daily_returns(self) -> pd.Series:
        """Simple returns; NaN on the first observation of every segment (never across a gap)."""
        if self.is_empty:
            return pd.Series(dtype=float)
        returns = self.close.pct_change()
        new_segment = self.segment.diff().fillna(1) != 0
        returns[new_segment] = np.nan
        return returns

    def provenance(self, start: date | None = None, end: date | None = None) -> Provenance:
        return Provenance(
            table=OBSERVATIONS_TABLE,
            ticker=self.ticker_symbol,
            start=start or self.first_date,
            end=end or self.last_date,
            note=f"{len(self)} observations"
            + (f", recorded as {'/'.join(self.source_tickers)}" if self.source_tickers else ""),
        )


def build_price_series(
    ticker_symbol: str, observations: Iterable[Mapping[str, Any]], config: AnalyticsConfig
) -> PriceSeries:
    """From the scraper's rows (any order, duplicates collapsed to the last) to a series.

    Rows with a non-positive close are dropped - they are data defects the quality
    checks report, not prices - so nothing downstream divides by zero.
    """
    threshold = config.market.gap_threshold_days
    records: dict[date, Mapping[str, Any]] = {}
    sources: list[str] = []
    for row in observations:
        close = row.get("close_price")
        if close is None or float(close) <= 0:
            continue
        day = date.fromisoformat(str(row["trade_date"])[:10])
        records[day] = row
        source = row.get("source_ticker")
        if source and source not in sources:
            sources.append(str(source))
    if not records:
        empty = pd.Series(dtype=float, index=pd.DatetimeIndex([]))
        return PriceSeries(
            ticker_symbol=ticker_symbol.upper(),
            close=empty,
            volume=empty.copy(),
            segment=pd.Series(dtype=int, index=pd.DatetimeIndex([])),
            gaps=(),
            source_tickers=(),
            row_ids=pd.Series(dtype=int, index=pd.DatetimeIndex([])),
            flagged=pd.Series(dtype=bool, index=pd.DatetimeIndex([])),
            gap_threshold_days=threshold,
        )
    days = sorted(records)
    index = pd.DatetimeIndex([pd.Timestamp(d) for d in days])
    closes = pd.Series([float(records[d]["close_price"]) for d in days], index=index, dtype=float)
    volumes = pd.Series(
        [np.nan if records[d].get("volume") is None else float(records[d]["volume"]) for d in days],
        index=index,
        dtype=float,
    )
    row_ids = pd.Series([int(records[d].get("id") or 0) for d in days], index=index, dtype=int)
    flagged = pd.Series(
        [bool(_is_flagged(records[d].get("quality_flags"))) for d in days], index=index, dtype=bool
    )
    gaps = find_gaps(days, threshold)
    gap_starts = {g.before for g in gaps}
    segment_ids: list[int] = []
    current = 0
    for day in days:
        if day in gap_starts:
            current += 1
        segment_ids.append(current)
    segment = pd.Series(segment_ids, index=index, dtype=int)
    return PriceSeries(
        ticker_symbol=ticker_symbol.upper(),
        close=closes,
        volume=volumes,
        segment=segment,
        gaps=tuple(gaps),
        source_tickers=tuple(sources),
        row_ids=row_ids,
        flagged=flagged,
        gap_threshold_days=threshold,
    )


def _is_flagged(flags: Any) -> bool:
    if not flags:
        return False
    return any("corporate" in str(f) or "split" in str(f) or "repaired" in str(f) for f in flags)


__all__ = ["OBSERVATIONS_TABLE", "Gap", "PriceSeries", "build_price_series", "find_gaps"]
