"""Fundamentals engine: synthetic statements, bank rules, trends, growth, PIT, real KCB/SCOM.

codegraph explore "fundamental_metrics quality_metrics growth_metrics trend_label"
"""

from __future__ import annotations

from collections.abc import Mapping
from datetime import date
from pathlib import Path

import pytest
from sqlalchemy import select

from app.web.config import Settings
from app.web.db.analytics import analytics_session
from app.web.db.analytics.models import FundamentalMetric
from app.web.db.analytics.services.fundamental_metrics import load_fundamental_metrics
from app.web.services.analytics.classification.service import classify_instruments
from app.web.services.analytics.config import DEFAULT_CONFIG as CONFIG
from app.web.services.analytics.config import AnalyticsConfig, FundamentalsConfig
from app.web.services.analytics.fundamentals import (
    compute_fundamentals,
    fundamental_metrics,
    growth_metrics,
    quality_metrics,
    trend_metrics,
)
from app.web.services.analytics.fundamentals.engine import (
    concept_series,
    sector_relative,
    trend_label,
)
from app.web.services.analytics.fundamentals.statements import StatementRow, load_statement_rows
from app.web.services.analytics.measure import Measure, MeasureStatus
from app.web.services.analytics.store import upgrade_analytics_db
from app.web.services.market_data.sources import NseScraperSource

pytestmark = pytest.mark.unit

SEEN = "2020-01-15T10:00:00+00:00"


def raw_row(
    ticker: str,
    statement: str,
    year: int,
    line_item: str,
    value: float | None,
    *,
    unit: str = "millions_kes",
    seen: str = SEEN,
    row_id: int = 0,
) -> dict[str, object]:
    return {
        "id": row_id or hash((ticker, statement, year, line_item)) % 1_000_000,
        "ticker_symbol": ticker,
        "statement": statement,
        "period_type": "annual",
        "fiscal_period_end": f"{year}-12-31",
        "fiscal_label": f"FY {year}",
        "line_item": line_item,
        "label": line_item.replace("_", " ").title(),
        "value": value,
        "value_raw": "-" if value is None else f"{value:,}",
        "unit": unit,
        "currency": "KES",
        "first_seen_at": seen,
    }


def company(
    years: Mapping[int, Mapping[str, float | None]], ticker: str = "X"
) -> list[StatementRow]:
    """Build statement rows from {year: {concept: value}} (millions; per-share in KES)."""
    rows: list[dict[str, object]] = []
    for year, values in years.items():
        for item, value in values.items():
            if item in ("eps_diluted", "dividend_per_share"):
                rows.append(raw_row(ticker, "income", year, item, value, unit="kes"))
            elif item in (
                "total_assets",
                "shareholders_equity",
                "total_common_equity",
                "total_debt",
                "cash_and_equivalents",
            ):
                rows.append(raw_row(ticker, "balance", year, item, value))
            elif item in ("operating_cash_flow", "free_cash_flow"):
                rows.append(raw_row(ticker, "cashflow", year, item, value))
            else:
                rows.append(raw_row(ticker, "income", year, item, value))
    # every row is first seen 2020-01-15: FY2019 is available from that day
    return load_statement_rows(rows, CONFIG)


def industrial(scale: float = 1.0) -> list[StatementRow]:
    years = {}
    for i, year in enumerate(range(2015, 2020)):
        g = (1.1**i) * scale
        years[year] = {
            "revenue": 1000 * g,
            "gross_profit": 400 * g,
            "operating_income": 200 * g,
            "ebitda": 260 * g,
            "interest_expense": -20 * g,
            "net_income_to_common": 120 * g,
            "eps_diluted": 12.0 * (1.1**i),
            "dividend_per_share": 5.0 * (1.1**i),
            "total_assets": 2000 * g,
            "total_common_equity": 800 * g,
            "total_debt": 300 * g,
            "cash_and_equivalents": 100 * g,
            "operating_cash_flow": 180 * g,
            "free_cash_flow": 150 * g,
        }
    return company(years)


AS_OF = date(2020, 6, 30)  # FY2019 (captured 2020-01-15) is the latest known year


# --- quality ------------------------------------------------------------------------


