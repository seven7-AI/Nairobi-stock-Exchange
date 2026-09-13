"""Point-in-time fundamentals: the source reads and the availability rules.

Runs against the real-data fixture (a slice of the scraper database captured
2026-09-13, see scripts/build_test_fixture.py) so the row shapes, units and
timestamps are the genuine article.

    codegraph explore "fetch_financial_statements load_statement_rows point_in_time"
"""

from __future__ import annotations

from datetime import UTC, date, datetime

import pytest

from app.web.services.analytics.config import DEFAULT_CONFIG, AnalyticsConfig, FundamentalsConfig
from app.web.services.analytics.fundamentals.statements import (
    availability_date,
    latest_line_item,
    line_item_series,
    load_statement_rows,
    periods_available,
    point_in_time,
    statement_measure,
)
from app.web.services.analytics.measure import MeasureStatus
from app.web.services.market_data.sources import NseScraperSource

pytestmark = pytest.mark.unit

CAPTURE_DAY = date(2026, 9, 13)


# --- source reads ---------------------------------------------------------------


def test_fixture_carries_the_expected_universe(fixture_source: NseScraperSource) -> None:
    tickers = {row["ticker_symbol"] for row in fixture_source.fetch_instruments()}
    assert tickers == {
        "KCB",
        "EQTY",
        "SCOM",
        "KEGN",
        "ABSA",
        "NCBA",
        "KENO",
        "ACCS",
        "KPC",
        "SKL",
        "^NASI",
        "^N20I",
    }
    assert fixture_source.has_observations()
    assert fixture_source.has_financial_statements()


def test_fetch_financial_statements_returns_every_captured_row(
    fixture_source: NseScraperSource,
) -> None:
    rows = fixture_source.fetch_financial_statements(
        "kcb", statement="income", period_type="annual"
    )
    assert rows, "KCB annual income statement was captured live on 2026-09-13"
    revenue = [r for r in rows if r["line_item"] == "revenue" and r["fiscal_label"] == "FY 2025"]
    assert len(revenue) == 1
    row = revenue[0]
    assert row["value"] == 173395.0
    assert row["value_raw"] == "173,395"
    assert row["unit"] == "millions_kes"
    assert row["fiscal_period_end"] == "2025-12-31"
    assert row["first_seen_at"].startswith("2026-09-13T")
    # ordered by period end, then first seen
    ends = [r["fiscal_period_end"] for r in rows]
    assert ends == sorted(ends)


def test_first_seen_before_filters_out_later_captures(fixture_source: NseScraperSource) -> None:
    before = fixture_source.fetch_financial_statements(
        "KCB", first_seen_before=datetime(2026, 9, 1, tzinfo=UTC)
    )
    assert before == []
    after = fixture_source.fetch_financial_statements(
        "KCB", first_seen_before=datetime(2026, 9, 14, tzinfo=UTC)
    )
    assert len(after) > 1000


def test_unknown_ticker_and_missing_filters(fixture_source: NseScraperSource) -> None:
    assert fixture_source.fetch_financial_statements("NOPE") == []
    assert (
        fixture_source.fetch_financial_statements("ACCS") == []
    )  # delisted 2012, nothing to crawl


def test_fetch_fundamental_snapshots_is_bounded_by_snapshot_date(
    fixture_source: NseScraperSource,
) -> None:
    rows = fixture_source.fetch_fundamental_snapshots("KCB")
    assert {r["view"] for r in rows} == {"overview", "performance", "dividends", "price", "profile"}
    assert all(r["snapshot_date"] == "2026-09-13" for r in rows)
    overview = next(r for r in rows if r["view"] == "overview")
    assert isinstance(overview["metrics"], dict)
    assert overview["metrics"]["marketCap"] > 1e11
    assert fixture_source.fetch_fundamental_snapshots("KCB", end=date(2026, 9, 12)) == []
    assert [
        r["view"] for r in fixture_source.fetch_fundamental_snapshots("KCB", view="dividends")
    ] == ["dividends"]


