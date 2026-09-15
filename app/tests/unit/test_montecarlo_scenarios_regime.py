"""Monte Carlo paths (seeded, convergent), scenario arithmetic, regime detection, jobs.

codegraph explore "simulate_paths scenario_outcome detect_regime compute_regime"
"""

from __future__ import annotations

from datetime import date
from pathlib import Path

import numpy as np
import pytest

from app.web.config import Settings
from app.web.db.analytics import analytics_session
from app.web.db.analytics.services.simulations import load_regimes, load_simulations
from app.web.services.analytics.classification.service import classify_instruments
from app.web.services.analytics.config import DEFAULT_CONFIG as CONFIG
from app.web.services.analytics.config import (
    AnalyticsConfig,
    MonteCarloConfig,
    RegimeConfig,
    ScenarioAssumptions,
    ScenarioConfig,
)
from app.web.services.analytics.measure import MeasureStatus
from app.web.services.analytics.montecarlo import compute_montecarlo, simulate_paths, simulate_stock
from app.web.services.analytics.montecarlo.engine import path_statistics, simulation_summary
from app.web.services.analytics.regime import compute_regime, detect_regime, regime_weights
from app.web.services.analytics.returns.service import load_universe
from app.web.services.analytics.risk.engine import Window, resolve_window
from app.web.services.analytics.scenarios import compute_scenarios, scenario_outcomes
from app.web.services.analytics.scenarios.engine import scenario_outcome
from app.web.services.analytics.store import upgrade_analytics_db
from app.web.services.market_data.sources import NseScraperSource

pytestmark = pytest.mark.unit


def test_paths_are_seeded_and_shaped() -> None:
    r = np.random.default_rng(1).normal(0.0005, 0.02, size=500)
    a = simulate_paths(r, horizon_days=21, n_paths=300, seed=5, method="bootstrap", block_days=21)
    b = simulate_paths(r, horizon_days=21, n_paths=300, seed=5, method="bootstrap", block_days=21)
    c = simulate_paths(r, horizon_days=21, n_paths=300, seed=6, method="bootstrap", block_days=21)
    assert a.shape == (300, 21) and np.array_equal(a, b) and not np.array_equal(a, c)
    # every step is one of the sampled returns
    steps = np.diff(np.concatenate([np.zeros((300, 1)), a], axis=1), axis=1)
    assert np.all(np.isin(np.round(steps, 12), np.round(r, 12)))
    with pytest.raises(ValueError, match="unknown simulation method"):
        simulate_paths(r, horizon_days=5, n_paths=2, seed=0, method="garch", block_days=3)


def test_block_bootstrap_keeps_contiguous_blocks() -> None:
    r = np.arange(100, dtype=float)  # the value is its own index
    paths = simulate_paths(
        r, horizon_days=9, n_paths=50, seed=3, method="block_bootstrap", block_days=3
    )
    steps = np.diff(np.concatenate([np.zeros((50, 1)), paths], axis=1), axis=1)
    for row in steps:
        for start in range(0, 9, 3):
            block = row[start : start + 3]
            assert np.array_equal(
                (block - block[0]) % 100, [0.0, 1.0, 2.0]
            )  # consecutive (circular)


def test_path_statistics_by_hand() -> None:
    paths = np.array([[0.1, -0.2, 0.05], [0.0, 0.0, 0.0]])
    terminal, max_dd = path_statistics(paths)
    assert terminal[0] == pytest.approx(np.expm1(0.05)) and terminal[1] == 0.0
    assert max_dd[0] == pytest.approx(1 - np.exp(-0.3)) and max_dd[1] == 0.0


def test_quantiles_converge_with_n() -> None:
    r = np.random.default_rng(11).normal(0.0, 0.015, size=750)
    small = simulate_paths(
        r, horizon_days=63, n_paths=500, seed=1, method="bootstrap", block_days=21
    )
    large = simulate_paths(
        r, horizon_days=63, n_paths=40_000, seed=1, method="bootstrap", block_days=21
    )
    other = simulate_paths(
        r, horizon_days=63, n_paths=40_000, seed=2, method="bootstrap", block_days=21
    )
    q_small, q_large, q_other = (
        np.quantile(np.expm1(p[:, -1]), [0.05, 0.5, 0.95]) for p in (small, large, other)
    )
    assert np.max(np.abs(q_large - q_other)) < 0.01  # seed noise at N = 40k is tiny
    assert np.max(np.abs(q_small - q_large)) < 0.05  # and the small run is in the neighbourhood
    # the 63-day sd of a 1.5 % daily process is about 11.9 %: q05 near -0.18, q95 near +0.22
    assert -0.22 < q_large[0] < -0.14 and 0.16 < q_large[2] < 0.26


