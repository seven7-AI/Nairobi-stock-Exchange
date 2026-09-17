"""Latest prices and short-horizon performance for the whole market.

Two sources, each with its honest limits: ``stockanalysis_stocks`` carries today's
price, change, volume, 52-week range and market cap for the tickers the scraper
enriches (one row per ticker, refreshed daily); ``stock_observations`` carries the
canonical close per trading day for everyone. Returns beyond one day come from the
analytics store (``market_metrics``) so they are the same numbers the profile shows.

    codegraph explore "latest_quotes build_market Quote MarketSnapshot"
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import date, datetime, timedelta
from statistics import median
from typing import Any

from app.web.config import Settings
from app.web.db.analytics import analytics_session
from app.web.db.analytics.models import MarketMetric
from app.web.db.analytics.services.classifications import load_classifications
from app.web.db.analytics.services.market_metrics import load_metrics
from app.web.db.analytics.services.summaries import latest_as_of
from app.web.services.analytics.classification.lookup import ClassificationIndex
from app.web.services.dashboard.cache import get_dashboard_cache, store_stamp
from app.web.services.dashboard.common import (
    NON_EQUITY_SECTORS,
    equity_universe,
    from_optional,
    known,
    unavailable,
)
from app.web.services.market_data.sources.nse_scraper import NseScraperSource

#: Windows shown on the market page, in display order.
PERFORMANCE_WINDOWS: tuple[tuple[str, str], ...] = (
    ("1d", "return_1d"),
    ("1w", "return_1w"),
    ("1m", "return_1m"),
)
BENCHMARK_INDICES: tuple[str, ...] = ("^NASI", "^N20I")
MOVERS = 10


@dataclass(frozen=True)
class Quote:
    ticker_symbol: str
    company_name: str | None
    sector: str | None
    industry: str | None
    price: dict[str, Any]
    change_pct: dict[str, Any]
    volume: dict[str, Any]
    low_52w: dict[str, Any]
    high_52w: dict[str, Any]
    market_cap: dict[str, Any]
    close: dict[str, Any]
    close_date: date | None
    scraped_at: datetime | None
    facts: dict[str, Any] = field(default_factory=dict)
    source: str = "none"


@dataclass(frozen=True)
class SectorPerf:
    sector: str
    members: int
    known_members: int
    median: dict[str, Any]


@dataclass(frozen=True)
class MarketSnapshot:
    as_of: date
    latest_market_date: date | None
    stocks_with_data: int
    universe: int
    quotes: list[Quote]
    performance: dict[str, list[SectorPerf]]
    top_movers: list[Quote]
    bottom_movers: list[Quote]
    index: dict[str, dict[str, Any]]
    coverage: dict[str, dict[str, int]]

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


def _parse_dt(value: Any) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(str(value))
    except ValueError:
        return None


def latest_quotes(settings: Settings, source: NseScraperSource) -> dict[str, Quote]:
    """One quote per classified equity; scraped fields when the scraper has the ticker,
    otherwise the last canonical close with every scraped field ``unavailable``.
    Cached per store version - the market, stocks and overview pages all start here."""
    return get_dashboard_cache(settings).get_or_compute(
        ("quotes",), store_stamp(settings), lambda: _latest_quotes(settings, source)
    )


def _latest_quotes(settings: Settings, source: NseScraperSource) -> dict[str, Quote]:
    with analytics_session(settings) as session:
        index = ClassificationIndex(load_classifications(session))
    spans = source.fetch_observation_spans()
    latest_day = max((last for _, last, _ in spans.values()), default=None)
    universe = equity_universe(index, latest_day or date.today())
    rows: dict[str, dict[str, Any]] = {}
    for scraped in source.fetch_latest_rows(limit=1000):
        ticker = str(scraped.get("ticker_symbol") or "").upper()
        if ticker and ticker not in rows:  # newest first
            rows[ticker] = scraped
    closes: dict[str, tuple[date, float]] = {}
    if latest_day is not None:
        window = latest_day - timedelta(days=10)
        for ticker, obs in source.fetch_observations_bulk(universe, start=window).items():
            for o in reversed(obs):
                close = o.get("close_price")
                if close is not None and float(close) > 0:
                    closes[ticker] = (date.fromisoformat(str(o["trade_date"])), float(close))
                    break
    quotes: dict[str, Quote] = {}
    for ticker in universe:
        assignment = index.sector_for(ticker, latest_day or date.today())
        row: dict[str, Any] | None = rows.get(ticker)
        close = closes.get(ticker)
        span = spans.get(ticker)
        no_scrape = (
            f"not on stockanalysis; last observation {span[1].isoformat()}"
            if span
            else "no scrape row and no observations"
        )
        if row is None:
            quotes[ticker] = Quote(
                ticker,
                None,
                assignment.sector_label if assignment else None,
                assignment.industry if assignment else None,
                known(close[1]) if close else unavailable(no_scrape),
                unavailable(no_scrape),
                unavailable(no_scrape),
                unavailable(no_scrape),
                unavailable(no_scrape),
                unavailable(no_scrape),
                known(close[1]) if close else unavailable("no observations"),
                close[0] if close else None,
                None,
                {},
                "stock_observations" if close else "none",
            )
            continue
        price_metrics = row.get("price_metrics") or {}
        overview = row.get("overview_metrics") or {}
        profile = row.get("profile_metrics") or {}
        quotes[ticker] = Quote(
            ticker,
            row.get("company_name"),
            assignment.sector_label if assignment else None,
            assignment.industry if assignment else profile.get("industry"),
            from_optional(row.get("stock_price"), "no price in the latest scrape"),
            from_optional(row.get("stock_change"), "no change in the latest scrape"),
            from_optional(price_metrics.get("volume"), "volume not in the latest scrape"),
            from_optional(price_metrics.get("low52"), "52-week low not in the latest scrape"),
            from_optional(price_metrics.get("high52"), "52-week high not in the latest scrape"),
            from_optional(overview.get("marketCap"), "market cap not in the latest scrape"),
            known(close[1]) if close else unavailable("no observations"),
            close[0] if close else None,
            _parse_dt(row.get("scraped_at")),
            {
                "industry": profile.get("industry"),
                "founded": profile.get("founded"),
                "employees": profile.get("employees"),
                "revenue": overview.get("revenue"),
            },
            "stockanalysis_stocks",
        )
    return quotes


def _sector_performance(
    session: Any, index: ClassificationIndex, day: date, metric: str
) -> tuple[list[SectorPerf], dict[str, int]]:
    rows = load_metrics(session, as_of_date=day, metric=metric)
    coverage: dict[str, int] = {}
    values: dict[str, list[float]] = {}
    members: dict[str, int] = {}
    for r in rows:
        coverage[str(r.status)] = coverage.get(str(r.status), 0) + 1
        assignment = index.sector_for(r.ticker_symbol, day)
        if assignment is None or assignment.sector_code in NON_EQUITY_SECTORS:
            continue
        members[assignment.sector_label] = members.get(assignment.sector_label, 0) + 1
        if r.status in ("known", "zero") and r.value is not None:
            values.setdefault(assignment.sector_label, []).append(float(r.value))
    # every classified sector is listed, known or not
    for ticker in index.tickers:
        assignment = index.sector_for(ticker, day)
        if assignment and assignment.sector_code not in NON_EQUITY_SECTORS:
            members.setdefault(assignment.sector_label, 0)
    out = []
    for sector, n in sorted(members.items()):
        vals = values.get(sector, [])
        if vals:
            m = known(median(vals))
        else:
            m = unavailable(f"no member has a known {metric} on {day.isoformat()}")
        out.append(SectorPerf(sector, n, len(vals), m))
    out.sort(key=lambda s: (s.median["value"] is None, -(s.median["value"] or 0.0)))
    return out, coverage


def build_market(
    settings: Settings, source: NseScraperSource, *, as_of: date | None = None
) -> MarketSnapshot | None:
    quotes = latest_quotes(settings, source)
    spans = source.fetch_observation_spans()
    latest_day, with_data = source.latest_trade_date_coverage()
    with analytics_session(settings) as session:
        day = as_of or latest_as_of(session, MarketMetric)
        if day is None:
            return None
        index = ClassificationIndex(load_classifications(session))
        performance: dict[str, list[SectorPerf]] = {}
        coverage: dict[str, dict[str, int]] = {}
        for label, metric in PERFORMANCE_WINDOWS:
            performance[label], coverage[metric] = _sector_performance(session, index, day, metric)
    movers = sorted(
        (q for q in quotes.values() if q.change_pct["value"] is not None),
        key=lambda q: float(q.change_pct["value"]),
    )
    index_block: dict[str, dict[str, Any]] = {}
    for symbol in BENCHMARK_INDICES:
        span = spans.get(symbol)
        if span is None:
            index_block[symbol] = {
                "status": "unavailable",
                "reason": "not in the source",
                "latest_known_as_of": None,
                "last": None,
            }
            continue
        _, last, _ = span
        stale = (day - last).days
        index_block[symbol] = {
            "status": "known" if stale <= 14 else "unavailable",
            "reason": None
            if stale <= 14
            else f"last observation {last.isoformat()} is {stale} days before {day.isoformat()}",
            "latest_known_as_of": last,
            "last": None,
        }
    # the index's last level, when we have it
    for symbol, block in index_block.items():
        last_day = block["latest_known_as_of"]
        if last_day is not None:
            obs = source.fetch_observations(symbol, start=last_day, end=last_day, limit=1)
            if obs and obs[0].get("close_price") is not None:
                block["last"] = float(obs[0]["close_price"])
    return MarketSnapshot(
        day,
        latest_day,
        with_data,
        len(quotes),
        sorted(quotes.values(), key=lambda q: q.ticker_symbol),
        performance,
        list(reversed(movers[-MOVERS:])),
        movers[:MOVERS],
        index_block,
        coverage,
    )


__all__ = [
    "BENCHMARK_INDICES",
    "MarketSnapshot",
    "Quote",
    "SectorPerf",
    "build_market",
    "latest_quotes",
]
