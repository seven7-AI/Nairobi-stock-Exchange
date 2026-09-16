"""The AI narrative layer: context building, the numeric-consistency check, gating,
storage and idempotency - all with a fake client. No network.

codegraph explore "narrate build_context check_numbers"
"""

from __future__ import annotations

from datetime import date
from pathlib import Path

import pytest
from sqlalchemy import select

from app.web.config import Settings
from app.web.db.analytics import analytics_session
from app.web.db.analytics.models import ResearchNarrative
from app.web.services.analytics.ai import build_context, check_numbers, latest_narrative, narrate
from app.web.services.analytics.ai.narrative import (
    PROMPT_VERSION,
    SYSTEM_PROMPT,
    context_hash,
    context_numbers,
)
from app.web.services.analytics.classification.service import classify_instruments
from app.web.services.analytics.research import build_profile
from app.web.services.analytics.store import upgrade_analytics_db
from app.web.services.jobs import run_pipeline
from app.web.services.market_data.sources import NseScraperSource
from app.web.utils.logger import redact_event

pytestmark = pytest.mark.unit


class FakeClient:
    def __init__(self, reply: str) -> None:
        self.reply = reply
        self.calls: list[tuple[str, str]] = []

    def complete(self, system: str, user: str) -> str:
        self.calls.append((system, user))
        return self.reply


class BrokenClient:
    def complete(self, system: str, user: str) -> str:
        raise RuntimeError("api down")


CONTEXT = {
    "ticker": "KCB",
    "score": {"overall": 45.8, "confidence": 0.87, "ranks": {"market": 8}},
    "returns": {"return_12m": "12.5%"},
    "value": {"pe": 4.52, "price": 94.0},
    "valuation": {"intrinsic_value": 99.6, "upside": "6.0%"},
    "data_as_of": {"ranking": "2024-12-31"},
}


def test_check_numbers_accepts_only_context_numbers() -> None:
    allowed = context_numbers(CONTEXT)
    assert {
        "45.8",
        "0.87",
        "87%",
        "8",
        "12.5%",
        "4.52",
        "94",
        "94.0",
        "99.6",
        "6%",
        "6.0%",
    } <= allowed
    clean = (
        "KCB scores 45.8 with confidence 87%, ranking 8th. Over 12 months it returned 12.5%; "
        "at a P/E of 4.52 and a price of 94 the intrinsic value of 99.6 implies 6% upside. "
        "Three of the seven factors are known. The data is as of 2024-12-31."
    )
    assert check_numbers(clean, CONTEXT) == []
    dirty = "KCB trades at 94 and pays a 9.1% yield; revenue grew 23% to KES 173,395m."
    assert check_numbers(dirty, CONTEXT) == ["9.1%", "23%", "173,395"]
    assert check_numbers("Confidence is 0.87 and the score is 45.80.", CONTEXT) == []
    assert check_numbers("A 12-month horizon, 2 methods, year 2024.", CONTEXT) == []
    assert check_numbers("The market fell 37% in 2008.", CONTEXT) == ["37%"]


@pytest.fixture
def populated(fixture_db_path: Path, tmp_path: Path) -> Settings:
    settings = Settings(
        NSE_SCRAPER_DB_PATH=str(fixture_db_path),
        NSE_SCRAPER_PATH=str(tmp_path / "scraper"),
        ANALYTICS_DB_PATH=str(tmp_path / "a.sqlite3"),
        AI_NARRATIVES_ENABLED=True,
    )
    upgrade_analytics_db(settings.analytics_db_path)
    source = NseScraperSource(settings)
    classify_instruments(settings, source)
    run_pipeline(settings, source, "daily", as_of=date(2024, 12, 31))
    run_pipeline(settings, source, "fundamentals", as_of=date(2024, 12, 31))
    return settings


