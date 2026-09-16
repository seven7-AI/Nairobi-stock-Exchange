"""The research profile service and CLI on the fixture store.

codegraph explore "build_profile render_profile research_command"
"""

from __future__ import annotations

from datetime import date
from pathlib import Path

import pytest

from app.web.config import Settings
from app.web.services.analytics.classification.service import classify_instruments
from app.web.services.analytics.research import build_profile, render_profile
from app.web.services.analytics.research.profile import BLOCKS, metric_block
from app.web.services.analytics.store import upgrade_analytics_db
from app.web.services.jobs import run_pipeline
from app.web.services.market_data.sources import NseScraperSource

pytestmark = pytest.mark.unit


def test_metric_block_marks_missing_rows() -> None:
    class Row:
        def __init__(
            self, metric: str, value: float | None, status: str, reason: str | None
        ) -> None:
            self.metric, self.value, self.status, self.reason = metric, value, status, reason

    block = metric_block(
        [Row("roe", 0.2, "known", None), Row("roa", None, "not_applicable", "bank")],
        ("roe", "roa", "fcf"),
        date(2024, 12, 31),
    )
    assert block["roe"] == {"value": 0.2, "status": "known", "reason": None}
    assert block["roa"]["status"] == "not_applicable" and block["roa"]["reason"] == "bank"
    assert block["fcf"] == {
        "value": None,
        "status": "unavailable",
        "reason": "fcf: not computed as of 2024-12-31",
    }
    assert set(BLOCKS) == {
        "returns",
        "momentum",
        "risk",
        "liquidity",
        "quality",
        "growth",
        "value",
        "dividend",
    }


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
    run_pipeline(settings, source, "daily", as_of=date(2024, 12, 31))
    run_pipeline(settings, source, "fundamentals", as_of=date(2024, 12, 31))
    return settings, source


def test_profile_from_the_store(populated: tuple[Settings, NseScraperSource]) -> None:
    settings, _ = populated
    assert build_profile(settings, "nope") is None
    profile = build_profile(settings, "kcb")
    assert profile is not None and profile.ticker_symbol == "KCB"
    assert (
        profile.as_of["market_metrics"] == "2024-12-31"
        and profile.as_of["fundamental_metrics"] == "2024-12-31"
    )
    assert profile.identity["sector"] == "Banking" and profile.identity["stints"] >= 1
    assert profile.metrics["quality"]["roe"]["status"] == "known"  # FY2023 statements are visible
    assert profile.metrics["quality"]["gross_margin"]["status"] == "not_applicable"  # a bank
    assert profile.metrics["growth"]["revenue_cagr_5y"]["status"] == "unavailable"
    assert profile.score["overall"]["status"] == "known" and profile.score["classification"]
    assert profile.score["explanation"]["disclaimer"]
    assert set(profile.factors) >= {"quality", "value", "momentum"}
    assert profile.valuation["intrinsic"]["status"] == "known" and set(
        profile.valuation["methods"]
    ) == {"pb_roe", "ddm"}
    assert profile.scenarios["outcomes"]["bear"]["assumptions"]["market_return"] == -0.25
    assert profile.forecast["status"] == "unavailable"  # the daily pipeline does not forecast
    assert profile.regime["status"] == "unavailable"
    assert profile.notes == []
    keno = build_profile(settings, "KENO")
    assert keno is not None and "no statements" in keno.notes[0]
    assert keno.metrics["momentum"]["momentum_12m_1m"]["status"] == "unavailable"
    earlier = build_profile(settings, "KCB", as_of=date(2019, 12, 31))
    assert earlier is not None and earlier.as_of["market_metrics"] is None
    assert earlier.score["status"] == "unavailable"
    text = render_profile(profile)
    assert "# KCB — research profile" in text and "[quality]" in text and "roe" in text
    assert "not_applicable" in text and "not investment advice" in text
    assert "score:" in text and "[valuation] intrinsic" in text


def test_cli_research(
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
        runner = CliRunner()
        text = runner.invoke(app, ["analytics", "research", "KCB"])
        assert text.exit_code == 0, text.output
        assert "# KCB — research profile" in text.output and "[value]" in text.output
        js = runner.invoke(app, ["analytics", "research", "KCB", "--json"])
        assert js.exit_code == 0 and '"ticker_symbol": "KCB"' in js.output
        missing = runner.invoke(app, ["analytics", "research", "NOPE"])
        assert missing.exit_code == 1 and "not an instrument" in missing.output
    finally:
        get_settings.cache_clear()
