"""``Measure`` - the six statuses, safe arithmetic and provenance. No I/O.

codegraph explore "Measure safe_div pct_change cagr"
"""

from __future__ import annotations

import math
from datetime import date

import pytest

from app.web.services.analytics.measure import (
    Measure,
    MeasureStatus,
    Provenance,
    all_known,
    as_measure,
    cagr,
    first_unusable,
    merge_provenance,
    pct_change,
    safe_div,
)

pytestmark = pytest.mark.unit

ROWS = Provenance(
    table="stock_observations", ticker="KCB", start=date(2024, 1, 2), end=date(2024, 12, 31)
)
STATEMENT = Provenance(
    table="financial_statements", ids=(17,), ticker="KCB", note="FY 2024 net income"
)


def test_known_carries_value_and_provenance() -> None:
    m = Measure.known(12.5, ROWS)
    assert m.status is MeasureStatus.KNOWN
    assert m.value == 12.5
    assert m.is_known and m.is_positive
    assert m.provenance == (ROWS,)


def test_exactly_zero_is_recorded_as_zero_not_known() -> None:
    m = Measure.known(0.0)
    assert m.status is MeasureStatus.ZERO
    assert m.is_known and not m.is_positive
    assert Measure.zero(STATEMENT).value == 0.0


@pytest.mark.parametrize(
    ("factory", "status"),
    [
        (Measure.missing, MeasureStatus.MISSING),
        (Measure.unavailable, MeasureStatus.UNAVAILABLE),
        (Measure.not_applicable, MeasureStatus.NOT_APPLICABLE),
        (Measure.not_meaningful, MeasureStatus.NOT_MEANINGFUL),
    ],
)
def test_non_values_carry_a_reason_and_no_number(factory, status) -> None:
    m = factory("because", ROWS)
    assert m.status is status
    assert m.value is None
    assert m.reason == "because"
    assert not m.is_known


def test_a_status_without_a_value_cannot_smuggle_one_in() -> None:
    with pytest.raises(ValueError):
        Measure(1.0, MeasureStatus.MISSING)
    with pytest.raises(ValueError):
        Measure(None, MeasureStatus.KNOWN)
    with pytest.raises(ValueError):
        Measure(math.nan, MeasureStatus.KNOWN)
    with pytest.raises(ValueError):
        Measure(math.inf, MeasureStatus.KNOWN)


def test_as_dict_is_the_stored_shape() -> None:
    m = Measure.known(3.0, STATEMENT)
    assert m.as_dict() == {
        "value": 3.0,
        "status": "known",
        "reason": None,
        "provenance": [
            {
                "table": "financial_statements",
                "ids": [17],
                "ticker": "KCB",
                "note": "FY 2024 net income",
            }
        ],
    }
    assert Measure.unavailable("gap").as_dict() == {
        "value": None,
        "status": "unavailable",
        "reason": "gap",
        "provenance": [],
    }


def test_as_measure_lifts_raw_numbers_and_none() -> None:
    assert as_measure(2).value == 2.0
    assert as_measure(None).status is MeasureStatus.MISSING
    assert as_measure(math.nan, reason="nan input").reason == "nan input"
    known = Measure.known(1.0)
    assert as_measure(known) is known


# --- arithmetic -------------------------------------------------------------------


def test_safe_div_known_inputs() -> None:
    ratio = safe_div(Measure.known(10.0, ROWS), Measure.known(4.0, STATEMENT), name="p/e")
    assert ratio.value == 2.5
    assert ratio.provenance == (ROWS, STATEMENT)


def test_safe_div_negative_denominator_is_not_meaningful_by_default() -> None:
    pe = safe_div(100.0, Measure.known(-5.0), name="p/e")
    assert pe.status is MeasureStatus.NOT_MEANINGFUL
    assert "negative" in (pe.reason or "")


def test_safe_div_allows_negative_denominator_when_told_to() -> None:
    assert safe_div(10.0, -5.0, require_positive_denominator=False).value == -2.0


def test_safe_div_zero_denominator_is_not_meaningful() -> None:
    assert safe_div(1.0, 0.0).status is MeasureStatus.NOT_MEANINGFUL
    assert safe_div(1.0, Measure.zero()).status is MeasureStatus.NOT_MEANINGFUL


def test_safe_div_propagates_the_first_unusable_input() -> None:
    missing = safe_div(Measure.missing("no eps"), 5.0, name="p/e")
    assert missing.status is MeasureStatus.MISSING
    assert missing.reason == "p/e: input missing (no eps)"
    unavailable = safe_div(5.0, Measure.unavailable("gap"), name="r")
    assert unavailable.status is MeasureStatus.UNAVAILABLE
    not_applicable = safe_div(Measure.not_applicable("bank"), 1.0)
    assert not_applicable.status is MeasureStatus.NOT_APPLICABLE
    assert safe_div(None, 1.0).status is MeasureStatus.MISSING


def test_pct_change() -> None:
    assert pct_change(110.0, 100.0).value == pytest.approx(0.10)
    assert pct_change(-50.0, -100.0).value == pytest.approx(0.5)  # loss narrowed: positive change
    assert pct_change(5.0, 0.0).status is MeasureStatus.NOT_MEANINGFUL
    assert pct_change(None, 1.0).status is MeasureStatus.MISSING


def test_cagr() -> None:
    assert cagr(200.0, 100.0, 3).value == pytest.approx(2 ** (1 / 3) - 1)
    assert cagr(100.0, -100.0, 3).status is MeasureStatus.NOT_MEANINGFUL
    assert cagr(-1.0, 100.0, 3).status is MeasureStatus.NOT_MEANINGFUL
    assert cagr(100.0, 100.0, 0).status is MeasureStatus.UNAVAILABLE
    assert cagr(Measure.missing("x"), 100.0, 3).status is MeasureStatus.MISSING


# --- helpers ----------------------------------------------------------------------


def test_merge_provenance_dedupes_and_keeps_order() -> None:
    a = Measure.known(1.0, ROWS, STATEMENT)
    b = Measure.known(2.0, STATEMENT)
    assert merge_provenance(a, b) == (ROWS, STATEMENT)


def test_first_unusable_and_all_known() -> None:
    assert first_unusable(Measure.known(1.0), Measure.zero()) is None
    bad = Measure.unavailable("gap")
    assert first_unusable(Measure.known(1.0), bad) is bad
    assert all_known([Measure.known(1.0), Measure.zero()])
    assert not all_known([Measure.known(1.0), Measure.missing("x")])


def test_with_provenance_appends() -> None:
    m = Measure.known(1.0, ROWS).with_provenance(STATEMENT)
    assert m.provenance == (ROWS, STATEMENT)
