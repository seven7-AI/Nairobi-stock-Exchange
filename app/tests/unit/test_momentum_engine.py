"""Momentum engine: synthetic trends, real KCB-vs-market numbers, peers, look-ahead.

codegraph explore "momentum_metrics compute_momentum trend_strength"
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from datetime import date, timedelta
from pathlib import Path

import pytest
from sqlalchemy import select

from app.web.config import Settings
from app.web.db.analytics import analytics_session
from app.web.db.analytics.models import JobRun, MarketMetric
from app.web.db.analytics.services.market_metrics import load_metrics
from app.web.services.analytics.classification.service import classify_instruments
from app.web.services.analytics.config import DEFAULT_CONFIG, AnalyticsConfig, MomentumConfig
from app.web.services.analytics.measure import MeasureStatus
from app.web.services.analytics.momentum import compute_momentum, momentum_metrics
from app.web.services.analytics.momentum.engine import (
    momentum_12_1,
    momentum_persistence,
    moving_average,
    range_position,
    relative_to_market,
    relative_to_sector,
    trend_strength,
)
from app.web.services.analytics.returns.engine import window_return
from app.web.services.analytics.series import PriceSeries, build_price_series
from app.web.services.analytics.store import upgrade_analytics_db
from app.web.services.market_data.sources import NseScraperSource

pytestmark = pytest.mark.unit


def rows(start: date, closes: Sequence[float], ticker: str = "X") -> list[dict[str, object]]:
    out: list[dict[str, object]] = []
    day = start
    for index, close in enumerate(closes):
        while day.weekday() >= 5:
            day += timedelta(days=1)
        out.append(
            {
                "id": index + 1,
                "trade_date": day.isoformat(),
                "close_price": close,
                "volume": 1000,
                "source_ticker": ticker,
                "quality_flags": [],
            }
        )
        day += timedelta(days=1)
    return out


def series(
    closes: Sequence[float], start: date = date(2022, 1, 3), ticker: str = "X"
) -> PriceSeries:
    return build_price_series(ticker, rows(start, closes, ticker), DEFAULT_CONFIG)


def geometric(n: int, daily: float, start_value: float = 100.0) -> list[float]:
    return [start_value * (1 + daily) ** i for i in range(n)]


AS_OF = date(2023, 12, 29)  # a Friday inside every synthetic series below


# --- absolute -------------------------------------------------------------------


def test_momentum_12_1_skips_the_last_month() -> None:
    s = series(geometric(600, 0.001))
    result = momentum_12_1(s, AS_OF)
    assert result.measure.is_known
    one_month_ago = s.close_on_or_before(date(2023, 11, 29))
    assert one_month_ago is not None
    assert result.window_end == one_month_ago[0]
    assert result.window_start is not None and result.window_start <= date(2022, 11, 30)
    twelve = window_return(s, AS_OF, "12M").measure.value
    assert twelve is not None and result.measure.value is not None
    # a constant-growth series: the same number of trading days, so the same return
    assert result.measure.value == pytest.approx(twelve, rel=0.05)


def test_momentum_12_1_needs_an_observation_a_month_ago() -> None:
    assert (
        momentum_12_1(series([1.0] * 5), date(2022, 1, 7)).measure.status
        is MeasureStatus.UNAVAILABLE
    )


# --- relative --------------------------------------------------------------------


def test_relative_to_market_subtracts_the_benchmark_return() -> None:
    stock = series(geometric(600, 0.002))
    market = series(geometric(600, 0.001), ticker="^NASI")
    out = relative_to_market(stock, market, AS_OF, "^NASI")
    own = window_return(stock, AS_OF, "3M").measure.value
    bench = window_return(market, AS_OF, "3M").measure.value
    assert own is not None and bench is not None
    assert out["relative_3m_vs_market"].measure.value == pytest.approx(own - bench)
    assert out["relative_12m_vs_market"].measure.provenance[-1].ticker == "^NASI"


def test_relative_to_market_without_a_benchmark_is_unavailable_with_the_reason() -> None:
    stock = series(geometric(600, 0.002))
    out = relative_to_market(stock, None, AS_OF, "^NASI")
    assert out["relative_1m_vs_market"].measure.status is MeasureStatus.UNAVAILABLE
    assert "^NASI" in (out["relative_1m_vs_market"].measure.reason or "")
    empty = build_price_series("^NASI", [], DEFAULT_CONFIG)
    assert (
        relative_to_market(stock, empty, AS_OF, "^NASI")["relative_1m_vs_market"].measure.status
        is MeasureStatus.UNAVAILABLE
    )


def test_relative_to_sector_uses_an_equal_weighted_peer_mean_and_a_minimum() -> None:
    stock = series(geometric(600, 0.002))
    peers = {
        "A": series(geometric(600, 0.001), ticker="A"),
        "B": series(geometric(600, 0.003), ticker="B"),
    }
    out = relative_to_sector(stock, peers, AS_OF, min_peers=2)
    own = window_return(stock, AS_OF, "6M").measure.value
    a = window_return(peers["A"], AS_OF, "6M").measure.value
    b = window_return(peers["B"], AS_OF, "6M").measure.value
    assert own is not None and a is not None and b is not None
    assert out["relative_6m_vs_sector"].measure.value == pytest.approx(own - (a + b) / 2)
    assert "2 sector peers" in (out["relative_6m_vs_sector"].measure.provenance[-1].note or "")
    thin = relative_to_sector(stock, {"A": peers["A"]}, AS_OF, min_peers=2)
    assert thin["relative_6m_vs_sector"].measure.status is MeasureStatus.UNAVAILABLE
    assert "only 1 peer" in (thin["relative_6m_vs_sector"].measure.reason or "")
    assert (
        relative_to_sector(stock, {}, AS_OF, min_peers=1)["relative_1m_vs_sector"].measure.status
        is MeasureStatus.UNAVAILABLE
    )


def test_relative_inherits_the_stock_blocker_first() -> None:
    stock = series([1.0] * 10)  # no 12M history
    market = series(geometric(600, 0.001), ticker="^NASI")
    out = relative_to_market(stock, market, date(2022, 1, 14), "^NASI")
    assert out["relative_12m_vs_market"].measure.status is MeasureStatus.UNAVAILABLE
    assert "history starts" in (out["relative_12m_vs_market"].measure.reason or "")


# --- moving averages and trend -------------------------------------------------


def test_moving_average_and_price_to_ma() -> None:
    closes = [float(i) for i in range(1, 301)]
    s = series(closes)
    last = s.last_date
    assert last is not None
    ma50 = moving_average(s, last, 50)
    assert ma50.measure.value == pytest.approx(sum(closes[-50:]) / 50)
    assert ma50.window_end == last
    assert moving_average(s, last, 500).measure.status is MeasureStatus.UNAVAILABLE
    out = momentum_metrics(s, last, benchmark=None, peers={}, config=DEFAULT_CONFIG)
    assert out["price_to_ma_50"].measure.value == pytest.approx(300 / (sum(closes[-50:]) / 50) - 1)
    assert out["ma_short_over_long"].measure.is_positive
    assert out["price_to_ma_200"].measure.is_positive


def test_moving_average_refuses_to_span_a_gap() -> None:
    raw = rows(date(2024, 10, 1), [10.0] * 40) + rows(date(2026, 7, 27), [20.0] * 30)
    s = build_price_series("X", raw, DEFAULT_CONFIG)
    result = moving_average(s, date(2026, 9, 5), 50)
    assert result.measure.status is MeasureStatus.UNAVAILABLE
    assert "span a data gap" in (result.measure.reason or "")


def test_trend_strength_is_signed_r_squared() -> None:
    up = trend_strength(series(geometric(600, 0.001)), AS_OF, "6M")
    assert up.measure.value is not None and up.measure.value > 0.99
    down = trend_strength(series(geometric(600, -0.001)), AS_OF, "6M")
    assert down.measure.value is not None and down.measure.value < -0.99
    flat = trend_strength(series([5.0] * 600), AS_OF, "6M")
    assert flat.measure.status is MeasureStatus.ZERO
    zigzag = trend_strength(series([10.0, 11.0] * 300), AS_OF, "6M")
    assert zigzag.measure.value is not None and abs(zigzag.measure.value) < 0.1
    short = trend_strength(series([1.0, 2.0, 3.0]), date(2022, 1, 5), "6M")
    assert short.measure.status is MeasureStatus.UNAVAILABLE


def test_momentum_persistence_counts_positive_months() -> None:
    s = series(geometric(600, 0.001))
    result = momentum_persistence(s, AS_OF)
    assert result.measure.value == 1.0
    falling = momentum_persistence(series(geometric(600, -0.001)), AS_OF)
    assert falling.measure.status is MeasureStatus.ZERO
    assert (
        momentum_persistence(series([1.0] * 30), date(2022, 2, 10)).measure.status
        is MeasureStatus.UNAVAILABLE
    )


def test_range_position() -> None:
    s = series(geometric(600, 0.001))
    out = range_position(s, AS_OF)
    assert out["distance_from_52w_high"].measure.status is MeasureStatus.ZERO  # at its high
    assert out["distance_from_52w_low"].measure.is_positive
    down = range_position(series(geometric(600, -0.001)), AS_OF)
    assert (
        down["distance_from_52w_high"].measure.value is not None
        and down["distance_from_52w_high"].measure.value < 0
    )
    assert down["distance_from_52w_low"].measure.status is MeasureStatus.ZERO


def test_momentum_metrics_reports_every_metric_and_honours_config() -> None:
    s = series(geometric(600, 0.001))
    config = AnalyticsConfig(momentum=MomentumConfig(ma_short=20, ma_long=100, trend_window="3M"))
    out = momentum_metrics(s, AS_OF, benchmark=None, peers={}, config=config)
    assert {
        "momentum_1m",
        "momentum_24m",
        "momentum_12m_1m",
        "relative_12m_vs_market",
        "relative_12m_vs_sector",
        "ma_20",
        "ma_100",
        "price_to_ma_20",
        "price_to_ma_100",
        "ma_short_over_long",
        "trend_strength_3m",
        "momentum_persistence_12m",
        "distance_from_52w_high",
        "distance_from_52w_low",
    } <= set(out)
    assert all(not math.isnan(r.measure.value) for r in out.values() if r.measure.value is not None)


# --- real numbers (fixture) --------------------------------------------------------


@pytest.fixture(scope="module")
def kcb(fixture_source: NseScraperSource) -> PriceSeries:
    return build_price_series("KCB", fixture_source.fetch_observations("KCB"), DEFAULT_CONFIG)


@pytest.fixture(scope="module")
def nasi(fixture_source: NseScraperSource) -> PriceSeries:
    return build_price_series("^NASI", fixture_source.fetch_observations("^NASI"), DEFAULT_CONFIG)


def test_kcb_relative_to_nasi_end_of_2019_hand_computed(
    kcb: PriceSeries, nasi: PriceSeries
) -> None:
    as_of = date(2019, 12, 31)
    out = relative_to_market(kcb.as_of(as_of), nasi.as_of(as_of), as_of, "^NASI")
    kcb_12m = 54.0 / 37.45 - 1  # 2018-12-31 -> 2019-12-31
    nasi_12m = 166.41 / 140.43 - 1
    assert out["relative_12m_vs_market"].measure.value == pytest.approx(kcb_12m - nasi_12m)
    assert out["relative_6m_vs_market"].measure.value == pytest.approx(
        (54.0 / 38.25 - 1) - (166.41 / 149.61 - 1)
    )


def test_kcb_12_1_and_range_end_of_2019(kcb: PriceSeries) -> None:
    as_of = date(2019, 12, 31)
    twelve_one = momentum_12_1(kcb.as_of(as_of), as_of)
    # end = last obs <= 2019-11-30 (2019-11-29, 50.0); start = last obs <= 2018-11-29 (39.25)
    assert twelve_one.measure.value == pytest.approx(50.0 / 39.25 - 1)
    assert twelve_one.window_start == date(2018, 11, 29)
    position = range_position(kcb.as_of(as_of), as_of)
    assert (
        position["distance_from_52w_high"].measure.status is MeasureStatus.ZERO
    )  # 54.0 was the 2019 high
    assert position["distance_from_52w_low"].measure.value == pytest.approx(54.0 / 36.3 - 1)


def test_kcb_relative_to_sector_end_of_2019(
    fixture_source: NseScraperSource, kcb: PriceSeries
) -> None:
    as_of = date(2019, 12, 31)
    peers = {
        t: build_price_series(t, fixture_source.fetch_observations(t), DEFAULT_CONFIG).as_of(as_of)
        for t in ("EQTY", "ABSA", "NCBA")
    }
    out = relative_to_sector(kcb.as_of(as_of), peers, as_of, min_peers=2)
    expected_peer_mean = (
        sum(window_return(p, as_of, "12M").measure.value or 0 for p in peers.values()) / 3
    )
    assert out["relative_12m_vs_sector"].measure.value == pytest.approx(
        (54.0 / 37.45 - 1) - expected_peer_mean
    )
    assert "3 sector peers" in (out["relative_12m_vs_sector"].measure.provenance[-1].note or "")


def test_kcb_after_the_gap_has_short_momentum_only(kcb: PriceSeries, nasi: PriceSeries) -> None:
    as_of = date(2026, 9, 12)
    out = momentum_metrics(
        kcb.as_of(as_of), as_of, benchmark=nasi.as_of(as_of), peers={}, config=DEFAULT_CONFIG
    )
    assert out["momentum_1m"].measure.is_known
    assert out["momentum_12m"].measure.status is MeasureStatus.UNAVAILABLE
    assert (
        out["relative_1m_vs_market"].measure.status is MeasureStatus.UNAVAILABLE
    )  # ^NASI ends 2024
    assert "^NASI" in (out["relative_1m_vs_market"].measure.reason or "")
    assert out["ma_200"].measure.status is MeasureStatus.UNAVAILABLE


def test_look_ahead(fixture_source: NseScraperSource, nasi: PriceSeries) -> None:
    raw = fixture_source.fetch_observations("KCB")
    as_of = date(2019, 12, 31)
    past = build_price_series(
        "KCB", [r for r in raw if r["trade_date"] <= "2019-12-31"], DEFAULT_CONFIG
    )
    tampered = build_price_series(
        "KCB",
        [dict(r, close_price=1.0) if r["trade_date"] > "2019-12-31" else r for r in raw],
        DEFAULT_CONFIG,
    )
    a = momentum_metrics(past, as_of, benchmark=nasi.as_of(as_of), peers={}, config=DEFAULT_CONFIG)
    b = momentum_metrics(
        tampered.as_of(as_of), as_of, benchmark=nasi.as_of(as_of), peers={}, config=DEFAULT_CONFIG
    )
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


def test_compute_momentum_uses_classification_peers_and_is_idempotent(settings: Settings) -> None:
    source = NseScraperSource(settings)
    classify_instruments(settings, source)
    as_of = date(2019, 12, 31)
    first = compute_momentum(settings, source, as_of=as_of)
    assert set(first.tickers_processed) >= {"KCB", "EQTY", "^NASI"}
    assert first.known_counts["relative_12m_vs_market"] >= 6
    second = compute_momentum(settings, source, as_of=as_of, tickers=["KCB"])
    assert second.tickers_processed == ("KCB",)
    with analytics_session(settings) as session:
        total = len(session.execute(select(MarketMetric)).scalars().all())
        assert total == first.rows_written  # the second run rewrote KCB's rows in place
        kcb = {r.metric: r for r in load_metrics(session, ticker_symbol="KCB", as_of_date=as_of)}
        assert kcb["relative_12m_vs_market"].value == pytest.approx(
            (54.0 / 37.45 - 1) - (166.41 / 140.43 - 1)
        )
        assert kcb["relative_12m_vs_sector"].status == "known"  # EQTY, ABSA, NCBA are banking peers
        provenance = kcb["relative_12m_vs_sector"].provenance or []
        assert "sector peers" in provenance[-1]["note"]
        nasi = {r.metric: r for r in load_metrics(session, ticker_symbol="^NASI", as_of_date=as_of)}
        assert (
            nasi["relative_12m_vs_sector"].status == "unavailable"
        )  # ^N20I alone is below min_peers
        run = session.execute(select(JobRun).where(JobRun.job_name == "momentum")).scalars().first()
        assert run is not None and run.details is not None and run.details["benchmark"] == "^NASI"


def test_cli_compute_momentum(settings: Settings, monkeypatch: pytest.MonkeyPatch) -> None:
    from typer.testing import CliRunner

    from app.cli.main import app
    from app.web.config import get_settings

    monkeypatch.setenv("ANALYTICS_DB_PATH", str(settings.analytics_db_path))
    monkeypatch.setenv("NSE_SCRAPER_DB_PATH", str(settings.scraper_database_path))
    monkeypatch.setenv("NSE_SCRAPER_PATH", str(settings.nse_scraper_path))
    get_settings.cache_clear()
    try:
        result = CliRunner().invoke(
            app, ["analytics", "compute", "momentum", "--as-of", "2019-12-31", "--ticker", "KCB"]
        )
        assert result.exit_code == 0, result.output
        assert "momentum_12m_1m" in result.output
    finally:
        get_settings.cache_clear()
