"""PriceSeries and the returns engine: synthetic edge cases, real KCB numbers, look-ahead.

codegraph explore "trailing_returns window_return PriceSeries build_price_series"
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import date, timedelta
from pathlib import Path

import pytest
from sqlalchemy import select

from app.web.config import Settings
from app.web.db.analytics import analytics_session
from app.web.db.analytics.models import JobRun, MarketMetric
from app.web.db.analytics.services.market_metrics import load_metrics
from app.web.services.analytics.config import DEFAULT_CONFIG
from app.web.services.analytics.measure import MeasureStatus
from app.web.services.analytics.returns import (
    METRIC_NAMES,
    WINDOWS,
    compute_returns,
    cumulative_return,
    rolling_returns,
    trailing_returns,
    window_return,
    ytd_return,
)
from app.web.services.analytics.series import build_price_series, find_gaps
from app.web.services.analytics.store import upgrade_analytics_db
from app.web.services.market_data.sources import NseScraperSource

pytestmark = pytest.mark.unit


def rows(start: date, closes: Sequence[float | None], **extra: object) -> list[dict[str, object]]:
    """Business-day observations from ``start``; a None close skips that day."""
    out: list[dict[str, object]] = []
    day = start
    for index, close in enumerate(closes):
        while day.weekday() >= 5:
            day += timedelta(days=1)
        if close is not None:
            row: dict[str, object] = {
                "id": index + 1,
                "trade_date": day.isoformat(),
                "close_price": close,
                "volume": 1000,
                "source_ticker": "X",
                "quality_flags": [],
            }
            row.update(extra)
            out.append(row)
        day += timedelta(days=1)
    return out


def series(closes: Sequence[float | None], start: date = date(2023, 1, 2)):
    return build_price_series("X", rows(start, closes), DEFAULT_CONFIG)


# --- PriceSeries ----------------------------------------------------------------


def test_series_orders_dedupes_and_drops_non_positive_closes() -> None:
    raw = rows(date(2023, 1, 2), [10.0, 11.0, 12.0])
    raw.append({**raw[1], "close_price": 99.0})  # duplicate date: last wins
    raw.append({**raw[2], "trade_date": "2023-01-05", "close_price": 0})  # dropped
    s = build_price_series("x", raw, DEFAULT_CONFIG)
    assert s.ticker_symbol == "X"
    assert list(s.close) == [10.0, 99.0, 12.0]
    assert s.first_date == date(2023, 1, 2) and s.last_date == date(2023, 1, 4)
    assert s.source_tickers == ("X",)


def test_gaps_and_segments() -> None:
    raw = rows(date(2024, 12, 27), [1.0, 2.0, 3.0]) + rows(date(2026, 7, 27), [4.0, 5.0])
    s = build_price_series("X", raw, DEFAULT_CONFIG)
    assert len(s.gaps) == 1 and s.gaps[0].after == date(2024, 12, 31) and s.gaps[0].days == 573
    assert list(s.segment) == [0, 0, 0, 1, 1]
    assert find_gaps([date(2024, 1, 1), date(2024, 1, 10)], 14) == []
    returns = s.daily_returns()
    assert returns.isna().tolist() == [True, False, False, True, False]  # never across the gap


def test_as_of_truncates_and_is_idempotent() -> None:
    s = series([1.0, 2.0, 3.0, 4.0])
    cut = s.as_of(date(2023, 1, 4))
    assert len(cut) == 3 and cut.last_date == date(2023, 1, 4)
    assert cut.as_of(date(2023, 1, 4)) is cut
    assert s.as_of(date(2022, 1, 1)).is_empty
    assert s.position_on_or_before(date(2023, 1, 1)) is None
    assert s.close_on_or_before(date(2023, 1, 8)) == (date(2023, 1, 5), 4.0)


def test_empty_series() -> None:
    s = build_price_series("X", [], DEFAULT_CONFIG)
    assert s.is_empty and s.first_date is None
    assert s.as_of(date(2024, 1, 1)).is_empty
    assert window_return(s, date(2024, 1, 1), "1M").measure.status is MeasureStatus.UNAVAILABLE


# --- windows -----------------------------------------------------------------------


def test_one_day_and_one_week_returns() -> None:
    s = series([100.0, 110.0, 121.0, 133.1, 146.41, 161.05, 177.16])
    one_day = window_return(s, date(2023, 1, 10), "1D")
    assert one_day.measure.value == pytest.approx(0.10, rel=1e-3)
    assert (one_day.start, one_day.end) == (date(2023, 1, 9), date(2023, 1, 10))
    # 1W: start is the last observation on or before end - 7 days (2023-01-03)
    one_week = window_return(s, date(2023, 1, 10), "1W")
    assert one_week.measure.value == pytest.approx(177.16 / 110.0 - 1)
    assert one_week.start == date(2023, 1, 3)


def test_as_of_on_a_non_trading_day_uses_the_last_observation() -> None:
    s = series([100.0, 110.0, 121.0, 133.1, 146.41])
    saturday = date(2023, 1, 7)
    result = window_return(s, saturday, "1D")
    assert result.end == date(2023, 1, 6) and result.measure.value == pytest.approx(0.10)


def test_insufficient_history_is_unavailable_with_the_reason() -> None:
    s = series([1.0] * 30)
    result = window_return(s, date(2023, 2, 10), "12M")
    assert result.measure.status is MeasureStatus.UNAVAILABLE
    assert "history starts 2023-01-02" in (result.measure.reason or "")
    assert (
        window_return(series([1.0]), date(2023, 1, 2), "1D").measure.reason
        == "return 1D: no previous observation"
    )


def test_window_across_a_gap_is_unavailable() -> None:
    raw = rows(date(2024, 10, 1), [10.0] * 60) + rows(date(2026, 7, 27), [20.0] * 5)
    s = build_price_series("X", raw, DEFAULT_CONFIG)
    result = window_return(s, date(2026, 7, 31), "6M")
    assert result.measure.status is MeasureStatus.UNAVAILABLE
    assert "crosses data gap" in (result.measure.reason or "")
    assert "2026-07-27" in (result.measure.reason or "")
    # a window that starts before the history began says so instead
    before = window_return(s, date(2026, 7, 31), "24M")
    assert "history starts 2024-10-01" in (before.measure.reason or "")
    # but a window entirely after the gap is fine
    assert window_return(s, date(2026, 7, 31), "1D").measure.is_known


def test_as_of_inside_a_gap_is_unavailable_not_stale_data() -> None:
    raw = rows(date(2024, 10, 1), [10.0] * 60) + rows(date(2026, 7, 27), [20.0] * 5)
    s = build_price_series("X", raw, DEFAULT_CONFIG)
    inside = window_return(s, date(2025, 6, 1), "1M")
    assert inside.measure.status is MeasureStatus.UNAVAILABLE
    assert "days before 2025-06-01" in (inside.measure.reason or "")


def test_delisted_instrument_after_its_last_observation() -> None:
    s = series([5.0] * 40)
    last = s.last_date
    assert last is not None
    soon = trailing_returns(s, last + timedelta(days=10))[METRIC_NAMES["1M"]]
    assert soon.measure.is_known
    later = trailing_returns(s, last + timedelta(days=60))[METRIC_NAMES["1M"]]
    assert later.measure.status is MeasureStatus.UNAVAILABLE


def test_thin_listing_does_not_stretch_a_short_window() -> None:
    raw = rows(date(2023, 1, 2), [10.0]) + rows(
        date(2023, 3, 1), [12.0]
    )  # two observations, 2 months apart
    s = build_price_series("X", raw, DEFAULT_CONFIG)
    assert s.gaps  # they are in different segments anyway
    result = window_return(s, date(2023, 3, 1), "1W")
    assert result.measure.status is MeasureStatus.UNAVAILABLE


def test_flagged_observation_inside_the_window_is_marked() -> None:
    raw = rows(date(2022, 12, 26), [100.0] * 6 + [10.0, 10.0])
    raw[6]["quality_flags"] = ["suspected_corporate_action"]  # 2023-01-03
    s = build_price_series("X", raw, DEFAULT_CONFIG)
    result = window_return(s, date(2023, 1, 4), "1W")
    assert result.contains_flagged and result.measure.value == pytest.approx(-0.9)
    assert "flagged" in (result.measure.provenance[0].note or "")


def test_ytd_return() -> None:
    raw = rows(date(2022, 12, 28), [50.0, 50.0, 60.0]) + rows(date(2023, 1, 2), [66.0, 72.0])
    s = build_price_series("X", raw, DEFAULT_CONFIG)
    result = ytd_return(s, date(2023, 1, 3))
    assert result.measure.value == pytest.approx(72.0 / 60.0 - 1)
    assert result.start == date(2022, 12, 30)
    no_prior = ytd_return(series([1.0, 2.0]), date(2023, 1, 3))
    assert no_prior.measure.status is MeasureStatus.UNAVAILABLE


def test_trailing_returns_covers_every_window_and_yoy_equals_12m() -> None:
    s = series([1.0 + i * 0.01 for i in range(1200)], start=date(2019, 1, 1))
    results = trailing_returns(s, date(2023, 6, 30))
    assert set(results) == set(METRIC_NAMES.values())
    assert results["return_yoy"] is results["return_12m"]
    assert results["return_36m"].measure.is_known
    assert results["return_1d"].measure.is_positive


def test_numerical_stability_on_tiny_prices() -> None:
    s = series([0.0001, 0.00011, 0.000121])
    assert window_return(s, date(2023, 1, 4), "1D").measure.value == pytest.approx(0.10, rel=1e-9)


def test_cumulative_and_rolling_returns() -> None:
    s = series([100.0, 110.0, 121.0, 133.1, 146.41, 161.05])
    assert cumulative_return(s, date(2023, 1, 2), date(2023, 1, 6)).measure.value == pytest.approx(
        0.4641
    )
    assert (
        cumulative_return(s, date(2023, 1, 6), date(2023, 1, 2)).measure.status
        is MeasureStatus.UNAVAILABLE
    )
    daily = rolling_returns(s, "1D")
    assert daily.isna().tolist()[0] and daily.iloc[1] == pytest.approx(0.10)
    weekly = rolling_returns(s, "1W")
    assert weekly.isna().sum() >= 5
    with pytest.raises(ValueError):
        window_return(s, date(2023, 1, 6), "2Y")


# --- real KCB numbers (fixture) ---------------------------------------------------


@pytest.fixture(scope="module")
def kcb(fixture_source: NseScraperSource):
    return build_price_series("KCB", fixture_source.fetch_observations("KCB"), DEFAULT_CONFIG)


def test_kcb_history_shape(kcb) -> None:
    assert kcb.first_date == date(2007, 1, 2) and float(kcb.close.iloc[0]) == 243.0
    assert len(kcb.gaps) == 1 and kcb.gaps[0].after == date(2024, 12, 31)
    assert kcb.gaps[0].before == date(2026, 7, 26)


def test_kcb_returns_at_end_of_2019_hand_computed(kcb) -> None:
    as_of = date(2019, 12, 31)
    results = trailing_returns(kcb.as_of(as_of), as_of)
    assert results["return_12m"].measure.value == pytest.approx(
        54.0 / 37.45 - 1
    )  # 2018-12-31 close 37.45
    assert results["return_12m"].start == date(2018, 12, 31)
    assert results["return_6m"].measure.value == pytest.approx(
        54.0 / 38.25 - 1
    )  # 2019-06-28 (28th: last obs <= 06-30)
    assert results["return_3m"].measure.value == pytest.approx(54.0 / 42.0 - 1)
    assert results["return_1w"].measure.value == pytest.approx(54.0 / 53.25 - 1)  # 2019-12-24
    assert results["return_1d"].measure.value == pytest.approx(54.0 / 53.25 - 1)  # 2019-12-30
    assert results["return_ytd"].measure.value == pytest.approx(54.0 / 37.45 - 1)
    assert results["return_36m"].measure.is_known
    assert not results["return_12m"].contains_flagged


def test_kcb_windows_crossing_the_2025_gap_are_unavailable(kcb) -> None:
    as_of = date(2026, 9, 12)
    results = trailing_returns(kcb.as_of(as_of), as_of)
    assert results["return_1w"].measure.is_known
    assert results["return_1m"].measure.is_known
    for metric in (
        "return_3m",
        "return_6m",
        "return_12m",
        "return_24m",
        "return_36m",
        "return_ytd",
    ):
        assert results[metric].measure.status is MeasureStatus.UNAVAILABLE, metric
        assert "gap" in (results[metric].measure.reason or "") or "before" in (
            results[metric].measure.reason or ""
        )
    inside = trailing_returns(kcb.as_of(date(2025, 6, 30)), date(2025, 6, 30))
    assert all(r.measure.status is MeasureStatus.UNAVAILABLE for r in inside.values())


def test_kcb_2007_split_window_is_flagged_or_visible(kcb) -> None:
    result = window_return(kcb.as_of(date(2007, 4, 30)), date(2007, 4, 30), "3M")
    assert (
        result.measure.value is not None and result.measure.value < -0.8
    )  # 243 -> ~22.5 unadjusted


def test_look_ahead_appending_future_rows_changes_nothing(fixture_source: NseScraperSource) -> None:
    raw = fixture_source.fetch_observations("KCB")
    as_of = date(2019, 12, 31)
    past_only = build_price_series(
        "KCB", [r for r in raw if r["trade_date"] <= "2019-12-31"], DEFAULT_CONFIG
    )
    everything = build_price_series("KCB", raw, DEFAULT_CONFIG)
    a = trailing_returns(past_only, as_of)
    b = trailing_returns(everything.as_of(as_of), as_of)
    assert {k: v.measure.as_dict() for k, v in a.items()} == {
        k: v.measure.as_dict() for k, v in b.items()
    }
    # and altering a future row cannot leak either
    tampered = [dict(r, close_price=1.0) if r["trade_date"] > "2019-12-31" else r for r in raw]
    c = trailing_returns(build_price_series("KCB", tampered, DEFAULT_CONFIG).as_of(as_of), as_of)
    assert {k: v.measure.as_dict() for k, v in a.items()} == {
        k: v.measure.as_dict() for k, v in c.items()
    }


# --- the compute job ---------------------------------------------------------------


@pytest.fixture
def settings(fixture_db_path: Path, tmp_path: Path) -> Settings:
    s = Settings(
        NSE_SCRAPER_DB_PATH=str(fixture_db_path),
        NSE_SCRAPER_PATH=str(tmp_path / "scraper"),
        ANALYTICS_DB_PATH=str(tmp_path / "a.sqlite3"),
    )
    upgrade_analytics_db(s.analytics_db_path)
    return s


def test_compute_returns_writes_one_row_per_metric_and_is_idempotent(settings: Settings) -> None:
    source = NseScraperSource(settings)
    as_of = date(2019, 12, 31)
    first = compute_returns(settings, source, as_of=as_of)
    assert first.rows_written == 12 * len(METRIC_NAMES)
    assert set(first.tickers_processed) >= {"KCB", "^NASI", "KENO"}
    assert first.tickers_skipped == {}
    assert first.known_counts["return_12m"] >= 8
    second = compute_returns(settings, source, as_of=as_of)
    assert second.calc_version_id == first.calc_version_id
    with analytics_session(settings) as session:
        rows = session.execute(select(MarketMetric)).scalars().all()
        assert len(rows) == first.rows_written  # upsert, not append
        kcb = {r.metric: r for r in load_metrics(session, ticker_symbol="kcb", as_of_date=as_of)}
        assert kcb["return_12m"].value == pytest.approx(54.0 / 37.45 - 1)
        assert kcb["return_12m"].status == "known" and kcb["return_12m"].window_start == date(
            2018, 12, 31
        )
        assert (
            kcb["return_12m"].provenance
            and kcb["return_12m"].provenance[0]["table"] == "stock_observations"
        )
        runs = session.execute(select(JobRun).where(JobRun.job_name == "returns")).scalars().all()
        assert [r.status for r in runs] == ["succeeded", "succeeded"]
        assert runs[0].details is not None and runs[0].details["known_counts"]["return_12m"] >= 8


def test_compute_returns_records_unavailable_rows_with_reasons(settings: Settings) -> None:
    source = NseScraperSource(settings)
    compute_returns(settings, source, as_of=date(2026, 9, 12), tickers=["KCB", "KENO"])
    with analytics_session(settings) as session:
        kcb = {r.metric: r for r in load_metrics(session, ticker_symbol="KCB")}
        assert kcb["return_12m"].status == "unavailable" and kcb["return_12m"].value is None
        assert "gap" in (kcb["return_12m"].reason or "")
        keno = {r.metric: r for r in load_metrics(session, ticker_symbol="KENO")}
        assert keno["return_1d"].status == "unavailable"  # delisted 2019
        assert "2019-10-11" in (keno["return_1d"].reason or "")


def test_cli_compute_returns(settings: Settings, monkeypatch: pytest.MonkeyPatch) -> None:
    from typer.testing import CliRunner

    from app.cli.main import app
    from app.web.config import get_settings

    monkeypatch.setenv("ANALYTICS_DB_PATH", str(settings.analytics_db_path))
    monkeypatch.setenv("NSE_SCRAPER_DB_PATH", str(settings.scraper_database_path))
    monkeypatch.setenv("NSE_SCRAPER_PATH", str(settings.nse_scraper_path))
    get_settings.cache_clear()
    try:
        result = CliRunner().invoke(
            app, ["analytics", "compute", "returns", "--as-of", "2019-12-31", "--ticker", "KCB"]
        )
        assert result.exit_code == 0, result.output
        assert "return_12m" in result.output and "1 / 1" in result.output
        bad = CliRunner().invoke(app, ["analytics", "compute", "returns", "--as-of", "yesterday"])
        assert bad.exit_code != 0
    finally:
        get_settings.cache_clear()


@pytest.mark.realdata
def test_live_kcb_agrees_with_the_fixture(live_source: NseScraperSource) -> None:
    kcb = build_price_series("KCB", live_source.fetch_observations("KCB"), DEFAULT_CONFIG)
    result = window_return(kcb.as_of(date(2019, 12, 31)), date(2019, 12, 31), "12M")
    assert result.measure.value == pytest.approx(54.0 / 37.45 - 1)
    assert len(WINDOWS) == 8
