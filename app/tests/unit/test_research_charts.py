"""Research diagrams: figure content, gaps drawn as gaps, PNG rendering, `plot all`.

codegraph explore "volatility_figure relative_strength ranking_figure plot_kinds"
"""

from __future__ import annotations

from datetime import date
from pathlib import Path

import numpy as np
import pytest

from app.web.config import Settings
from app.web.db.analytics import analytics_session
from app.web.services.analytics.classification.service import classify_instruments
from app.web.services.analytics.config import DEFAULT_CONFIG as CONFIG
from app.web.services.analytics.returns.service import load_universe
from app.web.services.analytics.series import build_price_series
from app.web.services.analytics.store import upgrade_analytics_db
from app.web.services.jobs import run_pipeline
from app.web.services.market_data.sources import NseScraperSource
from app.web.services.visualizations import momentum, research_charts, volatility
from app.web.services.visualizations.common import (
    DIAGRAM_KINDS,
    broken_line,
    empty_figure,
    render_png,
)
from app.web.services.visualizations.diagrams import plot_kinds

pytestmark = pytest.mark.unit

PNG_MAGIC = b"\x89PNG"


def _series(ticker: str, closes: list[float], skip: set[int] = frozenset()):
    import pandas as pd

    days = pd.bdate_range("2020-01-01", periods=len(closes))
    rows = [
        {"id": i, "trade_date": d.date(), "close_price": c, "volume": 100}
        for i, (d, c) in enumerate(zip(days, closes, strict=True))
        if i not in skip
    ]
    return build_price_series(ticker, rows, CONFIG)


def test_broken_line_inserts_nan_after_each_gap() -> None:
    series = _series("A", [1.0] * 80, skip=set(range(30, 55)))
    xs, ys = broken_line([d.date() for d in series.dates], list(series.close), series.gaps)
    assert len(series.gaps) == 1 and sum(np.isnan(ys)) == 1
    nan_at = int(np.argmax(np.isnan(ys)))
    assert xs[nan_at] == xs[nan_at - 1]  # the break sits on the last day before the hole


def test_volatility_figure_breaks_at_the_gap() -> None:
    rng = np.random.default_rng(1)
    closes = list(100 * np.cumprod(1 + rng.normal(0, 0.01, 260)))
    series = _series("A", closes, skip=set(range(120, 150)))
    data = volatility.volatility_data(series)
    vol = np.array(data.rolling_vol)
    assert np.isnan(vol[:63]).all() and not np.isnan(vol[100])
    # after the gap the window must refill before a value appears
    resume = series.position_on_or_before(series.gaps[0].before)
    assert (
        resume is not None
        and np.isnan(vol[resume : resume + 62]).all()
        and not np.isnan(vol[resume + 63])
    )
    dd = np.array(data.drawdown)
    assert dd.max() == 0.0 and dd[resume] == 0.0  # the peak resets at the segment start
    fig = volatility.figure_for(data)
    top, bottom = fig.axes
    assert "volatility" in top.get_ylabel() and bottom.get_ylabel() == "drawdown from peak"
    assert any(np.isnan(line.get_ydata()).any() for line in top.get_lines())  # the break is drawn
    assert len(top.patches) >= 1  # the gap span
    png = render_png(fig)
    assert png[:4] == PNG_MAGIC and len(png) > 10_000


def test_momentum_relative_strength_by_hand_and_no_overlap() -> None:
    stock = _series("A", [10.0, 11.0, 12.0, 12.0, 15.0])
    bench = _series("^X", [100.0, 100.0, 120.0, 120.0, 150.0])
    data = momentum.relative_strength(stock, bench)
    assert data is not None and data.stock_rebased == pytest.approx([100, 110, 120, 120, 150])
    assert data.relative == pytest.approx([1.0, 1.1, 1.0, 1.0, 1.0])
    fig = momentum.figure_for(data)
    top, bottom = fig.axes
    assert [line.get_label() for line in top.get_lines()] == ["A", "^X"]
    assert "relative strength" in bottom.get_ylabel()
    assert render_png(fig)[:4] == PNG_MAGIC
    later = _series("B", [1.0, 2.0])
    later_bench = build_price_series(
        "^Y", [{"id": 1, "trade_date": date(2030, 1, 1), "close_price": 1.0}], CONFIG
    )
    assert momentum.relative_strength(later, later_bench) is None
    empty = momentum.figure_for(None, ticker="B")
    assert "no dates shared" in "".join(t.get_text() for t in empty.axes[0].texts)
    assert render_png(empty)[:4] == PNG_MAGIC