def test_fetch_observations_bulk(fixture_source: NseScraperSource) -> None:
    series = fixture_source.fetch_observations_bulk(
        ["KCB", "^NASI", "NOPE", "kcb"], start=date(2024, 1, 1), end=date(2024, 12, 31)
    )
    assert set(series) == {"KCB", "^NASI", "NOPE"}
    assert series["NOPE"] == []
    assert len(series["KCB"]) > 200
    dates = [row["trade_date"] for row in series["KCB"]]
    assert dates == sorted(dates)
    assert dates[0] >= "2024-01-01" and dates[-1] <= "2024-12-31"
    assert isinstance(series["KCB"][0]["quality_flags"], list)
    assert fixture_source.fetch_observations_bulk([]) == {}


# --- availability rules ---------------------------------------------------------


def test_backfilled_capture_is_available_from_period_end_plus_lag() -> None:
    seen = datetime(2026, 9, 13, 11, 14, tzinfo=UTC)
    available, assumed = availability_date(
        seen, date(2021, 12, 31), "annual", DEFAULT_CONFIG, initial_capture=True
    )
    assert (available, assumed) == (date(2022, 3, 31), True)
    available, assumed = availability_date(
        seen, date(2026, 6, 30), "quarterly", DEFAULT_CONFIG, initial_capture=True
    )
    assert (available, assumed) == (date(2026, 8, 29), True)


def test_live_capture_keeps_its_first_seen_date() -> None:
    seen = datetime(2026, 9, 13, 11, 14, tzinfo=UTC)
    # published deadline (2026-11-09) is after the capture: we know it was known by 09-13
    available, assumed = availability_date(
        seen, date(2026, 9, 10), "current", DEFAULT_CONFIG, initial_capture=True
    )
    assert (available, assumed) == (date(2026, 9, 13), False)


def test_a_restatement_is_never_backdated() -> None:
    seen = datetime(2026, 11, 1, tzinfo=UTC)
    available, assumed = availability_date(
        seen, date(2021, 12, 31), "annual", DEFAULT_CONFIG, initial_capture=False
    )
    assert (available, assumed) == (date(2026, 11, 1), False)


def test_lag_is_configuration_not_a_literal() -> None:
    config = AnalyticsConfig(fundamentals=FundamentalsConfig(publication_lag_days_annual=120))
    seen = datetime(2026, 9, 13, tzinfo=UTC)
    available, _ = availability_date(
        seen, date(2024, 12, 31), "annual", config, initial_capture=True
    )
    assert available == date(2025, 4, 30)


# --- point-in-time over real rows ----------------------------------------------


@pytest.fixture(scope="module")
def kcb_rows(fixture_source: NseScraperSource):
    return load_statement_rows(fixture_source.fetch_financial_statements("KCB"), DEFAULT_CONFIG)


def test_load_statement_rows_applies_the_rules_to_real_captures(kcb_rows) -> None:
    fy2021 = next(r for r in kcb_rows if r.line_item == "revenue" and r.fiscal_label == "FY 2021")
    assert fy2021.fiscal_period_end == date(2021, 12, 31)
    assert (fy2021.available_from, fy2021.availability_assumed) == (date(2022, 3, 31), True)
    current = next(r for r in kcb_rows if r.period_type == "current" and r.line_item == "pe_ratio")
    assert (current.available_from, current.availability_assumed) == (CAPTURE_DAY, False)
    assert current.first_seen_at.tzinfo is not None


def test_point_in_time_hides_periods_not_yet_published(kcb_rows) -> None:
    assert periods_available(kcb_rows, date(2023, 6, 30), statement="income") == [
        date(2021, 12, 31),
        date(2022, 12, 31),
    ]
    assert periods_available(kcb_rows, date(2023, 3, 30), statement="income") == [
        date(2021, 12, 31)
    ]
    assert periods_available(kcb_rows, date(2021, 1, 1), statement="income") == []
    assert periods_available(kcb_rows, CAPTURE_DAY, statement="income")[-1] == date(2025, 12, 31)


