"""The stock list and the stock detail page.

The list is one snapshot of the universe (quotes + latest ranking, factor percentiles,
three valuation multiples), cached per store version and filtered, sorted and paged in
memory - the NSE has about a hundred instruments. The detail page is the research
profile (``build_profile``, unchanged) plus what the profile does not carry: the latest
quote, a price history with its gaps spelled out, fiscal-year statement rows, the stock
against its sector's medians, company facts, and a geographic block that is honestly
``unavailable`` - the scraper captures nothing geographic.

    codegraph explore "list_stocks build_stock_detail price_history statement_summary"
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import date, timedelta
from statistics import median
from typing import Any, Literal

from app.web.api.pagination import decode_cursor, encode_cursor
from app.web.config import Settings
from app.web.core.exceptions import DataValidationError
from app.web.db.analytics import analytics_session
from app.web.db.analytics.models import Forecast, FundamentalMetric, StockRanking
from app.web.db.analytics.services.classifications import load_classifications
from app.web.db.analytics.services.factor_scores import load_factor_scores
from app.web.db.analytics.services.fundamental_metrics import load_fundamental_metrics
from app.web.db.analytics.services.market_metrics import load_metrics
from app.web.db.analytics.services.stock_rankings import load_rankings
from app.web.db.analytics.services.summaries import latest_as_of, latest_known_as_of
from app.web.services.analytics.classification.lookup import ClassificationIndex
from app.web.services.analytics.config import DEFAULT_CONFIG
from app.web.services.analytics.fundamentals.engine import concept_series
from app.web.services.analytics.fundamentals.statements import load_statement_rows
from app.web.services.analytics.research.profile import ResearchProfile, build_profile
from app.web.services.analytics.series import find_gaps
from app.web.services.dashboard.cache import get_dashboard_cache, store_stamp
from app.web.services.dashboard.common import from_row, known, measure, unavailable
from app.web.services.dashboard.geography import geographic_block
from app.web.services.dashboard.market import Quote, latest_quotes
from app.web.services.market_data.sources.nse_scraper import NseScraperSource

SortKey = Literal[
    "ticker", "price", "change", "volume", "market_cap", "score", "pe", "pb", "dividend_yield"
]
SORT_KEYS: tuple[str, ...] = (
    "ticker",
    "price",
    "change",
    "volume",
    "market_cap",
    "score",
    "pe",
    "pb",
    "dividend_yield",
)
PriceRange = Literal["1m", "3m", "6m", "1y", "3y", "5y", "max"]
RANGE_DAYS: dict[str, int | None] = {
    "1m": 31,
    "3m": 93,
    "6m": 183,
    "1y": 366,
    "3y": 1096,
    "5y": 1827,
    "max": None,
}
Interval = Literal["daily", "weekly", "monthly"]
FACTORS: tuple[str, ...] = (
    "value",
    "quality",
    "growth",
    "momentum",
    "dividend",
    "risk",
    "liquidity",
)
LIST_MULTIPLES: tuple[str, ...] = ("pe", "pb", "dividend_yield")
#: Metrics the detail page compares with the sector median (market, then fundamental).
SECTOR_COMPARE_MARKET: tuple[str, ...] = (
    "return_1m",
    "return_12m",
    "volatility_annualised",
    "market_cap",
    "avg_daily_volume",
)
SECTOR_COMPARE_FUNDAMENTAL: tuple[str, ...] = (
    "pe",
    "pb",
    "dividend_yield",
    "roe",
    "net_margin",
    "revenue_growth_1y",
)
STATEMENT_CONCEPTS: tuple[str, ...] = (
    "revenue",
    "net_income",
    "eps",
    "dps",
    "equity",
    "total_assets",
    "ocf",
    "fcf",
)


@dataclass(frozen=True)
class StockRow:
    ticker_symbol: str
    company_name: str | None
    sector: str | None
    industry: str | None
    price: dict[str, Any]
    change_pct: dict[str, Any]
    volume: dict[str, Any]
    market_cap: dict[str, Any]
    pe: dict[str, Any]
    pb: dict[str, Any]
    dividend_yield: dict[str, Any]
    factor_percentiles: dict[str, float | None]
    overall_score: dict[str, Any]
    classification: str | None
    market_rank: int | None
    confidence: float | None
    value_trap_risk: int | None
    compounder_score: float | None
    as_of: date | None


@dataclass(frozen=True)
class StockPage:
    items: list[StockRow]
    next_cursor: str | None
    total: int
    as_of: date | None
    sort: str
    order: str

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class PricePoint:
    date: date
    close: float
    volume: float | None
    change_pct: float | None
    source: str
    flagged: bool


@dataclass(frozen=True)
class PriceHistory:
    ticker_symbol: str
    range: str
    interval: str
    start: date | None
    end: date | None
    points: list[PricePoint]
    gaps: list[dict[str, Any]]
    gap_threshold_days: int
    n_observations: int
    availability: dict[str, Any]
    source_tickers: list[str]
    #: When the requested window starts inside a hole (the 2025 gap, or before
    #: listing): the stretch with nothing in it, so a chart can shade it.
    missing_start: dict[str, Any] | None = None

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class FiscalYear:
    period_end: date
    label: str
    currency: str | None
    values: dict[str, dict[str, Any]]


@dataclass(frozen=True)
class Statements:
    ticker_symbol: str
    as_of: date
    period_type: str
    concepts: list[str]
    years: list[FiscalYear]
    availability: dict[str, Any]

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class StockDetail:
    ticker_symbol: str
    quote: Quote
    profile: dict[str, Any]
    prices: PriceHistory
    sector_comparison: list[dict[str, Any]]
    statements: Statements
    facts: dict[str, Any]
    geographic: dict[str, Any]
    forecast_availability: dict[str, Any]
    links: dict[str, str] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


# --- the list ---------------------------------------------------------------------------


def stock_universe_snapshot(
    settings: Settings, source: NseScraperSource
) -> tuple[date | None, list[StockRow]]:
    """Every classified equity with its quote, latest ranking, factor percentiles and
    multiples - cached per store version; the list endpoint filters and sorts this."""
    return get_dashboard_cache(settings).get_or_compute(
        ("stocks",), store_stamp(settings), lambda: _stock_universe_snapshot(settings, source)
    )


def _stock_universe_snapshot(
    settings: Settings, source: NseScraperSource
) -> tuple[date | None, list[StockRow]]:
    quotes = latest_quotes(settings, source)
    with analytics_session(settings) as session:
        day = latest_as_of(session, StockRanking)
        rankings = (
            {r.ticker_symbol: r for r in load_rankings(session, as_of_date=day)} if day else {}
        )
        scores: dict[str, dict[str, float | None]] = {}
        if day:
            for f in load_factor_scores(session, as_of_date=day):
                scores.setdefault(f.ticker_symbol, {})[f.factor] = (
                    f.percentile_market if f.status in ("known", "zero") else None
                )
        fm_day = latest_as_of(session, FundamentalMetric)
        multiples: dict[str, dict[str, dict[str, Any]]] = {}
        if fm_day:
            for name in LIST_MULTIPLES:
                for fm in load_fundamental_metrics(session, as_of_date=fm_day, metric=name):
                    multiples.setdefault(fm.ticker_symbol, {})[name] = from_row(fm)
    rows: list[StockRow] = []
    for ticker, q in sorted(quotes.items()):
        rank = rankings.get(ticker)
        m = multiples.get(ticker, {})
        fm_label = fm_day.isoformat() if fm_day else "any date"
        no_fund = f"not computed (no statements captured) as of {fm_label}"
        rows.append(
            StockRow(
                ticker,
                q.company_name,
                q.sector,
                q.industry,
                q.price,
                q.change_pct,
                q.volume,
                q.market_cap,
                m.get("pe", unavailable(no_fund)),
                m.get("pb", unavailable(no_fund)),
                m.get("dividend_yield", unavailable(no_fund)),
                {f: scores.get(ticker, {}).get(f) for f in FACTORS},
                _score(rank, day),
                rank.classification if rank else None,
                rank.market_rank if rank else None,
                rank.confidence if rank else None,
                rank.value_trap_risk if rank else None,
                rank.compounder_score if rank else None,
                rank.as_of_date if rank else None,
            )
        )
    return day, rows


def _score(r: Any, day: date | None) -> dict[str, Any]:
    if r is None:
        return unavailable(f"not ranked as of {day.isoformat() if day else 'any date'}")
    return measure(r.overall_score, str(r.status), r.reason)


def _sort_value(row: StockRow, key: str) -> tuple[int, Any]:
    """Known values first (0), everything else last (1) regardless of direction."""
    if key == "ticker":
        return (0, row.ticker_symbol)
    if key == "score":
        v = row.overall_score["value"]
    elif key == "change":
        v = row.change_pct["value"]
    else:
        v = getattr(row, key)["value"]
    return (1, 0.0) if v is None else (0, float(v))


def list_stocks(
    settings: Settings,
    source: NseScraperSource,
    *,
    q: str | None = None,
    sector: str | None = None,
    sort: str = "ticker",
    order: str = "asc",
    limit: int = 50,
    cursor: str | None = None,
) -> StockPage:
    if sort not in SORT_KEYS:
        raise DataValidationError(f"sort must be one of {', '.join(SORT_KEYS)}.")
    if order not in ("asc", "desc"):
        raise DataValidationError("order must be asc or desc.")
    day, rows = stock_universe_snapshot(settings, source)
    needle = (q or "").strip().lower()
    if needle:
        rows = [
            r
            for r in rows
            if needle in r.ticker_symbol.lower()
            or needle in (r.company_name or "").lower()
            or needle in (r.sector or "").lower()
        ]
    if sector:
        rows = [r for r in rows if (r.sector or "").lower() == sector.strip().lower()]
    known_rows = [r for r in rows if _sort_value(r, sort)[0] == 0]
    unknown_rows = [r for r in rows if _sort_value(r, sort)[0] == 1]
    known_rows.sort(key=lambda r: _sort_value(r, sort)[1], reverse=order == "desc")
    ordered = known_rows + unknown_rows
    offset = 0
    if cursor:
        payload = decode_cursor(cursor)
        if (
            payload.get("sort") != sort
            or payload.get("order") != order
            or payload.get("q") != (q or "")
            or payload.get("sector") != (sector or "")
        ):
            raise DataValidationError("This cursor belongs to a different query.")
        offset = int(payload.get("offset", 0))
    page = ordered[offset : offset + limit]
    next_cursor = (
        encode_cursor(
            {
                "offset": offset + limit,
                "sort": sort,
                "order": order,
                "q": q or "",
                "sector": sector or "",
            }
        )
        if offset + limit < len(ordered)
        else None
    )
    return StockPage(page, next_cursor, len(ordered), day, sort, order)


# --- prices -----------------------------------------------------------------------------


def _thin(points: list[PricePoint], interval: str) -> list[PricePoint]:
    if interval == "daily":
        return points
    keep: dict[tuple[int, int], PricePoint] = {}
    for p in points:  # the last observation of each ISO week / month wins
        key = (
            (p.date.isocalendar()[0], p.date.isocalendar()[1])
            if interval == "weekly"
            else (p.date.year, p.date.month)
        )
        keep[key] = p
    return list(keep.values())


def price_history(
    settings: Settings,
    source: NseScraperSource,
    ticker: str,
    *,
    range_: str = "1y",
    interval: str = "daily",
) -> PriceHistory | None:
    """Closes for one instrument (indices included) with every break longer than the
    engine's gap threshold listed explicitly; None when the store does not know it."""
    symbol = ticker.strip().upper()
    with analytics_session(settings) as session:
        index = ClassificationIndex(load_classifications(session))
    if symbol not in index.tickers:
        return None
    spans = source.fetch_observation_spans()
    span = spans.get(symbol)
    threshold = DEFAULT_CONFIG.market.gap_threshold_days
    if span is None:
        return PriceHistory(
            symbol,
            range_,
            interval,
            None,
            None,
            [],
            [],
            threshold,
            0,
            unavailable("no observations for this instrument"),
            [],
        )
    _, end, _ = span
    days = RANGE_DAYS[range_]
    start = end - timedelta(days=days) if days else None
    rows = source.fetch_observations(symbol, start=start, end=end, limit=20_000)
    points: list[PricePoint] = []
    sources: list[str] = []
    for o in rows:
        close = o.get("close_price")
        if close is None or float(close) <= 0:
            continue
        src = str(o.get("source_ticker") or symbol)
        if src not in sources:
            sources.append(src)
        flags = o.get("quality_flags") or []
        points.append(
            PricePoint(
                date.fromisoformat(str(o["trade_date"])),
                float(close),
                float(o["volume"]) if o.get("volume") is not None else None,
                float(o["change_pct"]) if o.get("change_pct") is not None else None,
                str(o.get("data_source") or ""),
                bool(flags),
            )
        )
    gaps = find_gaps((p.date for p in points), threshold)
    missing_start: dict[str, Any] | None = None
    if points and start is not None and (points[0].date - start).days > threshold:
        missing_start = {
            "from": start,
            "to": points[0].date,
            "days": (points[0].date - start).days,
        }
    if not points:
        availability = unavailable(f"no observations between {start} and {end}")
    elif missing_start and not gaps:
        availability = measure(
            None,
            "partial",
            f"nothing observed between {start} and {points[0].date} "
            f"({missing_start['days']} d at the start of the window)",
        )
    elif gaps:
        biggest = max(gaps, key=lambda g: g.days)
        availability = measure(
            None,
            "partial",
            f"{len(gaps)} gap(s) in the window; the longest "
            f"{biggest.after} -> {biggest.before} ({biggest.days} d)",
        )
    else:
        availability = measure(None, "known", None)
    return PriceHistory(
        symbol,
        range_,
        interval,
        points[0].date if points else None,
        points[-1].date if points else None,
        _thin(points, interval),
        [{"after": g.after, "before": g.before, "days": g.days} for g in gaps],
        threshold,
        len(points),
        availability,
        sources,
        missing_start,
    )


