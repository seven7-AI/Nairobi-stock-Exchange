"""Forecast baselines, distributions, evaluation math, and the jobs on real prices.

codegraph explore "forecast_returns ar1_horizon evaluate_forecast walk_forward"
"""

from __future__ import annotations

from datetime import date
from pathlib import Path

import numpy as np
import pandas as pd
import pytest
from scipy.stats import norm
from sqlalchemy import select

from app.web.config import Settings
from app.web.db.analytics import analytics_session
from app.web.db.analytics.models import ForecastEvaluation, ModelRegistryEntry
from app.web.db.analytics.services.forecasts import load_evaluations, load_forecasts
from app.web.services.analytics.classification.service import classify_instruments
from app.web.services.analytics.config import DEFAULT_CONFIG as CONFIG
from app.web.services.analytics.config import AnalyticsConfig, ForecastConfig
from app.web.services.analytics.forecasting import (
    compute_forecasts,
    evaluate_forecasts,
    forecast_returns,
    monthly_series,
    walk_forward,
)
from app.web.services.analytics.forecasting.engine import (
    Forecast,
    ar1_fit,
    ar1_horizon,
    beats_baselines,
    evaluate_forecast,
    ewma_estimate,
    horizon_distribution,
    mean_estimate,
    naive_estimate,
    p_first_passage,
    realised_return,
    shift_forward,
    summarise,
)
from app.web.services.analytics.measure import Measure, MeasureStatus, Provenance
from app.web.services.analytics.returns.service import load_universe
from app.web.services.analytics.store import upgrade_analytics_db
from app.web.services.market_data.sources import NseScraperSource

pytestmark = pytest.mark.unit

PROV = Provenance(table="t")


def test_shift_forward_clamps_to_month_end() -> None:
    assert shift_forward(date(2019, 1, 31), 1) == date(2019, 2, 28)
    assert shift_forward(date(2019, 12, 31), 3) == date(2020, 3, 31)
    assert shift_forward(date(2024, 2, 29), 12) == date(2025, 2, 28)


def test_naive_mean_and_ewma_by_hand() -> None:
    r = pd.Series(
        [0.01, -0.02, 0.03, 0.00, 0.02], index=pd.date_range("2020-01-31", periods=5, freq="ME")
    )
    mean, sd, inputs = naive_estimate(r, 4, CONFIG)
    assert mean == 0.0 and sd == pytest.approx(float(r.std(ddof=1)) * 2.0)
    mean, sd, inputs = mean_estimate(r, 3, CONFIG)
    assert mean == pytest.approx(0.008 * 3) and sd == pytest.approx(
        float(r.std(ddof=1)) * np.sqrt(3)
    )
    assert inputs["months_used"] == 5
    mean, sd, inputs = ewma_estimate(r, 1, CONFIG)
    assert mean == pytest.approx(float(r.ewm(halflife=12.0).mean().iloc[-1]))
    assert inputs["halflife_months"] == 12.0
    short = AnalyticsConfig(forecast=ForecastConfig(lookback_months=12))
    long = pd.Series(
        np.r_[np.full(24, 0.05), np.full(12, -0.01)],
        index=pd.date_range("2018-01-31", periods=36, freq="ME"),
    )
    assert mean_estimate(long, 1, short)[0] == pytest.approx(-0.01)  # only the last 12 months


