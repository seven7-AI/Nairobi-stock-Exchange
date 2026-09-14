"""Ranking engine: composite score, gates, detectors, explanation, and the job on real data.

codegraph explore "rank_universe compute_rankings value_trap compounder_score"
"""

from __future__ import annotations

from datetime import date
from pathlib import Path

import pytest
from sqlalchemy import select

from app.web.config import Settings
from app.web.db.analytics import analytics_session
from app.web.db.analytics.models import JobRun, ModelRegistryEntry
from app.web.db.analytics.services.stock_rankings import load_rankings
from app.web.services.analytics.classification.service import classify_instruments
from app.web.services.analytics.config import DEFAULT_CONFIG as CONFIG
from app.web.services.analytics.config import AnalyticsConfig, RankingConfig
from app.web.services.analytics.factors import compute_factors
from app.web.services.analytics.fundamentals import compute_fundamentals
from app.web.services.analytics.liquidity import compute_liquidity
from app.web.services.analytics.measure import Measure, MeasureStatus
from app.web.services.analytics.momentum import compute_momentum
from app.web.services.analytics.ranking import (
    CLASSES,
    FactorInput,
    TrapRisk,
    compute_rankings,
    rank_universe,
)
from app.web.services.analytics.ranking.engine import (
    classify,
    composite_score,
    compounder_score,
    value_trap,
)
from app.web.services.analytics.returns import compute_returns
from app.web.services.analytics.risk import compute_risk
from app.web.services.analytics.store import upgrade_analytics_db
from app.web.services.analytics.valuation_metrics import compute_valuation_metrics
from app.web.services.market_data.sources import NseScraperSource

pytestmark = pytest.mark.unit


def _factor(name: str, pct: float | None, coverage: float = 1.0) -> FactorInput:
    return FactorInput(
        name, pct, None, None, coverage, "known" if pct is not None else "unavailable"
    )


def test_composite_renormalises_over_available_factors() -> None:
    factors = {
        "quality": _factor("quality", 80.0),
        "value": _factor("value", 60.0, coverage=0.5),
        "momentum": _factor("momentum", 40.0),
        "growth": _factor("growth", None, coverage=0.0),
    }
    overall, confidence, per_factor = composite_score(factors, CONFIG)
    # weights quality .25, value .20, momentum .15 -> available share 0.60 of 1.00
    expected = (0.25 * 80 + 0.20 * 60 + 0.15 * 40) / 0.60
    assert overall.is_known and overall.value == pytest.approx(expected)
    mean_coverage = (0.25 * 1.0 + 0.20 * 0.5 + 0.15 * 1.0) / 0.60
    assert confidence == pytest.approx(0.60 * mean_coverage)
    assert per_factor["growth"] is None and per_factor["risk"] is None
    assert per_factor["quality"] == 80.0


def test_composite_unavailable_below_minimum_weight() -> None:
    overall, confidence, _ = composite_score({"liquidity": _factor("liquidity", 90.0)}, CONFIG)
    assert overall.status is MeasureStatus.UNAVAILABLE
    assert "5% of factor weight available" in (overall.reason or "")
    assert "missing quality" in (overall.reason or "")
    assert confidence == 0.0
    assert composite_score({}, CONFIG)[0].status is MeasureStatus.UNAVAILABLE


def test_classification_bands_and_caps() -> None:
    known = Measure.known
    assert classify(known(85.0), 0.9, 80.0, TrapRisk.LOW, CONFIG) == ("Strong Candidate", [])
    assert classify(known(65.0), 0.9, 80.0, None, CONFIG)[0] == "Buy Candidate"
    assert classify(known(50.0), 0.9, 80.0, None, CONFIG)[0] == "Watch"
    assert classify(known(35.0), 0.9, 80.0, None, CONFIG)[0] == "Neutral"
    assert classify(known(20.0), 0.9, 80.0, None, CONFIG)[0] == "Weak"
    assert classify(known(19.9), 0.9, 80.0, None, CONFIG)[0] == "Avoid"
    # caps only pull a class down to Watch, never up
    label, caps = classify(known(85.0), 0.9, 10.0, TrapRisk.LOW, CONFIG)
    assert label == "Watch" and caps == ["liquidity score 10 below the 20 gate"]
    label, caps = classify(known(85.0), 0.3, 80.0, None, CONFIG)
    assert label == "Watch" and "confidence 30%" in caps[0]
    label, caps = classify(known(85.0), 0.9, 80.0, TrapRisk.HIGH, CONFIG)
    assert label == "Watch" and caps == ["value-trap risk HIGH"]
    label, caps = classify(known(10.0), 0.9, 10.0, TrapRisk.HIGH, CONFIG)
    assert label == "Avoid" and caps == []  # already below Watch: the gates change nothing
    assert classify(known(50.0), 0.1, 10.0, TrapRisk.HIGH, CONFIG) == ("Watch", [])
    assert classify(Measure.unavailable("x"), 0.0, None, None, CONFIG) == (None, [])
    assert classify(known(85.0), 0.9, None, None, CONFIG)[0] == "Strong Candidate"
    assert tuple(CLASSES) == (
        "Strong Candidate",
        "Buy Candidate",
        "Watch",
        "Neutral",
        "Weak",
        "Avoid",
    )


