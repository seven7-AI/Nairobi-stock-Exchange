"""Portfolio engine: closed-form two-asset cases, validation, coverage, warnings, the job.

codegraph explore "analyse_portfolio validate_weights analyse_hypothetical_portfolio"
"""

from __future__ import annotations

from datetime import date
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from app.web.config import Settings
from app.web.db.analytics import analytics_session
from app.web.db.analytics.services.portfolio_analyses import load_portfolio_analyses
from app.web.services.analytics.classification.service import classify_instruments
from app.web.services.analytics.config import DEFAULT_CONFIG as CONFIG
from app.web.services.analytics.config import AnalyticsConfig, PortfolioConfig
from app.web.services.analytics.liquidity import compute_liquidity
from app.web.services.analytics.measure import MeasureStatus
from app.web.services.analytics.portfolio import (
    PortfolioInputs,
    WeightError,
    analyse_hypothetical_portfolio,
    analyse_portfolio,
    parse_weights,
    validate_weights,
)
from app.web.services.analytics.portfolio.engine import concentration, exposures
from app.web.services.analytics.store import upgrade_analytics_db
from app.web.services.market_data.sources import NseScraperSource

pytestmark = pytest.mark.unit


def _series(values: np.ndarray, start: str = "2020-01-01") -> pd.Series:
    return pd.Series(values, index=pd.bdate_range(start, periods=len(values)))


def two_assets(rho: float, n: int = 600, seed: int = 3) -> tuple[pd.Series, pd.Series]:
    rng = np.random.default_rng(seed)
    z = rng.normal(size=(n, 2))
    a = 0.0004 + 0.010 * z[:, 0]
    b = 0.0002 + 0.020 * (rho * z[:, 0] + np.sqrt(1 - rho**2) * z[:, 1])
    return _series(a), _series(b)


def test_two_asset_closed_form() -> None:
    a, b = two_assets(rho=0.3)
    inputs = PortfolioInputs(
        {"A": 0.6, "B": 0.4},
        {"A": a, "B": b},
        None,
        {"A": "banking", "B": "manufacturing"},
        {"A": "x", "B": "y"},
        {"A": 5e6, "B": 5e6},
    )
    out = analyse_portfolio(inputs, CONFIG)
    daily = 0.6 * a.to_numpy() + 0.4 * b.to_numpy()
    cov = np.cov(a.to_numpy(), b.to_numpy(), ddof=1)
    var = 0.36 * cov[0, 0] + 0.16 * cov[1, 1] + 2 * 0.24 * cov[0, 1]
    assert out.volatility.value == pytest.approx(np.sqrt(var * 252))
    assert out.expected_return.value == pytest.approx(daily.mean() * 252)
    assert out.sharpe.value == pytest.approx((daily.mean() * 252 - 0.12) / np.sqrt(var * 252))
    equity = np.cumprod(1 + daily)
    assert out.max_drawdown.value == pytest.approx(
        float((equity / np.maximum.accumulate(equity) - 1).min())
    )
    assert out.average_correlation.value == pytest.approx(np.corrcoef(a, b)[0, 1])
    assert out.correlation["A"]["B"] == pytest.approx(np.corrcoef(a, b)[0, 1]) and out.correlation[
        "A"
    ]["A"] == pytest.approx(1.0)
    assert out.beta.status is MeasureStatus.UNAVAILABLE  # no benchmark given
    assert out.coverage == 1.0 and out.hhi == pytest.approx(0.52)
    assert out.effective_positions == pytest.approx(1 / 0.52) and out.top_n_weight == 1.0
    assert out.sector_exposure == {"banking": 0.6, "manufacturing": 0.4}
    assert out.days_to_liquidate["A"] == pytest.approx(10e6 * 0.6 / (0.2 * 5e6))  # 6 days
    assert "A is 60% of the portfolio (limit 25%)" in out.warnings[0]
    assert out.inputs["observations"] == 600


def test_beta_against_benchmark_and_single_position() -> None:
    a, b = two_assets(rho=0.8)
    bench = b
    out = analyse_portfolio(
        PortfolioInputs({"A": 1.0}, {"A": a}, bench, {"A": "banking"}, {"A": None}, {}), CONFIG
    )
    expected_beta = np.cov(a, bench, ddof=1)[0, 1] / bench.var(ddof=1)
    assert out.beta.value == pytest.approx(expected_beta)
    assert out.average_correlation.status is MeasureStatus.NOT_APPLICABLE
    assert out.hhi == 1.0 and out.effective_positions == 1.0
    assert out.days_to_liquidate == {"A": None}
    assert any("A: no turnover data" in w for w in out.warnings)
    assert any("banking is 100%" in w for w in out.warnings)


def test_all_bank_portfolio_is_one_bet() -> None:
    rng = np.random.default_rng(9)
    common = rng.normal(size=500)
    banks = {
        t: _series(0.0003 + 0.015 * (0.9 * common + 0.436 * rng.normal(size=500)))
        for t in ("KCB", "EQTY", "ABSA", "NCBA", "SCBK")
    }
    weights = dict.fromkeys(banks, 0.2)
    out = analyse_portfolio(
        PortfolioInputs(
            weights, banks, None, dict.fromkeys(banks, "banking"), dict.fromkeys(banks, "Banks"), {}
        ),
        CONFIG,
    )
    assert out.sector_exposure == {"banking": pytest.approx(1.0)}
    assert out.hhi == pytest.approx(0.2) and out.effective_positions == pytest.approx(5.0)
    sector = next(w for w in out.warnings if w.startswith("banking is 100%"))
    assert "5 position(s)" in sector and "not 5 independent ones" in sector
    assert (out.average_correlation.value or 0) > 0.7
    assert any("positions move together" in w for w in out.warnings)
    assert not any(
        "HHI" in w for w in out.warnings
    )  # five equal weights are not concentrated by count