# --- statements -------------------------------------------------------------------------


def statement_summary(
    source: NseScraperSource, ticker: str, *, periods: int = 10, as_of: date | None = None
) -> Statements:
    """One row per fiscal year as known on ``as_of``: the headline concepts, each a
    measure (``missing`` when the statement never reported it)."""
    symbol = ticker.strip().upper()
    day = as_of or date.today()
    raw = source.fetch_financial_statements(symbol, period_type="annual")
    if not raw:
        return Statements(
            symbol,
            day,
            "annual",
            list(STATEMENT_CONCEPTS),
            [],
            unavailable("no statements captured for this instrument"),
        )
    rows = load_statement_rows(raw, DEFAULT_CONFIG)
    currency = next((str(r.get("currency")) for r in raw if r.get("currency")), None)
    by_period: dict[date, dict[str, dict[str, Any]]] = {}
    labels: dict[date, str] = {}
    for concept in STATEMENT_CONCEPTS:
        for period_end, m in concept_series(rows, day, concept):
            by_period.setdefault(period_end, {})[concept] = _slim(m.as_dict())
    for r in rows:
        if r.period_type == "annual":
            labels.setdefault(r.fiscal_period_end, r.fiscal_label)
    years = [
        FiscalYear(
            period_end,
            labels.get(period_end, period_end.isoformat()),
            currency,
            {
                c: by_period[period_end].get(
                    c, measure(None, "missing", f"{c} not reported for this period")
                )
                for c in STATEMENT_CONCEPTS
            },
        )
        for period_end in sorted(by_period, reverse=True)[:periods]
    ]
    availability = (
        measure(None, "known", None)
        if years
        else unavailable(f"no annual statement known on {day}")
    )
    return Statements(symbol, day, "annual", list(STATEMENT_CONCEPTS), years, availability)


