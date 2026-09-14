"""Factor engine: z-scores, direction, coverage, group ranks, and the job on real metrics.

codegraph explore "score_factors compute_factors winsorised_zscores"
"""

from __future__ import annotations

from datetime import date
from pathlib import Path

import pytest
from sqlalchemy import select

from app.web.config import Settings
from app.web.db.analytics import analytics_session
from app.web.db.analytics.models import CalcVersion
from app.web.db.analytics.services.factor_scores import load_factor_scores, metric_table_for
from app.web.services.analytics.classification.service import classify_instruments
from app.web.services.analytics.config import DEFAULT_CONFIG as CONFIG
from app.web.services.analytics.config import (
    AnalyticsConfig,
    FactorConfig,
    FactorDefinition,
    FactorInput,
)
from app.web.services.analytics.factors import compute_factors, score_factors
from app.web.services.analytics.factors.engine import (
    rank_within_groups,
    score_factor,
    winsorised_zscores,
)
from app.web.services.analytics.fundamentals import compute_fundamentals
from app.web.services.analytics.liquidity import compute_liquidity
from app.web.services.analytics.measure import MeasureStatus
from app.web.services.analytics.momentum import compute_momentum
from app.web.services.analytics.returns import compute_returns
from app.web.services.analytics.risk import compute_risk
from app.web.services.analytics.store import upgrade_analytics_db
from app.web.services.analytics.valuation_metrics import compute_valuation_metrics
from app.web.services.market_data.sources import NseScraperSource

pytestmark = pytest.mark.unit


def test_winsorised_zscores() -> None:
    values = {"A": 1.0, "B": 2.0, "C": 3.0, "D": 4.0, "E": 100.0}
    z = winsorised_zscores(values, lower=0.0, upper=0.8)  # E clipped to the 80th percentile
    assert z["E"] == max(z.values()) and z["A"] == min(z.values())
    assert abs(sum(z.values())) < 1e-9  # centred
    assert winsorised_zscores({"A": 1.0, "B": 2.0}, lower=0.05, upper=0.95) == {"A": 0.0, "B": 0.0}
    assert winsorised_zscores({"A": 5.0, "B": 5.0, "C": 5.0}, lower=0.05, upper=0.95) == {
        "A": 0.0,
        "B": 0.0,
        "C": 0.0,
    }
    assert winsorised_zscores({}, lower=0.05, upper=0.95) == {}


def test_direction_and_weights() -> None:
    definition = FactorDefinition(
        name="value",
        inputs=(
            FactorInput(metric="pe", source="fundamental", direction=-1),
            FactorInput(metric="fcf_yield", source="fundamental", weight=2.0),
        ),
    )
    metrics = {
        ("fundamental", "pe"): {"CHEAP": 3.0, "MID": 8.0, "DEAR": 20.0},
        ("fundamental", "fcf_yield"): {"CHEAP": 0.15, "MID": 0.08, "DEAR": 0.01},
    }
    out = score_factor(definition, metrics, ["CHEAP", "MID", "DEAR"], CONFIG)
    cheap, _mid, dear = (out[t][0].value for t in ("CHEAP", "MID", "DEAR"))
    assert cheap is not None and dear is not None and cheap > 0 > dear  # low P/E scores high
    assert out["CHEAP"][1] == 1.0  # full coverage
    pe_input = next(i for i in out["CHEAP"][2] if i.metric == "pe")
    assert pe_input.z is not None and pe_input.z > 0 and pe_input.value == 3.0