@pytest.fixture
def fixture_universe(fixture_settings: Settings, fixture_source: NseScraperSource) -> dict:
    return load_universe(fixture_source, CONFIG)


def test_simulate_stock_on_kcb(fixture_universe: dict) -> None:
    kcb = fixture_universe["KCB"]
    out = {
        (s.method, s.horizon_days): s
        for s in simulate_stock(kcb, date(2019, 12, 31), CONFIG, ticker="KCB")
    }
    assert set(out) == {
        (m, h) for m in ("bootstrap", "block_bootstrap") for h in (21, 63, 126, 252)
    }
    year = out[("bootstrap", 252)]
    assert year.measure.is_known and year.price == 54.0 and year.n_paths == 10_000
    assert year.seed == CONFIG.montecarlo.seed
    q = year.quantiles
    assert q["q05"] < q["q25"] < q["q50"] < q["q75"] < q["q95"]
    assert 0.0 < (year.p_positive or 0.0) < 1.0
    assert set(year.p_return_above) == {"-0.20", "-0.10", "+0.00", "+0.10", "+0.25"}
    assert year.p_return_above["+0.00"] == year.p_positive
    assert year.p_return_above["-0.20"] >= year.p_return_above["+0.25"]
    dd = year.p_drawdown_above
    assert (
        dd["0.10"] >= dd["0.20"] >= dd["0.30"] and 0.0 < (year.expected_max_drawdown or 0.0) < 1.0
    )
    assert year.inputs["observations"] >= 700 and year.inputs["window"] == "36M"
    # the same run again is byte-identical
    again = {
        (s.method, s.horizon_days): s
        for s in simulate_stock(kcb, date(2019, 12, 31), CONFIG, ticker="KCB")
    }
    assert again[("bootstrap", 252)].quantiles == q
    # a month has less dispersion than a year
    assert out[("bootstrap", 21)].quantiles["q95"] < q["q95"]
    # a window crossing the 2025 gap yields nothing
    blocked = simulate_stock(kcb, date(2026, 9, 13), CONFIG, ticker="KCB")
    assert all(s.measure.status is MeasureStatus.UNAVAILABLE for s in blocked)
    assert "gap" in (blocked[0].measure.reason or "") or "minimum" in (
        blocked[0].measure.reason or ""
    )
    few = AnalyticsConfig(montecarlo=MonteCarloConfig(n_paths=200, seed=1))
    window = resolve_window(kcb, date(2019, 12, 31), "36M", "x")
    assert isinstance(window, Window)
    r = np.diff(np.log(window.part.close.to_numpy(dtype=float)))
    s = simulation_summary("KCB", "bootstrap", 21, r, window, 54.0, few)
    assert s.n_paths == 200 and s.seed == 1


def test_scenario_arithmetic_and_verbatim_assumptions() -> None:
    bear = CONFIG.scenarios.scenarios[0]
    out = scenario_outcome("X", bear, price=100.0, beta=1.2, eps=10.0, pe=10.0, config=CONFIG)
    assert out.beta_path_price == pytest.approx(100 * (1 - 1.2 * 0.25))  # 70
    assert out.fundamental_path_price == pytest.approx(10 * 0.9 * 10 * 0.8)  # 72
    assert out.implied_price == pytest.approx(71.0) and out.measure.value == pytest.approx(-0.29)
    assert (
        out.assumptions["market_return"] == -0.25
        and out.assumptions["description"] == bear.description
    )
    assert (
        out.assumptions["paths_used"] == ["beta", "fundamental"]
        and out.assumptions["beta_source"] == "beta_12m"
    )
    no_pe = scenario_outcome("X", bear, price=100.0, beta=None, eps=None, pe=None, config=CONFIG)
    assert no_pe.fundamental_path_price is None and no_pe.implied_price == pytest.approx(75.0)
    assert no_pe.assumptions["beta_source"] == "default" and no_pe.assumptions["paths_used"] == [
        "beta"
    ]
    loss = scenario_outcome("X", bear, price=100.0, beta=1.0, eps=-2.0, pe=None, config=CONFIG)
    assert loss.fundamental_path_price is None
    assert (
        scenario_outcome(
            "X", bear, price=None, beta=1.0, eps=None, pe=None, config=CONFIG
        ).measure.status
        is MeasureStatus.UNAVAILABLE
    )
    names = [
        o.scenario
        for o in scenario_outcomes("X", price=10.0, beta=1.0, eps=None, pe=None, config=CONFIG)
    ]
    assert names == ["bear", "base", "bull"]
    custom = AnalyticsConfig(
        scenarios=ScenarioConfig(
            scenarios=(
                ScenarioAssumptions(
                    name="crash", market_return=-0.5, multiple_change=-0.5, earnings_growth=-0.5
                ),
            )
        )
    )
    crash = scenario_outcomes("X", price=10.0, beta=1.0, eps=1.0, pe=10.0, config=custom)[0]
    assert crash.scenario == "crash" and crash.implied_price == pytest.approx((5.0 + 2.5) / 2)


