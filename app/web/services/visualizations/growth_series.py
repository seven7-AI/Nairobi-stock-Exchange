"""Shape one instrument's observations into what a growth chart needs.

Pure: takes rows, returns a dataclass. No I/O, no plotting, and — deliberately — no
interpolation. Where the timeline has no observations the series has a ``Gap``, and the
chart draws that as a break, not a line.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from itertools import pairwise
from typing import Any

from app.web.core.exceptions import ResourceNotFoundError

#: Consecutive observations further apart than this are a gap. The archive's widest
#: holiday gap is 9 days, so 14 separates "the exchange was closed" from "no data".
GAP_THRESHOLD_DAYS = 14

#: A close-to-close ratio outside [1/x, x] between consecutive observations is flagged as
#: a suspected corporate action (split, consolidation, bonus). The archive's prices are
#: UNADJUSTED and its Adjust column is too sparse to build an adjusted series from - so
#: the step is marked on the chart, never smoothed away. KCB's 10:1 split on 2007-04-03
#: (212 -> 22.5) is the canonical example.
CORPORATE_ACTION_RATIO = 2.5


@dataclass(frozen=True)
class GrowthPoint:
    trade_date: date
    close: float
    data_source: str
    source_ticker: str


@dataclass(frozen=True)
class Gap:
    """A stretch with no observations, from the last point before it to the first after."""

    after: date
    before: date

    @property
    def days(self) -> int:
        return (self.before - self.after).days


@dataclass(frozen=True)
class SuspectedCorporateAction:
    """A step between two consecutive observations too large to be a price move."""

    on: date
    close_before: float
    close_after: float

    @property
    def ratio(self) -> float:
        return self.close_after / self.close_before


@dataclass
class StockGrowthSeries:
    ticker_symbol: str
    company_name: str
    sector: str | None
    instrument_type: str
    points: list[GrowthPoint]
    gaps: list[Gap] = field(default_factory=list)
    corporate_actions: list[SuspectedCorporateAction] = field(default_factory=list)

    # -- derived -------------------------------------------------------------
    @property
    def first(self) -> GrowthPoint:
        return self.points[0]

    @property
    def last(self) -> GrowthPoint:
        return self.points[-1]

    @property
    def high(self) -> GrowthPoint:
        return max(self.points, key=lambda p: p.close)

    @property
    def low(self) -> GrowthPoint:
        return min(self.points, key=lambda p: p.close)

    @property
    def overall_change_pct(self) -> float:
        return (self.last.close / self.first.close - 1.0) * 100.0

    @property
    def sources(self) -> list[str]:
        return sorted({p.data_source.split(":")[0] for p in self.points})

    @property
    def source_tickers(self) -> list[str]:
        """Codes the sources used, oldest first — shows a BBK → ABSA lineage on the chart."""
        seen: list[str] = []
        for point in self.points:
            if point.source_ticker not in seen:
                seen.append(point.source_ticker)
        return seen

    def points_per_year(self) -> dict[int, int]:
        counts: dict[int, int] = {}
        for point in self.points:
            counts[point.trade_date.year] = counts.get(point.trade_date.year, 0) + 1
        return counts

    def summary(self) -> dict[str, Any]:
        return {
            "ticker_symbol": self.ticker_symbol,
            "company_name": self.company_name,
            "sector": self.sector,
            "points": len(self.points),
            "first": {"date": self.first.trade_date.isoformat(), "close": self.first.close},
            "last": {"date": self.last.trade_date.isoformat(), "close": self.last.close},
            "high": {"date": self.high.trade_date.isoformat(), "close": self.high.close},
            "low": {"date": self.low.trade_date.isoformat(), "close": self.low.close},
            "overall_change_pct": round(self.overall_change_pct, 2),
            "gaps": [
                {"after": g.after.isoformat(), "before": g.before.isoformat(), "days": g.days}
                for g in self.gaps
            ],
            "sources": self.sources,
            "source_tickers": self.source_tickers,
            "suspected_corporate_actions": [
                {
                    "on": a.on.isoformat(),
                    "before": a.close_before,
                    "after": a.close_after,
                    "ratio": round(a.ratio, 3),
                }
                for a in self.corporate_actions
            ],
            "prices_are_adjusted": False,
        }


def build_growth_series(
    observations: list[dict[str, Any]],
    instrument: dict[str, Any] | None,
    *,
    gap_threshold_days: int = GAP_THRESHOLD_DAYS,
) -> StockGrowthSeries:
    """Turn ``fetch_observations`` rows into a series with its gaps identified.

    Rows are expected oldest-first (the source guarantees it) but are sorted anyway.
    Rows without a usable close are dropped and never invented.
    """
    points: list[GrowthPoint] = []
    for row in observations:
        close = row.get("close_price")
        raw_date = row.get("trade_date")
        if close is None or not raw_date:
            continue
        try:
            trade_date = date.fromisoformat(str(raw_date)[:10])
            close_value = float(close)
        except (TypeError, ValueError):
            continue
        if close_value <= 0:
            continue
        points.append(
            GrowthPoint(
                trade_date=trade_date,
                close=close_value,
                data_source=str(row.get("data_source") or "unknown"),
                source_ticker=str(row.get("source_ticker") or row.get("ticker_symbol") or ""),
            )
        )
    points.sort(key=lambda p: p.trade_date)

    ticker = str(
        (instrument or {}).get("ticker_symbol")
        or (observations[0].get("ticker_symbol") if observations else "")
        or ""
    ).upper()
    if not points:
        raise ResourceNotFoundError(
            f"No observations to chart for {ticker or 'this instrument'}.",
            detail=f"growth series empty for {ticker!r}",
        )

    gaps = [
        Gap(after=prev.trade_date, before=curr.trade_date)
        for prev, curr in pairwise(points)
        if (curr.trade_date - prev.trade_date).days > gap_threshold_days
    ]
    actions = [
        SuspectedCorporateAction(
            on=curr.trade_date, close_before=prev.close, close_after=curr.close
        )
        for prev, curr in pairwise(points)
        if (curr.trade_date - prev.trade_date).days <= gap_threshold_days
        and not (1 / CORPORATE_ACTION_RATIO <= curr.close / prev.close <= CORPORATE_ACTION_RATIO)
    ]

    meta = instrument or {}
    return StockGrowthSeries(
        ticker_symbol=ticker,
        company_name=str(meta.get("company_name") or ticker),
        sector=meta.get("sector"),
        instrument_type=str(meta.get("instrument_type") or "ordinary"),
        points=points,
        gaps=gaps,
        corporate_actions=actions,
    )


__all__ = [
    "CORPORATE_ACTION_RATIO",
    "GAP_THRESHOLD_DAYS",
    "Gap",
    "GrowthPoint",
    "StockGrowthSeries",
    "SuspectedCorporateAction",
    "build_growth_series",
]
