"""The NSE scraper data source.

Every test builds its own temporary SQLite database from the scraper's real
schema, so the suite never depends on ``~/nse-stock-scraper`` existing or on a
scrape having run.

    codegraph explore "NseScraperSource MarketDataSource DataFetcher load_historical"
"""

from __future__ import annotations

import json
import sqlite3
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest

from app.web.config import Settings
from app.web.core.exceptions import ExternalServiceError
from app.web.services.market_data.fetcher import DataFetcher
from app.web.services.market_data.sources import MarketDataSource, NseScraperSource

pytestmark = [pytest.mark.unit]

# Mirrors sql/sqlite/001_schema.sql in the scraper project. If that file changes,
# this must change with it - which is the point of keeping it explicit here.
SCHEMA = """
CREATE TABLE stockanalysis_stocks (
    ticker_symbol       TEXT PRIMARY KEY,
    company_name        TEXT NOT NULL,
    rank                INTEGER,
    stock_price         REAL,
    stock_change        REAL,
    scraped_at          TEXT NOT NULL,
    created_at          TEXT NOT NULL,
    updated_at          TEXT NOT NULL,
    overview_metrics    TEXT,
    performance_metrics TEXT,
    dividends_metrics   TEXT,
    price_metrics       TEXT,
    profile_metrics     TEXT,
    price_history       TEXT NOT NULL DEFAULT '[]'
);
CREATE TABLE stock_data (
    ticker_symbol TEXT PRIMARY KEY,
    stock_name    TEXT NOT NULL,
    stock_price   REAL NOT NULL,
    stock_change  REAL,
    scraped_at    TEXT NOT NULL,
    created_at    TEXT NOT NULL,
    price_history TEXT NOT NULL DEFAULT '[]'
);
"""


def _price_history(count: int, *, start: float = 20.0) -> str:
    base = datetime.now(tz=UTC) - timedelta(days=count)
    return json.dumps(
        [
            {
                "scraped_at": (base + timedelta(days=i)).isoformat(),
                "stock_price": round(start + i * 0.5, 2),
                "stock_change": 0.5,
            }
            for i in range(count)
        ]
    )


def _insert(
    connection: sqlite3.Connection,
    ticker: str,
    *,
    history_points: int = 30,
    scraped_at: str | None = None,
    overview: str | None = None,
) -> None:
    now = scraped_at or datetime.now(tz=UTC).isoformat()
    connection.execute(
        "INSERT INTO stockanalysis_stocks VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (
            ticker,
            f"{ticker} Plc",
            1,
            25.5,
            0.5,
            now,
            now,
            now,
            overview if overview is not None else json.dumps({"marketCap": 1000, "revenue": 500}),
            json.dumps({"tr1y": 12.5}),
            json.dumps({"dividendYield": 5.1}),
            json.dumps({"volume": 1000, "low52": 10.0, "high52": 30.0}),
            json.dumps({"industry": "Telecom"}),
            _price_history(history_points),
        ),
    )


@pytest.fixture
def scraper_root(tmp_path: Path) -> Path:
    """A temp directory laid out like the scraper project."""
    (tmp_path / "data").mkdir()
    (tmp_path / "reports" / "stats").mkdir(parents=True)
    (tmp_path / "reports" / "local_fallback").mkdir(parents=True)
    return tmp_path


@pytest.fixture
def scraper_db(scraper_root: Path) -> Path:
    db_path = scraper_root / "data" / "nse_scraper.sqlite3"
    connection = sqlite3.connect(db_path)
    connection.executescript(SCHEMA)
    for ticker in ("SCOM", "EQTY", "KCB"):
        _insert(connection, ticker)
    connection.commit()
    connection.close()
    return db_path


def _settings(scraper_root: Path, **overrides: Any) -> Settings:
    return Settings(
        SUPABASE_URL="https://placeholder.supabase.co",
        SUPABASE_KEY="placeholder",
        NSE_SCRAPER_PATH=scraper_root,
        **overrides,
    )


@pytest.fixture
def source(scraper_root: Path, scraper_db: Path) -> NseScraperSource:
    return NseScraperSource(_settings(scraper_root))


# --- initialization and path resolution -------------------------------------
def test_source_initializes_and_satisfies_the_protocol(source: NseScraperSource) -> None:
    assert source.name == "nse_scraper"
    assert isinstance(source, MarketDataSource)