def test_ar1_recovers_parameters_and_horizon_moments() -> None:
    rng = np.random.default_rng(7)
    c, phi, sigma = 0.01, 0.5, 0.02
    values = [0.0]
    for _ in range(4000):
        values.append(c + phi * values[-1] + rng.normal(0.0, sigma))
    c_hat, phi_hat, sigma_hat = ar1_fit(values)
    assert phi_hat == pytest.approx(phi, abs=0.04)
    assert c_hat == pytest.approx(c, abs=0.003)
    assert sigma_hat == pytest.approx(sigma, rel=0.05)
    # two steps ahead by hand from last = 0.03
    last = 0.03
    step1 = c + phi * last
    step2 = c + phi * step1
    mean, sd = ar1_horizon(c, phi, sigma, last, 2)
    assert mean == pytest.approx(step1 + step2)
    assert sd == pytest.approx(sigma * np.sqrt((1 + phi) ** 2 + 1))
    # phi = 0 is the mean model with an innovation sd
    mean0, sd0 = ar1_horizon(0.02, 0.0, 0.1, 5.0, 3)
    assert mean0 == pytest.approx(0.06) and sd0 == pytest.approx(0.1 * np.sqrt(3))
    assert ar1_fit([0.01, 0.01, 0.01]) == (0.01, 0.0, 0.0)  # no dispersion


def test_first_passage_probability() -> None:
    # zero drift: P(hit barrier a) = 2 Phi(a / sd)
    a = float(np.log1p(-0.2))
    assert p_first_passage(0.0, 0.3, 0.2) == pytest.approx(2 * norm.cdf(a / 0.3))
    assert p_first_passage(0.5, 0.01, 0.2) == pytest.approx(0.0, abs=1e-9)
    assert p_first_passage(-1.0, 0.01, 0.2) == pytest.approx(1.0, abs=1e-9)
    assert p_first_passage(-1.0, 0.0, 0.2) == 1.0 and p_first_passage(0.1, 0.0, 0.2) == 0.0
    # more drawdown probability with more volatility, less with more drift
    assert p_first_passage(0.0, 0.4, 0.2) > p_first_passage(0.0, 0.2, 0.2)
    assert p_first_passage(0.1, 0.3, 0.2) < p_first_passage(0.0, 0.3, 0.2)


def test_horizon_distribution_by_hand() -> None:
    f = horizon_distribution(
        "X",
        "mean",
        3,
        0.05,
        0.10,
        benchmark=(0.02, 0.08, 0.5),
        inputs={"k": 1},
        config=CONFIG,
        provenance=PROV,
    )
    assert f.measure.value == pytest.approx(np.expm1(0.05 + 0.5 * 0.01))
    assert f.quantiles["q50"] == pytest.approx(np.expm1(0.05))
    assert f.quantiles["q05"] == pytest.approx(np.expm1(0.05 - 0.10 * 1.6448536), abs=1e-6)
    assert f.quantiles["q95"] == pytest.approx(np.expm1(0.05 + 0.10 * 1.6448536), abs=1e-6)
    assert f.p_positive == pytest.approx(1 - norm.cdf(-0.5))
    rel_sd = np.sqrt(0.01 + 0.0064 - 2 * 0.5 * 0.10 * 0.08)
    assert f.p_outperform == pytest.approx(1 - norm.cdf(-0.03 / rel_sd))
    assert f.expected_vol == 0.10 and f.p_drawdown == pytest.approx(
        p_first_passage(0.05, 0.10, 0.2)
    )
    assert f.inputs == {"k": 1}
    no_bench = horizon_distribution(
        "X", "mean", 1, 0.0, 0.1, benchmark=None, inputs={}, config=CONFIG, provenance=PROV
    )
    assert no_bench.p_outperform is None and no_bench.measure.status is MeasureStatus.KNOWN
    flat = horizon_distribution(
        "X", "mean", 1, 0.0, 0.0, benchmark=None, inputs={}, config=CONFIG, provenance=PROV
    )
    assert flat.measure.status is MeasureStatus.UNAVAILABLE