def test_regime_weights_renormalise() -> None:
    base = {"quality": 0.5, "momentum": 0.3, "value": 0.2}
    out = regime_weights(base, {"momentum": -0.3, "quality": 0.1})
    assert out["momentum"] == 0.0 and sum(out.values()) == pytest.approx(1.0)
    assert out["quality"] == pytest.approx(0.6 / 0.8)
    assert regime_weights(base, {}) == base


def test_regime_labels_on_nasi(fixture_universe: dict) -> None:
    nasi = fixture_universe["^NASI"]
    n20i = fixture_universe["^N20I"]
    # NASI starts 2008-02-25: too young for 2008; the older N20I carries the crisis
    young = detect_regime(nasi, date(2008, 12, 31), CONFIG)
    assert young.measure.status is MeasureStatus.UNAVAILABLE
    assert "211 observations in the window, minimum 263" in (young.measure.reason or "")
    crisis = detect_regime(n20i, date(2008, 12, 31), CONFIG, index="^N20I")
    assert crisis.index == "^N20I" and crisis.volatility == "High-vol"
    assert crisis.trend == "Bear" and crisis.risk == "Risk-off" and crisis.measure.value == -1.0
    assert crisis.evidence["price_vs_ma"] < 0 and crisis.evidence["return_6m"] < -0.05
    assert (
        crisis.weight_overrides["quality"] == 0.10 and crisis.weight_overrides["momentum"] <= -0.10
    )
    covid = detect_regime(nasi, date(2020, 4, 30), CONFIG)
    assert covid.trend == "Bear" and covid.volatility == "High-vol" and covid.risk == "Risk-off"
    assert (
        covid.evidence["vol_ratio"] > 1.25 and covid.measure.reason == "Bear / High-vol / Risk-off"
    )
    boom = detect_regime(nasi, date(2017, 12, 29), CONFIG)
    assert boom.trend == "Bull" and boom.risk == "Risk-on" and boom.measure.value == 1.0
    assert boom.weight_overrides.get("momentum") == 0.10
    gap = detect_regime(nasi, date(2025, 6, 30), CONFIG)
    assert gap.measure.status is MeasureStatus.UNAVAILABLE and gap.trend is None
    after_gap = detect_regime(nasi, date(2026, 9, 13), CONFIG)
    assert after_gap.measure.status is MeasureStatus.UNAVAILABLE
    # a young index uses everything it has once the minimum length is met
    adaptive = detect_regime(nasi, date(2009, 12, 31), CONFIG)
    assert adaptive.measure.is_known and adaptive.evidence["window_start"] == "2008-02-25"
    for key in (
        "price",
        "ma_200",
        "price_vs_ma",
        "return_6m",
        "vol_63d_annualised",
        "vol_reference_median",
        "vol_ratio",
        "window_start",
        "window_end",
    ):
        assert key in crisis.evidence
    strict = AnalyticsConfig(regime=RegimeConfig(trend_threshold=0.9))
    assert detect_regime(nasi, date(2017, 12, 29), strict).trend == "Sideways"


# --- jobs ------------------------------------------------------------------------------


@pytest.fixture
def populated(fixture_db_path: Path, tmp_path: Path) -> tuple[Settings, NseScraperSource]:
    settings = Settings(
        NSE_SCRAPER_DB_PATH=str(fixture_db_path),
        NSE_SCRAPER_PATH=str(tmp_path / "scraper"),
        ANALYTICS_DB_PATH=str(tmp_path / "a.sqlite3"),
    )
    upgrade_analytics_db(settings.analytics_db_path)
    source = NseScraperSource(settings)
    classify_instruments(settings, source)
    return settings, source