def test_paths_derive_from_the_configured_root(scraper_root: Path) -> None:
    settings = _settings(scraper_root)
    assert settings.scraper_database_path == scraper_root / "data" / "nse_scraper.sqlite3"
    assert settings.scraper_stats_dir == scraper_root / "reports" / "stats"
    assert settings.scraper_fallback_dir == scraper_root / "reports" / "local_fallback"


def test_explicit_database_path_overrides_the_derived_one(
    scraper_root: Path, tmp_path: Path
) -> None:
    elsewhere = tmp_path / "somewhere" / "custom.sqlite3"
    settings = _settings(scraper_root, NSE_SCRAPER_DB_PATH=elsewhere)
    assert settings.scraper_database_path == elsewhere


# --- reading ----------------------------------------------------------------
def test_latest_rows_expose_every_expected_field(source: NseScraperSource) -> None:
    rows = source.fetch_latest_rows()
    assert len(rows) == 3
    expected = {
        "ticker_symbol",
        "company_name",
        "rank",
        "stock_price",
        "stock_change",
        "scraped_at",
        "created_at",
        "updated_at",
        "overview_metrics",
        "performance_metrics",
        "dividends_metrics",
        "price_metrics",
        "profile_metrics",
        "price_history",
    }
    assert expected <= set(rows[0])


def test_json_columns_are_decoded_not_returned_as_text(source: NseScraperSource) -> None:
    """SQLite stores these as TEXT; the pipeline expects dict/list, as Supabase gave."""
    row = source.fetch_latest_rows()[0]
    for column in (
        "overview_metrics",
        "performance_metrics",
        "dividends_metrics",
        "price_metrics",
        "profile_metrics",
    ):
        assert isinstance(row[column], dict), column
    assert isinstance(row["price_history"], list)
    assert row["overview_metrics"]["marketCap"] == 1000


def test_limit_is_respected(source: NseScraperSource) -> None:
    assert len(source.fetch_latest_rows(limit=2)) == 2


def test_historical_rows_are_empty_by_design(source: NseScraperSource) -> None:
    """One row per ticker upstream; history lives in price_history."""
    assert source.fetch_historical_rows(["SCOM"]) == []


def test_price_history_feeds_the_indicator_frame(
    scraper_root: Path, source: NseScraperSource
) -> None:
    """The end-to-end reason this source exists: a usable historical frame."""
    fetcher = DataFetcher(_settings(scraper_root), source)
    merged = fetcher.merge_current_data(fetcher.fetch_daily_window())
    frame = fetcher.load_historical(merged)

    assert not frame.empty
    assert set(frame.columns) >= {"ticker_symbol", "date", "stock_price"}
    # 3 tickers x 30 observations
    assert len(frame) == 90
    assert frame["stock_price"].notna().all()


def test_price_history_depth_reports_computable_windows(source: NseScraperSource) -> None:
    assert source.price_history_depth() == {30: 3}


# --- failure handling -------------------------------------------------------
def test_missing_database_raises_a_clean_domain_error(scraper_root: Path) -> None:
    source = NseScraperSource(_settings(scraper_root))  # no scraper_db fixture
    with pytest.raises(ExternalServiceError) as excinfo:
        source.fetch_latest_rows()
    assert "not available" in excinfo.value.message


def test_missing_database_is_reported_unreachable_not_raised(scraper_root: Path) -> None:
    health = NseScraperSource(_settings(scraper_root)).health_check()
    assert health.reachable is False
    assert health.status == "unreachable"


def test_empty_tables_return_an_empty_list(scraper_root: Path) -> None:
    db_path = scraper_root / "data" / "nse_scraper.sqlite3"
    connection = sqlite3.connect(db_path)
    connection.executescript(SCHEMA)
    connection.commit()
    connection.close()

    source = NseScraperSource(_settings(scraper_root))
    assert source.fetch_latest_rows() == []
    assert source.health_check().reachable is True


def test_missing_table_returns_empty_rather_than_crashing(scraper_root: Path) -> None:
    db_path = scraper_root / "data" / "nse_scraper.sqlite3"
    connection = sqlite3.connect(db_path)
    connection.execute("CREATE TABLE unrelated (id INTEGER)")
    connection.commit()
    connection.close()

    assert NseScraperSource(_settings(scraper_root)).fetch_latest_rows() == []


