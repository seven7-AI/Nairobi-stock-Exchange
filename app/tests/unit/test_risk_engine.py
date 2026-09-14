"""Risk engine: closed-form checks, real KCB / ^NASI numbers, config versioning, look-ahead.

codegraph explore "risk_metrics beta_and_correlation drawdown correlation_matrix"
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from datetime import date, timedelta
from pathlib import Path

import numpy as np
import pytest
from sqlalchemy import select

from app.web.config import Settings
from app.web.db.analytics import analytics_session
from app.web.db.analytics.models import CalcVersion, Correlation, MarketMetric
from app.web.db.analytics.services.correlations import load_correlations
from app.web.db.analytics.services.market_metrics import load_metrics
from app.web.services.analytics.classification.service import classify_instruments
from app.web.services.analytics.config import DEFAULT_CONFIG as CONFIG
from app.web.services.analytics.config import AnalyticsConfig, MarketConfig, RiskConfig
from app.web.services.analytics.measure import MeasureStatus
from app.web.services.analytics.risk import compute_risk, correlation_matrix, risk_metrics
from app.web.services.analytics.risk.engine import (
    beta_and_correlation,
    correlation_with_sector,
    drawdown,
    sharpe_and_sortino,
    volatility,
)
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
    return build_price_series(ticker, rows(start, closes, ticker), CONFIG)


def from_returns(
    daily: Sequence[float], start: date = date(2022, 1, 3), ticker: str = "X"
) -> PriceSeries:
    closes = [100.0]
    for r in daily:
        closes.append(closes[-1] * (1 + r))
    return series(closes, start, ticker)


AS_OF = date(2023, 12, 29)
rng = np.random.default_rng(7)
MARKET_RETURNS = rng.normal(0.0004, 0.01, 600).tolist()


# --- volatility -----------------------------------------------------------------------


def test_volatility_matches_numpy_and_annualises() -> None:
    s = from_returns(MARKET_RETURNS)
    out = volatility(s, AS_OF, CONFIG)
    daily = (
        s.between(out["volatility_daily"].window_start or AS_OF, AS_OF).close.pct_change().dropna()
    )
    assert out["volatility_daily"].measure.value == pytest.approx(float(daily.std(ddof=1)))
    assert out["volatility_annualised"].measure.value == pytest.approx(
        float(daily.std(ddof=1)) * math.sqrt(252)
    )
    assert (
        out["volatility_weekly"].measure.is_positive
        and out["volatility_monthly"].measure.is_positive
    )
    assert out["volatility_rolling_3m"].measure.is_positive
    assert (out["volatility_rolling_3m"].window_start or AS_OF) > (
        out["volatility_daily"].window_start or AS_OF
    )


def test_constant_price_has_zero_volatility_and_meaningless_sharpe() -> None:
    s = series([5.0] * 600)
    out = risk_metrics(s, AS_OF, benchmark=None, peers={}, config=CONFIG)
    assert out["volatility_daily"].measure.status is MeasureStatus.ZERO
    assert out["volatility_annualised"].measure.status is MeasureStatus.ZERO
    assert out["sharpe_12m"].measure.status is MeasureStatus.NOT_MEANINGFUL
    assert out["max_drawdown_36m"].measure.status is MeasureStatus.ZERO
    assert out["drawdown_recovery_days"].measure.status is MeasureStatus.NOT_APPLICABLE


def test_too_few_observations_is_unavailable_with_the_count() -> None:
    s = series([1.0, 1.1, 1.2] * 20)  # 60 observations but the 12M window needs history
    out = volatility(s, date(2022, 3, 25), CONFIG)
    assert out["volatility_daily"].measure.status is MeasureStatus.UNAVAILABLE
    short = AnalyticsConfig(risk=RiskConfig(volatility_window="1M", min_observations=100))
    out = volatility(s, date(2022, 3, 25), short)
    assert "minimum 100" in (out["volatility_daily"].measure.reason or "")


# --- drawdown -------------------------------------------------------------------------


def test_drawdown_peak_trough_and_recovery() -> None:
    closes = (
        [100.0] * 50 + [120.0] + list(range(119, 59, -1)) + [70.0] * 10 + [125.0] + [126.0] * 200
    )
    s = series(closes)
    last = s.last_date
    assert last is not None
    out = drawdown(s, last, CONFIG)
    assert out["max_drawdown_36m"].measure.value == pytest.approx(60 / 120 - 1)
    peak_day, trough_day = out["max_drawdown_36m"].window_start, out["max_drawdown_36m"].window_end
    assert peak_day is not None and trough_day is not None and peak_day < trough_day
    assert (
        float(s.close.loc[str(peak_day)]) == 120.0 and float(s.close.loc[str(trough_day)]) == 60.0
    )
    assert out["drawdown_current"].measure.status is MeasureStatus.ZERO  # at a new high
    recovery = out["drawdown_recovery_days"]
    assert recovery.measure.value is not None and recovery.measure.value > 0
    assert recovery.window_start == trough_day


def test_drawdown_not_yet_recovered_and_current_drawdown() -> None:
    closes = [100.0] * 300 + [120.0] + list(range(119, 89, -1)) + [95.0] * 20
    s = series(closes)
    last = s.last_date
    assert last is not None
    out = drawdown(s, last, CONFIG)
    assert out["drawdown_current"].measure.value == pytest.approx(95 / 120 - 1)
    assert out["max_drawdown_36m"].measure.value == pytest.approx(90 / 120 - 1)
    assert out["drawdown_recovery_days"].measure.status is MeasureStatus.UNAVAILABLE
    assert "not yet back" in (out["drawdown_recovery_days"].measure.reason or "")


def test_drawdown_falls_back_to_the_current_segment_for_short_history() -> None:
    s = series([100.0, 90.0, 80.0, 85.0])
    out = drawdown(s, date(2022, 1, 6), CONFIG)
    assert out["max_drawdown_36m"].measure.value == pytest.approx(-0.2)
    assert out["drawdown_current"].measure.value == pytest.approx(-0.15)


# --- beta and correlation ----------------------------------------------------------


def test_beta_of_a_leveraged_copy_is_the_leverage() -> None:
    market = from_returns(MARKET_RETURNS, ticker="^NASI")
    stock = from_returns([2 * r for r in MARKET_RETURNS])
    beta, corr = beta_and_correlation(stock, market, AS_OF, "12M", CONFIG, reference_name="^NASI")
    assert beta.measure.value == pytest.approx(2.0, rel=1e-6)
    assert corr.measure.value == pytest.approx(1.0, rel=1e-6)
    inverse = from_returns([-r for r in MARKET_RETURNS])
    beta, corr = beta_and_correlation(inverse, market, AS_OF, "12M", CONFIG, reference_name="^NASI")
    assert beta.measure.value == pytest.approx(-1.0, rel=1e-6)
    assert corr.measure.value == pytest.approx(-1.0, rel=1e-6)


def test_beta_needs_a_benchmark_with_the_window_and_enough_common_dates() -> None:
    stock = from_returns(MARKET_RETURNS)
    beta, _ = beta_and_correlation(stock, None, AS_OF, "12M", CONFIG, reference_name="^NASI")
    assert beta.measure.status is MeasureStatus.UNAVAILABLE and "^NASI" in (
        beta.measure.reason or ""
    )
    short_market = from_returns(MARKET_RETURNS[-40:], start=date(2023, 11, 1), ticker="^NASI")
    beta, _ = beta_and_correlation(
        stock, short_market, AS_OF, "12M", CONFIG, reference_name="^NASI"
    )
    assert beta.measure.status is MeasureStatus.UNAVAILABLE
    flat_market = series([1.0] * 600, ticker="^NASI")
    beta, _ = beta_and_correlation(stock, flat_market, AS_OF, "12M", CONFIG, reference_name="^NASI")
    assert beta.measure.status is MeasureStatus.NOT_MEANINGFUL


def test_correlation_with_sector_and_minimum_peers() -> None:
    stock = from_returns(MARKET_RETURNS)
    peers = {
        "A": from_returns([r + 0.001 for r in MARKET_RETURNS], ticker="A"),
        "B": from_returns([r * 0.5 for r in MARKET_RETURNS], ticker="B"),
    }
    result = correlation_with_sector(stock, peers, AS_OF, CONFIG)
    assert result.measure.value == pytest.approx(1.0, rel=1e-6)  # peers are affine copies
    thin = correlation_with_sector(stock, {"A": peers["A"]}, AS_OF, CONFIG)
    assert thin.measure.status is MeasureStatus.UNAVAILABLE and "only 1 peer" in (
        thin.measure.reason or ""
    )


def test_correlation_matrix_is_symmetric_upper_triangle() -> None:
    universe = {
        "A": from_returns(MARKET_RETURNS, ticker="A"),
        "B": from_returns([-r for r in MARKET_RETURNS], ticker="B"),
        "C": from_returns(rng.normal(0, 0.01, 600).tolist(), ticker="C"),
        "THIN": series([1.0, 2.0], ticker="THIN"),
    }
    pairs = correlation_matrix(universe, AS_OF, "12M", CONFIG)
    keys = {(a, b) for a, b, _, _ in pairs}
    assert keys == {("A", "B"), ("A", "C"), ("B", "C")}
    ab = next(v for a, b, v, _ in pairs if (a, b) == ("A", "B"))
    assert ab == pytest.approx(-1.0, rel=1e-6)
    assert all(n >= CONFIG.risk.min_observations for _, _, _, n in pairs)


# --- Sharpe / Sortino ---------------------------------------------------------------


def test_sharpe_and_sortino_use_the_configured_risk_free_rate() -> None:
    s = from_returns(MARKET_RETURNS)
    base = sharpe_and_sortino(s, AS_OF, CONFIG)
    higher_rf = AnalyticsConfig(market=MarketConfig(risk_free_rate=0.30))
    penalised = sharpe_and_sortino(s, AS_OF, higher_rf)
    assert (
        base["sharpe_12m"].measure.value is not None
        and penalised["sharpe_12m"].measure.value is not None
    )
    assert penalised["sharpe_12m"].measure.value < base["sharpe_12m"].measure.value
    assert "risk-free 12.00%" in (base["sharpe_12m"].measure.provenance[0].note or "")
    assert base["sortino_12m"].measure.value is not None
    daily = s.between(base["sharpe_12m"].window_start or AS_OF, AS_OF).close.pct_change().dropna()
    excess = daily - 0.12 / 252
    expected = float(excess.mean()) * 252 / (float(daily.std(ddof=1)) * math.sqrt(252))
    assert base["sharpe_12m"].measure.value == pytest.approx(expected)


def test_always_rising_series_has_no_downside_deviation() -> None:
    s = from_returns([0.002] * 600)
    out = sharpe_and_sortino(s, AS_OF, CONFIG)
    assert out["sharpe_12m"].measure.status is MeasureStatus.NOT_MEANINGFUL  # zero volatility
    assert out["sortino_12m"].measure.status is MeasureStatus.NOT_MEANINGFUL


# --- real numbers ----------------------------------------------------------------------


@pytest.fixture(scope="module")
def kcb(fixture_source: NseScraperSource) -> PriceSeries:
    return build_price_series("KCB", fixture_source.fetch_observations("KCB"), CONFIG)


@pytest.fixture(scope="module")
def nasi(fixture_source: NseScraperSource) -> PriceSeries:
    return build_price_series("^NASI", fixture_source.fetch_observations("^NASI"), CONFIG)


def test_kcb_2019_volatility_beta_and_correlation_hand_computed(
    kcb: PriceSeries, nasi: PriceSeries
) -> None:
    as_of = date(2019, 12, 31)
    out = risk_metrics(
        kcb.as_of(as_of), as_of, benchmark=nasi.as_of(as_of), peers={}, config=CONFIG
    )
    # 251 daily returns over 2018-12-31..2019-12-31, sample std 0.01484, x sqrt(252) = 0.2355
    assert out["volatility_daily"].measure.value == pytest.approx(0.01484, abs=5e-5)
    assert out["volatility_annualised"].measure.value == pytest.approx(0.2355, abs=1e-3)
    assert out["beta_12m"].measure.value == pytest.approx(0.6394, abs=1e-3)
    assert out["correlation_market_12m"].measure.value == pytest.approx(0.3799, abs=1e-3)
    assert out["beta_36m"].measure.is_known
    assert out["sharpe_12m"].measure.is_positive  # +44 % year against a 12 % risk-free rate


def test_nasi_2008_crash_drawdown(nasi: PriceSeries) -> None:
    as_of = date(2011, 12, 30)
    out = drawdown(
        nasi.as_of(as_of), as_of, AnalyticsConfig(risk=RiskConfig(drawdown_window="36M"))
    )
    # the window is 2008-12-30..2011-12-30, so the 2008-06-09 peak is outside it: look
    # at the full segment instead
    full = drawdown(
        nasi.as_of(date(2012, 12, 31)),
        date(2012, 12, 31),
        AnalyticsConfig(risk=RiskConfig(drawdown_window="36M")),
    )
    assert (
        out["max_drawdown_36m"].measure.value is not None
        and out["max_drawdown_36m"].measure.value < 0
    )
    assert full["max_drawdown_36m"].measure.value is not None
    # hand-computed on the full 2007-2012 series: -56.27 % from 2008-06-09 to 2009-03-09
    segment = nasi.between(date(2007, 1, 1), date(2012, 12, 31))
    running = segment.close.cummax()
    assert float((segment.close / running - 1).min()) == pytest.approx(-0.5627, abs=1e-4)


def test_kcb_after_the_gap_has_no_twelve_month_risk(kcb: PriceSeries, nasi: PriceSeries) -> None:
    as_of = date(2026, 9, 12)
    out = risk_metrics(
        kcb.as_of(as_of), as_of, benchmark=nasi.as_of(as_of), peers={}, config=CONFIG
    )
    assert out["volatility_daily"].measure.status is MeasureStatus.UNAVAILABLE
    assert "gap" in (out["volatility_daily"].measure.reason or "")
    assert out["beta_12m"].measure.status is MeasureStatus.UNAVAILABLE
    assert (
        out["volatility_rolling_3m"].measure.status is MeasureStatus.UNAVAILABLE
    )  # 3M crosses the gap too


def test_look_ahead(fixture_source: NseScraperSource, nasi: PriceSeries) -> None:
    raw = fixture_source.fetch_observations("KCB")
    as_of = date(2019, 12, 31)
    past = build_price_series("KCB", [r for r in raw if r["trade_date"] <= "2019-12-31"], CONFIG)
    tampered = build_price_series(
        "KCB",
        [dict(r, close_price=1.0) if r["trade_date"] > "2019-12-31" else r for r in raw],
        CONFIG,
    )
    a = risk_metrics(past, as_of, benchmark=nasi.as_of(as_of), peers={}, config=CONFIG)
    b = risk_metrics(
        tampered.as_of(as_of), as_of, benchmark=nasi.as_of(as_of), peers={}, config=CONFIG
    )
    assert {k: v.measure.as_dict() for k, v in a.items()} == {
        k: v.measure.as_dict() for k, v in b.items()
    }


# --- the compute job -------------------------------------------------------------------


@pytest.fixture
def settings(fixture_db_path: Path, tmp_path: Path) -> Settings:
    s = Settings(
        NSE_SCRAPER_DB_PATH=str(fixture_db_path),
        NSE_SCRAPER_PATH=str(tmp_path / "scraper"),
        ANALYTICS_DB_PATH=str(tmp_path / "a.sqlite3"),
    )
    upgrade_analytics_db(s.analytics_db_path)
    return s


def test_compute_risk_writes_metrics_and_the_correlation_matrix(settings: Settings) -> None:
    source = NseScraperSource(settings)
    classify_instruments(settings, source)
    as_of = date(2019, 12, 31)
    result = compute_risk(settings, source, as_of=as_of)
    assert result.known_counts["beta_12m"] >= 6
    with analytics_session(settings) as session:
        kcb = {r.metric: r for r in load_metrics(session, ticker_symbol="KCB", as_of_date=as_of)}
        assert kcb["beta_12m"].value == pytest.approx(0.6394, abs=1e-3)
        assert kcb["correlation_sector_12m"].status == "known"
        pairs = load_correlations(session, as_of_date=as_of, window="12M")
        assert pairs and all(p.ticker_a < p.ticker_b for p in pairs)
        kcb_eqty = next(p for p in pairs if (p.ticker_a, p.ticker_b) == ("EQTY", "KCB"))
        assert -1 <= kcb_eqty.value <= 1 and kcb_eqty.n_obs >= 200
        # idempotent: the same run rewrites in place
        before = len(session.execute(select(Correlation)).scalars().all())
    compute_risk(settings, source, as_of=as_of)
    with analytics_session(settings) as session:
        assert len(session.execute(select(Correlation)).scalars().all()) == before
        assert (
            len({r.calc_version_id for r in session.execute(select(MarketMetric)).scalars()}) == 1
        )


def test_a_changed_risk_free_rate_is_a_new_calc_version_and_keeps_old_rows(
    settings: Settings,
) -> None:
    source = NseScraperSource(settings)
    as_of = date(2019, 12, 31)
    compute_risk(settings, source, as_of=as_of, tickers=["KCB"], with_correlation_matrix=False)
    changed = AnalyticsConfig(market=MarketConfig(risk_free_rate=0.08))
    compute_risk(
        settings,
        source,
        as_of=as_of,
        tickers=["KCB"],
        config=changed,
        with_correlation_matrix=False,
    )
    with analytics_session(settings) as session:
        versions = session.execute(select(CalcVersion)).scalars().all()
        assert len(versions) == 2
        sharpes = list(load_metrics(session, ticker_symbol="KCB", metric="sharpe_12m"))
        assert len(sharpes) == 2 and sharpes[0].value != sharpes[1].value
        assert {s.calc_version_id for s in sharpes} == {v.id for v in versions}


def test_cli_compute_risk(settings: Settings, monkeypatch: pytest.MonkeyPatch) -> None:
    from typer.testing import CliRunner

    from app.cli.main import app
    from app.web.config import get_settings

    monkeypatch.setenv("ANALYTICS_DB_PATH", str(settings.analytics_db_path))
    monkeypatch.setenv("NSE_SCRAPER_DB_PATH", str(settings.scraper_database_path))
    monkeypatch.setenv("NSE_SCRAPER_PATH", str(settings.nse_scraper_path))
    get_settings.cache_clear()
    try:
        result = CliRunner().invoke(
            app,
            [
                "analytics",
                "compute",
                "risk",
                "--as-of",
                "2019-12-31",
                "--ticker",
                "KCB",
                "--no-matrix",
            ],
        )
        assert result.exit_code == 0, result.output
        assert "beta_12m" in result.output
    finally:
        get_settings.cache_clear()
