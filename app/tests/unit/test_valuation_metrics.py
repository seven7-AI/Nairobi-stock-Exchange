"""Valuation multiples and dividends: not-meaningful denominators, classes, real KCB numbers.

codegraph explore "valuation_metrics dividend_metrics relative_to_group"
"""

from __future__ import annotations

from datetime import date, timedelta
from pathlib import Path

import pytest

from app.tests.unit.test_fundamentals_engine import company, industrial, raw_row
from app.web.config import Settings
from app.web.db.analytics import analytics_session
from app.web.db.analytics.services.fundamental_metrics import load_fundamental_metrics
from app.web.services.analytics.classification.service import classify_instruments
from app.web.services.analytics.config import DEFAULT_CONFIG as CONFIG
from app.web.services.analytics.config import AnalyticsConfig, ValuationConfig
from app.web.services.analytics.fundamentals.engine import FundamentalResult
from app.web.services.analytics.fundamentals.statements import StatementRow, load_statement_rows
from app.web.services.analytics.measure import Measure, MeasureStatus
from app.web.services.analytics.series import PriceSeries, build_price_series
from app.web.services.analytics.store import upgrade_analytics_db
from app.web.services.analytics.valuation_metrics import (
    DividendClass,
    compute_valuation_metrics,
    dividend_metrics,
    multiples,
    valuation_metrics,
)
from app.web.services.analytics.valuation_metrics.engine import price_on, relative_to_group
from app.web.services.market_data.sources import NseScraperSource

pytestmark = pytest.mark.unit

AS_OF = date(2020, 6, 30)


def prices(close: float, days: int = 300, end: date = AS_OF, ticker: str = "X") -> PriceSeries:
    rows = []
    day = end - timedelta(days=days)
    index = 0
    while day <= end:
        if day.weekday() < 5:
            index += 1
            rows.append(
                {
                    "id": index,
                    "trade_date": day.isoformat(),
                    "close_price": close,
                    "volume": 100,
                    "source_ticker": ticker,
                    "quality_flags": [],
                }
            )
        day += timedelta(days=1)
    return build_price_series(ticker, rows, CONFIG)


# --- multiples -------------------------------------------------------------------------


def test_multiples_hand_computed() -> None:
    rows = industrial()
    g4 = 1.1**4
    out = multiples(rows, prices(120.0), AS_OF, sector_code="manufacturing")
    # FY2019: EPS 12 x 1.1^4, no share count reported -> market cap missing
    assert out["pe"].measure.value == pytest.approx(120.0 / (12.0 * g4))
    assert out["market_cap"].measure.status is MeasureStatus.MISSING
    assert out["pb"].measure.status is MeasureStatus.MISSING
    assert out["forward_pe"].measure.status is MeasureStatus.UNAVAILABLE
    assert out["dividend_yield"].measure.value == pytest.approx(5.0 * g4 / 120.0)
    assert out["payout_ratio"].measure.value == pytest.approx(5.0 / 12.0)
    assert out["pe_ttm"].measure.status is MeasureStatus.MISSING  # no TTM rows in the synthetic set
    assert out["price"].measure.value == 120.0 and out["price"].period_type == "observation"


def test_multiples_with_shares_market_cap_and_enterprise_value() -> None:
    years = {
        2019: {
            "revenue": 1000,
            "eps_diluted": 10.0,
            "shares_outstanding_diluted": 50,
            "total_common_equity": 400,
            "total_debt": 300,
            "cash_and_equivalents": 100,
            "ebitda": 260,
            "dividend_per_share": 4.0,
            "free_cash_flow": 150,
        }
    }
    rows = company(years)
    out = multiples(rows, prices(20.0), AS_OF, sector_code="manufacturing")
    market_cap = 20.0 * 50e6
    assert out["market_cap"].measure.value == pytest.approx(market_cap)
    assert out["enterprise_value"].measure.value == pytest.approx(market_cap + 300e6 - 100e6)
    assert out["pb"].measure.value == pytest.approx(market_cap / 400e6)
    assert out["ps"].measure.value == pytest.approx(market_cap / 1000e6)
    assert out["ev_ebitda"].measure.value == pytest.approx((market_cap + 200e6) / 260e6)
    assert out["ev_sales"].measure.value == pytest.approx((market_cap + 200e6) / 1000e6)
    assert out["fcf_yield"].measure.value == pytest.approx(150e6 / market_cap)
    bank = multiples(rows, prices(20.0), AS_OF, sector_code="banking")
    assert bank["ev_ebitda"].measure.status is MeasureStatus.NOT_APPLICABLE


