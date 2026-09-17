"""``derive_signals`` on plain objects: buckets, traps, compounders, valuations,
risk flags, factor combinations - every item tied to its stored numbers."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from typing import Any

from app.web.services.dashboard.signals import derive_signals

DAY = date(2026, 9, 16)


@dataclass
class Rank:
    ticker_symbol: str
    status: str = "known"
    reason: str | None = None
    overall_score: float | None = 60.0
    classification: str | None = "Watch"
    confidence: float = 0.65
    market_rank: int | None = 1
    value_trap_risk: int | None = 0
    compounder_score: float | None = 50.0
    model_name: str = "factor-model"
    model_version: str = "1"
    explanation: dict[str, Any] = field(default_factory=dict)


@dataclass
class Val:
    ticker_symbol: str
    method: str = "blended"
    status: str = "known"
    reason: str | None = None
    base: float | None = 100.0
    fair_low: float | None = 80.0
    fair_high: float | None = 120.0
    price: float | None = 90.0
    upside: float | None = 0.11
    margin_of_safety: float | None = 0.1
    uncertainty: float | None = 0.4
    actionable: bool | None = True
    assumptions: dict[str, Any] = field(default_factory=lambda: {"methods_used": ["ddm"]})


@dataclass
class Finding:
    severity: str
    check_name: str
    ticker_symbol: str | None
    trade_date: date | None
    detail: str


def _explanation(**kw: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "positive_factors": [],
        "negative_factors": [],
        "value_trap": {
            "risk": {"value": 0, "status": "known", "reason": "no signals"},
            "signals": [],
        },
        "compounder": {
            "score": {"value": 50, "status": "known", "reason": "5/10 criteria met"},
            "criteria_met": [],
        },
    }
    base.update(kw)
    return base


def test_buckets_traps_compounders_and_unscored() -> None:
    rankings = [
        Rank(
            "EQTY",
            overall_score=76.0,
            classification="Buy Candidate",
            market_rank=1,
            compounder_score=80.0,
            explanation=_explanation(
                positive_factors=["Strong quality (P90)", "Strong growth (P85)"],
                compounder={
                    "score": {"value": 80, "status": "known", "reason": "8/10 criteria met"},
                    "criteria_met": ["ROE", "EPS CAGR"],
                },
            ),
        ),
        Rank(
            "KCB",
            overall_score=52.0,
            classification="Watch",
            market_rank=2,
            value_trap_risk=1,
            explanation=_explanation(
                negative_factors=["momentum: not scored (unavailable)", "Weak dividend (P18)"],
                value_trap={
                    "risk": {"value": 1, "status": "known", "reason": "cheap on P/E"},
                    "signals": ["cheap on P/E -49% vs the market", "negative free cash flow"],
                },
            ),
        ),
        Rank(
            "XYZ",
            overall_score=30.0,
            classification="Avoid",
            market_rank=3,
            explanation=_explanation(negative_factors=["Weak quality (P5)", "Weak value (P10)"]),
        ),
        Rank(
            "NOPE",
            status="unavailable",
            reason="only 40% of factor weight scored",
            overall_score=None,
            classification=None,
            market_rank=None,
        ),
        Rank(
            "NOPE2",
            status="unavailable",
            reason="only 40% of factor weight scored",
            overall_score=None,
            classification=None,
            market_rank=None,
        ),
    ]
    out = derive_signals(
        day=DAY,
        rankings=rankings,
        valuations=[
            Val("EQTY", upside=0.25),
            Val("KCB", upside=-0.15, actionable=False),
            Val("XYZ", status="unavailable", upside=None),
            Val("EQTY", method="ddm", upside=0.5),
        ],
        findings=[
            Finding(
                "error", "universe_gap", None, None, "no observations 2025-01..2026-07 at /home/x"
            ),
            Finding("warning", "price_jumps", "KCB", date(2024, 11, 26), "close moved +900%"),
            Finding("info", "thin_history", "SKL", None, "25 rows"),
        ],
        sector_of={
            "EQTY": "Banking",
            "KCB": "Banking",
            "XYZ": "Insurance",
            "NOPE": None,
            "NOPE2": None,
        },
        compounder_threshold=70.0,
    )
    assert (
        out.model == "factor-model v1"
        and out.universe == 5
        and out.scored == 3
        and out.unscored == 2
    )
    assert out.unscored_reasons == {"only 40% of factor weight scored": 2}
    assert [i.ticker_symbol for i in out.buy_candidates] == ["EQTY"]
    assert [i.ticker_symbol for i in out.watch] == ["KCB"] and [
        i.ticker_symbol for i in out.avoid
    ] == ["XYZ"]
    assert out.neutral == [] and out.weak == []
    eqty = out.buy_candidates[0]
    assert eqty.overall_score == {"value": 76.0, "status": "known", "reason": None}
    assert eqty.link == "/stocks/EQTY" and eqty.sector == "Banking"
    # value trap carries its signals and label; compounder its criteria
    assert [t.ticker_symbol for t in out.value_traps] == ["KCB"]
    assert out.value_traps[0].extra["risk_label"] == "medium"
    assert out.value_traps[0].extra["signals"] == [
        "cheap on P/E -49% vs the market",
        "negative free cash flow",
    ]
    assert [c.ticker_symbol for c in out.compounders] == ["EQTY"]
    assert (
        out.compounders[0].extra["criteria_met"] == ["ROE", "EPS CAGR"]
        and out.compounders[0].extra["compounder_score"] == 80.0
    )
    # valuations: blended + known only, split on sign, sorted by size
    assert [v["ticker_symbol"] for v in out.valuation_upside] == ["EQTY"] and out.valuation_upside[
        0
    ]["methods_used"] == ["ddm"]
    assert [v["ticker_symbol"] for v in out.valuation_downside] == [
        "KCB"
    ] and out.valuation_downside[0]["actionable"] is False
    # risk flags: error first, warnings, no info; paths blanked; plus unavailable factors
    kinds = [(f.kind, f.severity, f.ticker_symbol) for f in out.risk_flags]
    assert kinds[:2] == [("data_quality", "error", None), ("data_quality", "warning", "KCB")]
    assert "<path>" in out.risk_flags[0].detail and out.risk_flags[1].link == "/stocks/KCB"
    assert ("unavailable_factors", "info", "KCB") in kinds and (
        "data_quality",
        "info",
        "SKL",
    ) not in kinds
    # factor combinations ignore "not scored" negatives
    assert [i.ticker_symbol for i in out.factor_combinations["positive"]] == ["EQTY"]
    assert [i.ticker_symbol for i in out.factor_combinations["negative"]] == ["XYZ"]
    assert "Not investment advice" in out.disclaimer


def test_threshold_and_ordering() -> None:
    rankings = [
        Rank("B", market_rank=2, compounder_score=70.0),
        Rank("A", market_rank=1, compounder_score=69.9),
        Rank("C", market_rank=None),
    ]
    out = derive_signals(
        day=DAY,
        rankings=rankings,
        valuations=[],
        findings=[],
        sector_of={},
        compounder_threshold=70.0,
    )
    assert [i.ticker_symbol for i in out.watch] == ["A", "B", "C"]  # rank order, unranked last
    assert [c.ticker_symbol for c in out.compounders] == ["B"]
    assert out.risk_flags == [] and out.valuation_upside == [] and out.compounder_threshold == 70.0
