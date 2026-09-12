"""The NSE scraper data source.

Reads the daily output of the **`~/nse-stock-scraper`** project. That project runs
two Scrapy spiders under cron at 09:00 Africa/Nairobi and writes to its own local
SQLite database:

    ~/nse-stock-scraper/
      data/nse_scraper.sqlite3            <- stockanalysis_stocks, stock_data
      reports/stats/<spider>-latest.json  <- quality-gate verdict per run
      reports/local_fallback/*.jsonl      <- rows whose database write failed

`nse-be` opens that database **read-only** and copies none of the scraper's logic.
The coupling is one file path plus two artifact directories.

The scraper's SQLite schema uses the same column names as the Postgres/Supabase
schema, with one encoding difference: SQLite has no JSONB, so the five metrics
columns and ``price_history`` are TEXT holding JSON. Decoding them is the only
transformation performed here, and it *restores* the shape the Supabase client
used to return - which is why nothing downstream needed to change.

    codegraph explore "NseScraperSource MarketDataSource DataFetcher load_historical"
"""

from __future__ import annotations

import json
import sqlite3
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

from app.web.config import Settings
from app.web.core.exceptions import ExternalServiceError
from app.web.services.market_data.sources.base import (
    STOCK_DATA_TABLE,
    STOCKANALYSIS_TABLE,
    SourceHealth,
    TableStat,
)
from app.web.utils.logger import get_logger

logger = get_logger("app.web.services.market_data.sources.nse_scraper")

SOURCE_NAME = "nse_scraper"

#: Columns holding JSON as TEXT. Decoded back to dict/list on read.
JSON_OBJECT_COLUMNS = (
    "overview_metrics",
    "performance_metrics",
    "dividends_metrics",
    "price_metrics",
    "profile_metrics",
)
JSON_ARRAY_COLUMNS = ("price_history",)

#: The canonical (ticker, trade_date) timeline the scraper project maintains:
#: 2007-2024 archive rows plus one row per ticker per daily scrape. See the scraper's
#: docs/CANONICAL_SCHEMA.md. Read-only here, like everything else in this source.
OBSERVATIONS_TABLE = "stock_observations"
INSTRUMENTS_TABLE = "instruments"

#: Spiders the scraper runs, and the table each one feeds.
SPIDER_TABLES = {
    "stockanalysis_scraper": STOCKANALYSIS_TABLE,
    "afx_scraper": STOCK_DATA_TABLE,
}


def _parse_timestamp(value: Any) -> datetime | None:
    """Parse the ISO-8601 text the scraper stores, tolerating a trailing Z."""
    if not isinstance(value, str) or not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)


def _decode_json_column(raw: Any, column: str, ticker: str, fallback: Any) -> Any:
    """Decode one JSON TEXT column.

    A malformed column degrades to ``fallback`` and is logged. It must never
    abort the read: one bad blob on one ticker would otherwise cost the whole
    day's market data.
    """
    if raw is None or raw == "":
        return fallback
    if isinstance(raw, (dict, list)):
        return raw
    try:
        decoded = json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        logger.warning("scraper_json_column_malformed", column=column, ticker=ticker)
        return fallback
    if not isinstance(decoded, type(fallback)):
        logger.warning(
            "scraper_json_column_unexpected_type",
            column=column,
            ticker=ticker,
            got=type(decoded).__name__,
        )
        return fallback
    return decoded


def _decode_row(row: sqlite3.Row) -> dict[str, Any]:
    """One SQLite row as the dict shape the rest of the pipeline consumes."""
    record: dict[str, Any] = dict(row)
    ticker = str(record.get("ticker_symbol", "?"))
    for column in JSON_OBJECT_COLUMNS:
        if column in record:
            record[column] = _decode_json_column(record[column], column, ticker, {})
    for column in JSON_ARRAY_COLUMNS:
        if column in record:
            record[column] = _decode_json_column(record[column], column, ticker, [])
    return record