def test_negative_denominators_are_not_meaningful() -> None:
    years = {
        2019: {
            "revenue": 100,
            "eps_diluted": -2.0,
            "shares_outstanding_diluted": 10,
            "total_common_equity": -5,
            "total_debt": 50,
            "cash_and_equivalents": 5,
            "ebitda": -20,
            "dividend_per_share": 1.0,
        }
    }
    out = multiples(company(years), prices(10.0), AS_OF, sector_code=None)
    assert out["pe"].measure.status is MeasureStatus.NOT_MEANINGFUL
    assert "negative" in (out["pe"].measure.reason or "")
    assert out["pb"].measure.status is MeasureStatus.NOT_MEANINGFUL
    assert out["ev_ebitda"].measure.status is MeasureStatus.NOT_MEANINGFUL
    assert out["payout_ratio"].measure.status is MeasureStatus.NOT_MEANINGFUL
    assert out["dividend_yield"].measure.value == pytest.approx(0.1)  # still a real yield


def test_price_must_be_current() -> None:
    stale = prices(10.0, end=AS_OF - timedelta(days=60))
    out = multiples(industrial(), stale, AS_OF, sector_code=None)
    assert out["pe"].measure.status is MeasureStatus.UNAVAILABLE
    assert "days before" in (out["pe"].measure.reason or "")
    assert isinstance(price_on(build_price_series("X", [], CONFIG), AS_OF), Measure)


def test_versus_history_uses_the_ratios_page_and_a_minimum() -> None:
    rows = list(industrial())
    ratio_rows = [
        raw_row("X", "ratios", year, "pe_ratio", value, unit="ratio")
        for year, value in ((2017, 8.0), (2018, 10.0), (2019, 12.0))
    ]
    with_history = load_statement_rows([*[_dump(r) for r in rows], *ratio_rows], CONFIG)
    out = valuation_metrics(with_history, prices(120.0), AS_OF, sector_code=None, config=CONFIG)
    pe = out["pe"].measure.value or 0
    assert out["pe_vs_history"].measure.value == pytest.approx(pe / 10.0 - 1)
    assert (
        out["pb_vs_history"].measure.status is MeasureStatus.MISSING
    )  # pb itself missing (no shares)
    thin = load_statement_rows([*[_dump(r) for r in rows], *ratio_rows[:2]], CONFIG)
    assert (
        valuation_metrics(thin, prices(120.0), AS_OF, sector_code=None, config=CONFIG)[
            "pe_vs_history"
        ].measure.status
        is MeasureStatus.UNAVAILABLE
    )


def _dump(r: StatementRow) -> dict[str, object]:
    return {
        "id": r.id,
        "ticker_symbol": r.ticker_symbol,
        "statement": r.statement,
        "period_type": r.period_type,
        "fiscal_period_end": r.fiscal_period_end.isoformat(),
        "fiscal_label": r.fiscal_label,
        "line_item": r.line_item,
        "label": r.label,
        "value": r.value,
        "value_raw": r.value_raw,
        "unit": r.unit,
        "currency": r.currency,
        "first_seen_at": r.first_seen_at.isoformat(),
    }


def test_relative_to_group() -> None:
    own = Measure.known(6.0)
    group = [
        Measure.known(4.0),
        Measure.known(5.0),
        Measure.known(12.0),
        Measure.not_meaningful("loss"),
    ]
    rel = relative_to_group(own, group, name="pe vs sector", min_members=3)
    assert rel.value == pytest.approx(6.0 / 5.0 - 1)
    assert (
        relative_to_group(own, group[:2], name="x", min_members=3).status
        is MeasureStatus.UNAVAILABLE
    )
    assert (
        relative_to_group(Measure.not_meaningful("loss"), group, name="x", min_members=1).status
        is MeasureStatus.NOT_MEANINGFUL
    )


# --- dividends -------------------------------------------------------------------------


def _dividend_case(
    dps: dict[int, float | None],
    eps: dict[int, float] | None = None,
    fcf: float = 500.0,
    paid: float = -100.0,
    price: float = 100.0,
) -> dict[str, FundamentalResult]:
    years: dict[int, dict[str, float | None]] = {}
    for year, value in dps.items():
        years[year] = {
            "revenue": 1000,
            "eps_diluted": (eps or {}).get(year, 10.0),
            "dividend_per_share": value,
            "free_cash_flow": fcf,
            "common_dividends_paid": paid,
        }
    rows = company(years)
    current = multiples(rows, prices(price), AS_OF, sector_code=None)
    return dividend_metrics(rows, AS_OF, current, CONFIG)