def test_malformed_json_degrades_the_column_but_keeps_the_row(scraper_root: Path) -> None:
    """One corrupt blob must not cost the whole day's market data."""
    db_path = scraper_root / "data" / "nse_scraper.sqlite3"
    connection = sqlite3.connect(db_path)
    connection.executescript(SCHEMA)
    _insert(connection, "SCOM", overview="{not valid json")
    connection.commit()
    connection.close()

    rows = NseScraperSource(_settings(scraper_root)).fetch_latest_rows()
    assert len(rows) == 1
    assert rows[0]["ticker_symbol"] == "SCOM"
    assert rows[0]["overview_metrics"] == {}
    # the columns that were fine are unaffected
    assert rows[0]["performance_metrics"] == {"tr1y": 12.5}


def test_database_is_opened_read_only(source: NseScraperSource) -> None:
    """nse-be must never be able to write to another project's database."""
    with (
        pytest.raises(sqlite3.OperationalError, match="readonly"),
        source._connect() as connection,
    ):
        connection.execute("UPDATE stockanalysis_stocks SET rank = 99")


# --- staleness --------------------------------------------------------------
def test_fresh_data_is_not_stale(source: NseScraperSource) -> None:
    health = source.health_check()
    assert health.reachable is True
    assert health.is_stale is False
    assert health.status == "ok"


def test_old_data_is_reported_stale(scraper_root: Path) -> None:
    """Readable but un-refreshed is a distinct failure from unreachable."""
    old = (datetime.now(tz=UTC) - timedelta(days=5)).isoformat()
    db_path = scraper_root / "data" / "nse_scraper.sqlite3"
    connection = sqlite3.connect(db_path)
    connection.executescript(SCHEMA)
    _insert(connection, "SCOM", scraped_at=old)
    connection.commit()
    connection.close()

    health = NseScraperSource(_settings(scraper_root)).health_check()
    assert health.reachable is True
    assert health.is_stale is True
    assert health.status == "stale"


# --- run artifacts ----------------------------------------------------------
def test_quality_gate_is_parsed(scraper_root: Path, scraper_db: Path) -> None:
    (scraper_root / "reports" / "stats" / "stockanalysis_scraper-latest.json").write_text(
        json.dumps({"quality_ok": True, "item_scraped_count": 123, "db_upsert_ok": 63})
    )
    gate = NseScraperSource(_settings(scraper_root)).read_quality_gate()
    assert gate["stockanalysis_scraper"]["quality_ok"] is True
    assert gate["stockanalysis_scraper"]["db_upsert_ok"] == 63


def test_missing_quality_gate_is_not_an_error(source: NseScraperSource) -> None:
    assert source.read_quality_gate() == {}


def test_failed_quality_gate_marks_the_source_degraded(
    scraper_root: Path, scraper_db: Path
) -> None:
    (scraper_root / "reports" / "stats" / "stockanalysis_scraper-latest.json").write_text(
        json.dumps({"quality_ok": False, "failures": ["too few items"]})
    )
    health = NseScraperSource(_settings(scraper_root)).health_check()
    assert health.reachable is True
    assert health.quality_ok is False
    assert health.status == "degraded"


def test_fallback_records_are_read(scraper_root: Path, scraper_db: Path) -> None:
    today = datetime.now(tz=UTC).date().isoformat()
    path = (
        scraper_root / "reports" / "local_fallback" / f"stockanalysis_stocks_fallback-{today}.jsonl"
    )
    path.write_text('{"ticker_symbol": "SCOM"}\n{"ticker_symbol": "EQTY"}\n')

    source = NseScraperSource(_settings(scraper_root))
    records = source.read_fallback_records()
    assert [r["ticker_symbol"] for r in records] == ["SCOM", "EQTY"]
    assert source.list_fallback_dates() == [today]


def test_malformed_fallback_line_is_skipped_not_fatal(scraper_root: Path, scraper_db: Path) -> None:
    """The file exists to salvage rows that failed to store; one bad line
    must not discard the rest."""
    today = datetime.now(tz=UTC).date().isoformat()
    path = scraper_root / "reports" / "local_fallback" / f"stock_data_fallback-{today}.jsonl"
    path.write_text('{"ticker_symbol": "SCOM"}\nnot json at all\n{"ticker_symbol": "KCB"}\n')

    records = NseScraperSource(_settings(scraper_root)).read_fallback_records()
    assert [r["ticker_symbol"] for r in records] == ["SCOM", "KCB"]


def test_missing_fallback_directory_is_not_an_error(scraper_root: Path, scraper_db: Path) -> None:
    (scraper_root / "reports" / "local_fallback").rmdir()
    source = NseScraperSource(_settings(scraper_root))
    assert source.read_fallback_records() == []
    assert source.list_fallback_dates() == []