def test_context_is_built_from_the_profile_only(populated: Settings) -> None:
    profile = build_profile(populated, "KCB")
    assert profile is not None
    context = build_context(profile)
    assert context["ticker"] == "KCB" and context["sector"] == "Banking"
    assert isinstance(context["score"]["overall"], float) and context["score"]["classification"]
    assert context["quality"]["roe"].endswith("%") and "unavailable" in context["forecast"]
    assert context["value"]["pe"] == round(profile.metrics["value"]["pe"]["value"], 2)
    assert (
        isinstance(context["valuation"], dict)
        and context["valuation"]["price"] == profile.valuation["price"]
    )
    assert "not investment advice" in context["disclaimer"]
    assert context_hash(context) == context_hash(build_context(profile))  # deterministic
    keno = build_profile(populated, "KENO")
    assert keno is not None
    assert build_context(keno)["score"]["overall"].startswith("unavailable")


def test_narrate_stores_accepts_rejects_and_reuses(populated: Settings) -> None:
    profile = build_profile(populated, "KCB")
    assert profile is not None
    context = build_context(profile)
    overall = context["score"]["overall"]
    good = FakeClient(
        f"KCB scores {overall} and is classified {context['score']['classification']}. "
        "These are model outputs, not investment advice."
    )
    result = narrate(populated, "KCB", client=good)
    assert result.status == "known" and result.narrative and result.row_id is not None
    assert result.as_of == date(2024, 12, 31) and result.prompt_version == PROMPT_VERSION
    assert (
        good.calls and good.calls[0][0] == SYSTEM_PROMPT and '"ticker": "KCB"' in good.calls[0][1]
    )
    again = narrate(populated, "KCB", client=FakeClient("never called"))
    assert again.reused and again.row_id == result.row_id and again.narrative == result.narrative
    bad = FakeClient(f"KCB scores {overall}; revenue grew 42.7% and the yield is 9.9%.")
    forced = narrate(populated, "KCB", client=bad, force=True)
    assert forced.status == "rejected" and forced.narrative is not None
    assert forced.reason == "numbers not in the context: 42.7%, 9.9%"
    broken = narrate(populated, "KCB", client=BrokenClient(), force=True)
    assert broken.status == "unavailable" and "api down" in (broken.reason or "")
    with analytics_session(populated) as session:
        rows = (
            session.execute(select(ResearchNarrative).order_by(ResearchNarrative.id))
            .scalars()
            .all()
        )
        assert [r.status for r in rows] == ["known", "rejected", "unavailable"]
        assert all(r.context_hash == result.context_hash for r in rows)
    latest = latest_narrative(populated, "KCB")
    assert latest is not None and latest.status == "unavailable"
    unknown = narrate(populated, "NOPE", client=good)
    assert unknown.status == "unavailable" and "not an instrument" in (unknown.reason or "")


def test_disabled_and_keyless_are_clean_statuses(populated: Settings) -> None:
    off = populated.model_copy(update={"ai_narratives_enabled": False})
    result = narrate(off, "KCB")
    assert result.status == "disabled" and "AI_NARRATIVES_ENABLED" in (result.reason or "")
    with analytics_session(populated) as session:
        assert session.execute(select(ResearchNarrative)).scalars().all() == []
    keyless = narrate(populated, "KCB")  # enabled, no key, no client
    assert keyless.status == "unavailable" and "ANTHROPIC_API_KEY" in (keyless.reason or "")


def test_api_keys_are_redacted_from_logs() -> None:
    event = redact_event(
        {"anthropic_api_key": "sk-ant-abcdefghijklmnop", "note": "sk-ant-api03-xyzxyzxyzxyz"}
    )
    assert "sk-ant" not in str(event)


def test_cli_narrate(populated: Settings, monkeypatch: pytest.MonkeyPatch) -> None:
    from typer.testing import CliRunner

    from app.cli.main import app
    from app.web.config import get_settings

    monkeypatch.setenv("ANALYTICS_DB_PATH", str(populated.analytics_db_path))
    monkeypatch.setenv("NSE_SCRAPER_DB_PATH", str(populated.scraper_database_path))
    monkeypatch.setenv("NSE_SCRAPER_PATH", str(populated.nse_scraper_path))
    monkeypatch.setenv("AI_NARRATIVES_ENABLED", "true")
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    get_settings.cache_clear()
    try:
        result = CliRunner().invoke(app, ["analytics", "narrate", "KCB"])
        assert result.exit_code == 1 and "no ANTHROPIC_API_KEY configured" in result.output
    finally:
        get_settings.cache_clear()
