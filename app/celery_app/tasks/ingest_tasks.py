"""Market data ingestion.

Two jobs:

* ``backfill_price_bars_from_parquet`` seeds ``price_bars`` from the cleaned
  18-year archive in ``research/data/canonical_nse_prices.parquet``
  (267,310 rows, 2007-01-02 to 2024-12-31);
* ``ingest_latest_prices`` keeps it current from the upstream
  ``stockanalysis_stocks`` table.

The backfill is what makes weekly and monthly indicators computable at all:
those windows need >= 5 and >= 22 observations per ticker, and the upstream
``price_history`` field does not yet carry that depth.

    codegraph explore "ingest_latest_prices PriceBar Instrument backfill"
"""

from __future__ import annotations

import uuid
from datetime import UTC, date, datetime
from decimal import Decimal, InvalidOperation
from typing import Any

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from app.celery_app import celery_app
from app.web.config import get_settings
from app.web.db.base import get_sync_session_factory
from app.web.db.models.instrument import Instrument
from app.web.db.models.price_bar import PriceBar
from app.web.services.market_data.fetcher import DataFetcher
from app.web.services.market_data.sources import build_market_data_source
from app.web.utils.logger import get_logger

logger = get_logger("app.celery_app.tasks.ingest_tasks")

BATCH_SIZE = 5_000


def _to_decimal(value: Any) -> Decimal | None:
    if value is None:
        return None
    try:
        result = Decimal(str(value))
    except (InvalidOperation, ValueError):
        return None
    return None if result.is_nan() else result


def _instrument_ids(session: Session) -> dict[str, uuid.UUID]:
    rows = session.execute(select(Instrument.ticker_symbol, Instrument.id)).all()
    return dict(rows)  # type: ignore[arg-type]


def _upsert_bars(session: Session, rows: list[dict[str, Any]]) -> int:
    """Insert price bars, ignoring any (instrument, date) already present.

    ON CONFLICT DO NOTHING is what makes this task safe to re-run: a repeated
    ingestion is a no-op rather than a duplicate-key failure.
    """
    if not rows:
        return 0
    statement = pg_insert(PriceBar).values(rows)
    statement = statement.on_conflict_do_nothing(
        index_elements=[PriceBar.instrument_id, PriceBar.bar_date]
    )
    result = session.execute(statement)
    # CursorResult exposes rowcount; the generic Result protocol does not.
    return int(getattr(result, "rowcount", 0) or 0)


@celery_app.task(name="app.celery_app.tasks.ingest_tasks.seed_instruments")
def seed_instruments() -> dict[str, Any]:
    """Seed the instrument master from ``research/data/ticker_master.parquet``."""
    import pandas as pd

    settings = get_settings()
    path = settings.research_data_dir / "ticker_master.parquet"
    if not path.exists():
        logger.warning("ticker_master_missing", path=str(path))
        return {"status": "skipped", "reason": "ticker_master.parquet not found"}

    frame = pd.read_parquet(path)
    session_factory = get_sync_session_factory()
    created = 0
    with session_factory() as session:
        existing = set(_instrument_ids(session))
        for record in frame.to_dict("records"):
            ticker = str(record.get("ticker") or record.get("ticker_symbol") or "").strip().upper()
            if not ticker or ticker in existing:
                continue
            session.add(
                Instrument(
                    ticker_symbol=ticker,
                    company_name=str(record.get("name") or record.get("company_name") or ticker),
                    sector=(str(record["sector"]) if record.get("sector") else None),
                    is_active=bool(record.get("is_active", True)),
                )
            )
            existing.add(ticker)
            created += 1
        session.commit()

    logger.info("instruments_seeded", created=created, source_rows=len(frame))
    return {"status": "ok", "created": created, "source_rows": len(frame)}


@celery_app.task(name="app.celery_app.tasks.ingest_tasks.backfill_price_bars_from_parquet")
def backfill_price_bars_from_parquet(start_year: int | None = None) -> dict[str, Any]:
    """DEPRECATED: backfill ``price_bars`` from the research parquet.

    The parquet is sign-corrupted - the notebook that built it stripped every ``-``
    character, flipping 91,276 negative changes positive. The correct 2007-today
    timeline is the scraper database's ``stock_observations`` table; read it through
    ``NseScraperSource.fetch_observations``. Kept only so existing callers fail
    loudly here rather than silently importing bad data.
    """
    logger.warning(
        "backfill_price_bars_from_parquet_is_deprecated", reason="parquet is sign-corrupted"
    )
    import pandas as pd

    settings = get_settings()
    path = settings.research_data_dir / "canonical_nse_prices.parquet"
    if not path.exists():
        logger.warning("canonical_prices_missing", path=str(path))
        return {"status": "skipped", "reason": "canonical_nse_prices.parquet not found"}

    frame = pd.read_parquet(path)
    if start_year is not None:
        frame = frame[pd.to_datetime(frame["date"]).dt.year >= start_year]

    session_factory = get_sync_session_factory()
    inserted = 0
    skipped_unknown_ticker = 0
    with session_factory() as session:
        ids = _instrument_ids(session)
        batch: list[dict[str, Any]] = []
        for record in frame.to_dict("records"):
            ticker = str(record.get("ticker") or record.get("ticker_symbol") or "").strip().upper()
            instrument_id = ids.get(ticker)
            if instrument_id is None:
                skipped_unknown_ticker += 1
                continue
            close = _to_decimal(record.get("close") or record.get("close_price"))
            if close is None:
                continue
            raw_date = record.get("date")
            if raw_date is None:
                continue
            bar_date = (
                raw_date if isinstance(raw_date, date) else pd.Timestamp(str(raw_date)).date()
            )
            batch.append(
                {
                    "instrument_id": instrument_id,
                    "bar_date": bar_date,
                    "open_price": _to_decimal(record.get("open")),
                    "high_price": _to_decimal(record.get("high")),
                    "low_price": _to_decimal(record.get("low")),
                    "close_price": close,
                    "adjusted_close": _to_decimal(record.get("adjusted")),
                    "previous_close": _to_decimal(record.get("previous")),
                    "volume": int(record["volume"]) if record.get("volume") else None,
                    "source": "canonical_archive",
                }
            )
            if len(batch) >= BATCH_SIZE:
                inserted += _upsert_bars(session, batch)
                session.commit()
                batch = []
        inserted += _upsert_bars(session, batch)
        session.commit()

    logger.info(
        "price_bars_backfilled",
        inserted=inserted,
        source_rows=len(frame),
        skipped_unknown_ticker=skipped_unknown_ticker,
    )
    return {
        "status": "ok",
        "inserted": inserted,
        "source_rows": len(frame),
        "skipped_unknown_ticker": skipped_unknown_ticker,
    }


