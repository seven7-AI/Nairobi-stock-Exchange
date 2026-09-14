"""Resolve the fair-value inputs for a date and store the valuations.

Inputs come from three places, all point-in-time: the statements known on the date
(per-share figures), the last close on or before it, and the metric rows already
stored for it (quality, growth, beta, liquidity, leverage - run those jobs first).
Peer multiples are the sector median (market median when the sector has too few
members) of the stored ``pe`` and ``ev_ebitda`` values.

    codegraph explore "compute_fair_value resolve_inputs value_stock"
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import UTC, date, datetime
from statistics import median

from app.web.config import Settings
from app.web.db.analytics import analytics_session
from app.web.db.analytics.models import JobRun, JobStatus
from app.web.db.analytics.services.classifications import load_classifications
from app.web.db.analytics.services.factor_scores import metric_table_for
from app.web.db.analytics.services.valuations import upsert_valuations
from app.web.services.analytics.classification.lookup import ClassificationIndex
from app.web.services.analytics.classification.taxonomy import OPERATING_SECTORS
from app.web.services.analytics.config import DEFAULT_CONFIG, AnalyticsConfig, register_calc_version
from app.web.services.analytics.fair_value.engine import Valuation, ValuationInputs, value_stock
from app.web.services.analytics.fundamentals.engine import concept_series, latest
from app.web.services.analytics.fundamentals.service import load_statements
from app.web.services.analytics.fundamentals.statements import StatementRow
from app.web.services.analytics.measure import Measure, Provenance
from app.web.services.analytics.returns.service import ComputeResult, load_universe
from app.web.services.analytics.series import PriceSeries
from app.web.services.analytics.valuation_metrics.engine import price_on
from app.web.services.market_data.sources.nse_scraper import NseScraperSource
from app.web.utils.logger import get_logger

logger = get_logger(__name__)

JOB_NAME = "fair_value"

#: Stored metrics the engine reads, by source table.
INPUT_METRICS: dict[str, tuple[str, ...]] = {
    "fundamental": (
        "roe",
        "payout_ratio",
        "revenue_cagr_3y",
        "dividend_cagr_3y",
        "debt_to_equity",
        "interest_coverage",
        "roe_trend",
        "net_margin_trend",
        "pe",
        "ev_ebitda",
    ),
    "market": ("beta_12m", "liquidity_score"),
}


def _latest_known(rows: Sequence[StatementRow], as_of: date, concept: str) -> Measure | None:
    current = latest(concept_series(rows, as_of, concept))
    return current[1] if current is not None else None


def _per_share(numerator: Measure | None, shares: Measure | None) -> float | None:
    if numerator is None or shares is None or not shares.is_positive:
        return None
    return float(numerator.value or 0.0) / float(shares.value or 1.0)


def peer_median(
    values: Mapping[str, float], members: Sequence[str], *, min_members: int
) -> float | None:
    """Median of the members' positive multiples; None below the minimum."""
    found = [values[t] for t in members if t in values and values[t] > 0]
    if len(found) < min_members:
        return None
    return float(median(found))


def resolve_inputs(
    ticker: str,
    rows: Sequence[StatementRow],
    series: PriceSeries,
    as_of: date,
    *,
    sector_code: str | None,
    metrics: Mapping[str, float],
    peers: Sequence[str],
    market: Sequence[str],
    multiples: Mapping[str, Mapping[str, float]],
    config: AnalyticsConfig,
) -> ValuationInputs:
    """Statements + price + stored metrics + peer medians -> the engine's inputs."""
    price = price_on(series, as_of)
    shares = _latest_known(rows, as_of, "shares")
    eps = _latest_known(rows, as_of, "eps")
    equity = _latest_known(rows, as_of, "equity")
    dps = _latest_known(rows, as_of, "dps")
    ebitda = _latest_known(rows, as_of, "ebitda")
    debt = _latest_known(rows, as_of, "total_debt")
    cash = _latest_known(rows, as_of, "cash")
    fcf_series = [(end, m) for end, m in concept_series(rows, as_of, "fcf") if m.is_known]
    shares_series = {end: m for end, m in concept_series(rows, as_of, "shares") if m.is_positive}
    fcf_history: list[float] = []
    for end, m in fcf_series:
        year_shares = shares_series.get(end, shares)
        per_share = _per_share(m, year_shares)
        if per_share is not None:
            fcf_history.append(per_share)
    fiscal_years = sum(1 for _, m in concept_series(rows, as_of, "revenue") if m.is_known)
    net_debt = (
        Measure.known(float(debt.value or 0.0) - float(cash.value or 0.0))
        if debt is not None and cash is not None and debt.is_known and cash.is_known
        else None
    )
    min_peers = config.fair_value.min_peers
    peer_pe = peer_median(multiples.get("pe", {}), peers, min_members=min_peers)
    pe_source = "sector median"
    if peer_pe is None:
        peer_pe = peer_median(
            multiples.get("pe", {}), [m for m in market if m != ticker], min_members=min_peers
        )
        pe_source = "market median"
    peer_ev = peer_median(multiples.get("ev_ebitda", {}), peers, min_members=min_peers)
    ev_source = "sector median"
    if peer_ev is None:
        peer_ev = peer_median(
            multiples.get("ev_ebitda", {}),
            [m for m in market if m != ticker],
            min_members=min_peers,
        )
        ev_source = "market median"
    provenance: list[Provenance] = []
    if not isinstance(price, Measure):
        provenance.append(price.provenance)
    if eps is not None:
        provenance.extend(eps.provenance)

    def stored(name: str) -> float | None:
        return metrics.get(name)

    return ValuationInputs(
        ticker_symbol=ticker,
        sector_code=sector_code,
        price=None if isinstance(price, Measure) else price.close,
        price_reason=price.reason if isinstance(price, Measure) else None,
        fiscal_years=fiscal_years,
        eps=eps.value if eps is not None and eps.is_known else None,
        bvps=_per_share(equity, shares),
        dps=dps.value if dps is not None and dps.is_known else None,
        ebitda_per_share=_per_share(ebitda, shares),
        net_debt_per_share=_per_share(net_debt, shares) if net_debt is not None else None,
        fcf_history=tuple(fcf_history),
        roe=stored("roe"),
        payout_ratio=stored("payout_ratio"),
        revenue_cagr_3y=stored("revenue_cagr_3y"),
        dividend_cagr_3y=stored("dividend_cagr_3y"),
        beta=stored("beta_12m"),
        liquidity_score=stored("liquidity_score"),
        debt_to_equity=stored("debt_to_equity"),
        interest_coverage=stored("interest_coverage"),
        roe_trend=stored("roe_trend"),
        net_margin_trend=stored("net_margin_trend"),
        peer_pe=peer_pe,
        peer_pe_source=pe_source if peer_pe is not None else None,
        peer_ev_ebitda=peer_ev,
        peer_ev_ebitda_source=ev_source if peer_ev is not None else None,
        provenance=tuple(provenance),
    )


