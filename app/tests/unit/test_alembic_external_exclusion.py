"""Alembic must never emit DDL against tables this repo does not own.

``stockanalysis_stocks`` is created and written by an external scraper that
lives outside this codebase. It is mapped read-only so services can query it,
which means it is attached to ``Base.metadata`` — and therefore visible to
``alembic revision --autogenerate``. The ``include_object`` hook is the only
thing standing between that mapping and a migration that would try to take
ownership of someone else's table.

    codegraph explore "include_object StockAnalysisStock skip_autogenerate"
"""

from __future__ import annotations

import pytest

from app.alembic.hooks import include_object
from app.web.db.models import Base
from app.web.db.models.external import StockAnalysisStock

EXTERNAL_TABLE = "stockanalysis_stocks"

OWNED_TABLES = {
    "organizations",
    "users",
    "onboarding_state",
    "instruments",
    "watchlists",
    "watchlist_items",
    "price_bars",
    "indicator_snapshots",
    "report_runs",
    "connectors",
}


@pytest.mark.unit
def test_external_table_is_registered_but_flagged() -> None:
    """The mapping must exist (services read it) and must carry the opt-out flag."""
    table = Base.metadata.tables[EXTERNAL_TABLE]
    assert StockAnalysisStock.__tablename__ == EXTERNAL_TABLE
    assert table.info.get("skip_autogenerate") is True


@pytest.mark.unit
def test_include_object_excludes_the_external_table() -> None:
    table = Base.metadata.tables[EXTERNAL_TABLE]
    assert include_object(table, EXTERNAL_TABLE, "table", False, None) is False


@pytest.mark.unit
def test_include_object_excludes_external_child_objects() -> None:
    """A diff must not leak in through a column or index of the excluded table."""
    table = Base.metadata.tables[EXTERNAL_TABLE]
    for column in table.columns:
        assert include_object(column, column.name, "column", False, None) is False
    for index in table.indexes:
        assert include_object(index, index.name, "index", False, None) is False


@pytest.mark.unit
def test_every_owned_table_is_still_included() -> None:
    """The hook must not over-reach: everything we do own stays in autogenerate."""
    for name in OWNED_TABLES:
        table = Base.metadata.tables[name]
        assert include_object(table, name, "table", False, None) is True
        for column in table.columns:
            assert include_object(column, column.name, "column", False, None) is True


@pytest.mark.unit
def test_owned_table_set_matches_metadata() -> None:
    """Adding a model without updating this test should fail loudly."""
    registered = set(Base.metadata.tables) - {EXTERNAL_TABLE}
    assert registered == OWNED_TABLES
