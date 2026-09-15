"""Backtester: arithmetic by hand, costs, ADV cap, survivorship, gap segments, metrics,
look-ahead mutation on real data, the stored run and the weight search.

codegraph explore "run_backtest simulate_segment run_model_backtest rankings_at"
"""

from __future__ import annotations

import sqlite3
from collections.abc import Sequence
from datetime import date
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from app.web.config import Settings
from app.web.db.analytics import analytics_session
from app.web.db.analytics.services.backtests import (
    load_backtest_equity,
    load_backtest_positions,
    load_backtest_results,
    load_backtest_runs,
)
from app.web.db.analytics.services.classifications import load_classifications
from app.web.services.analytics.backtesting import (
    market_only_ranking,
    run_backtest,
    run_model_backtest,
    weight_search,
)
from app.web.services.analytics.backtesting.engine import (
    listed_on,
    month_ends,
    relative_metrics,
    series_metrics,
    split_segments,
    target_weights,
    trading_calendar,
)
from app.web.services.analytics.backtesting.service import build_context, stock_prices
from app.web.services.analytics.backtesting.signals import ranking_signal, turnover_lookup
from app.web.services.analytics.classification.lookup import ClassificationIndex
from app.web.services.analytics.classification.service import classify_instruments
from app.web.services.analytics.config import DEFAULT_CONFIG as CONFIG
from app.web.services.analytics.config import AnalyticsConfig, BacktestConfig
from app.web.services.analytics.measure import MeasureStatus, Provenance
from app.web.services.analytics.series import build_price_series
from app.web.services.analytics.store import upgrade_analytics_db
from app.web.services.market_data.sources import NseScraperSource

pytestmark = pytest.mark.unit

RATE = CONFIG.backtest.costs.rate
NOTIONAL = CONFIG.backtest.notional


def series(
    ticker: str, closes: Sequence[float], start: date = date(2020, 1, 1), skip: Sequence[int] = ()
):
    """Business-day series; ``skip`` drops those day offsets (a delisting or a gap)."""
    days = pd.bdate_range(start, periods=len(closes))
    rows = [
        {"id": i, "ticker_symbol": ticker, "trade_date": d.date(), "close_price": c, "volume": 1000}
        for i, (d, c) in enumerate(zip(days, closes, strict=True))
        if i not in skip
    ]
    return build_price_series(ticker, rows, CONFIG)


def prefer(*order: str):
    def signal(day: date, listed: Sequence[str]) -> list[tuple[str, float]]:
        return [(t, 1.0) for t in order if t in listed]

    return signal


def test_calendar_month_ends_and_segments() -> None:
    a = series("A", [1.0] * 45)
    days = trading_calendar({"A": a}, date(2020, 1, 1), date(2020, 3, 31))
    assert days[0] == date(2020, 1, 1) and len(days) == 45
    assert month_ends(days) == [date(2020, 1, 31), date(2020, 2, 28), date(2020, 3, 3)]
    gap = series("B", [1.0] * 60, skip=range(20, 45))  # 25 business days missing
    bdays = pd.bdate_range(date(2020, 1, 1), periods=60)
    segments = split_segments(
        trading_calendar({"B": gap}, date(2020, 1, 1), date(2020, 12, 31)), 14
    )
    assert len(segments) == 2
    assert segments[0][-1] == bdays[19].date() and segments[1][0] == bdays[45].date()


def test_listed_on_is_point_in_time() -> None:
    a = series("A", [1.0] * 30)
    b = series("B", [1.0] * 10, start=date(2020, 2, 3))
    prices = {"A": a, "B": b}
    assert listed_on(prices, date(2020, 1, 15), 14) == ["A"]
    assert listed_on(prices, date(2020, 2, 5), 14) == ["A", "B"]
    assert listed_on(prices, date(2020, 3, 20), 14) == []  # both series ended in February
    assert listed_on(prices, date(2020, 2, 20), 14) == [
        "A",
        "B",
    ]  # within 14 days of the last price