def test_line_item_series_and_scaling(kcb_rows) -> None:
    series = line_item_series(kcb_rows, CAPTURE_DAY, statement="income", line_item="revenue")
    assert [d for d, _ in series] == [
        date(2021, 12, 31),
        date(2022, 12, 31),
        date(2023, 12, 31),
        date(2024, 12, 31),
        date(2025, 12, 31),
    ]
    latest = series[-1][1]
    assert latest.value == pytest.approx(173_395_000_000.0)  # millions -> KES
    assert latest.provenance[0].table == "financial_statements"
    assert "publication-lag assumption" in (latest.provenance[0].note or "")
    eps = latest_line_item(kcb_rows, CAPTURE_DAY, statement="income", line_item="eps_diluted")
    assert eps.value == pytest.approx(20.80, abs=0.01)  # per-share: unscaled
    margin = latest_line_item(
        kcb_rows, CAPTURE_DAY, statement="ratios", line_item="return_on_equity_roe"
    )
    assert margin.is_known and 0.05 < (margin.value or 0) < 0.60  # percent -> fraction


def test_dash_on_the_site_is_missing_not_zero(kcb_rows) -> None:
    fy2025 = point_in_time(kcb_rows, CAPTURE_DAY)[
        ("income", "annual", date(2025, 12, 31), "interest_income_on_investments")
    ]
    measure = statement_measure(fy2025)
    assert measure.status is MeasureStatus.MISSING
    assert measure.value is None
    assert "'-'" in (measure.reason or "")


def test_absent_line_item_is_missing_with_a_reason(kcb_rows) -> None:
    m = latest_line_item(kcb_rows, CAPTURE_DAY, statement="income", line_item="gross_profit")
    assert m.status is MeasureStatus.MISSING  # a bank has no gross profit line
    assert statement_measure(None).status is MeasureStatus.MISSING


def test_restatement_versions_are_selected_by_as_of() -> None:
    base = {
        "ticker_symbol": "X",
        "statement": "income",
        "period_type": "annual",
        "fiscal_period_end": "2024-12-31",
        "fiscal_label": "FY 2024",
        "line_item": "net_income",
        "label": "Net Income",
        "unit": "millions_kes",
        "currency": "KES",
    }
    original = {
        **base,
        "id": 1,
        "value": 100.0,
        "value_raw": "100",
        "first_seen_at": "2026-09-13T11:00:00+00:00",
    }
    restated = {
        **base,
        "id": 2,
        "value": 90.0,
        "value_raw": "90",
        "first_seen_at": "2026-11-01T09:00:00+00:00",
    }
    rows = load_statement_rows([restated, original], DEFAULT_CONFIG)
    assert [r.available_from for r in rows] == [date(2025, 3, 31), date(2026, 11, 1)]
    assert (
        latest_line_item(rows, date(2025, 3, 30), statement="income", line_item="net_income").status
        is MeasureStatus.MISSING
    )
    assert (
        latest_line_item(rows, date(2026, 10, 31), statement="income", line_item="net_income").value
        == 100e6
    )
    assert (
        latest_line_item(rows, date(2026, 11, 1), statement="income", line_item="net_income").value
        == 90e6
    )


def test_unknown_unit_is_unavailable_not_guessed() -> None:
    row = {
        "id": 1,
        "ticker_symbol": "X",
        "statement": "income",
        "period_type": "annual",
        "fiscal_period_end": "2024-12-31",
        "fiscal_label": "FY 2024",
        "line_item": "thing",
        "label": "Thing",
        "unit": "furlongs",
        "currency": "KES",
        "value": 1.0,
        "value_raw": "1",
        "first_seen_at": "2026-09-13T11:00:00+00:00",
    }
    (loaded,) = load_statement_rows([row], DEFAULT_CONFIG)
    assert statement_measure(loaded).status is MeasureStatus.UNAVAILABLE


# --- the live database ----------------------------------------------------------


@pytest.mark.realdata
def test_live_database_agrees_with_the_fixture_on_kcb_fy2025_revenue(
    live_source: NseScraperSource,
) -> None:
    rows = live_source.fetch_financial_statements("KCB", statement="income", period_type="annual")
    revenue = [r for r in rows if r["line_item"] == "revenue" and r["fiscal_label"] == "FY 2025"]
    assert revenue and revenue[0]["value"] == 173395.0
    assert len(live_source.fetch_instruments()) >= 102
