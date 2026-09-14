"""Valuation multiples and the dividend engine, point-in-time.

Multiples marry the last close on or before ``as_of`` with the latest fiscal-year
figures known on that date (and the trailing-twelve-month figures when the site
reports them):

* ``market_cap`` = price x diluted shares (statement), ``enterprise_value`` =
  market cap + total debt - cash;
* ``pe`` (annual EPS), ``pe_ttm``, ``forward_pe`` (``unavailable``: no estimates
  source), ``pb`` (market cap / common equity), ``ps``, ``ev_ebitda``, ``ev_sales``,
  ``dividend_yield`` / ``dividend_yield_ttm``, ``payout_ratio``, ``fcf_yield``;
* a negative or zero denominator - loss-making EPS, negative EBITDA, negative
  equity - is ``not_meaningful``, never a small multiple;
* ``pe_vs_history`` / ``pb_vs_history`` compare with the median of the company's own
  fiscal-year multiples on the site's ratios page as known on ``as_of``.

Dividends: ``dividend_years_paid`` and ``dividend_consistency`` over the fiscal
years known, ``dividend_cut`` (latest DPS below the prior year's), ``fcf_dividend_coverage``
(FCF over cash dividends paid), and ``dividend_class`` - Reliable payer, Growing payer,
High-yield, Potential dividend trap, Deteriorating, Non-payer - stored as a code with
the label as the reason. A missing dividend row is ``missing``; only a reported zero
counts as "paid nothing".

Sector and market medians (``pe_vs_sector`` etc.) are cross-sectional and added by the
service. Every value carries its statement rows and the price observation.

    codegraph explore "valuation_metrics dividend_metrics dividend_class multiples"
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date
from enum import IntEnum

import numpy as np

from app.web.services.analytics.classification.taxonomy import FINANCIAL_SECTORS
from app.web.services.analytics.config import AnalyticsConfig
from app.web.services.analytics.fundamentals.engine import (
    FundamentalResult,
    concept_series,
    latest,
    previous,
)
from app.web.services.analytics.fundamentals.statements import (
    StatementRow,
    line_item_series,
)
from app.web.services.analytics.measure import (
    Measure,
    Provenance,
    cagr,
    merge_provenance,
    safe_div,
)
from app.web.services.analytics.series import PriceSeries


class DividendClass(IntEnum):
    NON_PAYER = 0
    DETERIORATING = 1
    POTENTIAL_TRAP = 2
    HIGH_YIELD = 3
    RELIABLE_PAYER = 4
    GROWING_PAYER = 5

    @property
    def label(self) -> str:
        return {
            DividendClass.NON_PAYER: "Non-payer",
            DividendClass.DETERIORATING: "Deteriorating",
            DividendClass.POTENTIAL_TRAP: "Potential dividend trap",
            DividendClass.HIGH_YIELD: "High-yield",
            DividendClass.RELIABLE_PAYER: "Reliable payer",
            DividendClass.GROWING_PAYER: "Growing payer",
        }[self]


@dataclass(frozen=True, slots=True)
class PricePoint:
    day: date
    close: float
    provenance: Provenance


def price_on(series: PriceSeries, as_of: date) -> PricePoint | Measure:
    located = series.close_on_or_before(as_of)
    if located is None:
        return Measure.unavailable(f"price: no observation on or before {as_of}")
    day, close = located
    if (as_of - day).days > series.gap_threshold_days:
        return Measure.unavailable(
            f"price: last observation {day} is {(as_of - day).days} days before {as_of}"
        )
    return PricePoint(
        day,
        close,
        Provenance(
            table="stock_observations",
            ticker=series.ticker_symbol,
            start=day,
            end=day,
            note=f"close {close} on {day}",
        ),
    )


def _latest_value(
    rows: Sequence[StatementRow], as_of: date, concept: str, *, period_type: str = "annual"
) -> tuple[date, Measure] | Measure:
    series = concept_series(rows, as_of, concept, period_type=period_type)
    current = latest(series)
    if current is None:
        return Measure.missing(
            f"{concept}: not reported in any {period_type} statement known on {as_of}"
        )
    return current


def _put(
    out: dict[str, FundamentalResult],
    metric: str,
    measure: Measure,
    period_end: date | None,
    period_type: str | None = "annual",
) -> None:
    out[metric] = FundamentalResult(measure, period_end, period_type)


def multiples(
    rows: Sequence[StatementRow],
    price_series: PriceSeries,
    as_of: date,
    *,
    sector_code: str | None,
) -> dict[str, FundamentalResult]:
    out: dict[str, FundamentalResult] = {}
    price = price_on(price_series, as_of)
    if isinstance(price, Measure):
        for metric in (
            "price",
            "market_cap",
            "enterprise_value",
            "pe",
            "pe_ttm",
            "forward_pe",
            "pb",
            "ps",
            "ev_ebitda",
            "ev_sales",
            "dividend_yield",
            "dividend_yield_ttm",
            "payout_ratio",
            "fcf_yield",
        ):
            out[metric] = FundamentalResult(
                Measure(None, price.status, f"{metric}: {price.reason}")
            )
        return out
    price_measure = Measure.known(price.close, price.provenance)
    _put(out, "price", price_measure, price.day, "observation")

    eps = _latest_value(rows, as_of, "eps")
    period_end = eps[0] if not isinstance(eps, Measure) else None
    shares = _latest_value(rows, as_of, "shares")
    revenue = _latest_value(rows, as_of, "revenue")
    equity = _latest_value(rows, as_of, "equity")
    debt = _latest_value(rows, as_of, "total_debt")
    cash = _latest_value(rows, as_of, "cash")
    ebitda = _latest_value(rows, as_of, "ebitda")
    dps = _latest_value(rows, as_of, "dps")
    fcf = _latest_value(rows, as_of, "fcf")

    def m(item: tuple[date, Measure] | Measure) -> Measure:
        return item if isinstance(item, Measure) else item[1]

    if period_end is None and not isinstance(revenue, Measure):
        period_end = revenue[0]

    # market cap = price x shares
    if isinstance(shares, Measure):
        market_cap = Measure(None, shares.status, f"market cap: {shares.reason}")
    else:
        assert shares[1].value is not None
        market_cap = Measure.known(
            price.close * shares[1].value, price.provenance, *shares[1].provenance
        )
    _put(out, "market_cap", market_cap, period_end)

    debt_m, cash_m = m(debt), m(cash)
    if (
        market_cap.value is not None
        and market_cap.is_known
        and debt_m.is_known
        and debt_m.value is not None
        and cash_m.is_known
        and cash_m.value is not None
    ):
        ev = Measure.known(
            market_cap.value + debt_m.value - cash_m.value,
            *merge_provenance(market_cap, debt_m, cash_m),
        )
    else:
        blocker = next(x for x in (market_cap, debt_m, cash_m) if not x.is_known)
        ev = Measure(None, blocker.status, f"enterprise value: {blocker.reason}")
    _put(out, "enterprise_value", ev, period_end)

    _put(out, "pe", safe_div(price_measure, m(eps), name="P/E"), period_end)
    eps_ttm = _latest_value(rows, as_of, "eps", period_type="ttm")
    _put(
        out,
        "pe_ttm",
        safe_div(price_measure, m(eps_ttm), name="P/E (TTM)"),
        None if isinstance(eps_ttm, Measure) else eps_ttm[0],
        "ttm",
    )
    _put(
        out,
        "forward_pe",
        Measure.unavailable("forward P/E: no earnings-estimate source"),
        None,
        None,
    )
    _put(out, "pb", safe_div(market_cap, m(equity), name="P/B"), period_end)
    _put(out, "ps", safe_div(market_cap, m(revenue), name="P/S"), period_end)
    if sector_code in FINANCIAL_SECTORS:
        _put(
            out,
            "ev_ebitda",
            Measure.not_applicable("EV/EBITDA: not meaningful for a financial company"),
            period_end,
        )
        _put(
            out,
            "ev_sales",
            Measure.not_applicable("EV/Sales: not meaningful for a financial company"),
            period_end,
        )
    else:
        _put(out, "ev_ebitda", safe_div(ev, m(ebitda), name="EV/EBITDA"), period_end)
        _put(out, "ev_sales", safe_div(ev, m(revenue), name="EV/Sales"), period_end)
    _put(out, "dividend_yield", safe_div(m(dps), price_measure, name="dividend yield"), period_end)
    dps_ttm = _latest_value(rows, as_of, "dps", period_type="ttm")
    _put(
        out,
        "dividend_yield_ttm",
        safe_div(m(dps_ttm), price_measure, name="dividend yield (TTM)"),
        None if isinstance(dps_ttm, Measure) else dps_ttm[0],
        "ttm",
    )
    _put(out, "payout_ratio", safe_div(m(dps), m(eps), name="payout ratio"), period_end)
    _put(out, "fcf_yield", safe_div(m(fcf), market_cap, name="FCF yield"), period_end)
    return out


def _ratio_history(rows: Sequence[StatementRow], as_of: date, line_item: str) -> list[float]:
    """The site's own fiscal-year multiples (ratios page) known on ``as_of``."""
    series = line_item_series(
        rows, as_of, statement="ratios", line_item=line_item, period_type="annual"
    )
    return [m.value for _, m in series if m.is_known and m.value is not None and m.value > 0]