def test_evaluation_math_and_summary() -> None:
    f = Forecast(
        "X",
        1,
        "mean",
        Measure.known(0.05),
        quantiles={"q05": -0.10, "q95": 0.20},
        p_positive=0.7,
        p_outperform=0.4,
    )
    e = evaluate_forecast(f, 0.08, 0.10, date(2020, 1, 31))
    assert e.error == pytest.approx(0.03) and e.directional_hit is True
    assert e.benchmark_hit is True  # predicted underperformance (0.4) and it underperformed
    assert e.within_interval is True
    miss = evaluate_forecast(f, -0.30, None, date(2020, 1, 31))
    assert (
        miss.directional_hit is False
        and miss.benchmark_hit is None
        and miss.within_interval is False
    )
    summary = summarise([e, miss])
    assert summary["n"] == 2
    assert summary["mae"] == pytest.approx((0.03 + 0.35) / 2)
    assert summary["rmse"] == pytest.approx(np.sqrt((0.03**2 + 0.35**2) / 2))
    assert summary["directional_accuracy"] == 0.5 and summary["benchmark_hit_rate"] == 1.0
    assert summary["interval_coverage"] == 0.5
    assert summarise([])["n"] == 0 and summarise([])["mae"] is None


def test_candidate_gate() -> None:
    baselines = [
        {"mae": 0.10, "directional_accuracy": 0.55},
        {"mae": 0.12, "directional_accuracy": 0.60},
    ]
    assert beats_baselines({"mae": 0.09, "directional_accuracy": 0.60}, baselines, margin=0.0)
    assert not beats_baselines(
        {"mae": 0.09, "directional_accuracy": 0.58}, baselines, margin=0.0
    )  # worse hit rate
    assert not beats_baselines(
        {"mae": 0.095, "directional_accuracy": 0.65}, baselines, margin=0.10
    )  # not by 10%
    assert not beats_baselines({"mae": None}, baselines, margin=0.0)
    assert not beats_baselines({"mae": 0.01, "directional_accuracy": 1.0}, [], margin=0.0)


# --- on real prices (fixture) ---------------------------------------------------------


@pytest.fixture
def fixture_universe(fixture_settings: Settings, fixture_source: NseScraperSource) -> dict:
    return load_universe(fixture_source, CONFIG)


def test_monthly_series_is_point_in_time_and_gap_aware(fixture_universe: dict) -> None:
    kcb = fixture_universe["KCB"]
    m = monthly_series(kcb, date(2019, 12, 31), CONFIG)
    assert not isinstance(m, Measure)
    assert m.origin == date(2019, 12, 31) and float(m.closes.iloc[-1]) == 54.0
    assert m.closes.index[0].date() >= date(2007, 1, 1) and m.months >= 150
    assert m.log_returns.iloc[-1] == pytest.approx(np.log(54.0 / 50.0))  # Dec 2019 vs 2019-11-29
    mid_month = monthly_series(kcb, date(2019, 6, 14), CONFIG)
    assert not isinstance(mid_month, Measure) and mid_month.closes.index[-1].date() <= date(
        2019, 6, 14
    )
    stale = monthly_series(kcb, date(2025, 6, 30), CONFIG)
    assert isinstance(stale, Measure) and "days before 2025-06-30" in (stale.reason or "")
    scraper_era = monthly_series(kcb, date(2026, 9, 13), CONFIG)
    assert (
        not isinstance(scraper_era, Measure) and scraper_era.months < 4
    )  # the segment after the gap only
    forecasts = forecast_returns(scraper_era, None, CONFIG, ticker="KCB")
    assert len(forecasts) == 16 and all(
        f.measure.status is MeasureStatus.UNAVAILABLE for f in forecasts
    )
    assert "contiguous monthly returns, minimum 36" in (forecasts[0].measure.reason or "")


def test_forecast_returns_on_kcb(fixture_universe: dict) -> None:
    kcb = monthly_series(fixture_universe["KCB"], date(2019, 12, 31), CONFIG)
    nasi = monthly_series(fixture_universe["^NASI"], date(2019, 12, 31), CONFIG)
    out = {
        (f.model, f.horizon_months): f for f in forecast_returns(kcb, nasi, CONFIG, ticker="KCB")
    }
    assert set(out) == {(m, h) for m in ("naive", "mean", "ewma", "ar1") for h in (1, 3, 6, 12)}
    naive = out[("naive", 12)]
    assert naive.mean_log == 0.0 and naive.p_positive == pytest.approx(0.5)
    assert naive.sd_log == pytest.approx((out[("naive", 3)].sd_log or 0.0) * 2.0)  # sqrt(12/3)
    assert naive.p_outperform is not None and naive.inputs["benchmark_correlation"] is not None
    mean12 = out[("mean", 12)]
    assert (
        mean12.measure.is_known
        and mean12.quantiles["q05"] < mean12.quantiles["q50"] < mean12.quantiles["q95"]
    )
    assert 0.0 < (mean12.p_drawdown or 0.0) < 1.0
    ar1 = out[("ar1", 1)]
    assert abs(ar1.inputs["phi_used"]) <= 0.95 and ar1.inputs["months_used"] == 60
    for f in out.values():
        assert f.measure.provenance[0].end == date(2019, 12, 31)