class NseScraperSource:
    """Read-only access to the nse-stock-scraper project's daily output."""

    name = SOURCE_NAME

    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self.database_path: Path = settings.scraper_database_path
        self.stats_dir: Path = settings.scraper_stats_dir
        self.fallback_dir: Path = settings.scraper_fallback_dir
        self._timeout = settings.nse_scraper_read_timeout_seconds
        self._stale_after_hours = settings.nse_scraper_stale_after_hours

    # -- connection ---------------------------------------------------------
    def _connect(self) -> sqlite3.Connection:
        """Open the scraper's database read-only.

        ``mode=ro`` is not a convention but an enforcement: SQLite refuses every
        write on this handle. Combined with the read-only bind mount in
        docker-compose, `nse-be` cannot corrupt another project's database even
        through a bug. The busy timeout lets a read wait out a concurrent scrape
        rather than failing.
        """
        if not self.database_path.exists():
            raise ExternalServiceError(
                "The NSE scraper database is not available.",
                detail=f"missing scraper database at {self.database_path}",
            )
        try:
            connection = sqlite3.connect(
                f"file:{self.database_path}?mode=ro", uri=True, timeout=self._timeout
            )
        except sqlite3.Error as exc:
            raise ExternalServiceError(
                "The NSE scraper database could not be opened.",
                detail=f"{type(exc).__name__} opening {self.database_path}",
            ) from exc
        connection.row_factory = sqlite3.Row
        return connection

    def _table_exists(self, connection: sqlite3.Connection, table: str) -> bool:
        found = connection.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (table,)
        ).fetchone()
        return found is not None

    # -- reads --------------------------------------------------------------
    def fetch_latest_rows(
        self, limit: int = 1000, table: str = STOCKANALYSIS_TABLE
    ) -> list[dict[str, Any]]:
        """Latest scraped rows, newest first, JSON columns decoded."""
        with self._connect() as connection:
            if not self._table_exists(connection, table):
                logger.warning("scraper_table_missing", table=table)
                return []
            rows = connection.execute(
                f"SELECT * FROM {table} ORDER BY scraped_at DESC LIMIT ?",
                (limit,),
            ).fetchall()

        records = [_decode_row(row) for row in rows]
        logger.info("scraper_rows_fetched", table=table, rows=len(records))
        return records

    def fetch_historical_rows(
        self, ticker_symbols: list[str], days_back: int = 365
    ) -> list[dict[str, Any]]:
        """Empty by design.

        The scraper keeps **one row per ticker**; history lives in that row's
        ``price_history`` array, which the caller reads first and which is the
        deeper source anyway. There is no per-day row table to query.
        """
        logger.info(
            "scraper_historical_rows_not_applicable",
            tickers=len(ticker_symbols),
            days_back=days_back,
        )
        return []

    # -- canonical timeline -------------------------------------------------
    def has_observations(self) -> bool:
        """Whether the scraper database carries the canonical timeline yet."""
        with self._connect() as connection:
            return self._table_exists(connection, OBSERVATIONS_TABLE)

    def fetch_observations(
        self,
        ticker_symbol: str,
        *,
        start: date | None = None,
        end: date | None = None,
        limit: int = 10_000,
    ) -> list[dict[str, Any]]:
        """One instrument's daily observations, oldest first.

        ``ticker_symbol`` is the canonical code (``ABSA``); rows the archive recorded
        under a retired code (``BBK``) are already resolved and carry it in
        ``source_ticker``. Each row's ``quality_flags`` is decoded to a list.
        """
        clauses = ["ticker_symbol = ?"]
        params: list[Any] = [ticker_symbol.strip().upper()]
        if start is not None:
            clauses.append("trade_date >= ?")
            params.append(start.isoformat())
        if end is not None:
            clauses.append("trade_date <= ?")
            params.append(end.isoformat())
        params.append(limit)

        with self._connect() as connection:
            if not self._table_exists(connection, OBSERVATIONS_TABLE):
                logger.warning("scraper_table_missing", table=OBSERVATIONS_TABLE)
                return []
            rows = connection.execute(
                f"SELECT * FROM {OBSERVATIONS_TABLE} WHERE {' AND '.join(clauses)} "
                "ORDER BY trade_date ASC LIMIT ?",
                params,
            ).fetchall()

        records = []
        for row in rows:
            record = dict(row)
            record["quality_flags"] = _decode_json_column(
                record.get("quality_flags"), "quality_flags", record.get("ticker_symbol", "?"), []
            )
            records.append(record)
        logger.info("scraper_observations_fetched", ticker=params[0], rows=len(records))
        return records

    def fetch_instruments(self, *, sector: str | None = None) -> list[dict[str, Any]]:
        """The instrument master the scraper maintains: canonical ticker, type, sector."""
        with self._connect() as connection:
            if not self._table_exists(connection, INSTRUMENTS_TABLE):
                return []
            if sector is None:
                rows = connection.execute(
                    f"SELECT * FROM {INSTRUMENTS_TABLE} ORDER BY ticker_symbol"
                ).fetchall()
            else:
                rows = connection.execute(
                    f"SELECT * FROM {INSTRUMENTS_TABLE} WHERE sector = ? ORDER BY ticker_symbol",
                    (sector,),
                ).fetchall()
        return [dict(row) for row in rows]

    # -- run artifacts ------------------------------------------------------
    def read_quality_gate(self) -> dict[str, dict[str, Any]]:
        """The last run's verdict per spider.

        Scrapy exits 0 even when a spider scrapes nothing, so the scraper writes
        a ``quality_ok`` flag instead. Reading it lets `nse-be` tell a healthy
        run from a silently empty one before reporting on the data.
        """
        verdicts: dict[str, dict[str, Any]] = {}
        for spider in SPIDER_TABLES:
            path = self.stats_dir / f"{spider}-latest.json"
            if not path.is_file():
                continue
            try:
                verdicts[spider] = json.loads(path.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError):
                logger.warning("scraper_quality_gate_unreadable", spider=spider)
        return verdicts

    def read_fallback_records(self, on_date: date | None = None) -> list[dict[str, Any]]:
        """Rows the scraper could not write to its database.

        These files are the scraper's safety net: a row appears here only when a
        write threw. A malformed line is skipped rather than fatal - the point of
        the file is to salvage what survived.
        """
        if not self.fallback_dir.is_dir():
            return []
        day = (on_date or datetime.now(tz=UTC).date()).isoformat()

        records: list[dict[str, Any]] = []
        for path in sorted(self.fallback_dir.glob(f"*_fallback-{day}.jsonl")):
            try:
                lines = path.read_text(encoding="utf-8").splitlines()
            except OSError:
                logger.warning("scraper_fallback_unreadable", file=path.name)
                continue
            skipped = 0
            for line in lines:
                if not line.strip():
                    continue
                try:
                    records.append(json.loads(line))
                except json.JSONDecodeError:
                    skipped += 1
            if skipped:
                logger.warning("scraper_fallback_lines_skipped", file=path.name, skipped=skipped)
        logger.info("scraper_fallback_read", day=day, records=len(records))
        return records

    def list_fallback_dates(self) -> list[str]:
        """Dates for which the scraper wrote a fallback file, newest first."""
        if not self.fallback_dir.is_dir():
            return []
        dates = {
            path.stem.split("_fallback-", 1)[-1]
            for path in self.fallback_dir.glob("*_fallback-*.jsonl")
        }
        return sorted(dates, reverse=True)

    # -- health -------------------------------------------------------------
    def health_check(self) -> SourceHealth:
        """Readable, fresh, and did the last scrape pass its own gate."""
        location = str(self.database_path)
        if not self.database_path.exists():
            return SourceHealth(
                name=self.name,
                reachable=False,
                location=location,
                detail="Scraper database not found. Is NSE_SCRAPER_PATH correct?",
            )

        try:
            with self._connect() as connection:
                tables = [
                    self._table_stat(connection, table)
                    for table in (STOCKANALYSIS_TABLE, STOCK_DATA_TABLE)
                    if self._table_exists(connection, table)
                ]
                if self._table_exists(connection, OBSERVATIONS_TABLE):
                    tables.append(self._observations_stat(connection))
        except ExternalServiceError as exc:
            return SourceHealth(
                name=self.name, reachable=False, location=location, detail=exc.message
            )

        analytics = next((t for t in tables if t.name == STOCKANALYSIS_TABLE), None)
        newest = analytics.newest_scraped_at if analytics else None
        age_hours = (
            round((datetime.now(tz=UTC) - newest).total_seconds() / 3600, 2) if newest else None
        )

        gate = self.read_quality_gate().get("stockanalysis_scraper")
        quality_ok = bool(gate.get("quality_ok")) if gate else None

        return SourceHealth(
            name=self.name,
            reachable=True,
            location=location,
            detail=f"{len(tables)} table(s) readable",
            tables=tables,
            newest_scraped_at=newest,
            age_hours=age_hours,
            is_stale=age_hours is not None and age_hours > self._stale_after_hours,
            quality_ok=quality_ok,
        )

    def _table_stat(self, connection: sqlite3.Connection, table: str) -> TableStat:
        row = connection.execute(
            f"SELECT count(*), min(scraped_at), max(scraped_at) FROM {table}"
        ).fetchone()
        return TableStat(
            name=table,
            row_count=int(row[0] or 0),
            oldest_scraped_at=_parse_timestamp(row[1]),
            newest_scraped_at=_parse_timestamp(row[2]),
        )

    def _observations_stat(self, connection: sqlite3.Connection) -> TableStat:
        """The timeline is keyed on trade_date, not scraped_at."""
        row = connection.execute(
            f"SELECT count(*), min(trade_date), max(trade_date) FROM {OBSERVATIONS_TABLE}"
        ).fetchone()
        return TableStat(
            name=OBSERVATIONS_TABLE,
            row_count=int(row[0] or 0),
            oldest_scraped_at=_parse_timestamp(f"{row[1]}T00:00:00+00:00") if row[1] else None,
            newest_scraped_at=_parse_timestamp(f"{row[2]}T00:00:00+00:00") if row[2] else None,
        )

    def price_history_depth(self) -> dict[int, int]:
        """How many observations each ticker carries, as depth -> ticker count.

        Weekly indicators need >= 5 and monthly >= 22, so this is the direct
        answer to "which windows can actually be computed today".
        """
        with self._connect() as connection:
            if not self._table_exists(connection, STOCKANALYSIS_TABLE):
                return {}
            rows = connection.execute(
                f"SELECT json_array_length(price_history) AS depth, count(*) AS tickers "
                f"FROM {STOCKANALYSIS_TABLE} GROUP BY depth ORDER BY depth"
            ).fetchall()
        return {int(row["depth"] or 0): int(row["tickers"]) for row in rows}


__all__ = ["INSTRUMENTS_TABLE", "OBSERVATIONS_TABLE", "SOURCE_NAME", "NseScraperSource"]