def _slim(m: dict[str, Any]) -> dict[str, Any]:
    return {"value": m.get("value"), "status": m.get("status"), "reason": m.get("reason")}


# --- sector comparison ------------------------------------------------------------------


def sector_comparison(
    settings: Settings, profile: ResearchProfile, index: ClassificationIndex
) -> list[dict[str, Any]]:
    """The stock's value beside the median of its sector peers, per metric."""
    out: list[dict[str, Any]] = []
    with analytics_session(settings) as session:
        for source_name, names, block_names in (
            ("market_metrics", SECTOR_COMPARE_MARKET, ("returns", "momentum", "risk", "liquidity")),
            (
                "fundamental_metrics",
                SECTOR_COMPARE_FUNDAMENTAL,
                ("value", "quality", "growth", "dividend"),
            ),
        ):
            day_iso = profile.as_of.get(source_name)
            day = date.fromisoformat(day_iso) if day_iso else None
            peers = index.peers_for(profile.ticker_symbol, day) if day else []
            for name in names:
                stock = next(
                    (
                        profile.metrics[b][name]
                        for b in block_names
                        if name in profile.metrics.get(b, {})
                    ),
                    None,
                )
                if day is None or stock is None:
                    out.append(
                        {
                            "metric": name,
                            "stock": unavailable(f"{name}: not computed"),
                            "sector_median": unavailable("no result date"),
                            "sector_members": 0,
                            "known_peers": 0,
                            "percentile_in_sector": None,
                        }
                    )
                    continue
                loader = (
                    load_metrics if source_name == "market_metrics" else load_fundamental_metrics
                )
                values = [
                    float(r.value)
                    for r in loader(session, as_of_date=day, metric=name)
                    if r.ticker_symbol in peers
                    and r.status in ("known", "zero")
                    and r.value is not None
                ]
                if values:
                    med = known(median(values))
                    pct = (
                        round(
                            100.0
                            * sum(1 for v in values if v <= float(stock["value"]))
                            / len(values),
                            1,
                        )
                        if stock.get("value") is not None
                        else None
                    )
                else:
                    med = unavailable(f"no sector peer has a known {name} on {day}")
                    pct = None
                out.append(
                    {
                        "metric": name,
                        "stock": _slim(stock),
                        "sector_median": med,
                        "sector_members": len(peers),
                        "known_peers": len(values),
                        "percentile_in_sector": pct,
                    }
                )
    return out