def test_realised_return_rules(fixture_universe: dict) -> None:
    kcb = fixture_universe["KCB"]
    realised = realised_return(kcb, date(2018, 12, 31), 12, CONFIG)
    assert not isinstance(realised, Measure)
    assert realised == (pytest.approx(54.0 / 37.45 - 1.0), date(2019, 12, 31))
    into_gap = realised_return(kcb, date(2024, 12, 31), 12, CONFIG)
    assert isinstance(into_gap, Measure)
    assert into_gap.reason == "realised: last observation 2024-12-31 is 365 days before 2025-12-31"
    crossing = realised_return(kcb, date(2024, 12, 31), 20, CONFIG)  # lands in the scraper era
    assert isinstance(crossing, Measure) and "crosses a data gap" in (crossing.reason or "")
    future = realised_return(kcb.as_of(date(2019, 6, 30)), date(2019, 3, 29), 12, CONFIG)
    assert isinstance(future, Measure) and "has not elapsed" in (future.reason or "")
    assert isinstance(realised_return(kcb, date(2006, 1, 1), 1, CONFIG), Measure)


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


def test_compute_then_evaluate_only_when_elapsed(
    populated: tuple[Settings, NseScraperSource],
) -> None:
    settings, source = populated
    result = compute_forecasts(settings, source, as_of=date(2019, 12, 31))
    assert "^NASI" not in result.tickers and "KCB" in result.tickers and "SCOM" in result.tickers
    assert result.known_counts["ar1"] >= 4 and result.rows_written == len(result.tickers) * 16
    with analytics_session(settings) as session:
        rows = load_forecasts(session, as_of_date=date(2019, 12, 31), ticker_symbol="KCB")
        assert len(rows) == 16 and all(r.status == "known" for r in rows)
        assert rows[0].benchmark == "^NASI" and rows[0].drawdown_threshold == 0.2
        names = {m.name: m.status for m in session.execute(select(ModelRegistryEntry)).scalars()}
        assert names == {"naive": "active", "mean": "active", "ewma": "active", "ar1": "active"}
    early = evaluate_forecasts(settings, source, as_of=date(2020, 4, 15))
    assert early.evaluated > 0 and early.pending > 0  # 1m and 3m have elapsed, 6m and 12m have not
    with analytics_session(settings) as session:
        done = load_evaluations(session)
        assert {f.horizon_months for f, _ in done} == {1, 3}
        kcb_1m = next(
            e
            for f, e in done
            if f.ticker_symbol == "KCB" and f.horizon_months == 1 and f.model == "naive"
        )
        assert kcb_1m.realised_end_date == date(2020, 1, 31)
    later = evaluate_forecasts(settings, source, as_of=date(2021, 1, 31))
    assert later.pending == 0
    with analytics_session(settings) as session:
        done = load_evaluations(session)
        assert {f.horizon_months for f, _ in done} == {1, 3, 6, 12}
        assert len(done) == len({e.forecast_id for _, e in done})  # one evaluation per forecast
        count_before = session.execute(select(ForecastEvaluation)).scalars().all()
    again = evaluate_forecasts(settings, source, as_of=date(2021, 1, 31))
    assert again.evaluated == 0 and again.pending == 0
    with analytics_session(settings) as session:
        assert len(session.execute(select(ForecastEvaluation)).scalars().all()) == len(count_before)
    assert (
        later.summary["naive"]["12m"]["n"] >= 4 and later.summary["mean"]["1m"]["mae"] is not None
    )