def test_reliable_and_growing_payers() -> None:
    growing = _dividend_case({2015: 1.0, 2016: 1.1, 2017: 1.21, 2018: 1.331, 2019: 1.4641})
    assert growing["dividend_years_paid"].measure.value == 5.0
    assert growing["dividend_consistency"].measure.value == 1.0
    assert growing["dividend_cut"].measure.status is MeasureStatus.ZERO
    assert growing["dividend_cagr_3y"].measure.value == pytest.approx(0.1)
    assert growing["fcf_dividend_coverage"].measure.value == pytest.approx(5.0)
    assert growing["dividend_class"].measure.value == float(DividendClass.GROWING_PAYER)
    assert (growing["dividend_class"].measure.reason or "").startswith("Growing payer")
    flat = _dividend_case({2015: 1.0, 2016: 1.0, 2017: 1.0, 2018: 1.0, 2019: 1.0})
    assert flat["dividend_class"].measure.value == float(DividendClass.RELIABLE_PAYER)


def test_cut_and_stopped_dividends_are_deteriorating() -> None:
    cut = _dividend_case({2017: 2.0, 2018: 2.0, 2019: 1.0})
    assert cut["dividend_cut"].measure.value == 1.0
    assert cut["dividend_class"].measure.value == float(DividendClass.DETERIORATING)
    stopped = _dividend_case({2017: 2.0, 2018: 2.0, 2019: 0.0})
    assert stopped["dividend_class"].measure.value == float(DividendClass.DETERIORATING)
    assert stopped["dividend_years_paid"].measure.value == 2.0


def test_missing_dividend_row_is_missing_not_zero() -> None:
    gap = _dividend_case({2017: 2.0, 2018: None, 2019: 2.0})
    assert gap["dividend_years_paid"].measure.value == 2.0
    assert gap["dividend_consistency"].measure.value == pytest.approx(2 / 3)
    assert (
        gap["dividend_cut"].measure.status is MeasureStatus.ZERO
    )  # 2019 vs the last reported year 2017
    assert gap["dividend_class"].measure.value == float(DividendClass.DETERIORATING)
    assert "2 of 3" in (gap["dividend_class"].measure.reason or "")
    # '-' in every year: the site reports nothing, so nothing is known - not a non-payer
    nothing = _dividend_case({2018: None, 2019: None})
    assert nothing["dividend_years_paid"].measure.status is MeasureStatus.MISSING
    assert nothing["dividend_class"].measure.status is MeasureStatus.MISSING
    # an explicit zero every year IS a non-payer
    zero = _dividend_case({2018: 0.0, 2019: 0.0})
    assert zero["dividend_years_paid"].measure.status is MeasureStatus.ZERO
    assert zero["dividend_class"].measure.value == float(DividendClass.NON_PAYER)


def test_high_yield_versus_trap() -> None:
    high = _dividend_case(
        {2017: 9.0, 2018: 9.0, 2019: 9.0}, eps={2017: 10.0, 2018: 11.0, 2019: 12.0}, price=100.0
    )
    assert high["dividend_class"].measure.value == float(DividendClass.HIGH_YIELD)
    trap = _dividend_case(
        {2017: 9.0, 2018: 9.0, 2019: 9.0},
        eps={2017: 12.0, 2018: 11.0, 2019: 8.0},
        fcf=50.0,
        price=100.0,
    )
    assert trap["dividend_class"].measure.value == float(DividendClass.POTENTIAL_TRAP)
    reason = trap["dividend_class"].measure.reason or ""
    assert "EPS fell" in reason and "payout" in reason and "FCF below" in reason
    lenient = AnalyticsConfig(valuation=ValuationConfig(high_yield_threshold=0.20))
    rows = company(
        {
            y: {
                "revenue": 1000,
                "eps_diluted": 12.0,
                "dividend_per_share": 9.0,
                "free_cash_flow": 500,
                "common_dividends_paid": -100,
            }
            for y in (2017, 2018, 2019)
        }
    )
    current = multiples(rows, prices(100.0), AS_OF, sector_code=None)
    assert dividend_metrics(rows, AS_OF, current, lenient)["dividend_class"].measure.value == float(
        DividendClass.RELIABLE_PAYER
    )


def test_fcf_coverage_edge_cases() -> None:
    none_paid = _dividend_case({2018: 1.0, 2019: 1.0}, paid=0.0)
    assert none_paid["fcf_dividend_coverage"].measure.status is MeasureStatus.NOT_MEANINGFUL
    negative = _dividend_case({2018: 1.0, 2019: 1.0}, fcf=-50.0)
    assert negative["fcf_dividend_coverage"].measure.value == pytest.approx(-0.5)


# --- real KCB (fixture) ---------------------------------------------------------------


CAPTURE = date(2026, 9, 13)


@pytest.fixture(scope="module")
def kcb(fixture_source: NseScraperSource) -> tuple[list[StatementRow], PriceSeries]:
    rows = load_statement_rows(fixture_source.fetch_financial_statements("KCB"), CONFIG)
    series = build_price_series("KCB", fixture_source.fetch_observations("KCB"), CONFIG)
    return rows, series


