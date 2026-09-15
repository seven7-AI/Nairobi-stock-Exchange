"""Research API - the analytics store over HTTP.

Every endpoint reads stored, versioned results; nothing is computed on request.
The store is SQLite behind a sync session, so each handler runs its read in the
threadpool. Cursor pagination is by ticker symbol (stocks, rankings) or run id
(backtests).

    codegraph explore "research views.py build_profile load_rankings load_backtest_runs"
"""

from __future__ import annotations

from datetime import date as date_type
from typing import Any

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, select
from starlette.concurrency import run_in_threadpool

from app.web.api.deps import SettingsDep
from app.web.api.routers.research.schema import (
    BacktestPage,
    BacktestRow,
    BlockOut,
    HistoryOut,
    HistoryPoint,
    Measure,
    RankingPage,
    RankingRow,
    ResearchProfileOut,
    SectorRow,
    SectorsOut,
    StockPage,
    StockSummary,
)
from app.web.config import Settings
from app.web.core.exceptions import ResourceNotFoundError
from app.web.core.security import RESEARCH_ROLES, require_roles
from app.web.db.analytics import analytics_session
from app.web.db.analytics.models import StockRanking
from app.web.db.analytics.services.backtests import load_backtest_results, load_backtest_runs
from app.web.db.analytics.services.classifications import load_classifications
from app.web.db.analytics.services.stock_rankings import load_rankings
from app.web.services.analytics.classification.lookup import ClassificationIndex
from app.web.services.analytics.research import build_profile
from app.web.services.visualizations.research_charts import load_sector_performance

router = APIRouter(prefix="/research", tags=["research"])

ResearchUser = Depends(require_roles(*RESEARCH_ROLES))
Limit = Query(default=50, ge=1, le=200)
Cursor = Query(default=None, description="Opaque cursor from the previous page")
AsOf = Query(default=None, description="Date (YYYY-MM-DD); default latest stored")

BLOCK_NAMES = {
    "metrics": None,
    "valuation": "valuation",
    "forecast": "forecast",
    "risk": "risk",
    "factors": "factors",
}


def _profile_or_404(settings: Settings, ticker: str, as_of: date_type | None) -> Any:
    profile = build_profile(settings, ticker, as_of=as_of)
    if profile is None:
        raise ResourceNotFoundError(f"{ticker.upper()} is not an instrument in the analytics store.")
    return profile


def _list_stocks(settings: Settings, limit: int, cursor: str | None) -> StockPage:
    with analytics_session(settings) as session:
        index = ClassificationIndex(load_classifications(session))
        tickers = [t for t in index.tickers if not t.startswith("^")]
        latest = session.execute(select(func.max(StockRanking.as_of_date))).scalar_one_or_none()
        rankings = {r.ticker_symbol: r for r in load_rankings(session, as_of_date=latest)} if latest else {}
        start = 0
        if cursor:
            start = next((i for i, t in enumerate(tickers) if t > cursor), len(tickers))
        page = tickers[start : start + limit]
        items = []
        for t in page:
            assignment = index.sector_for(t, latest or date_type.today())
            r = rankings.get(t)
            items.append(
                StockSummary(
                    ticker_symbol=t,
                    sector=assignment.sector_label if assignment else None,
                    industry=assignment.industry if assignment else None,
                    as_of=r.as_of_date if r else None,
                    overall_score=r.overall_score if r else None,
                    status=r.status if r else None,
                    classification=r.classification if r else None,
                    confidence=r.confidence if r else None,
                    market_rank=r.market_rank if r else None,
                )
            )
        next_cursor = page[-1] if start + limit < len(tickers) and page else None
        return StockPage(items=items, next_cursor=next_cursor, total=len(tickers))


@router.get("/stocks", response_model=StockPage, dependencies=[ResearchUser])
async def list_stocks(settings: SettingsDep, limit: int = Limit, cursor: str | None = Cursor) -> StockPage:
    """Every classified instrument with its latest ranking summary, paginated by ticker."""
    return await run_in_threadpool(_list_stocks, settings, limit, cursor)