def test_quality_metrics_hand_computed() -> None:
    out = quality_metrics(industrial(), AS_OF, sector_code="manufacturing")
    g4, g3 = 1.1**4, 1.1**3
    ni, rev = 120 * g4, 1000 * g4
    avg_equity = (800 * g4 + 800 * g3) / 2
    avg_assets = (2000 * g4 + 2000 * g3) / 2
    assert out["roe"].measure.value == pytest.approx(ni / avg_equity)
    assert out["roa"].measure.value == pytest.approx(ni / avg_assets)
    assert out["net_margin"].measure.value == pytest.approx(0.12)
    assert out["gross_margin"].measure.value == pytest.approx(0.40)
    assert out["operating_margin"].measure.value == pytest.approx(0.20)
    assert out["ebitda_margin"].measure.value == pytest.approx(0.26)
    assert out["interest_coverage"].measure.value == pytest.approx(
        200 / 20
    )  # sign of the expense ignored
    assert out["asset_turnover"].measure.value == pytest.approx(rev / avg_assets)
    assert out["fcf"].measure.value == pytest.approx(150 * g4 * 1e6)  # scaled to KES
    assert out["fcf_margin"].measure.value == pytest.approx(0.15)
    assert out["debt_to_equity"].measure.value == pytest.approx(300 / 800)
    assert out["net_debt"].measure.value == pytest.approx((300 - 100) * g4 * 1e6)
    assert out["roe"].period_end == date(2019, 12, 31) and out["roe"].period_type == "annual"
    assert out["roe"].measure.provenance and all(
        p.table == "financial_statements" for p in out["roe"].measure.provenance
    )


def test_bank_rules() -> None:
    out = quality_metrics(industrial(), AS_OF, sector_code="banking")
    for metric in (
        "gross_margin",
        "operating_margin",
        "ebitda_margin",
        "interest_coverage",
        "asset_turnover",
    ):
        assert out[metric].measure.status is MeasureStatus.NOT_APPLICABLE, metric
    assert out["roe"].measure.is_known and out["net_margin"].measure.is_known


def test_negative_earnings_negative_fcf_and_missing_items() -> None:
    rows = company(
        {
            2018: {
                "revenue": 100,
                "net_income_to_common": -30,
                "free_cash_flow": -12,
                "total_common_equity": 50,
                "total_assets": 200,
                "total_debt": 80,
                "operating_income": -10,
                "interest_expense": -5,
            },
            2019: {
                "revenue": 90,
                "net_income_to_common": -40,
                "free_cash_flow": -20,
                "total_common_equity": -5,
                "total_assets": 180,
                "total_debt": 90,
                "operating_income": -15,
                "interest_expense": -6,
            },
        }
    )
    out = quality_metrics(rows, AS_OF, sector_code="manufacturing")
    assert out["net_margin"].measure.value == pytest.approx(
        -40 / 90
    )  # a loss is a real, negative margin
    assert out["fcf"].measure.value == pytest.approx(-20e6)
    assert out["roe"].measure.value == pytest.approx(
        -40 / ((50 - 5) / 2)
    )  # average equity still positive
    assert out["debt_to_equity"].measure.status is MeasureStatus.NOT_MEANINGFUL  # negative equity
    assert out["interest_coverage"].measure.value == pytest.approx(-15 / 6)
    assert (
        out["gross_margin"].measure.status is MeasureStatus.MISSING
    )  # gross profit never reported
    assert out["net_debt"].measure.status is MeasureStatus.MISSING  # cash never reported


def test_dash_cells_are_missing_and_skipped_labels_fall_through() -> None:
    rows = company(
        {
            2018: {
                "revenue": 100,
                "net_income": 10,
                "net_income_to_common": None,
                "total_common_equity": None,
                "shareholders_equity": 40,
            }
        }
    )
    series = concept_series(rows, AS_OF, "net_income")
    assert series[0][1].value == pytest.approx(
        10e6
    )  # net_income_to_common all '-', net_income used
    equity = concept_series(rows, AS_OF, "equity")
    assert equity[0][1].value == pytest.approx(40e6)
    out = quality_metrics(rows, AS_OF, sector_code=None)
    assert out["roe"].measure.value == pytest.approx(10 / 40)


def test_no_statements_at_all() -> None:
    out = fundamental_metrics([], AS_OF, sector_code=None, config=CONFIG)
    assert all(not r.measure.is_known for r in out.values())
    assert "no income statement" in (out["roe"].measure.reason or "")


# --- trends ------------------------------------------------------------------------


def test_trend_labels() -> None:
    assert (
        trend_label([0.11, 0.13, 0.16, 0.18, 0.20], stable_band=0.05, rising_is_better=True)[0] == 1
    )
    assert (
        trend_label([0.20, 0.18, 0.16, 0.13, 0.11], stable_band=0.05, rising_is_better=True)[0]
        == -1
    )
    assert trend_label([0.20, 0.205, 0.198, 0.202], stable_band=0.05, rising_is_better=True)[0] == 0
    # rising leverage is deteriorating
    assert trend_label([0.3, 0.4, 0.5], stable_band=0.05, rising_is_better=False)[0] == -1
    assert "improving" in trend_label([1, 2, 3], stable_band=0.05, rising_is_better=True)[1]


