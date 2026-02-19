"""Data ingestion from Supabase and local historical CSV archives."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import pandas as pd

from nse_analysis.config import Settings
from nse_analysis.database.connection import SupabaseConnection
from nse_analysis.database import queries
from nse_analysis.utils.logger import get_logger


class DataFetcher:
    """Coordinator for current-day and historical NSE data pulls."""

    def __init__(self, settings: Settings, conn: SupabaseConnection):
        self.settings = settings
        self.conn = conn
        self.logger = get_logger("nse_analysis.data.fetcher")

    def fetch_latest_stock_data(self) -> list[dict[str, Any]]:
        """Get latest rows from `stock_data`."""
        return queries.fetch_latest_rows(
            self.conn,
            table_name=self.settings.stock_table,
            timestamp_column="created_at",
            limit=500,
        )

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
    ) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
        """Fetch one-day rolling window from both source tables."""
        now_utc = as_of_utc or datetime.now(tz=timezone.utc)
        start = now_utc - timedelta(days=1)
        stock = queries.fetch_rows_by_date_range(
            self.conn,
            table_name=self.settings.stock_table,
            timestamp_column="created_at",
            start_dt=start,
            end_dt=now_utc,
        )
        analysis = queries.fetch_rows_by_date_range(
            self.conn,
            table_name=self.settings.stockanalysis_table,
            timestamp_column="scraped_at",
            start_dt=start,
            end_dt=now_utc,
        )
        self.logger.info(
            "daily_window_fetched",
            stock_rows=len(stock),
            analysis_rows=len(analysis),
            start=start.isoformat(),
            end=now_utc.isoformat(),
        )
        return stock, analysis

    def merge_current_data(
        self,
        stock_rows: list[dict[str, Any]],
        analysis_rows: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        """Merge both datasets on ticker symbol."""
        by_ticker: dict[str, dict[str, Any]] = {}
        for row in stock_rows:
            ticker = str(row.get("ticker_symbol", "")).strip()
            if not ticker:
                continue
            by_ticker[ticker] = {**row}
        for row in analysis_rows:
            ticker = str(row.get("ticker_symbol", "")).strip()
            if not ticker:
                continue
            merged = by_ticker.get(ticker, {})
            merged.update(row)
            by_ticker[ticker] = merged
        merged_rows = list(by_ticker.values())
        self.logger.info("current_data_merged", merged_rows=len(merged_rows))
        return merged_rows

    def load_historical_csv(self) -> pd.DataFrame:
        """Load historical NSE CSV files from `NSE_DATA`."""
        path = self.settings.historical_data_dir
        files = sorted(path.glob("NSE_data_all_stocks_*.csv"))
        frames: list[pd.DataFrame] = []
        for file_path in files:
            df = self._read_single_historical_file(file_path)
            if not df.empty:
                frames.append(df)
        if not frames:
            return pd.DataFrame()
        full = pd.concat(frames, ignore_index=True)
        full = full.sort_values(["ticker_symbol", "date"]).reset_index(drop=True)
        self.logger.info("historical_csv_loaded", rows=len(full), files=len(files))
        return full

    def _read_single_historical_file(self, file_path: Path) -> pd.DataFrame:
        """Read one raw file and normalize columns."""
        raw = pd.read_csv(file_path, dtype=str)
        rename_map = {
            "Date": "date",
            "Code": "ticker_symbol",
            "Name": "stock_name",
            "Day Price": "stock_price",
            "Change": "stock_change",
            "Volume": "volume",
            "12m Low": "low_12m",
            "12m High": "high_12m",
            "Day Low": "day_low",
            "Day High": "day_high",
            "Previous": "previous_close",
            "Change%": "change_percent",
        }
        df = raw.rename(columns=rename_map)
        required = {"date", "ticker_symbol", "stock_name", "stock_price"}
        if not required.issubset(df.columns):
            return pd.DataFrame()
        df = df[list(set(rename_map.values()) & set(df.columns))]
        df["date"] = pd.to_datetime(df["date"], errors="coerce", dayfirst=True, format="mixed")
        for numeric_col in [
            "stock_price",
            "stock_change",
            "volume",
            "low_12m",
            "high_12m",
            "day_low",
            "day_high",
            "previous_close",
            "change_percent",
        ]:
            if numeric_col in df.columns:
                cleaned = (
                    df[numeric_col]
                    .astype(str)
                    .str.replace(",", "", regex=False)
                    .str.replace("%", "", regex=False)
                    .replace("-", None)
                )
                df[numeric_col] = pd.to_numeric(cleaned, errors="coerce")
        df = df.dropna(subset=["date", "ticker_symbol", "stock_price"])
        return df