def _m(values: dict[str, float]) -> dict[str, Measure]:
    return {k: Measure.known(v) for k, v in values.items()}


def test_value_trap_high_with_three_signals() -> None:
    metrics = _m(
        {
            "pe_vs_market": -0.40,
            "pb": 0.6,
            "revenue_growth_1y": -0.05,
            "eps_growth_1y": -0.20,
            "roe_trend": -1.0,
            "momentum_12m_1m": 0.05,
            "fcf": 100.0,
        }
    )
    detector = value_trap(metrics, CONFIG)
    assert detector.measure.value == float(TrapRisk.HIGH)
    assert detector.signals == (
        "P/E -40% vs the market",
        "P/B 0.60",
        "revenue fell",
        "EPS fell",
        "ROE deteriorating",
    )
    assert (detector.measure.reason or "").startswith("HIGH: cheap on P/E -40% vs the market")


def test_value_trap_medium_low_and_unavailable() -> None:
    cheap_one_signal = _m({"pb": 0.5, "fcf": -10.0, "momentum_12m_1m": 0.2})
    assert value_trap(cheap_one_signal, CONFIG).measure.value == float(TrapRisk.MEDIUM)
    cheap_clean = _m({"pb": 0.5, "fcf": 10.0, "momentum_12m_1m": 0.2, "roe_trend": 1.0})
    low = value_trap(cheap_clean, CONFIG)
    assert low.measure.status is MeasureStatus.ZERO and low.measure.value == 0.0
    assert low.measure.reason == "LOW: cheap on P/B 0.50; no deterioration signals"
    not_cheap = _m({"pe_vs_market": 0.5, "pb": 3.0, "dividend_yield": 0.02, "fcf": -1.0})
    assert value_trap(not_cheap, CONFIG).measure.value == float(TrapRisk.LOW)
    assert value_trap(not_cheap, CONFIG).measure.reason == "LOW: negative free cash flow"
    # not cheap but deteriorating on many fronts is still worth a MEDIUM
    many = _m(
        {
            "pb": 3.0,
            "fcf": -1.0,
            "eps_growth_1y": -0.1,
            "revenue_growth_1y": -0.1,
            "dividend_cut": 1.0,
        }
    )
    assert value_trap(many, CONFIG).measure.value == float(TrapRisk.MEDIUM)
    unknown = value_trap(_m({"fcf": -1.0}), CONFIG)
    assert unknown.measure.status is MeasureStatus.UNAVAILABLE and unknown.signals == ()
    # a thin liquidity score counts; a missing one does not fire
    thin = _m({"pb": 0.5, "liquidity_score": 10.0, "fcf": -1.0, "eps_growth_1y": -0.5})
    assert value_trap(thin, CONFIG).measure.value == float(TrapRisk.HIGH)