def test_trend_metrics_on_an_improving_company_and_the_minimum() -> None:
    out = trend_metrics(industrial(), AS_OF, CONFIG)
    assert out["roe_trend"].measure.status is MeasureStatus.ZERO  # constant ROE by construction
    assert out["fcf_trend"].measure.value == 1.0 and "improving" in (
        out["fcf_trend"].measure.reason or ""
    )
    assert out["debt_to_equity_trend"].measure.status is MeasureStatus.ZERO
    two_years = company(
        {
            2018: {"revenue": 100, "net_income_to_common": 10, "total_common_equity": 50},
            2019: {"revenue": 120, "net_income_to_common": 14, "total_common_equity": 60},
        }
    )
    short = trend_metrics(two_years, AS_OF, CONFIG)
    assert short["roe_trend"].measure.status is MeasureStatus.UNAVAILABLE
    assert "minimum 3" in (short["roe_trend"].measure.reason or "")
    strict = AnalyticsConfig(fundamentals=FundamentalsConfig(trend_min_periods=2))
    assert trend_metrics(two_years, AS_OF, strict)["roe_trend"].measure.is_known


def test_deteriorating_quality_with_growing_revenue() -> None:
    years = {}
    for i, year in enumerate(range(2016, 2020)):
        years[year] = {
            "revenue": 100 * 1.2**i,
            "net_income_to_common": 20 - 4 * i,
            "total_common_equity": 100,
            "total_assets": 300,
        }
    out = fundamental_metrics(company(years), AS_OF, sector_code=None, config=CONFIG)
    assert out["revenue_cagr_3y"].measure.value == pytest.approx(0.2)
    assert out["net_margin_trend"].measure.value == -1.0
    assert out["roe_trend"].measure.value == -1.0


# --- growth ------------------------------------------------------------------------


def test_growth_and_cagr_hand_computed() -> None:
    out = growth_metrics(industrial(), AS_OF, CONFIG)
    assert out["revenue_growth_1y"].measure.value == pytest.approx(0.1)
    assert out["eps_growth_1y"].measure.value == pytest.approx(0.1)
    assert out["dividend_growth_1y"].measure.value == pytest.approx(0.1)
    assert out["revenue_cagr_3y"].measure.value == pytest.approx(0.1)
    assert out["eps_cagr_3y"].measure.value == pytest.approx(0.1)
    assert out["fcf_cagr_3y"].measure.value == pytest.approx(0.1)
    assert out["revenue_cagr_5y"].measure.status is MeasureStatus.UNAVAILABLE  # needs FY2014
    assert "starts 2015-12-31" in (out["revenue_cagr_5y"].measure.reason or "")
    assert out["revenue_growth_1y"].period_end == date(2019, 12, 31)


def test_growth_edge_cases() -> None:
    rows = company(
        {
            2016: {
                "revenue": 100,
                "net_income_to_common": -10,
                "eps_diluted": -1.0,
                "dividend_per_share": None,
            },
            2017: {
                "revenue": 0,
                "net_income_to_common": 5,
                "eps_diluted": 0.5,
                "dividend_per_share": None,
            },
            2018: {
                "revenue": 120,
                "net_income_to_common": -2,
                "eps_diluted": -0.2,
                "dividend_per_share": 1.0,
            },
            2019: {
                "revenue": 150,
                "net_income_to_common": 8,
                "eps_diluted": 0.8,
                "dividend_per_share": 1.5,
            },
        }
    )
    out = growth_metrics(rows, AS_OF, CONFIG)
    assert out["revenue_growth_1y"].measure.value == pytest.approx(0.25)
    assert out["eps_growth_1y"].measure.value == pytest.approx(
        (0.8 - -0.2) / 0.2
    )  # relative to |base|
    assert out["eps_cagr_3y"].measure.status is MeasureStatus.NOT_MEANINGFUL  # negative start
    assert out["revenue_cagr_3y"].measure.value == pytest.approx((150 / 100) ** (1 / 3) - 1)
    assert out["dividend_growth_1y"].measure.value == pytest.approx(0.5)
    one = company({2019: {"revenue": 10}})
    assert (
        growth_metrics(one, AS_OF, CONFIG)["revenue_growth_1y"].measure.status
        is MeasureStatus.UNAVAILABLE
    )
    assert (
        growth_metrics(one, AS_OF, CONFIG)["eps_growth_1y"].measure.status is MeasureStatus.MISSING
    )


