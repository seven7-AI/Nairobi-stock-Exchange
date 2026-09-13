"""The data-quality checks. Pure: rows in, findings out.

Each check takes plain dicts as the scraper source returns them and yields
``Finding`` values. Nothing here touches a database or a file, which is what
lets every check be tested with a handful of injected rows.

    codegraph explore "Finding price_jumps missing_periods impossible_values"
"""

from __future__ import annotations

import hashlib
from collections.abc import Iterable, Iterator, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta
from typing import Any

from app.web.db.analytics.models.data_quality_finding import Severity
from app.web.services.analytics.config import AnalyticsConfig

Observation = Mapping[str, Any]


@dataclass(frozen=True, slots=True)
class Finding:
    check: str
    severity: Severity
    detail: str
    ticker_symbol: str | None = None
    trade_date: date | None = None
    context: dict[str, Any] = field(default_factory=dict)

    @property
    def detail_hash(self) -> str:
        return hashlib.sha256(self.detail.encode("utf-8")).hexdigest()

    @property
    def identity(self) -> tuple[str, str | None, date | None, str]:
        return (self.check, self.ticker_symbol, self.trade_date, self.detail_hash)


def _as_date(value: Any) -> date:
    return value if isinstance(value, date) else date.fromisoformat(str(value)[:10])


def _f(value: Any) -> float | None:
    try:
        return None if value is None else float(value)
    except (TypeError, ValueError):
        return None


# --- price-level checks ---------------------------------------------------------------


def duplicate_observations(ticker: str, rows: Iterable[Observation]) -> Iterator[Finding]:
    """The same (ticker, trade_date) twice - impossible under the scraper's UNIQUE key,
    so seeing it means the read path or the source changed."""
    seen: dict[date, int] = {}
    for row in rows:
        day = _as_date(row["trade_date"])
        seen[day] = seen.get(day, 0) + 1
    for day, count in seen.items():
        if count > 1:
            yield Finding(
                "duplicate_observations",
                Severity.ERROR,
                f"{count} observations for {ticker} on {day.isoformat()}",
                ticker,
                day,
                {"count": count},
            )


def impossible_values(
    ticker: str, rows: Iterable[Observation], config: AnalyticsConfig
) -> Iterator[Finding]:
    """Prices that cannot be: non-positive close, low above high, close outside the day's
    range, 52-week low above 52-week high, negative volume."""
    tolerance = config.quality.ohlc_tolerance
    for row in rows:
        day = _as_date(row["trade_date"])
        close = _f(row.get("close_price"))
        low, high = _f(row.get("day_low")), _f(row.get("day_high"))
        year_low, year_high = _f(row.get("year_low")), _f(row.get("year_high"))
        volume = _f(row.get("volume"))
        if close is None or close <= 0:
            yield Finding(
                "impossible_values",
                Severity.ERROR,
                f"{ticker} {day}: close price {close!r} is not positive",
                ticker,
                day,
                {"close_price": close, "row_id": row.get("id")},
            )
            continue
        if low is not None and high is not None and low > high:
            yield Finding(
                "impossible_values",
                Severity.ERROR,
                f"{ticker} {day}: day low {low} above day high {high}",
                ticker,
                day,
                {"day_low": low, "day_high": high, "row_id": row.get("id")},
            )
        elif (
            low is not None
            and high is not None
            and not (low * (1 - tolerance) <= close <= high * (1 + tolerance))
        ):
            yield Finding(
                "impossible_values",
                Severity.WARNING,
                f"{ticker} {day}: close {close} outside the day's range {low}-{high}",
                ticker,
                day,
                {"close_price": close, "day_low": low, "day_high": high, "row_id": row.get("id")},
            )
        if year_low is not None and year_high is not None and year_low > year_high:
            yield Finding(
                "impossible_values",
                Severity.WARNING,
                f"{ticker} {day}: 52-week low {year_low} above 52-week high {year_high}",
                ticker,
                day,
                {"year_low": year_low, "year_high": year_high, "row_id": row.get("id")},
            )
        if volume is not None and volume < 0:
            yield Finding(
                "impossible_values",
                Severity.ERROR,
                f"{ticker} {day}: negative volume {volume}",
                ticker,
                day,
                {"volume": volume, "row_id": row.get("id")},
            )