def test_compounder_score_and_applicability() -> None:
    metrics = _m(
        {
            "revenue_cagr_3y": 0.12,
            "eps_cagr_3y": 0.10,
            "revenue_growth_1y": 0.08,
            "roe": 0.22,
            "roa": 0.03,
            "fcf": 500.0,
            "fcf_margin": 0.12,
            "debt_to_equity": 0.4,
            "net_margin_trend": 0.0,
            "dividend_cagr_3y": 0.05,
            "momentum_12m_1m": 0.10,
        }
    )
    industrial = compounder_score(metrics, CONFIG, sector_code="manufacturing")
    assert industrial.measure.value == pytest.approx(100.0 * 10 / 11)  # ROA 3% < 5%
    assert "ROA" not in industrial.signals and "leverage under control" in industrial.signals
    bank = compounder_score(metrics, CONFIG, sector_code="banking")
    # banks: ROA threshold 1% and leverage not judged -> 10 criteria, all met
    assert bank.measure.value == pytest.approx(100.0)
    assert "leverage under control" not in bank.signals and "ROA" in bank.signals
    few = compounder_score(_m({"roe": 0.3, "fcf": 1.0}), CONFIG, sector_code="banking")
    assert few.measure.status is MeasureStatus.UNAVAILABLE
    assert "2 of 10 criteria" in (few.measure.reason or "")
    none_met = {k: Measure.known(-abs(m.value or 0) - 1) for k, m in metrics.items()}
    zero = compounder_score(none_met, CONFIG, sector_code="banking")
    assert zero.measure.status is MeasureStatus.ZERO and zero.signals == ()


def test_rank_universe_orders_and_explains() -> None:
    def full(pct: float) -> dict[str, FactorInput]:
        return {name: _factor(name, pct) for name in CONFIG.ranking.weights}

    factors = {
        "A": full(90.0),
        "B": full(70.0),
        "C": full(30.0),
        "D": {"liquidity": _factor("liquidity", 50.0)},
    }
    metrics = {
        "A": _m({"pb": 0.5, "fcf": -1.0, "eps_growth_1y": -0.3, "revenue_growth_1y": -0.1}),
        "B": _m({"liquidity_score": 5.0}),
        "C": {},
        "D": {},
    }
    groups: dict[str, dict[str, str | None]] = {
        "sector": {"A": "banking", "B": "banking", "C": "tea", "D": "tea"},
        "industry": {"A": "x", "B": None, "C": "y", "D": "y"},
    }
    out = {r.ticker_symbol: r for r in rank_universe(factors, metrics, groups, CONFIG)}
    assert [out[t].market_rank for t in "ABCD"] == [1, 2, 3, None]
    assert out["A"].sector_rank == 1 and out["B"].sector_rank == 2 and out["C"].sector_rank == 1
    assert out["A"].industry_rank == 1 and out["B"].industry_rank is None
    assert out["A"].classification == "Watch"  # trap HIGH caps a Strong Candidate
    assert out["A"].value_trap.measure.value == float(TrapRisk.HIGH)
    assert out["B"].classification == "Watch"  # liquidity gate
    assert out["C"].classification == "Weak"  # 30 sits in the [20, 35) band
    assert out["D"].classification is None and out["D"].overall.status is MeasureStatus.UNAVAILABLE
    assert out["C"].compounder.measure.status is MeasureStatus.UNAVAILABLE

    explanation = out["A"].explanation
    assert set(explanation) == {
        "ticker",
        "model",
        "overall",
        "confidence",
        "classification",
        "factors",
        "positive_factors",
        "negative_factors",
        "value_trap",
        "compounder",
        "disclaimer",
        "ranks",
    }
    assert explanation["model"] == {"name": "factor-model", "version": "1"}
    assert explanation["overall"]["value"] == pytest.approx(90.0)
    assert set(explanation["factors"]) == set(CONFIG.ranking.weights)
    assert explanation["factors"]["quality"]["weight"] == 0.25
    assert any(p.startswith("Strong quality") for p in explanation["positive_factors"])
    assert any(
        n.startswith("Value-trap risk HIGH: cheap on P/B 0.50; ")
        for n in explanation["negative_factors"]
    )
    assert "Capped at Watch: value-trap risk HIGH" in explanation["negative_factors"]
    assert explanation["ranks"] == {"market": 1, "market_of": 3, "sector": 1, "industry": 1}
    assert explanation["value_trap"]["risk"]["value"] == 2.0
    assert "not investment advice" in explanation["disclaimer"]
    assert any("not scored" in n for n in out["D"].explanation["negative_factors"])


def test_custom_weights_change_the_model_hash() -> None:
    custom = AnalyticsConfig(ranking=RankingConfig(weights={"momentum": 1.0}, model_version="2"))
    assert custom.config_hash != CONFIG.config_hash
    overall, confidence, _ = composite_score({"momentum": _factor("momentum", 42.0)}, custom)
    assert overall.value == 42.0 and confidence == 1.0


# --- the job on real data (fixture) ---------------------------------------------------


