"""The fundamentals engine: quality, leverage, cash flow and growth from the statements.

Everything is computed **point-in-time** from ``StatementRow``s (``statements.py``):
only figures available on ``as_of`` are used, the latest available fiscal year is the
"current" period, and every number carries the statement rows it came from.

Concepts, not labels: the site prints bank and industrial statements differently
(``diluted_shares_outstanding`` vs ``shares_outstanding_diluted``, ``net_income`` vs
``net_income_to_common``), so each concept lists the labels that can carry it, in
order of preference.

Applicability: banks and insurers (``FINANCIAL_SECTORS``) have no gross profit,
no operating margin in the industrial sense, and interest is their raw material -
``gross_margin``, ``operating_margin``, ``ebitda_margin``, ``interest_coverage``
and ``asset_turnover`` are ``not_applicable`` for them rather than misleading.

Trends: over at least ``trend_min_periods`` fiscal years a least-squares slope,
relative to the mean absolute level, labels a metric *improving* (+1), *stable* (0)
or *deteriorating* (-1); for leverage the sign is inverted (rising debt-to-equity is
deteriorating). Growth: one-year change, and 3-/5-year CAGR that are ``unavailable``
until enough fiscal years exist and ``not_meaningful`` across a sign change.

    codegraph explore "fundamental_metrics concept_series trend_label growth_metrics"
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import date

import numpy as np

from app.web.services.analytics.classification.taxonomy import FINANCIAL_SECTORS
from app.web.services.analytics.config import AnalyticsConfig
from app.web.services.analytics.fundamentals.statements import (
    StatementRow,
    line_item_series,
    statement_measure,
)
from app.web.services.analytics.measure import (
    Measure,
    Provenance,
    cagr,
    merge_provenance,
    pct_change,
    safe_div,
)

#: concept -> (statement, labels in order of preference)
CONCEPTS: dict[str, tuple[str, tuple[str, ...]]] = {
    "revenue": ("income", ("revenue", "operating_revenue", "total_revenue")),
    "net_income": ("income", ("net_income_to_common", "net_income")),
    "gross_profit": ("income", ("gross_profit",)),
    "operating_income": ("income", ("operating_income", "ebit")),
    "ebitda": ("income", ("ebitda",)),
    "interest_expense": ("income", ("interest_expense",)),
    "eps": ("income", ("eps_diluted", "eps_basic")),
    "dps": ("income", ("dividend_per_share",)),
    "shares": (
        "income",
        (
            "shares_outstanding_diluted",
            "diluted_shares_outstanding",
            "shares_outstanding_basic",
            "basic_shares_outstanding",
        ),
    ),
    "total_assets": ("balance", ("total_assets",)),
    "equity": ("balance", ("total_common_equity", "shareholders_equity")),
    "total_debt": ("balance", ("total_debt",)),
    "cash": ("balance", ("cash_and_short_term_investments", "cash_and_equivalents")),
    "total_liabilities": ("balance", ("total_liabilities",)),
    "ocf": ("cashflow", ("operating_cash_flow",)),
    "fcf": ("cashflow", ("free_cash_flow",)),
    "capex": ("cashflow", ("capital_expenditures",)),
    "dividends_paid": ("cashflow", ("common_dividends_paid",)),
}

TREND_METRICS: dict[str, bool] = {
    # metric -> True when a rising value is an improvement
    "roe": True,
    "roa": True,
    "net_margin": True,
    "operating_margin": True,
    "gross_margin": True,
    "fcf": True,
    "debt_to_equity": False,
}


@dataclass(frozen=True, slots=True)
class FundamentalResult:
    measure: Measure
    #: The fiscal period the value describes (its end date), when there is one.
    period_end: date | None = None
    period_type: str | None = None


ConceptSeries = list[tuple[date, Measure]]


def concept_series(
    rows: Iterable[StatementRow], as_of: date, concept: str, *, period_type: str = "annual"
) -> ConceptSeries:
    """The concept's values per fiscal period as known on ``as_of``, oldest first.

    The first label with any known value wins; a label present but all ``-`` is
    skipped in favour of the next.
    """
    statement, labels = CONCEPTS[concept]
    rows = list(rows)
    for label in labels:
        series = line_item_series(
            rows, as_of, statement=statement, line_item=label, period_type=period_type
        )
        if any(measure.is_known for _, measure in series):
            return series
    return []


def latest(series: ConceptSeries) -> tuple[date, Measure] | None:
    """The most recent period whose value is known (or explicitly zero)."""
    for period_end, measure in reversed(series):
        if measure.is_known:
            return period_end, measure
    return None


def previous(series: ConceptSeries, before: date) -> tuple[date, Measure] | None:
    for period_end, measure in reversed(series):
        if period_end < before and measure.is_known:
            return period_end, measure
    return None


def _missing(concept: str, as_of: date) -> Measure:
    return Measure.missing(f"{concept}: not reported in any statement known on {as_of}")


def _value_at(series: ConceptSeries, period_end: date) -> Measure | None:
    for end, measure in series:
        if end == period_end:
            return measure
    return None


def average_with_prior(series: ConceptSeries, period_end: date, name: str) -> Measure:
    """Mean of the value at ``period_end`` and at the prior period; the value alone if
    there is no prior (with the note in the reason)."""
    current = _value_at(series, period_end)
    if current is None or not current.is_known:
        return Measure.missing(f"{name}: no value for {period_end}")
    prior = previous(series, period_end)
    assert current.value is not None
    if prior is None or prior[1].value is None:
        return Measure.known(current.value, *current.provenance, reason=f"{name}: single period")
    return Measure.known(
        (current.value + prior[1].value) / 2.0, *merge_provenance(current, prior[1])
    )


# --- quality ----------------------------------------------------------------------------


def quality_metrics(
    rows: Sequence[StatementRow], as_of: date, *, sector_code: str | None
) -> dict[str, FundamentalResult]:
    """ROE, ROA, margins, cash flow, leverage and coverage for the latest fiscal year."""
    financial = sector_code in FINANCIAL_SECTORS
    revenue = concept_series(rows, as_of, "revenue")
    net_income = concept_series(rows, as_of, "net_income")
    equity = concept_series(rows, as_of, "equity")
    assets = concept_series(rows, as_of, "total_assets")
    debt = concept_series(rows, as_of, "total_debt")
    cash = concept_series(rows, as_of, "cash")
    ocf = concept_series(rows, as_of, "ocf")
    fcf = concept_series(rows, as_of, "fcf")
    operating = concept_series(rows, as_of, "operating_income")
    gross = concept_series(rows, as_of, "gross_profit")
    ebitda = concept_series(rows, as_of, "ebitda")
    interest = concept_series(rows, as_of, "interest_expense")

    current = latest(net_income) or latest(revenue)
    if current is None:
        blocked = Measure.unavailable(f"no income statement known on {as_of}")
        return {
            metric: FundamentalResult(blocked)
            for metric in (
                "roe",
                "roa",
                "net_margin",
                "operating_margin",
                "gross_margin",
                "ebitda_margin",
                "fcf",
                "ocf",
                "fcf_margin",
                "total_debt",
                "net_debt",
                "debt_to_equity",
                "interest_coverage",
                "asset_turnover",
            )
        }
    period_end = current[0]

    def at(series: ConceptSeries, concept: str) -> Measure:
        value = _value_at(series, period_end)
        return value if value is not None else _missing(concept, as_of)

    ni = at(net_income, "net_income")
    rev = at(revenue, "revenue")
    out: dict[str, FundamentalResult] = {}

    def put(metric: str, measure: Measure) -> None:
        out[metric] = FundamentalResult(measure, period_end, "annual")

    put("roe", safe_div(ni, average_with_prior(equity, period_end, "average equity"), name="roe"))
    put("roa", safe_div(ni, average_with_prior(assets, period_end, "average assets"), name="roa"))
    put("net_margin", safe_div(ni, rev, name="net margin"))
    if financial:
        na = Measure.not_applicable
        put("gross_margin", na("gross margin: not meaningful for a financial company"))
        put("operating_margin", na("operating margin: not meaningful for a financial company"))
        put("ebitda_margin", na("EBITDA margin: not meaningful for a financial company"))
        put(
            "interest_coverage",
            na("interest coverage: interest is a financial company's cost of goods"),
        )
        put("asset_turnover", na("asset turnover: not meaningful for a financial company"))
    else:
        put("gross_margin", safe_div(at(gross, "gross_profit"), rev, name="gross margin"))
        put(
            "operating_margin",
            safe_div(at(operating, "operating_income"), rev, name="operating margin"),
        )
        put("ebitda_margin", safe_div(at(ebitda, "ebitda"), rev, name="EBITDA margin"))
        interest_paid = at(interest, "interest_expense")
        if interest_paid.is_known and interest_paid.value is not None:
            magnitude = Measure.known(abs(interest_paid.value), *interest_paid.provenance)
            put(
                "interest_coverage",
                safe_div(at(operating, "operating_income"), magnitude, name="interest coverage"),
            )
        else:
            put(
                "interest_coverage",
                Measure(None, interest_paid.status, f"interest coverage: {interest_paid.reason}"),
            )
        put(
            "asset_turnover",
            safe_div(
                rev, average_with_prior(assets, period_end, "average assets"), name="asset turnover"
            ),
        )
    put("fcf", at(fcf, "fcf"))
    put("ocf", at(ocf, "ocf"))
    put(
        "fcf_margin",
        safe_div(at(fcf, "fcf"), rev, name="FCF margin", require_positive_denominator=True),
    )
    total_debt = at(debt, "total_debt")
    put("total_debt", total_debt)
    cash_value = at(cash, "cash")
    if total_debt.is_known and cash_value.is_known:
        assert total_debt.value is not None and cash_value.value is not None
        put(
            "net_debt",
            Measure.known(
                total_debt.value - cash_value.value, *merge_provenance(total_debt, cash_value)
            ),
        )
    else:
        blocker = total_debt if not total_debt.is_known else cash_value
        put("net_debt", Measure(None, blocker.status, f"net debt: {blocker.reason}"))
    put("debt_to_equity", safe_div(total_debt, at(equity, "equity"), name="debt to equity"))
    return out


# --- trends ---------------------------------------------------------------------------


def trend_label(
    values: Sequence[float], *, stable_band: float, rising_is_better: bool
) -> tuple[int, str]:
    """(+1 improving, 0 stable, -1 deteriorating) from the slope of the last periods.

    The slope is scaled by the mean absolute level so a 20 % ROE drifting 0.5 pp a year
    is stable while a 2 % ROE doing the same is not.
    """
    y = np.asarray(values, dtype=float)
    x = np.arange(len(y), dtype=float)
    slope = float(np.polyfit(x, y, 1)[0])
    scale = float(np.mean(np.abs(y))) or 1.0
    relative = slope / scale
    if abs(relative) <= stable_band:
        return 0, f"stable (slope {relative:+.1%} of level per period)"
    improving = relative > 0 if rising_is_better else relative < 0
    return (
        (1, f"improving (slope {relative:+.1%} of level per period)")
        if improving
        else (
            -1,
            f"deteriorating (slope {relative:+.1%} of level per period)",
        )
    )


def _history(rows: Sequence[StatementRow], as_of: date, metric: str) -> list[tuple[date, Measure]]:
    """The metric per fiscal year, each computed from the statements up to that year end
    (still limited to what was known on ``as_of``)."""
    ends = sorted({r.fiscal_period_end for r in rows if r.period_type == "annual"})
    history: list[tuple[date, Measure]] = []
    for end in ends:
        if end > as_of:
            break
        known_rows = [r for r in rows if r.fiscal_period_end <= end]
        result = quality_metrics(known_rows, as_of, sector_code=None).get(metric)
        if result is not None and result.period_end == end:
            history.append((end, result.measure))
    return history


def trend_metrics(
    rows: Sequence[StatementRow], as_of: date, config: AnalyticsConfig
) -> dict[str, FundamentalResult]:
    cfg = config.fundamentals
    out: dict[str, FundamentalResult] = {}
    for metric, rising_is_better in TREND_METRICS.items():
        history = [(end, m) for end, m in _history(rows, as_of, metric) if m.is_known]
        name = f"{metric} trend"
        if len(history) < cfg.trend_min_periods:
            out[f"{metric}_trend"] = FundamentalResult(
                Measure.unavailable(
                    f"{name}: {len(history)} fiscal years with a value, "
                    f"minimum {cfg.trend_min_periods}"
                )
            )
            continue
        values = [m.value for _, m in history if m.value is not None]
        code, label = trend_label(
            values, stable_band=cfg.trend_stable_band, rising_is_better=rising_is_better
        )
        provenance = merge_provenance(*(m for _, m in history))
        measure = (
            Measure.known(float(code), *provenance, reason=label)
            if code != 0
            else Measure.zero(*provenance, reason=label)
        )
        out[f"{metric}_trend"] = FundamentalResult(measure, history[-1][0], "annual")
    return out


# --- growth ---------------------------------------------------------------------------


GROWTH_CONCEPTS = ("revenue", "eps", "net_income", "fcf", "dps")
GROWTH_NAMES = {
    "revenue": "revenue",
    "eps": "eps",
    "net_income": "net_income",
    "fcf": "fcf",
    "dps": "dividend",
}


def growth_metrics(
    rows: Sequence[StatementRow], as_of: date, config: AnalyticsConfig
) -> dict[str, FundamentalResult]:
    out: dict[str, FundamentalResult] = {}
    for concept in GROWTH_CONCEPTS:
        name = GROWTH_NAMES[concept]
        series = [(end, m) for end, m in concept_series(rows, as_of, concept) if m.is_known]
        current = latest(series)
        if current is None:
            blocked = _missing(concept, as_of)
            for metric in (f"{name}_growth_1y", f"{name}_cagr_3y", f"{name}_cagr_5y"):
                out[metric] = FundamentalResult(blocked)
            continue
        end, now = current
        prior = previous(series, end)
        out[f"{name}_growth_1y"] = FundamentalResult(
            pct_change(now, prior[1], name=f"{name} growth 1y")
            if prior is not None
            else Measure.unavailable(f"{name} growth 1y: only one fiscal year known"),
            end,
            "annual",
        )
        for years in (3, 5):
            target_end = date(end.year - years, end.month, end.day)
            base = _value_at(series, target_end) or _nearest_period(series, target_end)
            metric = f"{name}_cagr_{years}y"
            if base is None:
                out[metric] = FundamentalResult(
                    Measure.unavailable(
                        f"{metric}: needs a fiscal year ending around {target_end}; "
                        f"history known on {as_of} starts {series[0][0]}"
                    ),
                    end,
                    "annual",
                )
                continue
            out[metric] = FundamentalResult(cagr(now, base, years, name=metric), end, "annual")
    return out


def _nearest_period(
    series: ConceptSeries, target: date, tolerance_days: int = 40
) -> Measure | None:
    """A fiscal year end within a few weeks of the target (year-end changes, leap days)."""
    for end, measure in series:
        if abs((end - target).days) <= tolerance_days:
            return measure
    return None


# --- everything ------------------------------------------------------------------------


def fundamental_metrics(
    rows: Sequence[StatementRow], as_of: date, *, sector_code: str | None, config: AnalyticsConfig
) -> dict[str, FundamentalResult]:
    out = quality_metrics(rows, as_of, sector_code=sector_code)
    out.update(trend_metrics(rows, as_of, config))
    out.update(growth_metrics(rows, as_of, config))
    return out


def sector_relative(
    own: Measure, peers: Sequence[Measure], *, name: str, min_peers: int
) -> Measure:
    """``own - median(peers)`` when both sides are known."""
    if not own.is_known or own.value is None:
        return Measure(None, own.status, f"{name}: {own.reason}")
    values = [p.value for p in peers if p.is_known and p.value is not None]
    if len(values) < min_peers:
        return Measure.unavailable(
            f"{name}: {len(values)} peer(s) with a value, minimum {min_peers}"
        )
    median = float(np.median(values))
    return Measure.known(
        own.value - median,
        *own.provenance,
        Provenance(
            table="fundamental_metrics", note=f"median of {len(values)} sector peers = {median:.4f}"
        ),
    )


def statement_provenance_note(rows: Iterable[StatementRow]) -> str:
    rows = list(rows)
    if not rows:
        return "no statements"
    ends = sorted({r.fiscal_period_end for r in rows})
    return f"{len(rows)} statement rows, fiscal periods {ends[0]}..{ends[-1]}"


__all__ = [
    "CONCEPTS",
    "GROWTH_CONCEPTS",
    "TREND_METRICS",
    "FundamentalResult",
    "average_with_prior",
    "concept_series",
    "fundamental_metrics",
    "growth_metrics",
    "latest",
    "quality_metrics",
    "sector_relative",
    "statement_measure",
    "trend_label",
    "trend_metrics",
]