def test_single_stock_equity_by_hand_with_and_without_costs() -> None:
    closes = [10.0] * 23 + [12.0] * 20 + [9.0] * 19  # Jan (23 bdays) at 10, Feb at 12, Mar at 9
    prices = {"A": series("A", closes), "B": series("B", [5.0] * 62)}
    free = run_backtest(
        prices,
        prefer("A"),
        start=date(2020, 1, 1),
        end=date(2020, 3, 27),
        config=CONFIG,
        benchmarks={},
        top_n=1,
        cost_rate=0.0,
    )
    seg = free.segments[0]
    assert seg.equity.iloc[0] == NOTIONAL  # cash until the first month end
    first = seg.rebalances[0]
    assert first.day == date(2020, 1, 31) and first.targets == {"A": 1.0}
    assert seg.equity.loc[pd.Timestamp("2020-02-03")] == pytest.approx(NOTIONAL * 12 / 10)
    assert seg.equity.iloc[-1] == pytest.approx(NOTIONAL * 9 / 10)
    assert seg.costs_paid == 0.0 and free.linked["total_return"].value == pytest.approx(-0.1)
    costed = run_backtest(
        prices,
        prefer("A"),
        start=date(2020, 1, 1),
        end=date(2020, 3, 27),
        config=CONFIG,
        benchmarks={},
        top_n=1,
    )
    cseg = costed.segments[0]
    first_buy = cseg.trades[0]
    assert first_buy.action == "buy" and first_buy.value == pytest.approx(NOTIONAL / (1 + RATE))
    assert first_buy.cost == pytest.approx(NOTIONAL / (1 + RATE) * RATE)
    assert cseg.equity.loc[pd.Timestamp("2020-01-31")] == pytest.approx(NOTIONAL / (1 + RATE))
    # holding the same stock costs nothing at later rebalances
    assert len(cseg.trades) == 1 and cseg.costs_paid == pytest.approx(first_buy.cost)
    assert cseg.equity.iloc[-1] == pytest.approx(NOTIONAL / (1 + RATE) * 0.9)
    assert costed.linked["costs_paid"].value == pytest.approx(first_buy.cost)


def test_switching_positions_pays_both_sides() -> None:
    prices = {"A": series("A", [10.0] * 62), "B": series("B", [5.0] * 62)}

    def flip(day: date, listed: Sequence[str]) -> list[tuple[str, float]]:
        return [("A", 1.0)] if day.month % 2 == 1 else [("B", 1.0)]

    out = run_backtest(
        prices,
        flip,
        start=date(2020, 1, 1),
        end=date(2020, 3, 27),
        config=CONFIG,
        benchmarks={},
        top_n=1,
    )
    seg = out.segments[0]
    actions = [(t.day, t.ticker_symbol, t.action) for t in seg.trades]
    last = pd.bdate_range(date(2020, 1, 1), periods=62)[-1].date()  # 2020-03-26
    assert actions == [
        (date(2020, 1, 31), "A", "buy"),
        (date(2020, 2, 28), "A", "sell"),
        (date(2020, 2, 28), "B", "buy"),
        (last, "B", "sell"),
        (last, "A", "buy"),
    ]
    e1 = NOTIONAL / (1 + RATE)  # after the first buy
    e2 = e1 * (1 - RATE) / (1 + RATE)  # sold A (cost), bought B (cost)
    assert seg.equity.loc[pd.Timestamp("2020-02-28")] == pytest.approx(e2)
    assert seg.rebalances[1].turnover == pytest.approx(1.0)  # one-way: everything moved