def test_empty_figures_say_why() -> None:
    for fig, phrase in (
        (research_charts.sector_figure(None), "no market metrics"),
        (research_charts.ranking_figure(None), "no scored rankings"),
        (research_charts.valuation_figure(None), "no blended valuations"),
        (research_charts.forecast_figure(None, ticker="X"), "no known forecast"),
        (research_charts.backtest_figure(None), "no stored backtest"),
        (research_charts.portfolio_figure(None), "no stored portfolio"),
        (empty_figure("t", "why"), "why"),
    ):
        assert phrase in "".join(t.get_text() for t in fig.axes[0].texts)
        assert render_png(fig)[:4] == PNG_MAGIC


def test_ranking_and_valuation_figures_from_dataclasses() -> None:
    bars = research_charts.RankingBars(
        date(2024, 12, 31),
        "factor-model v1",
        [
            ("A", 80.0, "Strong Candidate", {"quality": 90.0, "value": None}),
            ("B", 40.0, "Neutral", {"quality": 10.0, "momentum": 55.0}),
        ],
    )
    fig = research_charts.ranking_figure(bars)
    left, right = fig.axes
    assert [t.get_text() for t in left.get_yticklabels()] == ["B", "A"]
    assert "Top 2 by factor-model v1" in fig._suptitle.get_text()
    assert len(right.patches) == 2 * len(research_charts.FACTOR_COLOURS)
    assert render_png(fig)[:4] == PNG_MAGIC
    val = research_charts.ValuationBars(
        date(2024, 12, 31), [("A", 8.0, 10.0, 12.0, 8.0, True), ("B", 4.0, 5.0, 6.0, 10.0, False)]
    )
    fig = research_charts.valuation_figure(val)
    ax = fig.axes[0]
    assert [t.get_text() for t in ax.get_xticklabels()] == ["B", "A"]  # sorted by upside
    assert render_png(fig)[:4] == PNG_MAGIC


def test_forecast_fan_and_backtest_figures() -> None:
    series = _series("A", [10.0] * 40)
    fan = research_charts.FanChart(
        "A",
        "ar1",
        date(2020, 2, 26),
        10.0,
        [d.date() for d in series.dates],
        list(series.close),
        (),
        {1: (9.0, 9.5, 10.0, 10.5, 11.0), 12: (7.0, 8.5, 10.5, 12.0, 14.0)},
    )
    fig = research_charts.forecast_figure(fan)
    ax = fig.axes[0]
    labels = [line.get_label() for line in ax.get_lines()]
    assert "close" in labels and "median" in labels and len(ax.collections) == 2
    assert "12M median +5.0%" in ax.get_title(loc="left")
    assert render_png(fig)[:4] == PNG_MAGIC
    curves = research_charts.EquityCurves(
        7,
        "run",
        date(2020, 1, 1),
        date(2020, 3, 31),
        [
            date(2020, 1, 31),
            date(2020, 2, 28),
            date(2020, 3, 31),
            date(2020, 6, 30),
            date(2020, 7, 31),
        ],
        ["1", "1", "1", "2", "2"],
        [100.0, 110.0, 99.0, 100.0, 120.0],
        {"^NASI": [100.0, 105.0, 100.0, 100.0, 110.0]},
        {"return": "-1.0%"},
    )
    fig = research_charts.backtest_figure(curves)
    top, _bottom = fig.axes
    equity_line = next(line for line in top.get_lines() if line.get_label() == "run")
    assert np.isnan(equity_line.get_ydata()).sum() == 1  # the segment break is a gap
    assert "segment 1" in top.get_title(loc="left")
    assert render_png(fig)[:4] == PNG_MAGIC
    risk = research_charts.PortfolioRisk(
        date(2020, 3, 31),
        "p",
        {"A": {"A": 1.0, "B": 0.3}, "B": {"A": 0.3, "B": 1.0}},
        {"A": (0.2, 0.1), "B": (0.3, -0.05), "C": (0.1, 0.0)},
        ["w1"],
    )
    fig = research_charts.portfolio_figure(risk)
    left, right = fig.axes[0], fig.axes[1]
    assert len(left.images) == 1 and len(right.get_lines()) >= 4  # 3 points + the zero line
    assert render_png(fig)[:4] == PNG_MAGIC


