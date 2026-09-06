"""The Supabase market-data source.

**Registered but not wired.** The scraper project switched to a local SQLite
backend (``DB_BACKEND=sqlite``), and its ``reports/local_fallback/`` directory
holds a failed-write file for every day between 2026-07-26 and 2026-09-06 -
those files are only produced when a database write throws. Nothing has
successfully written to the Supabase table since July, which is why the weekly
and monthly reports rendered 0.00%: the ``price_history`` behind them was empty.

This adapter is kept so the connectors API can still describe and test a
Supabase link, and so restoring that path later is a registry change rather than
a rewrite. Market data itself comes from :mod:`nse_scraper`.

    codegraph explore "SupabaseSource SupabaseConnection market_query_service"
"""

from __future__ import annotations

from typing import Any

from app.web.config import Settings
from app.web.core.exceptions import ExternalServiceError
from app.web.db.services import market_query_service as queries
from app.web.services.market_data.sources.base import SourceHealth
from app.web.services.market_data.supabase_client import SupabaseConnection
from app.web.utils.logger import get_logger

logger = get_logger("app.web.services.market_data.sources.supabase")

SOURCE_NAME = "supabase"


class SupabaseSource:
    """Thin adapter over the existing SupabaseConnection and query helpers."""

    name = SOURCE_NAME

    def __init__(self, settings: Settings, connection: SupabaseConnection | None = None) -> None:
        self._settings = settings
        self._connection = connection
        self.table = settings.stockanalysis_table

    @property
    def connection(self) -> SupabaseConnection:
        if self._connection is None:
            self._connection = SupabaseConnection(self._settings)
        return self._connection

    def fetch_latest_rows(self, limit: int = 1000) -> list[dict[str, Any]]:
        return queries.fetch_latest_rows(
            self.connection,
            table_name=self.table,
            timestamp_column="scraped_at",
            limit=limit,
        )

    def fetch_historical_rows(
        self, ticker_symbols: list[str], days_back: int = 365
    ) -> list[dict[str, Any]]:
        return queries.fetch_historical_by_tickers(
            self.connection,
            table_name=self.table,
            ticker_symbols=ticker_symbols,
            days_back=days_back,
            timestamp_column="scraped_at",
        )

    def health_check(self) -> SourceHealth:
        location = f"{self._settings.supabase_url}#{self.table}"
        try:
            result = self.connection.health_check(self.table)
        except Exception as exc:
            # The message can carry the host and key; keep it to the type name.
            logger.warning("supabase_source_unreachable", error=type(exc).__name__)
            return SourceHealth(
                name=self.name,
                reachable=False,
                location=location,
                detail="Supabase is not reachable.",
            )
        return SourceHealth(
            name=self.name,
            reachable=True,
            location=location,
            detail=f"sample_rows={result.get('sample_rows', 0)}",
        )


def build_supabase_source(settings: Settings) -> SupabaseSource:
    """Construct the Supabase source, or fail with a clear message."""
    if not settings.supabase_url or not settings.supabase_key:
        raise ExternalServiceError(
            "Supabase is not configured.",
            detail="SUPABASE_URL and SUPABASE_KEY are required for the supabase source",
        )
    return SupabaseSource(settings)


__all__ = ["SOURCE_NAME", "SupabaseSource", "build_supabase_source"]