def price_jumps(
    ticker: str, rows: Iterable[Observation], config: AnalyticsConfig
) -> Iterator[Finding]:
    """A close that moved more than the threshold against the previous observation.

    Suspected corporate actions the scraper already flagged are reported at INFO so the
    valuation engines see them; unflagged jumps are WARNINGs (a decimal slip, a split the
    archive did not mark, or a genuine crash - a human decides which). Across a data gap
    the move is unknowable, not a jump; ``missing_periods`` reports the gap instead.
    """
    threshold = config.quality.price_jump_threshold
    gap = timedelta(days=config.market.gap_threshold_days)
    previous: tuple[date, float] | None = None
    for row in rows:
        day = _as_date(row["trade_date"])
        close = _f(row.get("close_price"))
        if close is None or close <= 0:
            previous = None
            continue
        if previous is not None and day - previous[0] <= gap:
            prev_day, prev_close = previous
            change = close / prev_close - 1.0
            if abs(change) > threshold:
                flags = row.get("quality_flags") or []
                flagged = any("corporate" in str(f) or "split" in str(f) for f in flags)
                yield Finding(
                    "price_jumps",
                    Severity.INFO if flagged else Severity.WARNING,
                    f"{ticker} {day}: close moved {change:+.1%} "
                    f"({prev_close} on {prev_day} -> {close})",
                    ticker,
                    day,
                    {
                        "previous_close": prev_close,
                        "close_price": close,
                        "change": change,
                        "flagged": flagged,
                        "row_id": row.get("id"),
                    },
                )
        previous = (day, close)


def missing_periods(
    ticker: str, rows: Iterable[Observation], config: AnalyticsConfig
) -> Iterator[Finding]:
    """Breaks longer than the gap threshold inside an instrument's own span."""
    threshold = timedelta(days=config.market.gap_threshold_days)
    previous: date | None = None
    for row in rows:
        day = _as_date(row["trade_date"])
        if previous is not None and day - previous > threshold:
            length = (day - previous).days
            yield Finding(
                "missing_periods",
                Severity.WARNING,
                f"{ticker}: no observations for {length} days between {previous} and {day}",
                ticker,
                previous,
                {"gap_start": previous.isoformat(), "gap_end": day.isoformat(), "days": length},
            )
        previous = day


def zero_volume_streaks(
    ticker: str, rows: Iterable[Observation], config: AnalyticsConfig
) -> Iterator[Finding]:
    """Runs of consecutive zero-volume observations at or above the configured length."""
    minimum = config.quality.zero_volume_streak_days
    streak_start: date | None = None
    streak = 0
    last_day: date | None = None

    def emit(start: date, end: date, length: int) -> Finding:
        return Finding(
            "zero_volume_streaks",
            Severity.INFO,
            f"{ticker}: {length} consecutive zero-volume days from {start} to {end}",
            ticker,
            start,
            {"streak_start": start.isoformat(), "streak_end": end.isoformat(), "days": length},
        )

    for row in rows:
        day = _as_date(row["trade_date"])
        volume = _f(row.get("volume"))
        if volume is not None and volume == 0:
            if streak == 0:
                streak_start = day
            streak += 1
            last_day = day
        else:
            if streak >= minimum and streak_start is not None and last_day is not None:
                yield emit(streak_start, last_day, streak)
            streak, streak_start = 0, None
    if streak >= minimum and streak_start is not None and last_day is not None:
        yield emit(streak_start, last_day, streak)


def thin_history(
    ticker: str, rows: Sequence[Observation], config: AnalyticsConfig
) -> Iterator[Finding]:
    if 0 < len(rows) < config.quality.min_observations:
        yield Finding(
            "thin_history",
            Severity.INFO,
            f"{ticker}: only {len(rows)} observations (minimum {config.quality.min_observations})",
            ticker,
            None,
            {"observations": len(rows)},
        )


# --- universe-level checks -----------------------------------------------------------