# --- the detail page ---------------------------------------------------------------------


def build_stock_detail(
    settings: Settings, source: NseScraperSource, ticker: str, *, as_of: date | None = None
) -> StockDetail | None:
    profile = build_profile(settings, ticker, as_of=as_of)
    if profile is None:
        return None
    symbol = profile.ticker_symbol
    with analytics_session(settings) as session:
        index = ClassificationIndex(load_classifications(session))
        latest_forecast = latest_known_as_of(session, Forecast, ticker_symbol=symbol)
    quote = latest_quotes(settings, source).get(symbol) or Quote(
        symbol,
        None,
        profile.identity.get("sector"),
        profile.identity.get("industry"),
        unavailable("not an equity in the quote universe"),
        unavailable("not an equity in the quote universe"),
        unavailable("not an equity in the quote universe"),
        unavailable("not an equity in the quote universe"),
        unavailable("not an equity in the quote universe"),
        unavailable("not an equity in the quote universe"),
        unavailable("no observations"),
        None,
        None,
        {},
        "none",
    )
    prices = price_history(settings, source, symbol, range_="1y") or PriceHistory(
        symbol,
        "1y",
        "daily",
        None,
        None,
        [],
        [],
        DEFAULT_CONFIG.market.gap_threshold_days,
        0,
        unavailable("no observations"),
        [],
    )
    forecast_cells = [
        cell["expected_return"]
        for model in (profile.forecast.get("models") or {}).values()
        for cell in model.values()
    ]
    if any(c.get("status") in ("known", "zero") for c in forecast_cells):
        forecast_availability = measure(None, "known", None)
    else:
        reason = (
            next((c.get("reason") for c in forecast_cells if c.get("reason")), None)
            or profile.forecast.get("reason")
            or "forecast: not computed"
        )
        forecast_availability = unavailable(str(reason))
    forecast_availability["latest_known_as_of"] = latest_forecast
    facts = {
        "company_name": quote.company_name,
        "sector": profile.identity.get("sector"),
        "industry": profile.identity.get("industry") or quote.facts.get("industry"),
        "founded": quote.facts.get("founded"),
        "employees": quote.facts.get("employees"),
        "revenue": quote.facts.get("revenue"),
        "classification_source": profile.identity.get("classification_source"),
        "listed_since": None,
        "country": quote.facts.get("country"),
        "ceo": quote.facts.get("ceo"),
        "website": quote.facts.get("website"),
        "address": quote.facts.get("address"),
        "exchange": quote.facts.get("exchange"),
        "fiscal_year": quote.facts.get("fiscal_year"),
        "currency": quote.facts.get("currency"),
        "sic": quote.facts.get("sic"),
        "executives": quote.facts.get("executives"),
    }
    span = source.fetch_observation_spans().get(symbol)
    if span:
        facts["listed_since"] = span[0]
    return StockDetail(
        symbol,
        quote,
        profile.as_dict(),
        prices,
        sector_comparison(settings, profile, index),
        statement_summary(source, symbol, as_of=as_of),
        facts,
        geographic_block(quote.facts),
        forecast_availability,
        {
            "prices": f"/api/v1/dashboard/stocks/{symbol}/prices",
            "statements": f"/api/v1/dashboard/stocks/{symbol}/statements",
            "forecasts": f"/api/v1/dashboard/forecasts?ticker={symbol}",
        },
    )


__all__ = [
    "FACTORS",
    "SORT_KEYS",
    "PriceHistory",
    "Statements",
    "StockDetail",
    "StockPage",
    "StockRow",
    "build_stock_detail",
    "list_stocks",
    "price_history",
    "sector_comparison",
    "statement_summary",
    "stock_universe_snapshot",
]