def test_adv_cap_trims_and_leaves_cash() -> None:
    prices = {"A": series("A", [10.0] * 42), "B": series("B", [5.0] * 42)}
    tiny = lambda day, ticker: 1_000_000.0 if ticker == "A" else None  # noqa: E731
    targets, notes = target_weights(
        [("A", 1.0), ("B", 0.5)],
        day=date(2020, 1, 31),
        equity=NOTIONAL,
        top_n=2,
        config=CONFIG,
        turnover=tiny,
    )
    # cap = 20% x 5 days x KES 1m = KES 1m = 10% of a KES 10m book, below the 50% target
    assert (
        targets == {"A": pytest.approx(0.1), "B": 0.5}
        and "trimmed from 50.0% to 10.0%" in notes["A"]
    )
    out = run_backtest(
        prices,
        prefer("A", "B"),
        start=date(2020, 1, 1),
        end=date(2020, 2, 28),
        config=CONFIG,
        benchmarks={},
        turnover=tiny,
        top_n=2,
        cost_rate=0.0,
    )
    seg = out.segments[0]
    bought = {t.ticker_symbol: t.value for t in seg.trades if t.day == date(2020, 1, 31)}
    assert bought["A"] == pytest.approx(NOTIONAL * 0.1) and bought["B"] == pytest.approx(
        NOTIONAL * 0.5
    )
    assert seg.rebalances[0].notes["A"].startswith("trimmed")


def test_delisted_holding_exits_at_its_last_price() -> None:
    a = series("A", [10.0] * 62)
    gone = series("G", [8.0] * 30 + [6.0] * 5, skip=())  # last price 6.0 on day 35, then nothing
    prices = {"A": a, "G": gone}
    out = run_backtest(
        prices,
        prefer("G", "A"),
        start=date(2020, 1, 1),
        end=date(2020, 3, 27),
        config=CONFIG,
        benchmarks={},
        top_n=1,
        cost_rate=0.0,
    )
    seg = out.segments[0]
    assert seg.rebalances[0].targets == {"G": 1.0}
    assert seg.rebalances[1].targets == {
        "G": 1.0
    }  # still listed on 2020-02-18? no: last price 2020-02-18
    exits = [t for t in seg.trades if t.action == "exit"]
    assert len(exits) == 1
    exit_trade = exits[0]
    assert exit_trade.ticker_symbol == "G" and exit_trade.price == 6.0
    assert exit_trade.price_date == gone.last_date
    assert exit_trade.day == pd.bdate_range(date(2020, 1, 1), periods=62)[-1].date()
    # the book was valued at the frozen last price until the exit, then re-deployed into A
    assert seg.equity.loc[pd.Timestamp("2020-03-02")] == pytest.approx(NOTIONAL * 6 / 8)
    assert seg.rebalances[2].targets == {"A": 1.0}


def test_gap_splits_segments_and_links_them() -> None:
    a = series("A", [10.0] * 40 + [20.0] * 40 + [30.0] * 40, skip=range(60, 90))
    out = run_backtest(
        {"A": a},
        prefer("A"),
        start=date(2020, 1, 1),
        end=date(2020, 6, 30),
        config=CONFIG,
        benchmarks={},
        top_n=1,
        cost_rate=0.0,
    )
    assert len(out.segments) == 2 and any("2 segments" in n for n in out.notes)
    first, second = out.segments
    assert first.equity.iloc[0] == NOTIONAL and second.equity.iloc[0] == NOTIONAL  # fresh start
    g1 = first.equity.iloc[-1] / first.equity.iloc[0]
    g2 = second.equity.iloc[-1] / second.equity.iloc[0]
    assert out.linked["total_return"].value == pytest.approx(g1 * g2 - 1)


