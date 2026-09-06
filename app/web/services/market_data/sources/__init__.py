"""Market-data sources.

`nse-be` obtains raw NSE market data from the ``~/nse-stock-scraper`` project's
daily SQLite output. See :mod:`registry` for what is registered and active.
"""

from app.web.services.market_data.sources.base import (
    STOCK_DATA_TABLE,
    STOCKANALYSIS_TABLE,
    MarketDataSource,
    SourceHealth,
    TableStat,
)
from app.web.services.market_data.sources.nse_scraper import NseScraperSource
from app.web.services.market_data.sources.registry import (
    ACTIVE_SOURCE_NAME,
    AVAILABLE_SOURCES,
    build_market_data_source,
    build_source_by_name,
)
from app.web.services.market_data.sources.supabase import SupabaseSource

__all__ = [
    "ACTIVE_SOURCE_NAME",
    "AVAILABLE_SOURCES",
    "STOCKANALYSIS_TABLE",
    "STOCK_DATA_TABLE",
    "MarketDataSource",
    "NseScraperSource",
    "SourceHealth",
    "SupabaseSource",
    "TableStat",
    "build_market_data_source",
    "build_source_by_name",
]
