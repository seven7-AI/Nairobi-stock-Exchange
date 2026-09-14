"""Liquidity engine: volume-less periods, buckets, real KCB/SCOM numbers, look-ahead.

codegraph explore "liquidity_inputs liquidity_scores compute_liquidity"
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import date, timedelta
from pathlib import Path

import pytest

from app.web.config import Settings
from app.web.db.analytics import analytics_session
from app.web.db.analytics.services.market_metrics import load_metrics
from app.web.services.analytics.config import DEFAULT_CONFIG as CONFIG
from app.web.services.analytics.config import AnalyticsConfig, LiquidityConfig
from app.web.services.analytics.liquidity import (
    BUCKETS,
    compute_liquidity,
    liquidity_inputs,
    liquidity_scores,
)
from app.web.services.analytics.liquidity.engine import bucket_label, market_cap
from app.web.services.analytics.measure import MeasureStatus
from app.web.services.analytics.series import PriceSeries, build_price_series
from app.web.services.analytics.store import upgrade_analytics_db
from app.web.services.market_data.sources import NseScraperSource

pytestmark = pytest.mark.unit


def rows(
    start: date, closes: Sequence[float], volumes: Sequence[float | None], ticker: str = "X"
) -> list[dict[str, object]]:
    out: list[dict[str, object]] = []
    day = start
    for index, (close, volume) in enumerate(zip(closes, volumes, strict=True)):
        while day.weekday() >= 5:
            day += timedelta(days=1)
        out.append(
            {
                "id": index + 1,
                "trade_date": day.isoformat(),
                "close_price": close,
                "volume": volume,
                "source_ticker": ticker,
                "quality_flags": [],
            }
        )
        day += timedelta(days=1)
    return out


def series(
    closes: Sequence[float],
    volumes: Sequence[float | None],
    ticker: str = "X",
    start: date = date(2023, 1, 2),
) -> PriceSeries:
    return build_price_series(ticker, rows(start, closes, volumes, ticker), CONFIG)


AS_OF = date(2023, 12, 29)


def test_metrics_on_a_steady_liquid_stock() -> None:
    s = series([10.0] * 260, [1000.0] * 260)
    inputs = liquidity_inputs(s, AS_OF, [], CONFIG)
    m = inputs.metrics
    assert m["avg_daily_volume"].measure.value == 1000.0
    assert m["avg_daily_turnover"].measure.value == 10_000.0
    assert m["trading_frequency"].measure.value == pytest.approx(1.0, abs=0.02)
    assert m["zero_volume_days"].measure.status is MeasureStatus.ZERO
    assert m["zero_volume_share"].measure.status is MeasureStatus.ZERO
    assert m["volume_cv"].measure.status is MeasureStatus.ZERO
    assert inputs.steadiness == 1.0 and inputs.nonzero_share == 1.0
    assert m["market_cap"].measure.status is MeasureStatus.UNAVAILABLE
    assert m["free_float"].measure.status is MeasureStatus.UNAVAILABLE


def test_missing_volume_is_unavailable_not_zero() -> None:
    s = series([10.0] * 260, [None] * 260)
    inputs = liquidity_inputs(s, AS_OF, [], CONFIG)
    assert inputs.metrics["avg_daily_volume"].measure.status is MeasureStatus.UNAVAILABLE
    assert "volume reported on 0 of" in (inputs.metrics["avg_daily_volume"].measure.reason or "")
    assert inputs.metrics["trading_frequency"].measure.is_known  # prices still printed
    assert inputs.turnover is None
    few = series([10.0] * 260, [None] * 250 + [500.0] * 10)
    assert (
        liquidity_inputs(few, AS_OF, [], CONFIG).metrics["avg_daily_turnover"].measure.status
        is MeasureStatus.UNAVAILABLE
    )


def test_zero_volume_days_and_thin_trading() -> None:
    volumes = [100.0] * 200 + [0.0] * 60  # the zero days sit inside the 6M window
    s = series([10.0] * 260, volumes)
    m = liquidity_inputs(s, AS_OF, [], CONFIG).metrics
    assert (
        m["zero_volume_days"].measure.value is not None and m["zero_volume_days"].measure.value > 0
    )
    assert 0 < (m["zero_volume_share"].measure.value or 0) < 1
    thin = build_price_series("T", rows(date(2022, 1, 3), [5.0] * 400, [10.0] * 400)[::5], CONFIG)
    frequency = liquidity_inputs(thin, thin.last_date or AS_OF, [], CONFIG).metrics[
        "trading_frequency"
    ]
    assert frequency.measure.value is not None and frequency.measure.value < 0.3


def test_window_crossing_a_gap_is_unavailable() -> None:
    raw = rows(date(2024, 10, 1), [10.0] * 60, [100.0] * 60) + rows(
        date(2026, 7, 27), [20.0] * 10, [100.0] * 10
    )
    s = build_price_series("X", raw, CONFIG)
    inputs = liquidity_inputs(s, date(2026, 8, 7), [], CONFIG)
    assert inputs.metrics["avg_daily_volume"].measure.status is MeasureStatus.UNAVAILABLE
    assert inputs.turnover is None and inputs.frequency is None


def test_market_cap_is_point_in_time() -> None:
    snapshots = [
        {
            "id": 1,
            "ticker_symbol": "X",
            "view": "overview",
            "snapshot_date": "2026-09-13",
            "metrics": {"marketCap": 1e11},
        },
        {
            "id": 2,
            "ticker_symbol": "X",
            "view": "overview",
            "snapshot_date": "2026-09-20",
            "metrics": {"marketCap": 2e11},
        },
        {
            "id": 3,
            "ticker_symbol": "X",
            "view": "dividends",
            "snapshot_date": "2026-09-21",
            "metrics": {"dps": 1},
        },
    ]
    assert market_cap(snapshots, date(2026, 9, 12)).measure.status is MeasureStatus.UNAVAILABLE
    assert market_cap(snapshots, date(2026, 9, 15)).measure.value == 1e11
    latest = market_cap(snapshots, date(2026, 9, 30))
    assert latest.measure.value == 2e11 and latest.window_end == date(2026, 9, 20)
    assert latest.measure.provenance[0].ids == (2,)


def test_scores_are_percentile_ranks_across_the_universe() -> None:
    universe = {
        "BIG": series([100.0] * 260, [100_000.0] * 260, "BIG"),
        "MID": series([10.0] * 260, [10_000.0] * 260, "MID"),
        "SMALL": series([1.0] * 260, [100.0] * 160 + [0.0] * 100, "SMALL"),  # zeros in-window
        "SILENT": series([1.0] * 260, [None] * 260, "SILENT"),
    }
    inputs = {t: liquidity_inputs(s, AS_OF, [], CONFIG) for t, s in universe.items()}
    scores = liquidity_scores(inputs, AS_OF, CONFIG)
    big, mid, small = (scores[t][0].measure.value for t in ("BIG", "MID", "SMALL"))
    assert big is not None and mid is not None and small is not None
    assert big > mid > small
    assert scores["BIG"][1].measure.reason == "Highly liquid"
    assert scores["SMALL"][1].measure.reason in {"Moderately liquid", "Illiquid", "Very illiquid"}
    assert (scores["SMALL"][1].measure.value or 0) < (scores["BIG"][1].measure.value or 0)
    assert (
        scores["SILENT"][0].measure.status is MeasureStatus.UNAVAILABLE
    )  # no data is not illiquidity
    assert "cross-section of 3 instruments" in (scores["BIG"][0].measure.provenance[0].note or "")


def test_bucket_labels_follow_the_configured_bounds() -> None:
    assert bucket_label(95, CONFIG.liquidity.bucket_thresholds) == "Highly liquid"
    assert bucket_label(80, CONFIG.liquidity.bucket_thresholds) == "Highly liquid"
    assert bucket_label(79.9, CONFIG.liquidity.bucket_thresholds) == "Liquid"
    assert bucket_label(45, CONFIG.liquidity.bucket_thresholds) == "Moderately liquid"
    assert bucket_label(5, CONFIG.liquidity.bucket_thresholds) == "Very illiquid"
    strict = AnalyticsConfig(liquidity=LiquidityConfig(bucket_thresholds=(95.0, 90.0, 80.0, 50.0)))
    assert bucket_label(85, strict.liquidity.bucket_thresholds) == "Moderately liquid"
    assert next(label for _, label in BUCKETS) == "Highly liquid"


def test_weights_and_window_are_configuration() -> None:
    universe = {
        "STEADY": series([10.0] * 260, [1000.0] * 260, "STEADY"),
        "LUMPY": series([10.0] * 260, [1.0] * 250 + [250_000.0] * 10, "LUMPY"),
    }
    inputs = {t: liquidity_inputs(s, AS_OF, [], CONFIG) for t, s in universe.items()}
    default = liquidity_scores(inputs, AS_OF, CONFIG)
    steady_only = AnalyticsConfig(
        liquidity=LiquidityConfig(
            weight_turnover=0.0,
            weight_frequency=0.0,
            weight_nonzero_volume=0.0,
            weight_steadiness=1.0,
        )
    )
    alt = liquidity_scores(inputs, AS_OF, steady_only)
    assert (alt["STEADY"][0].measure.value or 0) > (alt["LUMPY"][0].measure.value or 0)
    assert default["LUMPY"][0].measure.value != alt["LUMPY"][0].measure.value
    short = AnalyticsConfig(liquidity=LiquidityConfig(window="1M"))
    assert (
        liquidity_inputs(universe["STEADY"], AS_OF, [], short)
        .metrics["avg_daily_volume"]
        .window_start
        is not None
    )
    assert (
        liquidity_inputs(universe["STEADY"], AS_OF, [], short)
        .metrics["avg_daily_volume"]
        .window_start
        or AS_OF
    ) > date(2023, 11, 1)


# --- real numbers (fixture) --------------------------------------------------------


def test_kcb_and_scom_second_half_2024_hand_computed(fixture_source: NseScraperSource) -> None:
    as_of = date(2024, 12, 31)
    kcb = build_price_series("KCB", fixture_source.fetch_observations("KCB"), CONFIG).as_of(as_of)
    scom = build_price_series("SCOM", fixture_source.fetch_observations("SCOM"), CONFIG).as_of(
        as_of
    )
    kcb_inputs = liquidity_inputs(kcb, as_of, [], CONFIG)
    scom_inputs = liquidity_inputs(scom, as_of, [], CONFIG)
    # 126 observations 2024-06-30..2024-12-31, all with volume, none zero
    assert kcb_inputs.metrics["avg_daily_volume"].measure.value == pytest.approx(920_560, rel=0.01)
    assert kcb_inputs.metrics["avg_daily_turnover"].measure.value == pytest.approx(
        32_017_842, rel=0.01
    )
    assert kcb_inputs.metrics["zero_volume_days"].measure.status is MeasureStatus.ZERO
    assert scom_inputs.metrics["avg_daily_volume"].measure.value == pytest.approx(
        7_109_197, rel=0.01
    )
    assert (scom_inputs.turnover or 0) > (kcb_inputs.turnover or 0)
    assert (
        kcb_inputs.metrics["market_cap"].measure.status is MeasureStatus.UNAVAILABLE
    )  # snapshots start 2026


def test_scraper_era_has_prices_but_no_volume(fixture_source: NseScraperSource) -> None:
    as_of = date(2026, 9, 12)
    kcb = build_price_series("KCB", fixture_source.fetch_observations("KCB"), CONFIG).as_of(as_of)
    snapshots = fixture_source.fetch_fundamental_snapshots("KCB", view="overview", end=as_of)
    # the default 6M window crosses the 2025 hole: everything is unavailable, naming the gap
    inputs = liquidity_inputs(kcb, as_of, snapshots, CONFIG)
    assert inputs.metrics["avg_daily_volume"].measure.status is MeasureStatus.UNAVAILABLE
    assert "gap" in (inputs.metrics["avg_daily_volume"].measure.reason or "")
    # a 1M window sits after the gap: prices are there, volume is not (a missing volume
    # is not zero)
    short = AnalyticsConfig(liquidity=LiquidityConfig(window="1M"))
    inputs = liquidity_inputs(kcb, as_of, snapshots, short)
    assert inputs.metrics["trading_frequency"].measure.is_known
    assert inputs.metrics["avg_daily_volume"].measure.status is MeasureStatus.UNAVAILABLE
    assert "volume reported on" in (inputs.metrics["avg_daily_volume"].measure.reason or "")


def test_kcb_market_cap_from_the_live_snapshot(fixture_source: NseScraperSource) -> None:
    as_of = date(2026, 9, 13)
    kcb = build_price_series("KCB", fixture_source.fetch_observations("KCB"), CONFIG).as_of(as_of)
    snapshots = fixture_source.fetch_fundamental_snapshots("KCB", view="overview", end=as_of)
    cap = liquidity_inputs(kcb, as_of, snapshots, CONFIG).metrics["market_cap"]
    assert cap.measure.value == pytest.approx(302_065_504_610)
    assert cap.window_end == date(2026, 9, 13)


def test_look_ahead(fixture_source: NseScraperSource) -> None:
    raw = fixture_source.fetch_observations("KCB")
    as_of = date(2024, 12, 31)
    past = build_price_series("KCB", [r for r in raw if r["trade_date"] <= "2024-12-31"], CONFIG)
    tampered = build_price_series(
        "KCB", [dict(r, volume=1) if r["trade_date"] > "2024-12-31" else r for r in raw], CONFIG
    )
    a = liquidity_inputs(past, as_of, [], CONFIG).metrics
    b = liquidity_inputs(tampered.as_of(as_of), as_of, [], CONFIG).metrics
    assert {k: v.measure.as_dict() for k, v in a.items()} == {
        k: v.measure.as_dict() for k, v in b.items()
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


def test_compute_liquidity_scores_the_universe(settings: Settings) -> None:
    source = NseScraperSource(settings)
    as_of = date(2024, 12, 31)
    result = compute_liquidity(settings, source, as_of=as_of)
    assert result.known_counts["liquidity_score"] >= 5
    with analytics_session(settings) as session:
        scores = {
            r.ticker_symbol: r
            for r in load_metrics(session, as_of_date=as_of, metric="liquidity_score")
        }
        buckets = {
            r.ticker_symbol: r
            for r in load_metrics(session, as_of_date=as_of, metric="liquidity_bucket")
        }
        assert scores["SCOM"].value is not None and scores["KCB"].value is not None
        assert scores["SCOM"].value >= scores["KCB"].value
        assert buckets["SCOM"].reason == "Highly liquid"
        assert scores["KENO"].status == "unavailable"  # delisted 2019
        assert scores["^NASI"].status == "unavailable"  # an index reports no volume
        assert "cross-section" in scores["SCOM"].provenance[0]["note"]  # type: ignore[index]
    again = compute_liquidity(settings, source, as_of=as_of, tickers=["KCB"])
    assert again.tickers_processed == ("KCB",)
    with analytics_session(settings) as session:
        after = {
            r.ticker_symbol: r
            for r in load_metrics(session, as_of_date=as_of, metric="liquidity_score")
        }
        assert after["KCB"].value == scores["KCB"].value  # same cross-section, same score


def test_cli_compute_liquidity(settings: Settings, monkeypatch: pytest.MonkeyPatch) -> None:
    from typer.testing import CliRunner

    from app.cli.main import app
    from app.web.config import get_settings

    monkeypatch.setenv("ANALYTICS_DB_PATH", str(settings.analytics_db_path))
    monkeypatch.setenv("NSE_SCRAPER_DB_PATH", str(settings.scraper_database_path))
    monkeypatch.setenv("NSE_SCRAPER_PATH", str(settings.nse_scraper_path))
    get_settings.cache_clear()
    try:
        result = CliRunner().invoke(
            app, ["analytics", "compute", "liquidity", "--as-of", "2024-12-31", "--ticker", "SCOM"]
        )
        assert result.exit_code == 0, result.output
        assert "liquidity_score" in result.output
    finally:
        get_settings.cache_clear()
