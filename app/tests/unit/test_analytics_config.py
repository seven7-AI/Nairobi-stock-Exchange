"""``AnalyticsConfig`` hashing and ``calc_versions`` registration.

codegraph explore "AnalyticsConfig register_calc_version CalcVersion"
"""

from __future__ import annotations

import json
from datetime import timedelta
from pathlib import Path

import pytest
from pydantic import ValidationError
from sqlalchemy import select

from app.web.config import Settings
from app.web.db.analytics import analytics_session
from app.web.db.analytics.models import CalcVersion
from app.web.services.analytics.config import (
    DEFAULT_CONFIG,
    AnalyticsConfig,
    FundamentalsConfig,
    MarketConfig,
    register_calc_version,
)
from app.web.services.analytics.store import upgrade_analytics_db

pytestmark = pytest.mark.unit


def test_defaults_are_the_documented_starting_assumptions() -> None:
    assert DEFAULT_CONFIG.fundamentals.publication_lag_days_annual == 90
    assert DEFAULT_CONFIG.fundamentals.publication_lag_days_interim == 60
    assert DEFAULT_CONFIG.market.gap_threshold_days == 14
    assert DEFAULT_CONFIG.market.benchmark_index == "^NASI"
    assert DEFAULT_CONFIG.fundamentals.publication_lag("annual") == timedelta(days=90)
    assert DEFAULT_CONFIG.fundamentals.publication_lag("quarterly") == timedelta(days=60)
    assert DEFAULT_CONFIG.fundamentals.publication_lag("semiannual") == timedelta(days=60)


def test_hash_is_deterministic_and_sensitive_to_every_field() -> None:
    a = AnalyticsConfig()
    b = AnalyticsConfig()
    assert a.config_hash() == b.config_hash()
    assert len(a.config_hash()) == 64
    changed = AnalyticsConfig(market=MarketConfig(risk_free_rate=0.13))
    assert changed.config_hash() != a.config_hash()
    lagged = AnalyticsConfig(fundamentals=FundamentalsConfig(publication_lag_days_annual=120))
    assert lagged.config_hash() not in {a.config_hash(), changed.config_hash()}


def test_config_is_frozen_and_validated() -> None:
    with pytest.raises(ValidationError):
        MarketConfig(risk_free_rate=1.5)
    with pytest.raises(ValidationError):
        FundamentalsConfig(publication_lag_days_annual=-1)
    with pytest.raises(ValidationError):
        DEFAULT_CONFIG.market.risk_free_rate = 0.2  # type: ignore[misc]


def test_canonical_json_sorts_keys() -> None:
    text = DEFAULT_CONFIG.canonical_json()
    keys = list(json.loads(text))
    assert keys == sorted(keys) and "factors" in keys and "fundamentals" in keys
    assert " " not in text


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    s = Settings(ANALYTICS_DB_PATH=str(tmp_path / "a.sqlite3"))
    upgrade_analytics_db(s.analytics_db_path)
    return s


def test_register_calc_version_is_idempotent_per_config(settings: Settings) -> None:
    with analytics_session(settings) as session:
        first = register_calc_version(session, DEFAULT_CONFIG)
        again = register_calc_version(session, AnalyticsConfig())
        assert first.id == again.id
        other = register_calc_version(
            session, AnalyticsConfig(market=MarketConfig(risk_free_rate=0.10))
        )
        assert other.id != first.id
    with analytics_session(settings) as session:
        rows = session.execute(select(CalcVersion).order_by(CalcVersion.id)).scalars().all()
        assert [r.name for r in rows] == ["analytics", "analytics"]
        assert rows[0].config_json["market"]["risk_free_rate"] == 0.12
        assert rows[1].config_json["market"]["risk_free_rate"] == 0.10
        assert rows[0].version == DEFAULT_CONFIG.version