def test_sector_relative_growth() -> None:
    own = Measure.known(0.20)
    peers = [Measure.known(0.05), Measure.known(0.10), Measure.known(0.15), Measure.missing("x")]
    rel = sector_relative(own, peers, name="revenue growth vs sector", min_peers=3)
    assert rel.value == pytest.approx(0.10)
    assert "median of 3 sector peers" in (rel.provenance[-1].note or "")
    assert (
        sector_relative(own, peers[:2], name="x", min_peers=3).status is MeasureStatus.UNAVAILABLE
    )
    assert (
        sector_relative(Measure.missing("m"), peers, name="x", min_peers=1).status
        is MeasureStatus.MISSING
    )


# --- point in time ------------------------------------------------------------------


def test_fy2019_is_invisible_before_it_was_captured() -> None:
    # every row was first seen 2020-01-15, before FY2019's 2020-03-31 publication
    # deadline, so the capture date is the availability date
    rows = industrial()
    before = quality_metrics(rows, date(2020, 1, 14), sector_code=None)
    after = quality_metrics(rows, date(2020, 1, 15), sector_code=None)
    assert before["roe"].period_end == date(2018, 12, 31)
    assert after["roe"].period_end == date(2019, 12, 31)
    # a backfilled capture (seen long after) falls back to period end + 90 days
    late = load_statement_rows(
        [raw_row("Y", "income", 2019, "revenue", 10.0, seen="2026-09-13T00:00:00+00:00")], CONFIG
    )
    # 2019-12-31 + 90 days = 2020-03-30 (leap year)
    assert concept_series(late, date(2020, 3, 29), "revenue") == []
    assert concept_series(late, date(2020, 3, 30), "revenue")[0][0] == date(2019, 12, 31)


