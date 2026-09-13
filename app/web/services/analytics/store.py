"""Programmatic control of the analytics store's schema.

The CLI (``nse-analysis analytics upgrade|status``), the job runner and the
tests all go through these functions rather than shelling out to ``alembic``,
so a temporary file can be migrated exactly the way the real one is.

    codegraph explore "upgrade_analytics_db analytics_db_status AnalyticsDbStatus"
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from alembic import command
from alembic.config import Config
from alembic.runtime.migration import MigrationContext
from alembic.script import ScriptDirectory
from sqlalchemy import inspect, text

from app.web.config import ROOT_DIR
from app.web.db.analytics.base import analytics_url, build_analytics_engine
from app.web.utils.logger import get_logger

logger = get_logger(__name__)

ALEMBIC_INI = ROOT_DIR / "alembic.ini"
ANALYTICS_INI_SECTION = "analytics"


@dataclass(frozen=True)
class AnalyticsDbStatus:
    """What ``nse-analysis analytics status`` reports."""

    path: Path
    exists: bool
    current_revision: str | None
    head_revision: str | None
    #: Row counts per table, empty when the file does not exist yet.
    tables: dict[str, int] = field(default_factory=dict)

    @property
    def is_current(self) -> bool:
        return self.exists and self.current_revision == self.head_revision


def analytics_alembic_config(db_path: Path) -> Config:
    """The ``[analytics]`` Alembic config pointed at ``db_path``."""
    config = Config(str(ALEMBIC_INI), ini_section=ANALYTICS_INI_SECTION)
    config.set_main_option("sqlalchemy.url", analytics_url(db_path))
    return config


def head_revision(db_path: Path) -> str | None:
    return ScriptDirectory.from_config(analytics_alembic_config(db_path)).get_current_head()


def current_revision(db_path: Path) -> str | None:
    if not db_path.exists():
        return None
    engine = build_analytics_engine(db_path)
    try:
        with engine.connect() as connection:
            return MigrationContext.configure(connection).get_current_revision()
    finally:
        engine.dispose()


def upgrade_analytics_db(db_path: Path, revision: str = "head") -> str | None:
    """Migrate the file to ``revision`` (creating it if absent); returns the new revision.

    Safe to call repeatedly: an up-to-date file is a no-op.
    """
    db_path.parent.mkdir(parents=True, exist_ok=True)
    before = current_revision(db_path)
    command.upgrade(analytics_alembic_config(db_path), revision)
    after = current_revision(db_path)
    logger.info("analytics_db_upgraded", path=str(db_path), before=before, after=after)
    return after


def downgrade_analytics_db(db_path: Path, revision: str = "base") -> str | None:
    command.downgrade(analytics_alembic_config(db_path), revision)
    after = current_revision(db_path)
    logger.info("analytics_db_downgraded", path=str(db_path), revision=after)
    return after


def analytics_db_status(db_path: Path) -> AnalyticsDbStatus:
    """Revision and per-table row counts, without changing anything."""
    head = head_revision(db_path)
    if not db_path.exists():
        return AnalyticsDbStatus(
            path=db_path, exists=False, current_revision=None, head_revision=head
        )
    engine = build_analytics_engine(db_path)
    try:
        with engine.connect() as connection:
            current = MigrationContext.configure(connection).get_current_revision()
            counts: dict[str, int] = {}
            for table in sorted(inspect(connection).get_table_names()):
                if table == "alembic_version":
                    continue
                # Table names come from the schema we own, never from input.
                count = connection.execute(text(f'SELECT COUNT(*) FROM "{table}"')).scalar()
                counts[table] = int(count or 0)
    finally:
        engine.dispose()
    return AnalyticsDbStatus(
        path=db_path, exists=True, current_revision=current, head_revision=head, tables=counts
    )


__all__ = [
    "AnalyticsDbStatus",
    "analytics_alembic_config",
    "analytics_db_status",
    "current_revision",
    "downgrade_analytics_db",
    "head_revision",
    "upgrade_analytics_db",
]