def test_coverage_rule() -> None:
    definition = FactorDefinition(
        name="quality",
        inputs=(
            FactorInput(metric="roe", source="fundamental"),
            FactorInput(metric="roa", source="fundamental"),
            FactorInput(metric="net_margin", source="fundamental"),
        ),
    )
    metrics = {
        ("fundamental", "roe"): {"A": 0.2, "B": 0.1, "C": 0.05},
        ("fundamental", "roa"): {"A": 0.02, "B": 0.01},
        ("fundamental", "net_margin"): {"A": 0.3},
    }
    out = score_factor(definition, metrics, ["A", "B", "C"], CONFIG)
    assert out["A"][1] == pytest.approx(1.0)
    assert out["B"][1] == pytest.approx(2 / 3) and out["B"][0].is_known
    assert out["C"][1] == pytest.approx(1 / 3)
    assert out["C"][0].status is MeasureStatus.UNAVAILABLE
    assert "coverage 33%" in (out["C"][0].reason or "")
    strict = AnalyticsConfig(factors=FactorConfig(min_coverage=0.9))
    assert (
        score_factor(definition, metrics, ["A", "B", "C"], strict)["B"][0].status
        is MeasureStatus.UNAVAILABLE
    )


def test_rank_within_groups_and_minimum_size() -> None:
    scores = {"A": 1.0, "B": 2.0, "C": 3.0, "D": 4.0, "E": 0.5}
    groups: dict[str, dict[str, str | None]] = {
        "market": dict.fromkeys(scores, "market"),
        "sector": {"A": "bank", "B": "bank", "C": "bank", "D": "tea", "E": "tea"},
        "industry": {"A": "x", "B": None, "C": "x", "D": "y", "E": "y"},
    }
    ranks = rank_within_groups(scores, groups, min_group_size=3)
    assert ranks["D"]["market"] == 100.0 and ranks["E"]["market"] == 20.0
    assert ranks["C"]["sector"] == 100.0 and ranks["A"]["sector"] == pytest.approx(100 / 3)
    assert ranks["D"]["sector"] is None  # tea has two members
    assert ranks["B"]["industry"] is None and ranks["A"]["industry"] is None  # unknown / too small
    ranks2 = rank_within_groups(scores, groups, min_group_size=2)
    assert ranks2["A"]["industry"] == 50.0 and ranks2["D"]["sector"] == 100.0


def test_score_factors_reports_every_factor_and_group_sizes() -> None:
    config = AnalyticsConfig(
        factors=FactorConfig(
            factors=(
                FactorDefinition(
                    name="momentum", inputs=(FactorInput(metric="momentum_6m", source="market"),)
                ),
                FactorDefinition(
                    name="value",
                    inputs=(FactorInput(metric="pe", source="fundamental", direction=-1),),
                ),
            ),
            min_group_size=2,
        )
    )
    metrics = {
        ("market", "momentum_6m"): {"A": 0.1, "B": 0.2, "C": -0.1},
        ("fundamental", "pe"): {"A": 5.0},
    }
    groups: dict[str, dict[str, str | None]] = {
        "sector": {"A": "bank", "B": "bank", "C": "tea"},
        "industry": {"A": None, "B": None, "C": None},
    }
    out = score_factors(metrics, ["A", "B", "C"], groups, config)
    assert {(s.ticker_symbol, s.factor) for s in out} == {
        (t, f) for t in "ABC" for f in ("momentum", "value")
    }
    momentum = {s.ticker_symbol: s for s in out if s.factor == "momentum"}
    assert momentum["B"].percentile_market == 100.0 and momentum["B"].percentile_sector == 100.0
    assert momentum["C"].percentile_sector is None and momentum["C"].percentile_industry is None
    assert momentum["A"].group_sizes == {"market": 3, "sector": 2}
    value = {s.ticker_symbol: s for s in out if s.factor == "value"}
    assert value["A"].measure.status is MeasureStatus.ZERO  # alone: no dispersion, z = 0
    assert value["B"].measure.status is MeasureStatus.UNAVAILABLE


# --- the job on real metrics (fixture) ------------------------------------------------


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
    return settings