def universe_gap(
    spans: Mapping[str, tuple[date, date, int]],
    per_ticker_gaps: Iterable[Finding],
    config: AnalyticsConfig,
) -> Iterator[Finding]:
    """A gap shared by most of the universe is one finding, not a hundred.

    The 2025-01 -> 2026-07 hole is the case: every instrument that survived 2024 shows
    the same break. Reported at ERROR because every window that crosses it is
    unavailable, and de-duplicated so the per-ticker rows stay as detail.
    """
    counts: dict[tuple[str, str], int] = {}
    for finding in per_ticker_gaps:
        key = (finding.context["gap_start"], finding.context["gap_end"])
        counts[key] = counts.get(key, 0) + 1
    active = len(spans)
    for (gap_start, gap_end), count in counts.items():
        if active and count >= max(5, active // 3):
            yield Finding(
                "universe_gap",
                Severity.ERROR,
                f"{count} instruments share a data gap from {gap_start} to {gap_end}",
                None,
                date.fromisoformat(gap_start),
                {"gap_start": gap_start, "gap_end": gap_end, "instruments": count},
            )


def stale_data(
    latest_trade_date: date | None, now: datetime, stale_after_hours: int
) -> Iterator[Finding]:
    if latest_trade_date is None:
        yield Finding("stale_data", Severity.ERROR, "no observations at all", None, None, {})
        return
    age = now - datetime.combine(latest_trade_date, datetime.min.time(), tzinfo=UTC)
    if age > timedelta(hours=stale_after_hours):
        yield Finding(
            "stale_data",
            Severity.ERROR,
            f"latest observation is {latest_trade_date}, {age.days} days old "
            f"(limit {stale_after_hours}h)",
            None,
            latest_trade_date,
            {"latest_trade_date": latest_trade_date.isoformat(), "age_days": age.days},
        )


def broken_scrape(quality_gate: Mapping[str, Mapping[str, Any]]) -> Iterator[Finding]:
    """The scraper's own verdict on its last run, surfaced here."""
    for spider, report in quality_gate.items():
        if report and report.get("quality_ok") is False:
            failures = (
                "; ".join(str(f) for f in report.get("failures") or []) or "quality gate failed"
            )
            yield Finding(
                "broken_scrape",
                Severity.ERROR,
                f"{spider}: {failures}",
                None,
                None,
                {
                    "spider": spider,
                    "finished_at": report.get("finished_at"),
                    "failures": list(report.get("failures") or []),
                },
            )


def unclassified_instruments(
    instruments: Iterable[Mapping[str, Any]],
    classified: Mapping[str, list[tuple[date, date | None]]],
    spans: Mapping[str, tuple[date, date, int]],
) -> Iterator[Finding]:
    """Instruments whose last observation is not covered by any classification stint."""
    for instrument in instruments:
        ticker = str(instrument["ticker_symbol"])
        span = spans.get(ticker)
        if span is None:
            continue
        last = span[1]
        stints = classified.get(ticker, [])
        if not any(start <= last and (end is None or last <= end) for start, end in stints):
            yield Finding(
                "unclassified_instruments",
                Severity.WARNING,
                f"{ticker}: no sector classification covers its last observation {last}",
                ticker,
                last,
                {"last_observation": last.isoformat()},
            )


# --- fundamentals checks ------------------------------------------------------------


def balance_sheet_consistency(
    ticker: str, statement_rows: Iterable[Mapping[str, Any]], config: AnalyticsConfig
) -> Iterator[Finding]:
    """assets == liabilities + equity within tolerance, per period, on the balance sheet."""
    tolerance = config.quality.balance_sheet_tolerance
    wanted = {
        "total_assets",
        "total_liabilities",
        "shareholders_equity",
        "total_liabilities_and_equity",
    }
    by_period: dict[tuple[str, str], dict[str, float]] = {}
    for row in statement_rows:
        if row.get("statement") != "balance" or row.get("value") is None:
            continue
        item = str(row.get("line_item"))
        if item in wanted:
            key = (str(row["period_type"]), str(row["fiscal_period_end"]))
            by_period.setdefault(key, {})[item] = float(row["value"])
    for (period_type, period_end), values in sorted(by_period.items()):
        assets = values.get("total_assets")
        total = values.get("total_liabilities_and_equity")
        if total is None and "total_liabilities" in values and "shareholders_equity" in values:
            total = values["total_liabilities"] + values["shareholders_equity"]
        if assets is None or total is None or assets == 0:
            continue
        drift = abs(assets - total) / abs(assets)
        if drift > tolerance:
            yield Finding(
                "balance_sheet_consistency",
                Severity.WARNING,
                f"{ticker} {period_type} {period_end}: assets {assets:,.0f} vs "
                f"liabilities+equity {total:,.0f} ({drift:.1%} apart)",
                ticker,
                date.fromisoformat(period_end),
                {
                    "period_type": period_type,
                    "period_end": period_end,
                    "total_assets": assets,
                    "liabilities_plus_equity": total,
                    "drift": drift,
                },
            )


def missing_fundamentals(
    ticker: str,
    has_statements: bool,
    span: tuple[date, date, int] | None,
    scraper_era_start: date,
) -> Iterator[Finding]:
    """An instrument trading in the scraper era with no statements captured yet."""
    if span is None or span[1] < scraper_era_start or has_statements:
        return
    yield Finding(
        "missing_fundamentals",
        Severity.INFO,
        f"{ticker}: trading through {span[1]} but no financial statements captured yet",
        ticker,
        None,
        {"last_observation": span[1].isoformat()},
    )


__all__ = [
    "Finding",
    "balance_sheet_consistency",
    "broken_scrape",
    "duplicate_observations",
    "impossible_values",
    "missing_fundamentals",
    "missing_periods",
    "price_jumps",
    "stale_data",
    "thin_history",
    "unclassified_instruments",
    "universe_gap",
    "zero_volume_streaks",
]