def test_metrics_by_hand() -> None:
    days = pd.bdate_range("2019-01-01", periods=522)  # two years and a bit
    equity = pd.Series(NOTIONAL * (1.0 + 0.0004) ** np.arange(len(days)), index=days)
    m = series_metrics(equity, CONFIG, provenance=Provenance(table="t"), turnover=0.2)
    total = 1.0004**521 - 1
    assert m["total_return"].value == pytest.approx(total)
    years = (days[-1] - days[0]).days / 365.25
    assert m["cagr"].value == pytest.approx((1 + total) ** (1 / years) - 1)
    assert m["max_drawdown"].value == 0.0 and m["max_drawdown"].status is MeasureStatus.ZERO
    assert m["sharpe"].status is MeasureStatus.NOT_MEANINGFUL  # constant growth: zero vol
    assert m["monthly_win_rate"].value == 1.0 and m["avg_monthly_turnover"].value == 0.2
    assert m["best_year"].reason in ("2019", "2020") and m["worst_year"].reason in ("2019", "2020")
    assert m["calmar"].status is MeasureStatus.NOT_MEANINGFUL
    short = series_metrics(equity.iloc[:100], CONFIG, provenance=Provenance(table="t"))
    assert (
        short["cagr"].status is MeasureStatus.UNAVAILABLE
        and short["best_year"].status is MeasureStatus.UNAVAILABLE
    )
    rel = relative_metrics(equity, equity, CONFIG, provenance=Provenance(table="t"))
    assert rel["beta"].value == pytest.approx(1.0) and rel["alpha"].value == pytest.approx(
        0.0, abs=1e-12
    )
    assert rel["excess_return"].status is MeasureStatus.ZERO
    assert rel["information_ratio"].status is MeasureStatus.NOT_MEANINGFUL
    double = equity * np.linspace(1.0, 1.5, len(equity))
    rel2 = relative_metrics(double, equity, CONFIG, provenance=Provenance(table="t"))
    assert (rel2["alpha"].value or 0) > 0 and (rel2["excess_return"].value or 0) > 0
    few = relative_metrics(
        equity.iloc[:120], equity.iloc[:120], CONFIG, provenance=Provenance(table="t")
    )
    assert few["alpha"].status is MeasureStatus.UNAVAILABLE and "minimum 12" in (
        few["alpha"].reason or ""
    )


# --- real data --------------------------------------------------------------------------


@pytest.fixture
def populated(fixture_db_path: Path, tmp_path: Path) -> tuple[Settings, NseScraperSource, Path]:
    db = tmp_path / "scraper.sqlite3"
    db.write_bytes(fixture_db_path.read_bytes())
    settings = Settings(
        NSE_SCRAPER_DB_PATH=str(db),
        NSE_SCRAPER_PATH=str(tmp_path / "scraper"),
        ANALYTICS_DB_PATH=str(tmp_path / "a.sqlite3"),
    )
    upgrade_analytics_db(settings.analytics_db_path)
    source = NseScraperSource(settings)
    classify_instruments(settings, source)
    return settings, source, db


MARKET_ONLY = market_only_ranking(AnalyticsConfig(backtest=BacktestConfig(top_n=3)))


def _positions(settings: Settings, source: NseScraperSource, start: date, end: date):
    with analytics_session(settings) as session:
        index = ClassificationIndex(load_classifications(session))
    ctx = build_context(source, index, MARKET_ONLY)
    prices = stock_prices(ctx.prices, index)
    out = run_backtest(
        prices,
        ranking_signal(ctx),
        start=start,
        end=end,
        config=MARKET_ONLY,
        benchmarks={"^NASI": ctx.prices["^NASI"]},
        turnover=turnover_lookup(ctx),
        top_n=3,
    )
    return out


def test_look_ahead_mutation_leaves_earlier_positions_identical(
    populated: tuple[Settings, NseScraperSource, Path],
) -> None:
    settings, source, db = populated
    cutoff = date(2019, 6, 30)
    before = _positions(settings, source, date(2019, 1, 1), date(2019, 12, 31))
    assert before.segments and len(before.segments[0].rebalances) == 12
    early_trades = [t for t in before.segments[0].trades if t.day <= cutoff]
    early_targets = [r.targets for r in before.segments[0].rebalances if r.day <= cutoff]
    assert early_trades and any(early_targets)
    # perturb everything after the cutoff: triple every close and volume
    with sqlite3.connect(db) as conn:
        conn.execute(
            "update stock_observations set close_price = close_price * 3, volume = volume * 3 "
            "where trade_date > ?",
            (cutoff.isoformat(),),
        )
        conn.commit()
    after = _positions(settings, source, date(2019, 1, 1), date(2019, 12, 31))
    assert [t for t in after.segments[0].trades if t.day <= cutoff] == early_trades
    assert [r.targets for r in after.segments[0].rebalances if r.day <= cutoff] == early_targets
    assert (
        before.segments[0]
        .equity.loc[: pd.Timestamp(cutoff)]
        .equals(after.segments[0].equity.loc[: pd.Timestamp(cutoff)])
    )
    # and the perturbation did change what followed
    assert not before.segments[0].equity.equals(after.segments[0].equity)


