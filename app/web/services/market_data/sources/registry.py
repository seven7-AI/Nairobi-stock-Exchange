"""The available market-data sources.

```text
Data Sources
│
├── nse_scraper   ~/nse-stock-scraper -> data/nse_scraper.sqlite3   [ACTIVE]
│                 daily Scrapy job, read-only SQLite
│
└── supabase      stockanalysis_stocks table                        [registered, not wired]
```

`build_market_data_source` returns the scraper source. There is deliberately no
"which source" setting: a selector implies a live choice, and there is only one
working source. Adding a second later means adding it here, not threading a flag
through the call chain.

    codegraph explore "build_market_data_source AVAILABLE_SOURCES AppState"
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from app.web.config import Settings
from app.web.services.market_data.sources.base import MarketDataSource
from app.web.services.market_data.sources.nse_scraper import NseScraperSource
from app.web.services.market_data.sources.supabase import build_supabase_source

#: Every source this service knows how to construct, by name.
AVAILABLE_SOURCES: dict[str, Callable[[Settings], Any]] = {
    "nse_scraper": NseScraperSource,
    "supabase": build_supabase_source,
}

#: The source that actually feeds market data today.
ACTIVE_SOURCE_NAME = "nse_scraper"


def build_market_data_source(settings: Settings) -> MarketDataSource:
    """The market-data source: the NSE scraper's daily SQLite output."""
    source: MarketDataSource = NseScraperSource(settings)
    return source


def build_source_by_name(name: str, settings: Settings) -> MarketDataSource:
    """Construct a named source. Used by the connectors test endpoint."""
    factory = AVAILABLE_SOURCES.get(name)
    if factory is None:
        raise KeyError(f"Unknown market data source: {name}")
    built: MarketDataSource = factory(settings)
    return built


__all__ = [
    "ACTIVE_SOURCE_NAME",
    "AVAILABLE_SOURCES",
    "build_market_data_source",
    "build_source_by_name",
]
