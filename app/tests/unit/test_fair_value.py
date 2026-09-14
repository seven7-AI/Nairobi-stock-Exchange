"""Fair-value engine: each method by hand, applicability, blending, uncertainty, the job.

codegraph explore "value_stock dcf_value justified_pb_value compute_fair_value"
"""

from __future__ import annotations

from datetime import date
from pathlib import Path

import pytest

from app.web.config import Settings
from app.web.db.analytics import analytics_session
from app.web.db.analytics.services.valuations import load_valuations
from app.web.services.analytics.classification.service import classify_instruments
from app.web.services.analytics.config import DEFAULT_CONFIG as CONFIG
from app.web.services.analytics.config import AnalyticsConfig, FairValueConfig, MarketConfig
from app.web.services.analytics.fair_value import ValuationInputs, compute_fair_value, value_stock
from app.web.services.analytics.fair_value.engine import (
    cost_of_equity,
    dcf_value,
    ddm_value,
    justified_pb_value,
    multiple_value,
)
from app.web.services.analytics.fair_value.service import peer_median
from app.web.services.analytics.fundamentals import compute_fundamentals
from app.web.services.analytics.liquidity import compute_liquidity
from app.web.services.analytics.measure import MeasureStatus
from app.web.services.analytics.returns import compute_returns
from app.web.services.analytics.risk import compute_risk
from app.web.services.analytics.store import upgrade_analytics_db
from app.web.services.analytics.valuation_metrics import compute_valuation_metrics
from app.web.services.market_data.sources import NseScraperSource

pytestmark = pytest.mark.unit


def bank(**overrides: object) -> ValuationInputs:
    base = {
        "ticker_symbol": "BNK",
        "sector_code": "banking",
        "price": 120.0,
        "fiscal_years": 4,
        "bvps": 100.0,
        "roe": 0.25,
        "payout_ratio": 0.40,
        "dps": 5.0,
        "dividend_cagr_3y": 0.20,
        "liquidity_score": 80.0,
        "beta": 1.0,
    }
    base.update(overrides)
    return ValuationInputs(**base)  # type: ignore[arg-type]


def industrial(**overrides: object) -> ValuationInputs:
    base = {
        "ticker_symbol": "IND",
        "sector_code": "manufacturing",
        "price": 80.0,
        "fiscal_years": 4,
        "eps": 10.0,
        "ebitda_per_share": 20.0,
        "net_debt_per_share": 30.0,
        "fcf_history": (10.0, 12.0, 14.0),
        "revenue_cagr_3y": 0.10,
        "peer_pe": 8.0,
        "peer_pe_source": "sector median",
        "peer_ev_ebitda": 6.0,
        "peer_ev_ebitda_source": "sector median",
        "liquidity_score": 80.0,
        "beta": 1.0,
        "debt_to_equity": 0.5,
        "interest_coverage": 6.0,
    }
    base.update(overrides)
    return ValuationInputs(**base)  # type: ignore[arg-type]


def test_cost_of_equity_capm_with_clamped_beta() -> None:
    rate, assumptions = cost_of_equity(None, CONFIG)
    assert rate == pytest.approx(0.19) and assumptions["beta_source"] == "default"
    assert cost_of_equity(0.6394, CONFIG)[0] == pytest.approx(0.12 + 0.6394 * 0.07)
    assert cost_of_equity(3.0, CONFIG)[0] == pytest.approx(0.12 + 1.5 * 0.07)
    assert cost_of_equity(0.1, CONFIG)[0] == pytest.approx(0.12 + 0.5 * 0.07)


def test_justified_pb_by_hand() -> None:
    # retention 0.6 x ROE 0.25 = 0.15, capped at 10%; r = 19%
    out = justified_pb_value(bank(), CONFIG)
    assert out.base == pytest.approx((0.25 - 0.10) / (0.19 - 0.10) * 100)  # 166.67
    assert out.bear == pytest.approx((0.2125 - 0.10) / (0.20 - 0.10) * 100)  # 112.5
    assert out.bull == pytest.approx((0.275 - 0.10) / (0.18 - 0.10) * 100)  # 218.75
    assert out.assumptions["sustainable_growth"] == 0.10 and out.assumptions["retention"] == 0.6
    assert (
        justified_pb_value(bank(roe=-0.05), CONFIG).measure.status is MeasureStatus.NOT_MEANINGFUL
    )
    assert (
        justified_pb_value(bank(bvps=-3.0), CONFIG).measure.status is MeasureStatus.NOT_MEANINGFUL
    )
    missing = justified_pb_value(bank(bvps=None, roe=None), CONFIG)
    assert missing.measure.status is MeasureStatus.UNAVAILABLE
    assert missing.measure.reason == "justified P/B: missing book value per share, ROE"
    # no payout known -> 50% retention assumed and said so
    assert (
        justified_pb_value(bank(payout_ratio=None), CONFIG).assumptions["retention_source"]
        == "default 50%"
    )
    cheap_money = AnalyticsConfig(
        market=MarketConfig(risk_free_rate=0.05),
        fair_value=FairValueConfig(equity_risk_premium=0.0),
    )
    assert justified_pb_value(bank(), cheap_money).measure.status is MeasureStatus.NOT_MEANINGFUL