def test_look_ahead_a_restatement_captured_later_is_invisible() -> None:
    base = industrial()
    restated = raw_row(
        "X",
        "income",
        2019,
        "net_income_to_common",
        999.0,
        seen="2020-09-01T00:00:00+00:00",
        row_id=777,
    )
    rows = load_statement_rows(
        [
            *[
                {
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
                for r in base
            ],
            restated,
        ],
        CONFIG,
    )
    on_june = quality_metrics(rows, AS_OF, sector_code=None)
    original = quality_metrics(base, AS_OF, sector_code=None)
    assert on_june["net_margin"].measure.as_dict() == original["net_margin"].measure.as_dict()
    later = quality_metrics(rows, date(2020, 9, 2), sector_code=None)
    assert later["net_margin"].measure.value == pytest.approx(999 / (1000 * 1.1**4))


# --- real statements (fixture) ---------------------------------------------------------


@pytest.fixture(scope="module")
def kcb_rows(fixture_source: NseScraperSource) -> list[StatementRow]:
    return load_statement_rows(fixture_source.fetch_financial_statements("KCB"), CONFIG)


@pytest.fixture(scope="module")
def scom_rows(fixture_source: NseScraperSource) -> list[StatementRow]:
    return load_statement_rows(fixture_source.fetch_financial_statements("SCOM"), CONFIG)


CAPTURE = date(2026, 9, 13)


def test_kcb_fy2025_hand_computed(kcb_rows: list[StatementRow]) -> None:
    out = fundamental_metrics(kcb_rows, CAPTURE, sector_code="banking", config=CONFIG)
    assert out["roe"].period_end == date(2025, 12, 31)
    # net income to common 66,819 m over average common equity (331,466 + 274,888) / 2
    assert out["roe"].measure.value == pytest.approx(66_819 / ((331_466 + 274_888) / 2))
    # the site's ROE (20.88 %) averages quarterly equity; annual averaging lands within 1.5 pp
    assert abs((out["roe"].measure.value or 0) - 0.2088) < 0.015
    assert out["roa"].measure.value == pytest.approx(66_819 / ((2_147_206 + 1_962_320) / 2))
    assert abs((out["roa"].measure.value or 0) - 0.0317) < 0.002
    assert out["net_margin"].measure.value == pytest.approx(66_819 / 173_395)
    assert out["interest_coverage"].measure.status is MeasureStatus.NOT_APPLICABLE
    assert out["fcf"].measure.value == pytest.approx(-130_880e6)  # negative FCF, kept as such
    assert out["debt_to_equity"].measure.value == pytest.approx(95_151 / 331_466)
    assert out["revenue_growth_1y"].measure.value == pytest.approx(173_395 / 164_148 - 1)
    assert out["eps_growth_1y"].measure.value == pytest.approx(20.8 / 18.7 - 1)
    assert out["revenue_cagr_3y"].measure.value == pytest.approx((173_395 / 116_381) ** (1 / 3) - 1)
    assert out["revenue_cagr_5y"].measure.status is MeasureStatus.UNAVAILABLE
    assert out["dividend_growth_1y"].measure.value == pytest.approx(5.0 / 3.0 - 1)
    assert out["roe_trend"].measure.is_known


def test_kcb_dividend_gap_year_is_missing_not_zero(kcb_rows: list[StatementRow]) -> None:
    series = concept_series(kcb_rows, CAPTURE, "dps")
    by_year = {end.year: m for end, m in series}
    assert by_year[2023].status is MeasureStatus.MISSING  # shown as '-' on the site
    assert by_year[2024].value == 3.0


def test_scom_fy2026_industrial_metrics(scom_rows: list[StatementRow]) -> None:
    out = fundamental_metrics(scom_rows, CAPTURE, sector_code="telecommunication", config=CONFIG)
    assert out["roe"].period_end == date(2026, 3, 31)
    assert out["gross_margin"].measure.value == pytest.approx(314_552 / 423_866)
    assert out["operating_margin"].measure.value == pytest.approx(160_118 / 423_866)
    assert out["ebitda_margin"].measure.value == pytest.approx(225_656 / 423_866)
    assert out["interest_coverage"].measure.value == pytest.approx(160_118 / 18_991)
    assert out["asset_turnover"].measure.value == pytest.approx(423_866 / ((518_045 + 515_284) / 2))
    assert out["fcf_margin"].measure.value == pytest.approx(89_758 / 423_866)
    assert out["revenue_cagr_3y"].measure.value == pytest.approx((423_866 / 308_313) ** (1 / 3) - 1)


def test_kcb_as_of_2023_sees_only_fy2022(kcb_rows: list[StatementRow]) -> None:
    out = fundamental_metrics(kcb_rows, date(2023, 3, 30), sector_code="banking", config=CONFIG)
    assert out["roe"].period_end == date(2021, 12, 31)  # FY2022 available from 2023-03-31
    assert out["revenue_cagr_3y"].measure.status is MeasureStatus.UNAVAILABLE
    assert out["roe_trend"].measure.status is MeasureStatus.UNAVAILABLE  # one fiscal year


# --- the compute job -----------------------------------------------------------------


@pytest.fixture
def settings(fixture_db_path: Path, tmp_path: Path) -> Settings:
    s = Settings(
        NSE_SCRAPER_DB_PATH=str(fixture_db_path),
        NSE_SCRAPER_PATH=str(tmp_path / "scraper"),
        ANALYTICS_DB_PATH=str(tmp_path / "a.sqlite3"),
    )
    upgrade_analytics_db(s.analytics_db_path)
    return s


def test_compute_fundamentals_with_sector_relative_growth(settings: Settings) -> None:
    source = NseScraperSource(settings)
    classify_instruments(settings, source)
    result = compute_fundamentals(settings, source, as_of=CAPTURE)
    assert set(result.tickers_processed) == {"KCB", "EQTY", "SCOM", "KEGN"}
    assert result.tickers_skipped["ACCS"] == "no financial statements captured"
    assert result.known_counts["roe"] == 4
    with analytics_session(settings) as session:
        kcb = {
            r.metric: r
            for r in load_fundamental_metrics(session, ticker_symbol="KCB", as_of_date=CAPTURE)
        }
        assert kcb["roe"].value == pytest.approx(66_819 / ((331_466 + 274_888) / 2))
        assert kcb["roe"].period_end == date(2025, 12, 31)
        # only EQTY shares the banking sector in the fixture: below min_peers
        assert kcb["revenue_growth_1y_vs_sector"].status == "unavailable"
        assert "1 peer" in (kcb["revenue_growth_1y_vs_sector"].reason or "")
        rows_before = len(session.execute(select(FundamentalMetric)).scalars().all())
    compute_fundamentals(settings, source, as_of=CAPTURE)
    with analytics_session(settings) as session:
        assert len(session.execute(select(FundamentalMetric)).scalars().all()) == rows_before


def test_cli_compute_fundamentals(settings: Settings, monkeypatch: pytest.MonkeyPatch) -> None:
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
            ["analytics", "compute", "fundamentals", "--as-of", "2026-09-13", "--ticker", "SCOM"],
        )
        assert result.exit_code == 0, result.output
        assert "revenue_cagr_3y" in result.output
    finally:
        get_settings.cache_clear()