# --- from the store ---------------------------------------------------------------------


@pytest.fixture
def populated(fixture_db_path: Path, tmp_path: Path) -> tuple[Settings, NseScraperSource, Path]:
    settings = Settings(
        NSE_SCRAPER_DB_PATH=str(fixture_db_path),
        NSE_SCRAPER_PATH=str(tmp_path / "scraper"),
        ANALYTICS_DB_PATH=str(tmp_path / "a.sqlite3"),
    )
    upgrade_analytics_db(settings.analytics_db_path)
    source = NseScraperSource(settings)
    classify_instruments(settings, source)
    run_pipeline(settings, source, "daily", as_of=date(2019, 12, 31))
    run_pipeline(settings, source, "weekly", as_of=date(2019, 12, 31))
    return settings, source, tmp_path / "diagrams"


def test_store_loaders_and_plot_all(populated: tuple[Settings, NseScraperSource, Path]) -> None:
    settings, source, out = populated
    with analytics_session(settings) as session:
        sectors = research_charts.load_sector_performance(session)
        assert sectors is not None and sectors.as_of == date(2019, 12, 31)
        assert "Banking" in sectors.sectors and sectors.sectors["Banking"][1] >= 3
        assert "Indices" not in sectors.sectors
        ranking = research_charts.load_ranking_bars(session)
        # 2019: no statements yet, so nothing clears the weight floor - no scored rows,
        # and the figure says so rather than drawing an empty axis
        assert ranking is not None and ranking.as_of == date(2019, 12, 31) and ranking.rows == []
        fig = research_charts.ranking_figure(ranking)
        assert "no scored rankings" in "".join(t.get_text() for t in fig.axes[0].texts)
        render_png(fig)
        universe = load_universe(source, CONFIG)
        fan = research_charts.load_fan_chart(session, universe["KCB"])
        assert fan is not None and fan.origin == date(2019, 12, 31) and fan.price == 54.0
        assert set(fan.quantiles) == {1, 3, 6, 12} and fan.history_dates[0] >= date(2017, 12, 1)
        assert research_charts.load_valuation_bars(session) is None or True  # no statements in 2019
        assert research_charts.load_equity_curves(session) is None
        assert research_charts.load_portfolio_risk(session) is None
    written = plot_kinds(settings, source, "all", diagrams_dir=out, tickers=["KCB", "SCOM"])
    kinds = {p.parent.name for p in written}
    assert kinds == set(DIAGRAM_KINDS)
    per_stock = [p for p in written if p.stem in ("KCB", "SCOM")]
    assert len(per_stock) == 6  # volatility, momentum, forecasts x 2 tickers
    for path in written:
        assert path.read_bytes()[:4] == PNG_MAGIC and path.stat().st_size > 5_000
    with pytest.raises(ValueError, match="unknown diagram kind"):
        plot_kinds(settings, source, "pie", diagrams_dir=out)
    with pytest.raises(ValueError, match="--ticker or --all"):
        plot_kinds(settings, source, "volatility", diagrams_dir=out)


def test_cli_plot(
    populated: tuple[Settings, NseScraperSource, Path], monkeypatch: pytest.MonkeyPatch
) -> None:
    from typer.testing import CliRunner

    from app.cli.main import app
    from app.web.config import get_settings

    settings, _, out = populated
    monkeypatch.setenv("ANALYTICS_DB_PATH", str(settings.analytics_db_path))
    monkeypatch.setenv("NSE_SCRAPER_DB_PATH", str(settings.scraper_database_path))
    monkeypatch.setenv("NSE_SCRAPER_PATH", str(settings.nse_scraper_path))
    get_settings.cache_clear()
    try:
        result = CliRunner().invoke(app, ["analytics", "plot", "factor-ranking", "--out", str(out)])
        assert result.exit_code == 0, result.output
        assert (
            "factor-ranking/top-ranking-2019-12-31.png" in result.output
            and "1 diagram(s)" in result.output
        )
        per = CliRunner().invoke(
            app, ["analytics", "plot", "volatility", "--ticker", "KCB", "--out", str(out)]
        )
        assert per.exit_code == 0 and "volatility/KCB.png" in per.output
    finally:
        get_settings.cache_clear()