@router.get("/stocks/{ticker}", response_model=ResearchProfileOut, dependencies=[ResearchUser])
async def stock_profile(ticker: str, settings: SettingsDep, as_of: date_type | None = AsOf) -> ResearchProfileOut:
    """The full research profile: score, factors, every metric block, valuation, forecast,
    scenarios, simulation, regime, model versions, data as-of."""
    profile = await run_in_threadpool(_profile_or_404, settings, ticker, as_of)
    return ResearchProfileOut(**profile.as_dict())


def _block(profile: Any, name: str) -> BlockOut:
    if name == "metrics":
        data = profile.metrics
        day = profile.as_of.get("market_metrics")
    elif name == "risk":
        data = {"risk": profile.metrics["risk"], "liquidity": profile.metrics["liquidity"]}
        day = profile.as_of.get("market_metrics")
    elif name == "factors":
        data = {"factors": profile.factors, "score": profile.score}
        day = profile.as_of.get("ranking")
    elif name == "valuation":
        data = {"valuation": profile.valuation, "value": profile.metrics["value"], "dividend": profile.metrics["dividend"]}
        day = profile.as_of.get("valuation")
    else:  # forecast
        data = {"forecast": profile.forecast, "scenarios": profile.scenarios, "simulation": profile.simulation}
        day = profile.as_of.get("forecast")
    return BlockOut(ticker_symbol=profile.ticker_symbol, as_of=day, block=name, data=data)


def _make_block_route(name: str) -> None:
    async def handler(ticker: str, settings: SettingsDep, as_of: date_type | None = AsOf) -> BlockOut:
        profile = await run_in_threadpool(_profile_or_404, settings, ticker, as_of)
        return _block(profile, name)

    handler.__name__ = f"stock_{name}"
    handler.__doc__ = f"The {name} block of the research profile."
    router.add_api_route(
        f"/stocks/{{ticker}}/{name}", handler, methods=["GET"], response_model=BlockOut,
        dependencies=[ResearchUser], name=f"stock_{name}",
    )


for _name in ("metrics", "valuation", "forecast", "risk", "factors"):
    _make_block_route(_name)


def _history(settings: Settings, ticker: str, limit: int) -> HistoryOut:
    symbol = ticker.upper()
    with analytics_session(settings) as session:
        index = ClassificationIndex(load_classifications(session))
        if symbol not in index.tickers:
            raise ResourceNotFoundError(f"{symbol} is not an instrument in the analytics store.")
        rows = load_rankings(session, ticker_symbol=symbol)
        newest: dict[date_type, StockRanking] = {}
        for r in rows:
            newest[r.as_of_date] = r  # ordered by rank then ticker; the last write per date wins
        points = [
            HistoryPoint(as_of=d, overall_score=r.overall_score, status=r.status, classification=r.classification, market_rank=r.market_rank)
            for d, r in sorted(newest.items())
        ][-limit:]
    return HistoryOut(ticker_symbol=symbol, points=points)


@router.get("/stocks/{ticker}/history", response_model=HistoryOut, dependencies=[ResearchUser])
async def stock_history(ticker: str, settings: SettingsDep, limit: int = Limit) -> HistoryOut:
    """The instrument's stored ranking per evaluation date, oldest first."""
    return await run_in_threadpool(_history, settings, ticker, limit)