def test_dividend_discount_by_hand() -> None:
    out = ddm_value(bank(), CONFIG)  # growth capped at 10%
    assert out.base == pytest.approx(5.0 * 1.10 / 0.09)  # 61.11
    assert out.bear == pytest.approx(5.0 * 1.08 / 0.12)  # 45.0
    assert out.bull == pytest.approx(5.0 * 1.10 / 0.08)  # 68.75
    assert out.assumptions["growth_source"] == "dividend 3y CAGR (clamped)"
    retention = ddm_value(bank(dividend_cagr_3y=None), CONFIG)
    assert (
        retention.assumptions["growth"] == 0.10
        and "retention" in retention.assumptions["growth_source"]
    )
    flat = ddm_value(bank(dividend_cagr_3y=None, roe=None), CONFIG)
    assert flat.base == pytest.approx(5.0 / 0.19) and flat.assumptions["growth"] == 0.0
    assert ddm_value(bank(dps=0.0), CONFIG).measure.status is MeasureStatus.NOT_MEANINGFUL
    assert ddm_value(bank(dps=None), CONFIG).measure.status is MeasureStatus.UNAVAILABLE


def test_dcf_by_hand() -> None:
    out = dcf_value(industrial(), CONFIG)  # base FCF 12, growth 10%, r 19%, terminal 5%
    assert out.base == pytest.approx(108.4233, abs=1e-3)
    assert out.bear == pytest.approx(78.2071, abs=1e-3)
    assert out.bull == pytest.approx(148.7693, abs=1e-3)
    assert (
        out.assumptions["fcf_years_averaged"] == 3 and out.assumptions["fcf_per_share_base"] == 12.0
    )
    negative = dcf_value(industrial(fcf_history=(5.0, -20.0, 3.0)), CONFIG)
    assert negative.measure.status is MeasureStatus.NOT_MEANINGFUL
    assert "not positive" in (negative.measure.reason or "")
    assert dcf_value(industrial(fcf_history=()), CONFIG).measure.status is MeasureStatus.UNAVAILABLE
    clamped = dcf_value(industrial(revenue_cagr_3y=0.60), CONFIG)
    assert clamped.assumptions["growth"] == 0.15


def test_relative_multiples_by_hand() -> None:
    ev = multiple_value(
        "ev_ebitda",
        "ebitda_per_share",
        20.0,
        6.0,
        "sector median",
        industrial(),
        CONFIG,
        subtract_net_debt=True,
    )
    assert (ev.bear, ev.base, ev.bull) == (
        pytest.approx(66.0),
        pytest.approx(90.0),
        pytest.approx(114.0),
    )
    pe = multiple_value(
        "pe_relative",
        "eps",
        10.0,
        8.0,
        "market median",
        industrial(),
        CONFIG,
        subtract_net_debt=False,
    )
    assert (pe.bear, pe.base, pe.bull) == (
        pytest.approx(64.0),
        pytest.approx(80.0),
        pytest.approx(96.0),
    )
    assert pe.assumptions["multiple_source"] == "market median"
    loss = multiple_value(
        "pe_relative", "eps", -2.0, 8.0, "x", industrial(), CONFIG, subtract_net_debt=False
    )
    assert loss.measure.status is MeasureStatus.NOT_MEANINGFUL
    no_peers = multiple_value(
        "pe_relative", "eps", 10.0, None, None, industrial(), CONFIG, subtract_net_debt=False
    )
    assert no_peers.measure.status is MeasureStatus.UNAVAILABLE and "peer median" in (
        no_peers.measure.reason or ""
    )
    drowned = multiple_value(
        "ev_ebitda",
        "ebitda_per_share",
        20.0,
        6.0,
        "x",
        industrial(net_debt_per_share=500.0),
        CONFIG,
        subtract_net_debt=True,
    )
    assert drowned.measure.status is MeasureStatus.NOT_MEANINGFUL