def test_kcb_multiples_on_capture_day_hand_computed(
    kcb: tuple[list[StatementRow], PriceSeries],
) -> None:
    rows, series = kcb
    out = valuation_metrics(rows, series, CAPTURE, sector_code="banking", config=CONFIG)
    # close 94.0 on 2026-09-13; FY2025 EPS 20.80, TTM EPS 22.22; 3,213 m diluted shares
    assert out["price"].measure.value == 94.0
    assert out["pe"].measure.value == pytest.approx(94.0 / 20.8)
    assert out["pe_ttm"].measure.value == pytest.approx(94.0 / 22.22)
    market_cap = 94.0 * 3_213e6
    assert out["market_cap"].measure.value == pytest.approx(market_cap)
    assert out["pb"].measure.value == pytest.approx(market_cap / 331_466e6)
    assert out["ps"].measure.value == pytest.approx(market_cap / 173_395e6)
    assert out["ev_ebitda"].measure.status is MeasureStatus.NOT_APPLICABLE
    assert out["dividend_yield"].measure.value == pytest.approx(5.0 / 94.0)
    assert out["dividend_yield_ttm"].measure.value == pytest.approx(
        6.0 / 94.0
    )  # the site's 6.23 % uses TTM DPS
    assert out["payout_ratio"].measure.value == pytest.approx(5.0 / 20.8)
    assert out["fcf_yield"].measure.value == pytest.approx(-130_880e6 / market_cap)
    # the site's fiscal-year P/E history 4.28, 3.02, 1.95, 2.23, 3.16 -> median 3.02
    assert out["pe_vs_history"].measure.value == pytest.approx((94.0 / 20.8) / 3.02 - 1)


def test_kcb_dividend_profile(kcb: tuple[list[StatementRow], PriceSeries]) -> None:
    rows, series = kcb
    out = valuation_metrics(rows, series, CAPTURE, sector_code="banking", config=CONFIG)
    # DPS 3.0, 2.0, '-', 3.0, 5.0 over FY2021..FY2025
    assert out["dividend_years_paid"].measure.value == 4.0
    assert out["dividend_consistency"].measure.value == pytest.approx(4 / 5)
    assert out["dividend_cut"].measure.status is MeasureStatus.ZERO
    assert out["dividend_cagr_3y"].measure.value == pytest.approx((5.0 / 2.0) ** (1 / 3) - 1)
    assert out["fcf_dividend_coverage"].measure.value == pytest.approx(-130_880 / 11_247)
    assert out["dividend_class"].measure.value == float(
        DividendClass.DETERIORATING
    )  # the FY2023 gap
    assert "4 of 5" in (out["dividend_class"].measure.reason or "")


def test_look_ahead_on_prices(kcb: tuple[list[StatementRow], PriceSeries]) -> None:
    rows, series = kcb
    as_of = date(2024, 12, 31)
    a = valuation_metrics(rows, series.as_of(as_of), as_of, sector_code="banking", config=CONFIG)
    # the full series carries 2026 prices; the engine must not see past as_of
    b = valuation_metrics(rows, series, as_of, sector_code="banking", config=CONFIG)
    assert {k: v.measure.as_dict() for k, v in a.items()} == {
        k: v.measure.as_dict() for k, v in b.items()
    }
    assert a["pe"].period_end == date(2023, 12, 31)  # FY2024 not yet published on 2024-12-31


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


def test_compute_valuation_metrics_with_relatives(settings: Settings) -> None:
    source = NseScraperSource(settings)
    classify_instruments(settings, source)
    result = compute_valuation_metrics(settings, source, as_of=CAPTURE)
    assert set(result.tickers_processed) == {"KCB", "EQTY", "SCOM", "KEGN"}
    with analytics_session(settings) as session:
        kcb = {
            r.metric: r
            for r in load_fundamental_metrics(session, ticker_symbol="KCB", as_of_date=CAPTURE)
        }
        assert kcb["pe"].value == pytest.approx(94.0 / 20.8)
        assert kcb["pe_vs_market"].status == "known"  # EQTY, SCOM, KEGN all have a positive P/E
        assert kcb["pe_vs_sector"].status == "unavailable"  # one banking peer in the fixture
        assert kcb["dividend_class"].reason is not None and kcb["dividend_class"].reason.startswith(
            "Deteriorating"
        )
    again = compute_valuation_metrics(settings, source, as_of=CAPTURE, tickers=["SCOM"])
    assert again.tickers_processed == ("SCOM",)


def test_cli_compute_valuation_metrics(settings: Settings, monkeypatch: pytest.MonkeyPatch) -> None:
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
                "valuation-metrics",
                "--as-of",
                "2026-09-13",
                "--ticker",
                "KCB",
            ],
        )
        assert result.exit_code == 0, result.output
        assert "dividend_class" in result.output
    finally:
        get_settings.cache_clear()
