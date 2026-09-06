"""Market data ingestion.

Coordinates pulls from whichever :class:`MarketDataSource` is wired in. The
fetcher itself knows nothing about SQLite, Supabase or Scrapy - it takes rows in
the agreed shape and shapes them for the indicator layer.

    codegraph explore "DataFetcher MarketDataSource load_historical pipeline"
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

import pandas as pd

from app.web.config import Settings
from app.web.services.market_data.sources.base import MarketDataSource
from app.web.utils.logger import get_logger


class DataFetcher:
    """Coordinator for current-day and historical NSE data pulls."""

    def __init__(self, settings: Settings, source: MarketDataSource):
        self.settings = settings
        self.source = source
        self.logger = get_logger("app.web.services.market_data.fetcher")

    @property
    def source_name(self) -> str:
        return self.source.name

    def fetch_latest_analysis_data(self) -> list[dict[str, Any]]:
        """Latest rows from the configured source."""
        return self.source.fetch_latest_rows(limit=500)

    def fetch_daily_window(self, as_of_utc: datetime | None = None) -> list[dict[str, Any]]:
        """Fetch the latest rows the source holds.

        The scraper keeps one row per ticker rather than one row per scrape, so
        this is a plain "latest rows" read; ``merge_current_data`` deduplicates
        defensively in case a source ever returns more than one row per ticker.
        """
        analysis = self.source.fetch_latest_rows(limit=1000)
        self.logger.info(
            "daily_window_fetched",
            source=self.source_name,
            analysis_rows=len(analysis),
            as_of=as_of_utc.isoformat() if as_of_utc else None,
        )
        return analysis

    def merge_current_data(
        self,
        analysis_rows: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        """Get latest row per ticker from analysis data."""
        # Sort by scraped_at descending to ensure we get the latest row per ticker
        sorted_rows = sorted(
            analysis_rows,
            key=lambda r: r.get("scraped_at", ""),
            reverse=True,
        )
        by_ticker: dict[str, dict[str, Any]] = {}
        for row in sorted_rows:
            ticker = str(row.get("ticker_symbol", "")).strip()
            if not ticker:
                continue
            # Keep the most recent row per ticker
            if ticker not in by_ticker:
                by_ticker[ticker] = {**row}
        merged_rows = list(by_ticker.values())
        self.logger.info("current_data_merged", merged_rows=len(merged_rows))
        return merged_rows

    def load_historical(
        self, merged_rows: list[dict[str, Any]], days_back: int | None = None
    ) -> pd.DataFrame:
        """Build the historical price frame the indicator layer consumes.

        Each row's ``price_history`` array is the primary history: the scraper
        appends to it whenever a ticker's price or change moves, giving 29-32
        observations for most tickers - enough for the 5-point weekly and
        22-point monthly windows. Only if that is empty does this fall back to
        asking the source for per-day rows.
        """
        days: int = days_back or self.settings.historical_days_back

        # `merged_rows` is supplied by the caller, which has already fetched and
        # deduplicated it. This method used to re-run fetch_daily_window() and
        # merge_current_data() itself, so every pipeline run hit the upstream
        # source twice for identical data.
        if not merged_rows:
            self.logger.warning("no_tickers_found_for_historical")
            return pd.DataFrame()

        frame = self._history_from_price_history(merged_rows)
        if not frame.empty:
            return frame
        return self._history_from_source_rows(merged_rows, days)

    def _history_from_price_history(self, merged_rows: list[dict[str, Any]]) -> pd.DataFrame:
        """Flatten each row's ``price_history`` array into a tidy frame."""
        historical_data: list[dict[str, Any]] = []
        for row in merged_rows:
            ticker = str(row.get("ticker_symbol", "")).strip()
            price_history = row.get("price_history")
            if not isinstance(price_history, list):
                continue
            for entry in price_history:
                if not isinstance(entry, dict):
                    continue
                entry_date = entry.get("date") or entry.get("scraped_at") or entry.get("timestamp")
                entry_price = entry.get("price") or entry.get("stock_price")
                if entry_date and entry_price is not None:
                    historical_data.append(
                        {
                            "ticker_symbol": ticker,
                            "date": entry_date,
                            "stock_price": entry_price,
                        }
                    )

        if not historical_data:
            return pd.DataFrame()

        df = pd.DataFrame(historical_data)
        df["date"] = pd.to_datetime(df["date"], errors="coerce", utc=True)
        df["stock_price"] = pd.to_numeric(df["stock_price"], errors="coerce")
        df = df.dropna(subset=["ticker_symbol", "date", "stock_price"])
        df = df.sort_values(["ticker_symbol", "date"]).reset_index(drop=True)

        self.logger.info(
            "historical_data_loaded_from_price_history",
            source=self.source_name,
            rows=len(df),
            tickers=len(set(df["ticker_symbol"])),
        )
        return df

    def _history_from_source_rows(
        self, merged_rows: list[dict[str, Any]], days: int
    ) -> pd.DataFrame:
        """Fallback: ask the source for per-day historical rows.

        Sources that keep one row per ticker return nothing here, which is the
        honest answer rather than an error.
        """
        ticker_symbols = [
            str(row.get("ticker_symbol", "")).strip()
            for row in merged_rows
            if row.get("ticker_symbol")
        ]
        historical_rows = self.source.fetch_historical_rows(ticker_symbols, days_back=days)
        if not historical_rows:
            self.logger.warning("no_historical_data_fetched", source=self.source_name)
            return pd.DataFrame()

        df = pd.DataFrame(historical_rows)
        if "scraped_at" in df.columns:
            df["date"] = pd.to_datetime(df["scraped_at"], errors="coerce", utc=True)

        required_cols = ["ticker_symbol", "date", "stock_price"]
        missing_cols = [col for col in required_cols if col not in df.columns]
        if missing_cols:
            self.logger.warning("missing_columns_in_historical", missing=missing_cols)
            return pd.DataFrame()

        df["stock_price"] = pd.to_numeric(df["stock_price"], errors="coerce")
        df = df.sort_values(["ticker_symbol", "date"]).reset_index(drop=True)
        df = df.dropna(subset=["ticker_symbol", "date", "stock_price"])

        self.logger.info(
            "historical_data_loaded_from_rows",
            source=self.source_name,
            rows=len(df),
            tickers=len(ticker_symbols),
            days_back=days,
        )
        return df


__all__ = ["DataFetcher"]