@pytest.fixture
def populated(fixture_db_path: Path, tmp_path: Path) -> Settings:
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
    compute_momentum(settings, source, as_of=as_of)
    compute_risk(settings, source, as_of=as_of, with_correlation_matrix=False)
    compute_liquidity(settings, source, as_of=as_of)
    compute_fundamentals(settings, source, as_of=as_of)
    compute_valuation_metrics(settings, source, as_of=as_of)
    compute_factors(settings, as_of=as_of)
    return settings


def test_compute_rankings_on_real_factors(populated: Settings) -> None:
    as_of = date(2024, 12, 31)
    result = compute_rankings(populated, as_of=as_of)
    assert set(result.universe) == {"KCB", "EQTY", "SCOM", "KEGN", "ABSA", "NCBA", "KENO", "ACCS"}
    assert result.rows_written == 8
    assert result.scored >= 4  # at least the four with statements clear the weight gate
    assert result.classes.get("unscored", 0) >= 1  # KENO: delisted, no factor known
    with analytics_session(populated) as session:
        rows = {r.ticker_symbol: r for r in load_rankings(session, as_of_date=as_of)}
        assert set(rows) == set(result.universe)
        ranked = sorted(
            (r for r in rows.values() if r.market_rank is not None),
            key=lambda r: r.market_rank or 0,
        )
        assert [r.market_rank for r in ranked] == list(range(1, len(ranked) + 1))
        scores = [r.overall_score or 0.0 for r in ranked]
        assert scores == sorted(scores, reverse=True)
        keno = rows["KENO"]
        assert keno.status == "unavailable" and keno.classification is None
        assert keno.market_rank is None and keno.explanation["ranks"]["market"] is None
        kcb = rows["KCB"]
        assert kcb.status == "known" and kcb.classification in CLASSES
        assert kcb.model_name == "factor-model" and kcb.model_version == "1"
        assert kcb.quality_score is not None and kcb.momentum_score is not None
        assert kcb.explanation["factors"]["quality"]["percentile_market"] == kcb.quality_score
        assert kcb.value_trap_risk in (0, 1, 2)  # KCB has P/E, P/B and yield on the date
        assert kcb.compounder_score is not None
        assert kcb.sector_rank is not None  # banking has four members with momentum
        model = session.execute(select(ModelRegistryEntry)).scalars().one()
        assert (model.name, model.version, model.kind) == ("factor-model", "1", "factor")
        assert model.params["weights"]["quality"] == 0.25
        assert model.id == result.model_id
        run = session.execute(select(JobRun).where(JobRun.job_name == "rankings")).scalars().one()
        assert run.status == "succeeded" and (run.details or {})["scored"] == result.scored
    # idempotent: same rows, same model row
    again = compute_rankings(populated, as_of=as_of)
    assert again.rows_written == result.rows_written and again.model_id == result.model_id
    with analytics_session(populated) as session:
        assert len(load_rankings(session, as_of_date=as_of)) == 8
        assert len(session.execute(select(ModelRegistryEntry)).scalars().all()) == 1


def test_cli_compute_and_show_rankings(
    populated: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    from typer.testing import CliRunner

    from app.cli.main import app
    from app.web.config import get_settings

    monkeypatch.setenv("ANALYTICS_DB_PATH", str(populated.analytics_db_path))
    monkeypatch.setenv("NSE_SCRAPER_DB_PATH", str(populated.scraper_database_path))
    monkeypatch.setenv("NSE_SCRAPER_PATH", str(populated.nse_scraper_path))
    get_settings.cache_clear()
    try:
        runner = CliRunner()
        empty = runner.invoke(app, ["analytics", "rank"])
        assert empty.exit_code == 1 and "no rankings stored" in empty.output
        result = runner.invoke(app, ["analytics", "compute", "rankings", "--as-of", "2024-12-31"])
        assert result.exit_code == 0, result.output
        assert "rows written 8" in result.output
        shown = runner.invoke(app, ["analytics", "rank", "--top", "3"])
        assert shown.exit_code == 0, shown.output
        assert "2024-12-31" in shown.output and "factor-model" in shown.output
        one = runner.invoke(app, ["analytics", "rank", "--ticker", "kcb"])
        assert one.exit_code == 0, one.output
        assert '"disclaimer"' in one.output
    finally:
        get_settings.cache_clear()