def test_walk_forward_scores_the_baselines(populated: tuple[Settings, NseScraperSource]) -> None:
    settings, source = populated
    quarterly = AnalyticsConfig(forecast=ForecastConfig(walk_forward_step_months=3))
    result = walk_forward(
        settings,
        source,
        tickers=["KCB", "EQTY"],
        start=date(2016, 1, 31),
        end=date(2019, 12, 31),
        config=quarterly,
    )
    assert result.evaluated > 0 and result.admitted == ()
    for model in ("naive", "mean", "ewma", "ar1"):
        assert result.summary[model]["1m"]["n"] >= 20
        assert (
            result.summary[model]["12m"]["n"] >= 8
        )  # origins up to 2018-12 have elapsed by 2019-12
        assert 0.0 <= result.summary[model]["1m"]["interval_coverage"] <= 1.0
    with analytics_session(settings) as session:
        origins = {f.as_of_date for f in load_forecasts(session, ticker_symbol="KCB")}
        assert date(2016, 1, 31) in origins and date(2019, 10, 31) in origins and len(origins) == 16
        registry = {m.name: m for m in session.execute(select(ModelRegistryEntry)).scalars()}
        assert (registry["ar1"].performance or {})["1m"]["n"] == result.summary["ar1"]["1m"]["n"]
        # a forecast made at an origin only saw prices up to that origin
        early = load_forecasts(
            session, as_of_date=date(2016, 1, 31), ticker_symbol="KCB", model="mean"
        )
        assert all((f.provenance or [{}])[0].get("end") == "2016-01-31" for f in early)


def test_candidate_without_estimator_is_unavailable_and_never_admitted(
    populated: tuple[Settings, NseScraperSource],
) -> None:
    settings, source = populated
    config = AnalyticsConfig(forecast=ForecastConfig(candidate_models=("gbm",)))
    result = compute_forecasts(
        settings, source, as_of=date(2019, 12, 31), tickers=["KCB"], config=config
    )
    assert "gbm" not in result.known_counts
    with analytics_session(settings) as session:
        gbm = load_forecasts(session, ticker_symbol="KCB", model="gbm")
        assert len(gbm) == 4 and all(r.status == "unavailable" for r in gbm)
        assert "no estimator registered" in (gbm[0].reason or "")
        entry = session.execute(
            select(ModelRegistryEntry).where(ModelRegistryEntry.name == "gbm")
        ).scalar_one()
        assert entry.status == "candidate"
    evaluate_forecasts(settings, source, as_of=date(2021, 1, 31), config=config)
    with analytics_session(settings) as session:
        entry = session.execute(
            select(ModelRegistryEntry).where(ModelRegistryEntry.name == "gbm")
        ).scalar_one()
        assert entry.status == "candidate"  # nothing to judge: stays out


def test_cli_forecast_commands(
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
        computed = runner.invoke(
            app, ["analytics", "compute", "forecasts", "--as-of", "2019-12-31", "--ticker", "KCB"]
        )
        assert computed.exit_code == 0, computed.output
        assert "ar1" in computed.output and "rows written 16" in computed.output
        evaluated = runner.invoke(
            app, ["analytics", "forecast", "evaluate", "--as-of", "2021-01-31"]
        )
        assert evaluated.exit_code == 0, evaluated.output
        assert "admitted candidates: none" in evaluated.output and "pending 0" in evaluated.output
        wf = runner.invoke(
            app,
            [
                "analytics",
                "forecast",
                "walk-forward",
                "--ticker",
                "SCOM",
                "--from",
                "2019-01-31",
                "--to",
                "2019-06-28",
            ],
        )
        assert wf.exit_code == 0, wf.output
        assert "out-of-sample summary" in wf.output
    finally:
        get_settings.cache_clear()
