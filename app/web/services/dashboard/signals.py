"""Research signals: the structured conclusions already stored by the ranking, fair
value and data-quality engines, regrouped for a reader.

``derive_signals`` is pure - it takes rows and returns buckets - so it is tested on
plain objects. Every item carries the numbers it was derived from and a link to the
stock; nothing here computes a new number.

    codegraph explore "derive_signals build_signals Signals load_rankings load_valuations"
"""

from __future__ import annotations

from collections import Counter
from dataclasses import asdict, dataclass, field
from datetime import date
from typing import Any

from app.web.config import Settings
from app.web.db.analytics import analytics_session
from app.web.db.analytics.models import StockRanking
from app.web.db.analytics.services.classifications import load_classifications
from app.web.db.analytics.services.data_quality import open_findings
from app.web.db.analytics.services.stock_rankings import load_rankings
from app.web.db.analytics.services.summaries import latest_as_of
from app.web.db.analytics.services.valuations import load_valuations
from app.web.services.analytics.classification.lookup import ClassificationIndex
from app.web.services.dashboard.common import measure, sanitise_text

BUCKETS: tuple[str, ...] = ("Buy Candidate", "Watch", "Neutral", "Weak", "Avoid")
BUCKET_KEYS: dict[str, str] = {
    "Buy Candidate": "buy_candidates",
    "Watch": "watch",
    "Neutral": "neutral",
    "Weak": "weak",
    "Avoid": "avoid",
}
TRAP_LABELS: dict[int, str] = {0: "low", 1: "medium", 2: "high"}
DISCLAIMER = (
    "Stored model outputs regrouped for reading: classifications, value-trap and "
    "compounder signals, valuation gaps and open data-quality findings. Not investment advice."
)
MAX_RISK_FLAGS = 200


@dataclass(frozen=True)
class SignalItem:
    ticker_symbol: str
    sector: str | None
    classification: str | None
    overall_score: dict[str, Any]
    confidence: float
    market_rank: int | None
    positive_factors: list[str]
    negative_factors: list[str]
    link: str
    extra: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class RiskFlag:
    kind: str
    ticker_symbol: str | None
    severity: str
    check_name: str | None
    detail: str
    trade_date: date | None
    link: str | None


@dataclass(frozen=True)
class Signals:
    as_of: date
    model: str
    universe: int
    scored: int
    unscored: int
    unscored_reasons: dict[str, int]
    buy_candidates: list[SignalItem]
    watch: list[SignalItem]
    neutral: list[SignalItem]
    weak: list[SignalItem]
    avoid: list[SignalItem]
    value_traps: list[SignalItem]
    compounders: list[SignalItem]
    compounder_threshold: float
    valuation_upside: list[dict[str, Any]]
    valuation_downside: list[dict[str, Any]]
    risk_flags: list[RiskFlag]
    factor_combinations: dict[str, list[SignalItem]]
    disclaimer: str

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


def _link(ticker: str) -> str:
    return f"/stocks/{ticker}"


def _item(rk: Any, sector: str | None, **extra: Any) -> SignalItem:
    explanation = rk.explanation or {}
    return SignalItem(
        rk.ticker_symbol,
        sector,
        rk.classification,
        measure(rk.overall_score, str(rk.status), rk.reason),
        float(rk.confidence or 0.0),
        rk.market_rank,
        list(explanation.get("positive_factors") or []),
        list(explanation.get("negative_factors") or []),
        _link(rk.ticker_symbol),
        extra,
    )