def compute_fair_value(
    settings: Settings,
    source: NseScraperSource,
    *,
    as_of: date | None = None,
    tickers: list[str] | None = None,
    config: AnalyticsConfig = DEFAULT_CONFIG,
) -> ComputeResult:
    day = as_of or datetime.now(UTC).date()
    started = datetime.now(UTC)
    with analytics_session(settings) as session:
        version = register_calc_version(session, config)
        run = JobRun(job_name=JOB_NAME, started_at=started, as_of_date=day)
        session.add(run)
        session.flush()
        try:
            index = ClassificationIndex(load_classifications(session))
            universe = load_universe(source, config)
            instruments = list(universe)
            requested = {t.strip().upper() for t in tickers} if tickers else set(instruments)
            statements = load_statements(source, instruments, config)
            table = metric_table_for(session, day)
            per_ticker: dict[str, dict[str, float]] = {}
            for source_name, names in INPUT_METRICS.items():
                for name in names:
                    for t, value in table.get((source_name, name), {}).items():
                        per_ticker.setdefault(t, {})[name] = value
            multiples = {
                "pe": table.get(("fundamental", "pe"), {}),
                "ev_ebitda": table.get(("fundamental", "ev_ebitda"), {}),
            }
            market = [
                t
                for t in instruments
                if (a := index.sector_for(t, day)) is not None
                and a.sector_code in OPERATING_SECTORS
            ]
            results: list[Valuation] = []
            skipped: dict[str, str] = {}
            known: dict[str, int] = {}
            for ticker in instruments:
                if ticker not in requested:
                    continue
                rows = statements.get(ticker, [])
                if not rows:
                    skipped[ticker] = "no financial statements captured"
                    continue
                assignment = index.sector_for(ticker, day)
                inputs = resolve_inputs(
                    ticker,
                    rows,
                    universe[ticker].as_of(day),
                    day,
                    sector_code=assignment.sector_code if assignment else None,
                    metrics=per_ticker.get(ticker, {}),
                    peers=[p for p in index.peers_for(ticker, day) if p in per_ticker],
                    market=market,
                    multiples=multiples,
                    config=config,
                )
                valuation = value_stock(inputs, config)
                results.append(valuation)
                for m in valuation.methods:
                    if m.base is not None:
                        known[m.method] = known.get(m.method, 0) + 1
                if valuation.intrinsic.is_known:
                    known["blended"] = known.get("blended", 0) + 1
            written = upsert_valuations(
                session, results, as_of_date=day, calc_version_id=version.id
            )
        except Exception as exc:
            run.status = JobStatus.FAILED
            run.error = f"{type(exc).__name__}: {exc}"
            run.finished_at = datetime.now(UTC)
            raise
        run.status = JobStatus.SUCCEEDED
        run.finished_at = datetime.now(UTC)
        run.rows_written = written
        run.watermark = day.isoformat()
        run.details = {
            "calc_version_id": version.id,
            "instruments": len(results),
            "skipped": len(skipped),
            "known_counts": known,
        }
        version_id = version.id
    processed = [r.ticker_symbol for r in results]
    logger.info(
        "fair_value_computed",
        as_of=day.isoformat(),
        instruments=len(processed),
        rows=written,
        known=known,
        calc_version_id=version_id,
    )
    return ComputeResult(JOB_NAME, day, version_id, written, tuple(processed), skipped, known)


__all__ = ["INPUT_METRICS", "JOB_NAME", "compute_fair_value", "peer_median", "resolve_inputs"]
