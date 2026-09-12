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


# --- canonical timeline (stock_observations, maintained by the scraper project) ---------
OBSERVATIONS_SCHEMA = """
CREATE TABLE instruments (
    ticker_symbol TEXT PRIMARY KEY, company_name TEXT NOT NULL, instrument_type TEXT NOT NULL,
    parent_ticker TEXT, sector TEXT, sector_source TEXT, first_seen_date TEXT, last_seen_date TEXT,
    is_active INTEGER NOT NULL DEFAULT 1, created_at TEXT NOT NULL, updated_at TEXT NOT NULL
);
CREATE TABLE stock_observations (
    id INTEGER PRIMARY KEY AUTOINCREMENT, ticker_symbol TEXT NOT NULL, trade_date TEXT NOT NULL,
    source_ticker TEXT NOT NULL, company_name TEXT, close_price REAL NOT NULL, previous_close REAL,
    day_low REAL, day_high REAL, year_low REAL, year_high REAL, change_abs REAL, change_pct REAL,
    volume INTEGER, adjusted_price REAL, data_source TEXT NOT NULL, source_file TEXT,
    source_row INTEGER,
    source_date_raw TEXT, quality_flags TEXT NOT NULL DEFAULT '[]', created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL, UNIQUE (ticker_symbol, trade_date)
);
"""


@pytest.fixture
def timeline_db(scraper_root: Path, scraper_db: Path) -> Path:
    connection = sqlite3.connect(scraper_db)
    connection.executescript(OBSERVATIONS_SCHEMA)
    now = datetime.now(tz=UTC).isoformat()
    connection.execute(
        "INSERT INTO instruments VALUES ('ABSA','Absa Bank Kenya Plc','ordinary',NULL,"
        "'Banking','f',"
        "'2007-01-02','2026-09-12',1,?,?)",
        (now, now),
    )
    connection.execute(
        "INSERT INTO instruments VALUES ('KCB','KCB Group Plc','ordinary',NULL,'Banking','f',"
        "'2007-01-02','2026-09-12',1,?,?)",
        (now, now),
    )
    rows = [
        ("ABSA", "2012-12-31", "BBK", 15.75, "nse_archive:2012", '["date_repaired"]'),
        ("ABSA", "2013-01-02", "ABSA", 15.7, "nse_archive:2013", "[]"),
        ("ABSA", "2026-09-12", "ABSA", 34.95, "nse_scraper", '["scrape_date_is_observation_date"]'),
        ("KCB", "2007-01-02", "KCB", 243.0, "nse_archive:2007", "[]"),
    ]
    for ticker, day, src, close, source, flags in rows:
        connection.execute(
            "INSERT INTO stock_observations (ticker_symbol, trade_date, source_ticker, "
            "close_price, "
            "data_source, quality_flags, created_at, updated_at) VALUES (?,?,?,?,?,?,?,?)",
            (ticker, day, src, close, source, flags, now, now),
        )
    connection.commit()
    connection.close()
    return scraper_db


def test_observations_come_back_oldest_first_with_lineage_preserved(
    scraper_root: Path, timeline_db: Path
) -> None:
    source = NseScraperSource(_settings(scraper_root))
    rows = source.fetch_observations("absa")  # case-insensitive
    assert [r["trade_date"] for r in rows] == ["2012-12-31", "2013-01-02", "2026-09-12"]
    assert rows[0]["source_ticker"] == "BBK"  # the archive's old code survives
    assert rows[0]["quality_flags"] == ["date_repaired"]  # decoded, not TEXT
    assert {r["data_source"] for r in rows} == {
        "nse_archive:2012",
        "nse_archive:2013",
        "nse_scraper",
    }


def test_observations_honour_the_date_window(scraper_root: Path, timeline_db: Path) -> None:
    from datetime import date as date_type

    source = NseScraperSource(_settings(scraper_root))
    rows = source.fetch_observations("ABSA", start=date_type(2013, 1, 1), end=date_type(2020, 1, 1))
    assert [r["trade_date"] for r in rows] == ["2013-01-02"]


def test_instruments_filter_by_sector(scraper_root: Path, timeline_db: Path) -> None:
    source = NseScraperSource(_settings(scraper_root))
    assert {r["ticker_symbol"] for r in source.fetch_instruments(sector="Banking")} == {
        "ABSA",
        "KCB",
    }
    assert source.fetch_instruments(sector="Agricultural") == []


def test_timeline_absent_is_empty_not_an_error(source: NseScraperSource) -> None:
    """A scraper database that predates the canonical tables still serves its old shape."""
    assert source.has_observations() is False
    assert source.fetch_observations("KCB") == []
    assert source.fetch_instruments() == []
    assert source.health_check().reachable is True


def test_health_reports_the_timeline_span(scraper_root: Path, timeline_db: Path) -> None:
    health = NseScraperSource(_settings(scraper_root)).health_check()
    stat = next(t for t in health.tables if t.name == "stock_observations")
    assert stat.row_count == 4
    assert (
        stat.oldest_scraped_at is not None
        and stat.oldest_scraped_at.date().isoformat() == "2007-01-02"
    )