def test_delisted_keno_is_held_and_exits_on_real_data(
    populated: tuple[Settings, NseScraperSource, Path],
) -> None:
    settings, source, _ = populated
    with analytics_session(settings) as session:
        index = ClassificationIndex(load_classifications(session))
    ctx = build_context(source, index, MARKET_ONLY)
    prices = stock_prices(ctx.prices, index)
    out = run_backtest(
        prices,
        prefer("KENO", "KCB", "EQTY"),
        start=date(2019, 7, 1),
        end=date(2019, 12, 31),
        config=MARKET_ONLY,
        benchmarks={},
        top_n=2,
        cost_rate=0.0,
    )
    seg = out.segments[0]
    assert "KENO" in seg.rebalances[0].targets  # listed in July 2019
    exits = [t for t in seg.trades if t.action == "exit"]
    assert len(exits) == 1 and exits[0].ticker_symbol == "KENO"
    assert exits[0].price_date == date(2019, 10, 11) and exits[0].day == date(2019, 10, 31)
    last_close = ctx.prices["KENO"].close_on_or_before(date(2019, 10, 11))
    assert last_close is not None and exits[0].price == last_close[1]
    assert "KENO" not in seg.rebalances[-1].targets


def test_run_model_backtest_stores_everything(
    populated: tuple[Settings, NseScraperSource, Path],
) -> None:
    settings, source, _ = populated
    result = run_model_backtest(
        settings,
        source,
        start=date(2019, 1, 1),
        end=date(2019, 12, 31),
        name="test",
        config=MARKET_ONLY,
    )
    assert result.result.segments and result.equal_weight is not None
    with analytics_session(settings) as session:
        runs = load_backtest_runs(session)
        assert [r.name for r in runs] == ["test", "test:equal_weight"]
        run = runs[0]
        assert (
            run.model_name == "factor-model-market-only"
            and run.top_n == 3
            and run.status == "known"
        )
        assert run.weights == {"momentum": 0.5, "risk": 0.3, "liquidity": 0.2}
        assert run.costs["rate"] == pytest.approx(RATE) and run.benchmarks == ["^NASI", "^N20I"]
        rows = load_backtest_results(session, run.id)
        metrics = {(r.segment, r.series, r.metric): r for r in rows}
        assert metrics[("1", "portfolio", "total_return")].status == "known"
        assert metrics[("1", "^NASI", "total_return")].status == "known"
        assert ("1", "portfolio", "alpha_vs_^NASI") in metrics
        assert metrics[("linked", "portfolio", "total_return")].value == pytest.approx(
            result.result.linked["total_return"].value
        )
        positions = load_backtest_positions(session, run.id)
        assert positions and all(p.weight is not None for p in positions if p.action == "buy")
        equity = load_backtest_equity(session, run.id)
        assert (
            len(equity) == len(result.result.segments[0].equity)
            and equity[0].benchmarks is not None
        )
        ew = runs[1]
        assert ew.purpose == "benchmark" and ew.costs["rate"] == 0.0
    headline = result.headline()
    assert headline["segments"][0]["portfolio"]["total_return"] is not None
    assert "equal_weight" in headline["segments"][0]