def test_value_stock_blends_and_measures_margin() -> None:
    out = value_stock(industrial(), CONFIG)
    assert [m.method for m in out.methods] == ["dcf", "ev_ebitda", "pe_relative"]
    intrinsic = (108.4233 + 90.0 + 80.0) / 3
    assert out.intrinsic.value == pytest.approx(intrinsic, abs=1e-3)
    assert out.fair_low == pytest.approx((78.2071 + 66.0 + 64.0) / 3, abs=1e-3)
    assert out.fair_high == pytest.approx((148.7693 + 114.0 + 96.0) / 3, abs=1e-3)
    assert out.upside.value == pytest.approx(intrinsic / 80.0 - 1.0, abs=1e-4)
    assert out.margin_of_safety.value == pytest.approx((intrinsic - 80.0) / intrinsic, abs=1e-4)
    assert out.uncertainty == pytest.approx(0.10) and out.actionable is True
    assert out.assumptions["methods_used"] == ["dcf", "ev_ebitda", "pe_relative"]
    financial = value_stock(bank(), CONFIG)
    assert [m.method for m in financial.methods] == ["pb_roe", "ddm"]
    assert financial.intrinsic.value == pytest.approx((166.6667 + 61.1111) / 2, abs=1e-3)
    assert "methods disagree" in financial.uncertainty_flags  # 166 vs 61 on a 114 blend


def test_not_applicable_and_unavailable() -> None:
    for sector in ("indices", "etf", "reit", None):
        out = value_stock(industrial(sector_code=sector), CONFIG)
        assert out.methods == () and out.intrinsic.status is MeasureStatus.NOT_APPLICABLE
        assert out.margin_of_safety.status is MeasureStatus.NOT_APPLICABLE
    empty = value_stock(bank(bvps=None, roe=None, dps=None), CONFIG)
    assert empty.intrinsic.status is MeasureStatus.UNAVAILABLE
    assert "pb_roe: justified P/B: missing" in (empty.intrinsic.reason or "")
    assert "ddm: dividend discount: missing" in (empty.intrinsic.reason or "")
    assert empty.uncertainty is None and empty.actionable is None
    no_price = value_stock(industrial(price=None, price_reason="price: stale"), CONFIG)
    assert no_price.intrinsic.is_known and no_price.upside.status is MeasureStatus.UNAVAILABLE
    assert no_price.margin_of_safety.reason == "price: stale"


def test_margin_of_safety_is_not_a_signal_under_uncertainty() -> None:
    shaky = value_stock(
        industrial(
            fiscal_years=2,
            ebitda_per_share=None,
            eps=None,
            liquidity_score=10.0,
            roe_trend=-1.0,
            beta=None,
        ),
        CONFIG,
    )
    # single method (DCF only) + thin history + deteriorating + illiquid + no beta
    assert shaky.uncertainty == pytest.approx(0.10 + 0.20 + 0.15 + 0.15 + 0.15 + 0.05)
    assert shaky.actionable is False
    assert shaky.margin_of_safety.is_known  # the number is still reported, just flagged
    assert set(shaky.uncertainty_flags) == {
        "single method",
        "2 fiscal year(s) of statements",
        "deteriorating ROE or margins",
        "thin or unknown liquidity",
        "no beta: default used",
    }
    levered = value_stock(industrial(debt_to_equity=2.5), CONFIG)
    assert "balance-sheet risk" in levered.uncertainty_flags
    bank_leverage_not_judged = value_stock(bank(debt_to_equity=8.0), CONFIG)
    assert "balance-sheet risk" not in bank_leverage_not_judged.uncertainty_flags
    capped = value_stock(
        industrial(
            fiscal_years=1,
            liquidity_score=None,
            beta=None,
            roe_trend=-1.0,
            debt_to_equity=5.0,
            ebitda_per_share=None,
            eps=None,
        ),
        CONFIG,
    )
    assert capped.uncertainty == 0.95


def test_peer_median_rule() -> None:
    values = {"A": 5.0, "B": 8.0, "C": -3.0, "D": 12.0}
    assert peer_median(values, ["A", "B", "C", "D"], min_members=3) == 8.0
    assert peer_median(values, ["A", "B", "C"], min_members=3) is None  # C is not positive
    assert peer_median(values, ["A", "Z"], min_members=2) is None