def test_missing_history_reports_partial_coverage() -> None:
    a, _ = two_assets(rho=0.0)
    short = _series(np.full(30, 0.001))
    out = analyse_portfolio(
        PortfolioInputs(
            {"A": 0.5, "B": 0.3, "C": 0.2},
            {"A": a, "B": short},
            None,
            {"A": "banking", "B": "tea", "C": None},
            {},
            {"A": 1e6},
        ),
        CONFIG,
    )
    assert out.coverage == pytest.approx(0.5)
    assert out.expected_return.status is MeasureStatus.UNAVAILABLE
    assert out.expected_return.reason == (
        "portfolio: 50% of the weight has enough history; missing B (30 obs), C (no series)"
    )
    assert out.volatility.status is MeasureStatus.UNAVAILABLE and out.correlation == {}
    assert out.sector_exposure == {"banking": 0.5, "tea": 0.3, "unclassified": 0.2}
    assert out.days_to_liquidate["A"] is not None and out.days_to_liquidate["C"] is None
    assert out.inputs["missing"] == ["B", "C"]


def test_weights_validation_and_parsing() -> None:
    assert validate_weights({"kcb ": 0.5, "EQTY": 0.5}, CONFIG) == {"KCB": 0.5, "EQTY": 0.5}
    with pytest.raises(WeightError, match=r"sum to 0\.9000"):
        validate_weights({"A": 0.5, "B": 0.4}, CONFIG)
    with pytest.raises(WeightError, match="positive"):
        validate_weights({"A": 1.2, "B": -0.2}, CONFIG)
    with pytest.raises(WeightError, match="appears twice"):
        validate_weights({"a": 0.5, "A": 0.5}, CONFIG)
    with pytest.raises(WeightError, match="no weights"):
        validate_weights({}, CONFIG)
    loose = AnalyticsConfig(portfolio=PortfolioConfig(weight_tolerance=0.05))
    assert validate_weights({"A": 0.52, "B": 0.5}, loose)["A"] == 0.52
    assert parse_weights("KCB=0.2, eqty=0.8") == {"KCB": 0.2, "EQTY": 0.8}
    with pytest.raises(WeightError, match="TICKER=WEIGHT"):
        parse_weights("KCB:0.2")
    with pytest.raises(WeightError, match="not a number"):
        parse_weights("KCB=lots")
    assert concentration({"A": 0.5, "B": 0.3, "C": 0.2}, 2) == (
        pytest.approx(0.38),
        pytest.approx(1 / 0.38),
        0.8,
    )
    assert exposures({"A": 0.5, "B": 0.5}, {"A": "x"}) == {"x": 0.5, "unclassified": 0.5}


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
    compute_liquidity(settings, source, as_of=date(2019, 12, 31))
    return settings, source


def test_portfolio_job_on_real_prices(populated: tuple[Settings, NseScraperSource]) -> None:
    settings, source = populated
    result = analyse_hypothetical_portfolio(
        settings,
        source,
        {"KCB": 0.4, "EQTY": 0.3, "SCOM": 0.3},
        name="banks-and-safaricom",
        as_of=date(2019, 12, 31),
    )
    a = result.analysis
    assert a.coverage == 1.0 and a.expected_return.is_known and a.volatility.is_known
    assert a.beta.is_known and 0.0 < (a.beta.value or 0) < 2.0  # against ^NASI
    assert a.sector_exposure == {
        "banking": pytest.approx(0.7),
        "telecommunication": pytest.approx(0.3),
    }
    assert any(w.startswith("banking is 70%") for w in a.warnings)
    assert any(w.startswith("KCB is 40%") for w in a.warnings)
    assert a.days_to_liquidate["SCOM"] is not None and a.days_to_liquidate["KCB"] is not None
    assert a.inputs["end"] == "2019-12-31" and a.inputs["observations"] >= 600
    with analytics_session(settings) as session:
        rows = load_portfolio_analyses(session, name="banks-and-safaricom")
        assert len(rows) == 1 and rows[0].id == result.row_id
        assert rows[0].metrics["volatility"]["status"] == "known"
        assert rows[0].weights == {"KCB": 0.4, "EQTY": 0.3, "SCOM": 0.3}
        assert rows[0].notional == 10_000_000.0
    # a delisted stock with too little history in the window is named, not dropped
    partial = analyse_hypothetical_portfolio(
        settings, source, {"KCB": 0.5, "KENO": 0.5}, name="partial", as_of=date(2024, 12, 31)
    )
    assert partial.analysis.coverage == 0.5
    assert "missing KENO" in (partial.analysis.expected_return.reason or "")
    with pytest.raises(WeightError):
        analyse_hypothetical_portfolio(settings, source, {"KCB": 0.5}, as_of=date(2019, 12, 31))


def test_cli_portfolio_analyse(
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
        ok = runner.invoke(
            app,
            [
                "analytics",
                "portfolio",
                "analyse",
                "--weights",
                "KCB=0.5,EQTY=0.5",
                "--as-of",
                "2019-12-31",
            ],
        )
        assert ok.exit_code == 0, ok.output
        assert "banking is 100%" in ok.output and "volatility" in ok.output
        bad = runner.invoke(
            app,
            ["analytics", "portfolio", "analyse", "--weights", "KCB=0.5", "--as-of", "2019-12-31"],
        )
        assert bad.exit_code != 0 and "sum to 0.5000" in bad.output
    finally:
        get_settings.cache_clear()
