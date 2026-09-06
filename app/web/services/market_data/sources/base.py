"""The market-data source contract.

A source answers one question: *what are the latest scraped NSE rows?* It returns
plain ``list[dict]`` in the shape the rest of the pipeline already consumes -
``merge_current_data``, ``load_historical`` and ``calculate_batch`` are all
written against it and need no knowledge of where the rows came from.

    codegraph explore "MarketDataSource NseScraperSource DataFetcher registry"
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Protocol, runtime_checkable

#: The table every analytics path reads. One row per ticker; history lives in
#: the row's ``price_history`` array.
STOCKANALYSIS_TABLE = "stockanalysis_stocks"

#: The legacy per-ticker price table. Retained for reporting completeness only.
STOCK_DATA_TABLE = "stock_data"


@dataclass(frozen=True)
class TableStat:
    """Row count and recency for one table in a source."""

    name: str
    row_count: int
    newest_scraped_at: datetime | None = None
    oldest_scraped_at: datetime | None = None


@dataclass
class SourceHealth:
    """What a source can tell an operator about itself.

    ``reachable`` answers "can we read it at all". ``is_stale`` answers "is what
    we read recent enough to report on". They are separate because a source that
    reads perfectly but has not been refreshed for a week is not healthy, and
    collapsing the two hides exactly that failure.
    """

    name: str
    reachable: bool
    location: str
    detail: str = ""
    tables: list[TableStat] = field(default_factory=list)
    newest_scraped_at: datetime | None = None
    age_hours: float | None = None
    is_stale: bool = False
    quality_ok: bool | None = None

    @property
    def status(self) -> str:
        if not self.reachable:
            return "unreachable"
        if self.quality_ok is False:
            return "degraded"
        if self.is_stale:
            return "stale"
        return "ok"

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "status": self.status,
            "reachable": self.reachable,
            "location": self.location,
            "detail": self.detail,
            "newest_scraped_at": (
                self.newest_scraped_at.isoformat() if self.newest_scraped_at else None
            ),
            "age_hours": self.age_hours,
            "is_stale": self.is_stale,
            "quality_ok": self.quality_ok,
            "tables": [
                {
                    "name": table.name,
                    "row_count": table.row_count,
                    "newest_scraped_at": (
                        table.newest_scraped_at.isoformat() if table.newest_scraped_at else None
                    ),
                }
                for table in self.tables
            ],
        }


@runtime_checkable
class MarketDataSource(Protocol):
    """Where `nse-be` obtains raw NSE market data."""

    #: Stable identifier, matching the ConnectorType value where one exists.
    name: str

    def fetch_latest_rows(self, limit: int = 1000) -> list[dict[str, Any]]:
        """Latest scraped rows, newest first."""
        ...

    def fetch_historical_rows(
        self, ticker_symbols: list[str], days_back: int = 365
    ) -> list[dict[str, Any]]:
        """Historical rows for the given tickers.

        Sources that keep one row per ticker return an empty list: their history
        lives in each row's ``price_history`` array, which the caller reads first.
        """
        ...

    def health_check(self) -> SourceHealth:
        """Whether the source is readable, and how fresh what it holds is."""
        ...


__all__ = [
    "STOCKANALYSIS_TABLE",
    "STOCK_DATA_TABLE",
    "MarketDataSource",
    "SourceHealth",
    "TableStat",
]