def derive_signals(
    *,
    day: date,
    rankings: list[Any],
    valuations: list[Any],
    findings: list[Any],
    sector_of: dict[str, str | None],
    compounder_threshold: float = 70.0,
) -> Signals:
    """Regroup stored rows into the reader's buckets. Pure."""
    buckets: dict[str, list[SignalItem]] = {k: [] for k in BUCKET_KEYS.values()}
    traps: list[SignalItem] = []
    compounders: list[SignalItem] = []
    positive: list[SignalItem] = []
    negative: list[SignalItem] = []
    unscored: Counter[str] = Counter()
    scored = 0
    model = ""
    for rk in sorted(
        rankings, key=lambda r: (r.market_rank is None, r.market_rank or 0, r.ticker_symbol)
    ):
        model = model or f"{rk.model_name} v{rk.model_version}"
        sector = sector_of.get(rk.ticker_symbol)
        explanation = rk.explanation or {}
        if rk.status not in ("known", "zero"):
            unscored[sanitise_text(rk.reason) or "not scored"] += 1
            continue
        scored += 1
        key = BUCKET_KEYS.get(rk.classification or "")
        if key:
            buckets[key].append(_item(rk, sector))
        if rk.value_trap_risk is not None and rk.value_trap_risk >= 1:
            trap = explanation.get("value_trap") or {}
            traps.append(
                _item(
                    rk,
                    sector,
                    risk=int(rk.value_trap_risk),
                    risk_label=TRAP_LABELS.get(int(rk.value_trap_risk), str(rk.value_trap_risk)),
                    signals=list(trap.get("signals") or []),
                    reason=(trap.get("risk") or {}).get("reason"),
                )
            )
        if rk.compounder_score is not None and rk.compounder_score >= compounder_threshold:
            comp = explanation.get("compounder") or {}
            compounders.append(
                _item(
                    rk,
                    sector,
                    compounder_score=float(rk.compounder_score),
                    criteria_met=list(comp.get("criteria_met") or []),
                    reason=(comp.get("score") or {}).get("reason"),
                )
            )
        positives = list(explanation.get("positive_factors") or [])
        negatives = [
            n for n in (explanation.get("negative_factors") or []) if "not scored" not in n
        ]
        if len(positives) >= 2 and not negatives:
            positive.append(_item(rk, sector))
        elif len(negatives) >= 2 and not positives:
            negative.append(_item(rk, sector))
    upside: list[dict[str, Any]] = []
    downside: list[dict[str, Any]] = []
    for v in valuations:
        if v.method != "blended" or v.status not in ("known", "zero") or v.upside is None:
            continue
        row = {
            "ticker_symbol": v.ticker_symbol,
            "sector": sector_of.get(v.ticker_symbol),
            "price": v.price,
            "intrinsic": measure(v.base, str(v.status), v.reason),
            "fair_low": v.fair_low,
            "fair_high": v.fair_high,
            "upside": v.upside,
            "margin_of_safety": v.margin_of_safety,
            "uncertainty": v.uncertainty,
            "actionable": bool(v.actionable),
            "methods_used": list((v.assumptions or {}).get("methods_used") or []),
            "link": _link(v.ticker_symbol),
        }
        (upside if v.upside > 0 else downside).append(row)
    upside.sort(key=lambda r: -float(r["upside"]))
    downside.sort(key=lambda r: float(r["upside"]))
    flags: list[RiskFlag] = []
    order = {"error": 0, "warning": 1, "info": 2}
    for f in sorted(findings, key=lambda f: (order.get(str(f.severity), 3), str(f.check_name))):
        if str(f.severity) not in ("error", "warning"):
            continue
        flags.append(
            RiskFlag(
                "data_quality",
                f.ticker_symbol,
                str(f.severity),
                f.check_name,
                sanitise_text(f.detail) or "",
                f.trade_date,
                _link(f.ticker_symbol) if f.ticker_symbol else None,
            )
        )
        if len(flags) >= MAX_RISK_FLAGS:
            break
    for rk in rankings:
        explanation = rk.explanation or {}
        missing = [n for n in (explanation.get("negative_factors") or []) if "not scored" in n]
        if rk.status in ("known", "zero") and missing:
            flags.append(
                RiskFlag(
                    "unavailable_factors",
                    rk.ticker_symbol,
                    "info",
                    "factor_coverage",
                    "; ".join(missing),
                    day,
                    _link(rk.ticker_symbol),
                )
            )
    return Signals(
        day,
        model,
        len(rankings),
        scored,
        sum(unscored.values()),
        dict(unscored),
        buckets["buy_candidates"],
        buckets["watch"],
        buckets["neutral"],
        buckets["weak"],
        buckets["avoid"],
        traps,
        compounders,
        compounder_threshold,
        upside,
        downside,
        flags,
        {"positive": positive, "negative": negative},
        DISCLAIMER,
    )


def build_signals(
    settings: Settings, *, as_of: date | None = None, compounder_threshold: float = 70.0
) -> Signals | None:
    with analytics_session(settings) as session:
        day = as_of or latest_as_of(session, StockRanking)
        if day is None:
            return None
        index = ClassificationIndex(load_classifications(session))
        rankings = load_rankings(session, as_of_date=day)
        if not rankings:
            return None
        valuations = load_valuations(session, as_of_date=day, method="blended")
        findings = open_findings(session)
        sector_of = {
            r.ticker_symbol: (
                a.sector_label if (a := index.sector_for(r.ticker_symbol, day)) else None
            )
            for r in rankings
        }
        for v in valuations:
            sector_of.setdefault(
                v.ticker_symbol,
                (a.sector_label if (a := index.sector_for(v.ticker_symbol, day)) else None),
            )
        return derive_signals(
            day=day,
            rankings=rankings,
            valuations=valuations,
            findings=findings,
            sector_of=sector_of,
            compounder_threshold=compounder_threshold,
        )


__all__ = [
    "BUCKETS",
    "DISCLAIMER",
    "RiskFlag",
    "SignalItem",
    "Signals",
    "build_signals",
    "derive_signals",
]