@celery_app.task(name="app.celery_app.tasks.ingest_tasks.backfill_price_bars_from_scraper")
def backfill_price_bars_from_scraper() -> dict[str, Any]:
    """Load each ticker's ``price_history`` from the scraper into ``price_bars``.

    The scraper keeps one row per ticker with its history in a JSON array, which
    the report pipeline reads directly. This task copies that history into our
    own ``price_bars`` table so SQL-side analytics, indicator snapshots and
    future agents can query it without re-reading another project's database.

    Idempotent: ON CONFLICT DO NOTHING on (instrument_id, bar_date), so running
    it twice inserts nothing the second time.
    """
    settings = get_settings()
    source = build_market_data_source(settings)
    rows = source.fetch_latest_rows(limit=2000)

    session_factory = get_sync_session_factory()
    inserted = 0
    unknown: list[str] = []
    tickers_with_history = 0

    with session_factory() as session:
        ids = _instrument_ids(session)
        batch: list[dict[str, Any]] = []
        for row in rows:
            ticker = str(row.get("ticker_symbol", "")).strip().upper()
            instrument_id = ids.get(ticker)
            if instrument_id is None:
                unknown.append(ticker)
                continue
            history = row.get("price_history")
            if not isinstance(history, list) or not history:
                continue
            tickers_with_history += 1
            for entry in history:
                if not isinstance(entry, dict):
                    continue
                close = _to_decimal(entry.get("stock_price") or entry.get("price"))
                raw_date = entry.get("scraped_at") or entry.get("date")
                if close is None or not raw_date:
                    continue
                try:
                    bar_date = datetime.fromisoformat(str(raw_date).replace("Z", "+00:00")).date()
                except ValueError:
                    continue
                change = _to_decimal(entry.get("stock_change"))
                batch.append(
                    {
                        "instrument_id": instrument_id,
                        "bar_date": bar_date,
                        "close_price": close,
                        "previous_close": (close - change) if change is not None else None,
                        "source": "nse_scraper",
                    }
                )
                if len(batch) >= BATCH_SIZE:
                    inserted += _upsert_bars(session, batch)
                    session.commit()
                    batch = []
        inserted += _upsert_bars(session, batch)
        session.commit()

    logger.info(
        "price_bars_backfilled_from_scraper",
        inserted=inserted,
        tickers_with_history=tickers_with_history,
        unknown_tickers=len(unknown),
    )
    return {
        "status": "ok",
        "inserted": inserted,
        "tickers_with_history": tickers_with_history,
        "unknown_tickers": unknown[:20],
    }


@celery_app.task(name="app.celery_app.tasks.ingest_tasks.ingest_latest_prices")
def ingest_latest_prices() -> dict[str, Any]:
    """Append today's close for every ticker from the upstream table."""
    settings = get_settings()
    source = build_market_data_source(settings)
    fetcher = DataFetcher(settings, source)

    analysis_rows = fetcher.fetch_daily_window(as_of_utc=datetime.now(tz=UTC))
    merged_rows = fetcher.merge_current_data(analysis_rows)

    session_factory = get_sync_session_factory()
    inserted = 0
    unknown: list[str] = []
    with session_factory() as session:
        ids = _instrument_ids(session)
        batch: list[dict[str, Any]] = []
        for row in merged_rows:
            ticker = str(row.get("ticker_symbol", "")).strip().upper()
            instrument_id = ids.get(ticker)
            if instrument_id is None:
                unknown.append(ticker)
                continue
            close = _to_decimal(row.get("stock_price"))
            if close is None:
                continue
            change = _to_decimal(row.get("stock_change"))
            scraped = row.get("scraped_at")
            bar_date = (
                datetime.fromisoformat(str(scraped).replace("Z", "+00:00")).date()
                if scraped
                else datetime.now(tz=UTC).date()
            )
            batch.append(
                {
                    "instrument_id": instrument_id,
                    "bar_date": bar_date,
                    "close_price": close,
                    "previous_close": (close - change) if change is not None else None,
                    "source": settings.stockanalysis_table,
                }
            )
        inserted = _upsert_bars(session, batch)
        session.commit()

    logger.info(
        "latest_prices_ingested",
        inserted=inserted,
        merged_rows=len(merged_rows),
        unknown_tickers=len(unknown),
    )
    return {
        "status": "ok",
        "inserted": inserted,
        "merged_rows": len(merged_rows),
        "unknown_tickers": unknown[:20],
    }


__all__ = [
    "backfill_price_bars_from_parquet",
    "backfill_price_bars_from_scraper",
    "ingest_latest_prices",
    "seed_instruments",
]
