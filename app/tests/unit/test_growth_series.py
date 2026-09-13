"""The stock-growth series and chart, from synthetic observations. No I/O.

codegraph explore "build_growth_series figure_for render_png"
"""

from __future__ import annotations

from datetime import date, timedelta

import pytest

from app.web.core.exceptions import ResourceNotFoundError
from app.web.services.visualizations import (
    GAP_THRESHOLD_DAYS,
    build_growth_series,
    figure_for,
    render_png,
)

pytestmark = [pytest.mark.unit]

INSTRUMENT = {
    "ticker_symbol": "KCB",
    "company_name": "KCB Group Plc",
    "sector": "Banking",
    "instrument_type": "ordinary",
}


def _rows(spec: list[tuple[str, float]], source: str = "nse_archive:2020", ticker: str = "KCB"):
    return [
        {
            "ticker_symbol": "KCB",
            "trade_date": d,
            "close_price": c,
            "data_source": source,
            "source_ticker": ticker,
        }
        for d, c in spec
    ]


def _daily(start: date, closes: list[float], **kw):
    return _rows([((start + timedelta(days=i)).isoformat(), c) for i, c in enumerate(closes)], **kw)


def test_first_last_high_low_and_change() -> None:
    series = build_growth_series(_daily(date(2020, 1, 1), [10.0, 12.0, 8.0, 11.0]), INSTRUMENT)
    assert series.first.close == 10.0 and series.first.trade_date == date(2020, 1, 1)
    assert series.last.close == 11.0 and series.last.trade_date == date(2020, 1, 4)
    assert series.high.close == 12.0 and series.low.close == 8.0
    assert series.overall_change_pct == pytest.approx(10.0)
    assert series.sources == ["nse_archive"]


def test_a_real_hole_is_a_gap_but_a_holiday_is_not() -> None:
    rows = _rows(
        [
            ("2020-01-01", 10.0),
            ("2020-01-02", 10.5),
            ("2020-01-11", 10.6),  # 9 days: the archive's widest holiday gap
            ("2020-02-10", 11.0),  # 30 days: no data
        ]
    )
    series = build_growth_series(rows, INSTRUMENT)
    assert len(series.gaps) == 1
    assert (series.gaps[0].after, series.gaps[0].before, series.gaps[0].days) == (
        date(2020, 1, 11),
        date(2020, 2, 10),
        30,
    )
    assert GAP_THRESHOLD_DAYS == 14


def test_figure_breaks_the_line_at_the_gap_and_never_connects() -> None:
    import numpy as np

    rows = _rows([("2020-01-01", 10.0), ("2020-01-02", 10.5), ("2020-03-01", 11.0)])
    fig = figure_for(build_growth_series(rows, INSTRUMENT))
    ax = fig.axes[0]
    line = ax.get_lines()[0]  # the close series is drawn first
    ys = np.asarray(line.get_ydata(), dtype=float)
    assert int(np.isnan(ys).sum()) == 1  # the break inserted after the last point before the gap
    assert len(ax.patches) == 1  # the shaded "no data" band (axvspan)
    render_png(fig)


def test_split_is_detected_not_smoothed() -> None:
    """KCB 2007-04-03: 212 -> 22.5. The step stays; it is marked."""
    rows = _daily(date(2007, 4, 1), [227.0, 212.0, 22.5, 22.75])
    series = build_growth_series(rows, INSTRUMENT)
    assert len(series.corporate_actions) == 1
    action = series.corporate_actions[0]
    assert action.on == date(2007, 4, 3)
    assert action.ratio == pytest.approx(22.5 / 212.0)
    assert series.summary()["prices_are_adjusted"] is False
    assert [p.close for p in series.points] == [227.0, 212.0, 22.5, 22.75]  # untouched
    fig = figure_for(series)
    dashed = [ln for ln in fig.axes[0].get_lines() if ln.get_linestyle() == "--"]
    assert len(dashed) == 1  # one marker per suspected corporate action
    render_png(fig)


def test_a_step_across_a_gap_is_not_called_a_corporate_action() -> None:
    """Twenty months apart, a 3x move is plausible; only same-window steps are flagged."""
    rows = _rows([("2024-12-31", 41.6), ("2026-07-26", 130.0)])
    series = build_growth_series(rows, INSTRUMENT)
    assert series.gaps and not series.corporate_actions


def test_lineage_is_visible_in_source_tickers() -> None:
    rows = _rows([("2012-12-31", 15.75)], ticker="BBK") + _rows(
        [("2013-01-02", 15.7)], ticker="ABSA"
    )
    series = build_growth_series(rows, {**INSTRUMENT, "ticker_symbol": "ABSA"})
    assert series.source_tickers == ["BBK", "ABSA"]
    fig = figure_for(series)
    assert "traded as BBK → ABSA" in fig.axes[0].get_title(loc="left")
    render_png(fig)


def test_empty_series_is_an_error_not_a_blank_chart() -> None:
    with pytest.raises(ResourceNotFoundError):
        build_growth_series([], INSTRUMENT)
    with pytest.raises(ResourceNotFoundError):
        build_growth_series(_rows([("2020-01-01", None)]), INSTRUMENT)  # type: ignore[list-item]


def test_unusable_rows_are_dropped_never_invented() -> None:
    rows = _rows(
        [("2020-01-01", 10.0), ("bad-date", 11.0), ("2020-01-03", 0.0), ("2020-01-04", 12.0)]
    )
    series = build_growth_series(rows, INSTRUMENT)
    assert [p.close for p in series.points] == [10.0, 12.0]


def test_render_png_produces_a_png_and_closes_the_figure() -> None:
    import matplotlib.pyplot as plt

    plt.close("all")
    rows = _daily(date(2020, 1, 1), [10.0, 11.0, 12.0])
    png = render_png(figure_for(build_growth_series(rows, INSTRUMENT)))
    assert png[:8] == b"\x89PNG\r\n\x1a\n"
    assert 10_000 < len(png) < 2_000_000
    assert plt.get_fignums() == []  # nothing left open for --all to accumulate