def test_metric_table_reads_only_known_values(populated: Settings) -> None:
    with analytics_session(populated) as session:
        table = metric_table_for(session, date(2024, 12, 31))
    assert ("market", "momentum_12m_1m") in table and "KCB" in table[("market", "momentum_12m_1m")]
    assert ("fundamental", "roe") in table and set(table[("fundamental", "roe")]) <= {
        "KCB",
        "EQTY",
        "SCOM",
        "KEGN",
    }
    assert "KENO" not in table.get(
        ("market", "momentum_12m_1m"), {}
    )  # delisted: unavailable rows excluded


def test_compute_factors_on_real_metrics(populated: Settings) -> None:
    as_of = date(2024, 12, 31)
    result = compute_factors(populated, as_of=as_of)
    # operating sectors only, as classified on the date: no indices, and KPC/SKL only
    # list in 2026
    assert set(result.universe) == {"KCB", "EQTY", "SCOM", "KEGN", "ABSA", "NCBA", "KENO", "ACCS"}
    assert result.known_counts["momentum"] >= 6
    assert result.known_counts["quality"] == 4  # the four with statements
    with analytics_session(populated) as session:
        rows = {
            (r.ticker_symbol, r.factor): r for r in load_factor_scores(session, as_of_date=as_of)
        }
        kcb_mom = rows[("KCB", "momentum")]
        assert kcb_mom.status == "known" and kcb_mom.percentile_market is not None
        assert kcb_mom.percentile_sector is not None  # KCB, EQTY, ABSA, NCBA are banking
        assert kcb_mom.inputs and any(
            i["metric"] == "momentum_12m_1m" and i["status"] == "known" for i in kcb_mom.inputs
        )
        keno = rows[("KENO", "momentum")]
        assert keno.status == "unavailable" and keno.coverage == 0.0
        kcb_quality = rows[("KCB", "quality")]
        assert kcb_quality.status == "known" and kcb_quality.coverage >= 0.5
        assert (
            kcb_quality.percentile_sector is None
        )  # only KCB and EQTY have fundamentals in banking
        version_ids = {r.calc_version_id for r in rows.values()}
        assert len(version_ids) == 1
    again = compute_factors(populated, as_of=as_of)
    assert again.rows_written == result.rows_written
    with analytics_session(populated) as session:
        assert len(load_factor_scores(session, as_of_date=as_of)) == result.rows_written


def test_changed_factor_definition_is_a_new_version(populated: Settings) -> None:
    as_of = date(2024, 12, 31)
    compute_factors(populated, as_of=as_of)
    slim = AnalyticsConfig(
        factors=FactorConfig(
            factors=(
                FactorDefinition(
                    name="momentum", inputs=(FactorInput(metric="momentum_6m", source="market"),)
                ),
            )
        )
    )
    compute_factors(populated, as_of=as_of, config=slim)
    with analytics_session(populated) as session:
        versions = session.execute(select(CalcVersion)).scalars().all()
        assert len(versions) == 2
        momentum = load_factor_scores(
            session, as_of_date=as_of, ticker_symbol="KCB", factor="momentum"
        )
        assert len(momentum) == 2 and len({m.calc_version_id for m in momentum}) == 2


def test_cli_compute_factors(populated: Settings, monkeypatch: pytest.MonkeyPatch) -> None:
    from typer.testing import CliRunner

    from app.cli.main import app
    from app.web.config import get_settings

    monkeypatch.setenv("ANALYTICS_DB_PATH", str(populated.analytics_db_path))
    monkeypatch.setenv("NSE_SCRAPER_DB_PATH", str(populated.scraper_database_path))
    monkeypatch.setenv("NSE_SCRAPER_PATH", str(populated.nse_scraper_path))
    get_settings.cache_clear()
    try:
        result = CliRunner().invoke(
            app, ["analytics", "compute", "factors", "--as-of", "2024-12-31"]
        )
        assert result.exit_code == 0, result.output
        assert "momentum" in result.output and "quality" in result.output
    finally:
        get_settings.cache_clear()