def versus_history(
    rows: Sequence[StatementRow],
    as_of: date,
    current: dict[str, FundamentalResult],
    *,
    min_years: int,
) -> dict[str, FundamentalResult]:
    out: dict[str, FundamentalResult] = {}
    for metric, line_item in (("pe", "pe_ratio"), ("pb", "pb_ratio")):
        own = current[metric].measure
        history = _ratio_history(rows, as_of, line_item)
        name = f"{metric} vs history"
        if not own.is_known or own.value is None:
            out[f"{metric}_vs_history"] = FundamentalResult(
                Measure(None, own.status, f"{name}: {own.reason}")
            )
            continue
        if len(history) < min_years:
            out[f"{metric}_vs_history"] = FundamentalResult(
                Measure.unavailable(
                    f"{name}: {len(history)} fiscal-year multiples on record, minimum {min_years}"
                )
            )
            continue
        median = float(np.median(history))
        provenance = (
            *own.provenance,
            Provenance(
                table="financial_statements",
                note=f"median {line_item} over {len(history)} fiscal years = {median:.2f}",
            ),
        )
        out[f"{metric}_vs_history"] = FundamentalResult(
            Measure.known(own.value / median - 1.0, *provenance),
            current[metric].period_end,
            "annual",
        )
    return out


# --- dividends ---------------------------------------------------------------------