# --- the job on real data (fixture) ---------------------------------------------------


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
    as_of = date(2024, 12, 31)
    compute_returns(settings, source, as_of=as_of)
    compute_risk(settings, source, as_of=as_of, with_correlation_matrix=False)
    compute_liquidity(settings, source, as_of=as_of)
    compute_fundamentals(settings, source, as_of=as_of)
    compute_valuation_metrics(settings, source, as_of=as_of)
    return settings, source


def test_compute_fair_value_on_real_statements(
    populated: tuple[Settings, NseScraperSource],
) -> None:
    settings, source = populated
    as_of = date(2024, 12, 31)
    result = compute_fair_value(settings, source, as_of=as_of)
    assert set(result.tickers_processed) == {"KCB", "EQTY", "SCOM", "KEGN"}
    assert result.tickers_skipped["KENO"] == "no financial statements captured"
    assert result.known_counts["pb_roe"] == 2 and result.known_counts["blended"] >= 3
    with analytics_session(settings) as session:
        kcb = {v.method: v for v in load_valuations(session, as_of_date=as_of, ticker_symbol="KCB")}
        assert set(kcb) == {"pb_roe", "ddm", "blended"}  # a bank: no DCF / EV methods
        pb = kcb["pb_roe"]
        assert (
            pb.status == "known"
            and pb.bear is not None
            and pb.base is not None
            and pb.bull is not None
        )
        assert pb.bear <= pb.base <= pb.bull
        assert (pb.assumptions or {})["beta_source"] == "beta_12m (clamped)"
        assert (pb.assumptions or {})["risk_free_rate"] == 0.12
        blended = kcb["blended"]
        assert blended.status == "known" and blended.price is not None
        assert blended.fair_low is not None and blended.fair_high is not None
        assert blended.fair_low <= (blended.base or 0.0) <= blended.fair_high
        assert blended.margin_of_safety == pytest.approx(1 - blended.price / (blended.base or 1.0))
        assert blended.uncertainty is not None and blended.actionable is not None
        assert "methods_used" in (blended.assumptions or {})
        scom = {
            v.method: v for v in load_valuations(session, as_of_date=as_of, ticker_symbol="SCOM")
        }
        assert set(scom) == {"dcf", "ev_ebitda", "pe_relative", "blended"}
        assert scom["pe_relative"].status == "known"
        assert (scom["pe_relative"].assumptions or {})[
            "multiple_source"
        ] == "market median"  # alone in telecom
        assert (
            scom["dcf"].status == "known"
            and (scom["dcf"].assumptions or {})["fcf_years_averaged"] >= 1
        )
    again = compute_fair_value(settings, source, as_of=as_of)
    assert again.rows_written == result.rows_written
    with analytics_session(settings) as session:
        assert len(load_valuations(session, as_of_date=as_of)) == result.rows_written


def test_fair_value_is_point_in_time(populated: tuple[Settings, NseScraperSource]) -> None:
    settings, source = populated
    early = compute_fair_value(settings, source, as_of=date(2022, 6, 30), tickers=["KCB"])
    with analytics_session(settings) as session:
        rows = load_valuations(session, as_of_date=date(2022, 6, 30), ticker_symbol="KCB")
        by_method = {v.method: v for v in rows}
        # FY2021 statements are visible (period end + 90 d), nothing later. The stored
        # ROE for that date was never computed, so justified P/B says so instead of
        # borrowing the 2024 number; the dividend discount alone carries the blend and
        # the uncertainty score flags it as not actionable.
        assert by_method["pb_roe"].status == "unavailable"
        assert by_method["pb_roe"].reason == "justified P/B: missing ROE"
        assert by_method["ddm"].status == "known"
        blended = by_method["blended"]
        assert blended.status == "known" and blended.base == by_method["ddm"].base
        assert blended.price == 38.65  # KCB close on 2022-06-30
        assert blended.uncertainty is not None and blended.uncertainty >= 0.6
        assert blended.actionable is False
        assert "single method" in (blended.assumptions or {})["uncertainty_flags"]
    assert early.rows_written == 3


def test_cli_compute_fair_value(
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
        result = CliRunner().invoke(
            app,
            [
                "analytics",
                "compute",
                "fair-value",
                "--as-of",
                "2024-12-31",
                "--ticker",
                "KCB",
                "--ticker",
                "SCOM",
            ],
        )
        assert result.exit_code == 0, result.output
        assert "blended" in result.output and "pb_roe" in result.output
    finally:
        get_settings.cache_clear()