def _rankings(settings: Settings, as_of: date_type | None, limit: int, cursor: str | None) -> RankingPage:
    with analytics_session(settings) as session:
        day = as_of or session.execute(select(func.max(StockRanking.as_of_date))).scalar_one_or_none()
        if day is None:
            raise ResourceNotFoundError("No rankings stored yet. Run the daily pipeline first.")
        index = ClassificationIndex(load_classifications(session))
        rows = load_rankings(session, as_of_date=day)
        if not rows:
            raise ResourceNotFoundError(f"No rankings stored for {day.isoformat()}.")
        rows.sort(key=lambda r: (r.market_rank is None, r.market_rank or 0, r.ticker_symbol))
        start = 0
        if cursor:
            start = next((i for i, r in enumerate(rows) if r.ticker_symbol == cursor), -1) + 1
        page = rows[start : start + limit]
        items = [
            RankingRow(
                ticker_symbol=r.ticker_symbol, market_rank=r.market_rank, overall_score=r.overall_score,
                status=r.status, confidence=r.confidence, classification=r.classification,
                value_trap_risk=r.value_trap_risk, compounder_score=r.compounder_score,
                sector=(a.sector_label if (a := index.sector_for(r.ticker_symbol, day)) else None),
            )
            for r in page
        ]
        model = f"{rows[0].model_name} v{rows[0].model_version}"
        next_cursor = page[-1].ticker_symbol if start + limit < len(rows) and page else None
    return RankingPage(as_of=day, model=model, items=items, next_cursor=next_cursor, total=len(rows))


@router.get("/rankings", response_model=RankingPage, dependencies=[ResearchUser])
async def rankings(settings: SettingsDep, as_of: date_type | None = AsOf, limit: int = Limit, cursor: str | None = Cursor) -> RankingPage:
    """The ranking table for a date, best first; unscored instruments follow with their reason."""
    return await run_in_threadpool(_rankings, settings, as_of, limit, cursor)


def _sectors(settings: Settings, as_of: date_type | None, metric: str) -> SectorsOut:
    with analytics_session(settings) as session:
        data = load_sector_performance(session, as_of=as_of, metric=metric)
    if data is None:
        raise ResourceNotFoundError("No market metrics stored yet. Run the daily pipeline first.")
    return SectorsOut(
        as_of=data.as_of, metric=data.metric,
        sectors=[SectorRow(sector=k, members=n, median_value=v) for k, (v, n) in data.sectors.items()],
    )


@router.get("/sectors", response_model=SectorsOut, dependencies=[ResearchUser])
async def sectors(settings: SettingsDep, as_of: date_type | None = AsOf, metric: str = Query(default="return_12m", pattern=r"^[a-z0-9_]+$")) -> SectorsOut:
    """Median of a stored market metric per sector, with the member count."""
    return await run_in_threadpool(_sectors, settings, as_of, metric)


def _backtests(settings: Settings, limit: int, cursor: str | None) -> BacktestPage:
    with analytics_session(settings) as session:
        runs = load_backtest_runs(session)
        start = 0
        if cursor:
            start = next((i for i, r in enumerate(runs) if str(r.id) == cursor), -1) + 1
        page = runs[start : start + limit]
        items = []
        for run in page:
            results = {(r.segment, r.series, r.metric): r for r in load_backtest_results(session, run.id)}
            linked = results.get(("linked", "portfolio", "total_return"))
            first = {
                k: {"value": row.value, "status": row.status, "reason": row.reason}
                for k in ("total_return", "cagr", "volatility", "sharpe", "max_drawdown", "alpha_vs_^NASI", "beta_vs_^NASI")
                if (row := results.get(("1", "portfolio", k))) is not None
            }
            items.append(
                BacktestRow(
                    run_id=run.id, name=run.name, purpose=run.purpose,
                    model=f"{run.model_name} v{run.model_version}", start_date=run.start_date,
                    end_date=run.end_date, top_n=run.top_n, cost_rate=float(run.costs.get("rate", 0.0)),
                    segments=run.segments, status=run.status,
                    linked_total_return=Measure(value=linked.value, status=linked.status, reason=linked.reason) if linked else Measure(status=run.status, reason=run.reason),
                    first_segment=first,
                )
            )
        next_cursor = str(page[-1].id) if start + limit < len(runs) and page else None
    return BacktestPage(items=items, next_cursor=next_cursor, total=len(runs))


@router.get("/backtests", response_model=BacktestPage, dependencies=[ResearchUser])
async def backtests(settings: SettingsDep, limit: int = Limit, cursor: str | None = Cursor) -> BacktestPage:
    """Stored backtest runs with their headline metrics, oldest first."""
    return await run_in_threadpool(_backtests, settings, limit, cursor)


__all__ = ["router"]