def dividend_metrics(
    rows: Sequence[StatementRow],
    as_of: date,
    current: dict[str, FundamentalResult],
    config: AnalyticsConfig,
) -> dict[str, FundamentalResult]:
    cfg = config.valuation
    out: dict[str, FundamentalResult] = {}
    dps_series = concept_series(rows, as_of, "dps")
    eps_series = concept_series(rows, as_of, "eps")
    known_years = [(end, m) for end, m in dps_series][-cfg.dividend_history_years :]
    reported = [(end, m) for end, m in known_years if m.is_known]
    period_end = known_years[-1][0] if known_years else None

    if not known_years:
        blocked = Measure.missing(f"dividends: no dividend row in any statement known on {as_of}")
        for metric in (
            "dividend_years_paid",
            "dividend_consistency",
            "dividend_cut",
            "dividend_cagr_3y",
            "fcf_dividend_coverage",
        ):
            out[metric] = FundamentalResult(blocked)
        out["dividend_class"] = FundamentalResult(blocked)
        return out

    paid = [(end, m) for end, m in reported if m.is_positive]
    provenance = merge_provenance(*(m for _, m in reported)) if reported else ()
    _put(
        out,
        "dividend_years_paid",
        Measure.known(float(len(paid)), *provenance) if paid else Measure.zero(*provenance),
        period_end,
    )
    _put(
        out,
        "dividend_consistency",
        Measure.known(len(paid) / len(known_years), *provenance)
        if paid
        else Measure.zero(*provenance),
        period_end,
    )

    latest_dps = latest(dps_series)
    prior_dps = previous(dps_series, latest_dps[0]) if latest_dps else None
    if latest_dps is None:
        cut = Measure.missing("dividend cut: no reported dividend")
    elif prior_dps is None:
        cut = Measure.unavailable("dividend cut: only one fiscal year with a reported dividend")
    else:
        assert latest_dps[1].value is not None and prior_dps[1].value is not None
        fell = latest_dps[1].value < prior_dps[1].value
        cut = (
            Measure.known(1.0, *merge_provenance(latest_dps[1], prior_dps[1]))
            if fell
            else Measure.zero(*merge_provenance(latest_dps[1], prior_dps[1]))
        )
    _put(out, "dividend_cut", cut, period_end)

    if latest_dps is not None:
        target = date(latest_dps[0].year - 3, latest_dps[0].month, latest_dps[0].day)
        base = next((m for end, m in dps_series if abs((end - target).days) <= 40), None)
        _put(
            out,
            "dividend_cagr_3y",
            cagr(latest_dps[1], base, 3, name="dividend cagr 3y")
            if base is not None
            else Measure.unavailable(f"dividend cagr 3y: no fiscal year ending around {target}"),
            period_end,
        )
    else:
        _put(
            out,
            "dividend_cagr_3y",
            Measure.missing("dividend cagr 3y: no reported dividend"),
            period_end,
        )

    fcf = _latest_value(rows, as_of, "fcf")
    paid_cash = _latest_value(rows, as_of, "dividends_paid")
    if isinstance(paid_cash, Measure) or paid_cash[1].value is None:
        _put(
            out,
            "fcf_dividend_coverage",
            Measure(
                None,
                (paid_cash if isinstance(paid_cash, Measure) else paid_cash[1]).status,
                "FCF dividend coverage: dividends paid not reported",
            ),
            period_end,
        )
    elif paid_cash[1].value == 0:
        _put(
            out,
            "fcf_dividend_coverage",
            Measure.not_meaningful("FCF dividend coverage: no cash dividends paid"),
            period_end,
        )
    else:
        magnitude = Measure.known(abs(paid_cash[1].value), *paid_cash[1].provenance)
        _put(
            out,
            "fcf_dividend_coverage",
            safe_div(
                fcf if isinstance(fcf, Measure) else fcf[1], magnitude, name="FCF dividend coverage"
            ),
            period_end,
        )

    # --- classification ---
    yield_measure = current["dividend_yield"].measure
    payout = current["payout_ratio"].measure
    latest_eps = latest(eps_series)
    prior_eps = previous(eps_series, latest_eps[0]) if latest_eps else None
    eps_falling = bool(
        latest_eps
        and prior_eps
        and latest_eps[1].value is not None
        and prior_eps[1].value is not None
        and latest_eps[1].value < prior_eps[1].value
    )
    coverage = out["fcf_dividend_coverage"].measure
    reasons: list[str] = []
    if not paid:
        klass = DividendClass.NON_PAYER
        reasons.append("no dividend paid in the fiscal years on record")
    elif cut.is_positive:
        klass = DividendClass.DETERIORATING
        reasons.append("latest dividend below the prior year's")
    elif reported and not reported[-1][1].is_positive:
        klass = DividendClass.DETERIORATING
        reasons.append("no dividend in the latest fiscal year after paying before")
    else:
        high_yield = (
            yield_measure.is_known and (yield_measure.value or 0) >= cfg.high_yield_threshold
        )
        trap_signals = []
        if eps_falling:
            trap_signals.append("EPS fell")
        if payout.is_known and (payout.value or 0) > cfg.payout_trap_threshold:
            trap_signals.append(f"payout {payout.value:.0%} of earnings")
        if payout.status.value == "not_meaningful":
            trap_signals.append("negative earnings")
        if coverage.is_known and (coverage.value or 0) < 1.0:
            trap_signals.append("FCF below dividends paid")
        consistent = len(paid) >= min(cfg.reliable_min_years, len(known_years)) and len(
            paid
        ) == len(known_years)
        growing = out["dividend_cagr_3y"].measure.is_positive
        if high_yield and trap_signals:
            klass = DividendClass.POTENTIAL_TRAP
            reasons.append(f"yield {yield_measure.value:.1%} with " + ", ".join(trap_signals))
        elif high_yield:
            klass = DividendClass.HIGH_YIELD
            reasons.append(f"yield {yield_measure.value:.1%}")
        elif consistent and growing:
            klass = DividendClass.GROWING_PAYER
            reasons.append(
                f"paid every year on record, 3y CAGR {out['dividend_cagr_3y'].measure.value:+.1%}"
            )
        elif consistent:
            klass = DividendClass.RELIABLE_PAYER
            reasons.append(f"paid in all {len(known_years)} fiscal years on record")
        else:
            klass = (
                DividendClass.DETERIORATING
                if len(paid) < len(known_years)
                else DividendClass.RELIABLE_PAYER
            )
            reasons.append(f"paid in {len(paid)} of {len(known_years)} fiscal years on record")
    label = f"{klass.label}: " + "; ".join(reasons)
    measure = (
        Measure.known(float(klass), *provenance, reason=label)
        if klass != DividendClass.NON_PAYER
        else Measure.zero(*provenance, reason=label)
    )
    _put(out, "dividend_class", measure, period_end)
    return out


