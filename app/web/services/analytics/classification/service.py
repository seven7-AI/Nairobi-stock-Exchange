"""Build + persist, the one call the CLI and the jobs make.

codegraph explore "classify_instruments build_classifications replace_classifications"
"""

from __future__ import annotations

from dataclasses import dataclass

from app.web.config import ROOT_DIR, Settings
from app.web.db.analytics import analytics_session
from app.web.db.analytics.services.classifications import (
    load_classifications,
    replace_classifications,
)
from app.web.services.analytics.classification.builder import BuildReport, build_classifications
from app.web.services.analytics.classification.lookup import ClassificationIndex
from app.web.services.market_data.sources.nse_scraper import NseScraperSource

NSE_DATA_DIR = ROOT_DIR / "NSE_DATA"


@dataclass(frozen=True)
class ClassifyResult:
    rows_written: int
    tickers: int
    unclassified: tuple[str, ...]
    skipped_rows: tuple[str, ...]


def classify_instruments(settings: Settings, source: NseScraperSource) -> ClassifyResult:
    """Rebuild ``classifications`` from the sector files + curated map + instrument master."""
    report: BuildReport = build_classifications(source, NSE_DATA_DIR)
    with analytics_session(settings) as session:
        written = replace_classifications(session, report.records)
    return ClassifyResult(written, len(report.tickers), report.unclassified, report.skipped_rows)


def load_index(settings: Settings) -> ClassificationIndex:
    with analytics_session(settings) as session:
        return ClassificationIndex(load_classifications(session))


__all__ = ["NSE_DATA_DIR", "ClassifyResult", "classify_instruments", "load_index"]