def test_weight_search_reports_out_of_sample(
    populated: tuple[Settings, NseScraperSource, Path],
) -> None:
    settings, source, _ = populated
    candidates = {
        "momentum_heavy": {"momentum": 0.7, "risk": 0.2, "liquidity": 0.1},
        "risk_heavy": {"momentum": 0.2, "risk": 0.6, "liquidity": 0.2},
    }
    out = weight_search(
        settings,
        source,
        candidates=candidates,
        start=date(2018, 7, 1),
        split=date(2019, 1, 1),
        end=date(2019, 6, 30),
        config=MARKET_ONLY,
        top_n=3,
    )
    assert set(out.in_sample) == set(candidates) == set(out.out_of_sample)
    assert out.best_in_sample in candidates
    assert all(m["total_return"].is_known for m in out.in_sample.values())
    with analytics_session(settings) as session:
        purposes = {r.purpose for r in load_backtest_runs(session)}
        assert purposes == {"weight_search:in_sample", "weight_search:out_of_sample"}
        first = load_backtest_runs(session, purpose="weight_search:in_sample")[0]
        assert first.model_version.startswith("search:") and first.end_date == date(2019, 1, 1)
    with pytest.raises(ValueError, match="start < split < end"):
        weight_search(
            settings,
            source,
            candidates=candidates,
            start=date(2019, 1, 1),
            split=date(2018, 1, 1),
            end=date(2019, 6, 30),
            config=MARKET_ONLY,
        )


def test_cli_backtest_commands(
    populated: tuple[Settings, NseScraperSource, Path], monkeypatch: pytest.MonkeyPatch
) -> None:
    from typer.testing import CliRunner

    from app.cli.main import app
    from app.web.config import get_settings

    settings, _, _ = populated
    monkeypatch.setenv("ANALYTICS_DB_PATH", str(settings.analytics_db_path))
    monkeypatch.setenv("NSE_SCRAPER_DB_PATH", str(settings.scraper_database_path))
    monkeypatch.setenv("NSE_SCRAPER_PATH", str(settings.nse_scraper_path))
    get_settings.cache_clear()
    try:
        runner = CliRunner()
        run = runner.invoke(
            app,
            [
                "analytics",
                "backtest",
                "run",
                "--from",
                "2019-01-01",
                "--to",
                "2019-06-30",
                "--top-n",
                "2",
                "--market-only",
                "--name",
                "cli",
            ],
        )
        assert run.exit_code == 0, run.output
        assert (
            "segment 1" in run.output and "linked:" in run.output and "costs_paid" in run.output
        )  # rich truncates the table in the test terminal; the summary lines survive
        compare = runner.invoke(app, ["analytics", "backtest", "compare"])
        assert compare.exit_code == 0, compare.output
        assert "1 cli (run)" in compare.output
        assert "2 cli:equal_weight (benchmark)" in compare.output
        bad = runner.invoke(
            app,
            [
                "analytics",
                "backtest",
                "weight-search",
                "--from",
                "2019-01-01",
                "--split",
                "2019-03-01",
                "--to",
                "2019-06-30",
                "--candidate",
                "oops",
            ],
        )
        assert bad.exit_code != 0
    finally:
        get_settings.cache_clear()


def test_benchmark_with_a_hole_is_measured_on_its_longest_stretch() -> None:
    a = series("A", [10.0 + i * 0.01 for i in range(400)])
    bench = series("^B", [100.0 + i * 0.05 for i in range(400)], skip=range(150, 200))
    from app.web.services.analytics.backtesting.engine import benchmark_level, longest_continuous

    days = [d.date() for d in a.dates]
    level = benchmark_level(bench, days, NOTIONAL, 14)
    assert level is not None and level.isna().sum() == 40 and level.iloc[0] == NOTIONAL
    stretch = longest_continuous(level)
    assert not stretch.isna().any() and len(stretch) == 200  # the run after the hole
    out = run_backtest(
        {"A": a},
        prefer("A"),
        start=days[0],
        end=days[-1],
        config=CONFIG,
        benchmarks={"^B": bench},
        top_n=1,
        cost_rate=0.0,
    )
    seg = out.segments[0]
    bench_metrics = seg.metrics["^B"]
    assert bench_metrics["total_return"].is_known
    assert "longest continuous stretch" in (bench_metrics["total_return"].provenance[0].note or "")
    assert seg.metrics["portfolio"][
        "alpha_vs_^B"
    ].status is not MeasureStatus.UNAVAILABLE or "minimum" in (
        seg.metrics["portfolio"]["alpha_vs_^B"].reason or ""
    )
    assert seg.metrics["portfolio"]["excess_return_vs_^B"].is_known