def valuation_metrics(
    rows: Sequence[StatementRow],
    price_series: PriceSeries,
    as_of: date,
    *,
    sector_code: str | None,
    config: AnalyticsConfig,
) -> dict[str, FundamentalResult]:
    out = multiples(rows, price_series, as_of, sector_code=sector_code)
    out.update(versus_history(rows, as_of, out, min_years=config.valuation.min_history_years))
    out.update(dividend_metrics(rows, as_of, out, config))
    return out


def relative_to_group(
    own: Measure, group: Sequence[Measure], *, name: str, min_members: int
) -> Measure:
    """``own / median(group) - 1`` for a multiple; ``unavailable`` below ``min_members``."""
    if not own.is_known or own.value is None:
        return Measure(None, own.status, f"{name}: {own.reason}")
    values = [g.value for g in group if g.is_known and g.value is not None and g.value > 0]
    if len(values) < min_members:
        return Measure.unavailable(
            f"{name}: {len(values)} comparable(s) with a positive multiple, minimum {min_members}"
        )
    median = float(np.median(values))
    return Measure.known(
        own.value / median - 1.0,
        *own.provenance,
        Provenance(table="fundamental_metrics", note=f"median of {len(values)} = {median:.3f}"),
    )


__all__ = [
    "DividendClass",
    "PricePoint",
    "dividend_metrics",
    "multiples",
    "price_on",
    "relative_to_group",
    "valuation_metrics",
    "versus_history",
]
