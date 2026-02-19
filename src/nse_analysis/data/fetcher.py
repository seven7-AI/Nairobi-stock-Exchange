"""Data ingestion from Supabase stockanalysis_stocks table."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

import pandas as pd

from nse_analysis.config import Settings
from nse_analysis.database.connection import SupabaseConnection
from nse_analysis.database import queries
from nse_analysis.utils.logger import get_logger


class DataFetcher:
    """Coordinator for current-day and historical NSE data pulls from stockanalysis_stocks."""

    def __init__(self, settings: Settings, conn: SupabaseConnection):
        self.settings = settings
        self.conn = conn
        self.logger = get_logger("nse_analysis.data.fetcher")

    def fetch_latest_analysis_data(self) -> list[dict[str, Any]]:
        """Get latest rows from `stockanalysis_stocks`."""
        return queries.fetch_latest_rows(
            self.conn,
            table_name=self.settings.stockanalysis_table,
            timestamp_column="scraped_at",
            limit=500,
        )

    def fetch_daily_window(
        self, as_of_utc: datetime | None = None
    ) -> list[dict[str, Any]]:
        """Fetch latest row per ticker from stockanalysis_stocks table.
        
        Since the scraper now keeps historical data (not just upserting),
        we fetch the latest row per ticker instead of a date range.
        """
        # Fetch latest rows ordered by scraped_at descending
        # The merge_current_data will deduplicate to get one row per ticker
        analysis = queries.fetch_latest_rows(
            self.conn,
            table_name=self.settings.stockanalysis_table,
            timestamp_column="scraped_at",
            limit=1000,  # Get enough rows to cover all tickers
        )
        self.logger.info(
            "daily_window_fetched",
            analysis_rows=len(analysis),
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

    def load_historical_from_supabase(self, days_back: int | None = None) -> pd.DataFrame:
        """Load historical price data from stockanalysis_stocks table.
        
        First tries to use price_history field from latest rows if available,
        otherwise falls back to fetching historical rows by date range.
        """
        days = days_back or getattr(self.settings, "historical_days_back", 365)
        
        # Get latest rows per ticker
        latest_rows = self.fetch_daily_window()
        merged_rows = self.merge_current_data(latest_rows)
        
        if not merged_rows:
            self.logger.warning("no_tickers_found_for_historical")
            return pd.DataFrame()
        
        # Try to extract historical data from price_history field first
        historical_data: list[dict[str, Any]] = []
        price_history_used = 0
        
        for row in merged_rows:
            ticker = str(row.get("ticker_symbol", "")).strip()
            price_history = row.get("price_history")
            
            # Check if price_history exists and is a list
            if isinstance(price_history, list) and len(price_history) > 0:
                # Extract price history entries
                for entry in price_history:
                    if isinstance(entry, dict):
                        # Expected format: {"date": "...", "price": ...} or similar
                        entry_date = entry.get("date") or entry.get("scraped_at") or entry.get("timestamp")
                        entry_price = entry.get("price") or entry.get("stock_price")
                        
                        if entry_date and entry_price is not None:
                            historical_data.append({
                                "ticker_symbol": ticker,
                                "date": entry_date,
                                "stock_price": entry_price,
                            })
                            price_history_used += 1
        
        # If we got data from price_history, use it
        if historical_data:
            df = pd.DataFrame(historical_data)
            df["date"] = pd.to_datetime(df["date"], errors="coerce", utc=True)
            df["stock_price"] = pd.to_numeric(df["stock_price"], errors="coerce")
            df = df.dropna(subset=["ticker_symbol", "date", "stock_price"])
            df = df.sort_values(["ticker_symbol", "date"]).reset_index(drop=True)
            
            self.logger.info(
                "historical_data_loaded_from_price_history",
                rows=len(df),
                tickers=len(set(df["ticker_symbol"])),
                price_history_entries=price_history_used,
            )
            return df
        
        # Fallback: Fetch historical rows by date range
        ticker_symbols = [str(row.get("ticker_symbol", "")).strip() for row in merged_rows if row.get("ticker_symbol")]
        
        historical_rows = queries.fetch_historical_by_tickers(
            self.conn,
            table_name=self.settings.stockanalysis_table,
            ticker_symbols=ticker_symbols,
            days_back=days,
            timestamp_column="scraped_at",
        )
        
        if not historical_rows:
            self.logger.warning("no_historical_data_fetched")
            return pd.DataFrame()
        
        # Convert to DataFrame
        df = pd.DataFrame(historical_rows)
        
        # Rename scraped_at to date for compatibility with calculator
        if "scraped_at" in df.columns:
            df["date"] = pd.to_datetime(df["scraped_at"], errors="coerce", utc=True)
        
        # Ensure required columns exist
        required_cols = ["ticker_symbol", "date", "stock_price"]
        missing_cols = [col for col in required_cols if col not in df.columns]
        if missing_cols:
            self.logger.warning("missing_columns_in_historical", missing=missing_cols)
            return pd.DataFrame()
        
        # Convert stock_price to numeric
        df["stock_price"] = pd.to_numeric(df["stock_price"], errors="coerce")
        
        # Sort by ticker and date
        df = df.sort_values(["ticker_symbol", "date"]).reset_index(drop=True)
        
        # Drop rows with missing required data
        df = df.dropna(subset=["ticker_symbol", "date", "stock_price"])
        
        self.logger.info(
            "historical_data_loaded_from_rows",
            rows=len(df),
            tickers=len(ticker_symbols),
            days_back=days,
        )
        return df