def test_montecarlo_and_scenario_jobs(populated: tuple[Settings, NseScraperSource]) -> None:
    settings, source = populated
    quick = AnalyticsConfig(montecarlo=MonteCarloConfig(n_paths=500))
    result = compute_montecarlo(
        settings, source, as_of=date(2019, 12, 31), tickers=["KCB", "SCOM", "^NASI"], config=quick
    )
    assert set(result.tickers_processed) == {"KCB", "SCOM"}  # the index is not a target
    assert result.rows_written == 16 and result.known_counts["bootstrap"] == 8
    with analytics_session(settings) as session:
        rows = load_simulations(session, as_of_date=date(2019, 12, 31), ticker_symbol="KCB")
        assert len(rows) == 8 and all(r.status == "known" and r.n_paths == 500 for r in rows)
        assert rows[0].scenario == "" and rows[0].p_return_above is not None
    again = compute_montecarlo(
        settings, source, as_of=date(2019, 12, 31), tickers=["KCB", "SCOM"], config=quick
    )
    assert again.rows_written == 16
    with analytics_session(settings) as session:
        assert len(load_simulations(session, as_of_date=date(2019, 12, 31))) == 16
    scen = compute_scenarios(settings, source, as_of=date(2019, 12, 31), tickers=["KCB", "SCOM"])
    assert scen.rows_written == 6 and scen.known_counts == {"bear": 2, "base": 2, "bull": 2}
    with analytics_session(settings) as session:
        rows = load_simulations(
            session, as_of_date=date(2019, 12, 31), ticker_symbol="KCB", method="scenario"
        )
        assert [r.scenario for r in rows] == ["base", "bear", "bull"]
        bear = next(r for r in rows if r.scenario == "bear")
        assert bear.price == 54.0 and bear.horizon_days == 252
        assumptions = bear.assumptions or {}
        assert assumptions["market_return"] == -0.25 and assumptions["beta_source"] == "default"
        assert assumptions["paths_used"] == ["beta"]  # no stored beta / P/E for the date
        assert bear.implied_price == pytest.approx(54.0 * 0.75)


def test_regime_job_over_2008_and_the_gap(populated: tuple[Settings, NseScraperSource]) -> None:
    settings, source = populated
    result = compute_regime(settings, source, start=date(2008, 1, 31), end=date(2009, 12, 31))
    assert result.index == "^NASI" and result.rows_written == 24
    with analytics_session(settings) as session:
        rows = load_regimes(session)
        by_date = {r.as_of_date: r for r in rows}
        assert len(by_date) == 24 and all(r.status in ("known", "zero") for r in rows)
        # NASI cannot cover 2008 (it starts 2008-02-25): those dates come from N20I
        assert by_date[date(2008, 1, 31)].index_symbol == "^N20I"
        assert by_date[date(2008, 1, 31)].trend == "Bear"
        late_2008 = [r for d, r in by_date.items() if date(2008, 10, 31) <= d <= date(2009, 3, 31)]
        assert len(late_2008) == 6
        assert all(r.trend == "Bear" and r.risk == "Risk-off" for r in late_2008)
        assert sum(r.volatility == "High-vol" for r in late_2008) >= 4
        assert all(r.evidence and r.weight_overrides for r in late_2008)
        assert by_date[date(2009, 12, 31)].index_symbol == "^NASI"  # old enough by then
        assert by_date[date(2009, 11, 30)].trend == "Bull"
    single = compute_regime(settings, source, as_of=date(2025, 6, 30))
    assert single.rows_written == 1 and single.labels == {"unavailable": 1}
    again = compute_regime(settings, source, start=date(2008, 1, 31), end=date(2009, 12, 31))
    assert again.rows_written == 24
    with analytics_session(settings) as session:
        assert len(load_regimes(session)) == 25


def test_cli_montecarlo_scenarios_regime(
    populated: tuple[Settings, NseScraperSource], monkeypatch: pytest.MonkeyPatch
) -> None:
    from typer.testing import CliRunner

    from app.cli.main import app
    from app.web.config import get_settings

    settings, _ = populated
    monkeypatch.setenv("ANALYTICS_DB_PATH", str(settings.analytics_db_path))
    monkeypatch.setenv("NSE_SCRAPER_DB_PATH", str(settings.scraper_database_path))
    monkeypatch.setenv("NSE_SCRAPER_PATH", str(settings.nse_scraper_path))
    get_settings.cache_clear()
    try:
        runner = CliRunner()
        mc = runner.invoke(
            app, ["analytics", "compute", "montecarlo", "--as-of", "2019-12-31", "--ticker", "KCB"]
        )
        assert mc.exit_code == 0, mc.output
        assert "block_bootstrap" in mc.output and "rows written 8" in mc.output
        sc = runner.invoke(
            app, ["analytics", "compute", "scenarios", "--as-of", "2019-12-31", "--ticker", "KCB"]
        )
        assert sc.exit_code == 0, sc.output
        assert "bear" in sc.output and "rows written 3" in sc.output
        rg = runner.invoke(app, ["analytics", "compute", "regime", "--as-of", "2020-04-30"])
        assert rg.exit_code == 0, rg.output
        assert "Bear / High-vol / Risk-off" in rg.output and "vol_ratio" in rg.output
    finally:
        get_settings.cache_clear()
