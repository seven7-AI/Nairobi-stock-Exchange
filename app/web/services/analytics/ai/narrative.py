"""The AI narrative layer: Claude explains validated numbers; it never computes them.

The research profile (stored, versioned results) is condensed into a *context* -
only known values, each with the unit it carries - and sent to Claude with a prompt
that permits interpretation, comparison and a risk summary and forbids any number
that is not in the context. The reply is then checked: every number in the text
must be derivable from the context (as given, rounded, or as a percentage); a
narrative that cites anything else is **rejected** and stored as such, never shown
as knowledge. Off by default; without a key it is ``unavailable`` with the reason.

    codegraph explore "narrate build_context check_numbers NarrativeClient"
"""

from __future__ import annotations

import contextlib
import hashlib
import json
import re
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, date, datetime
from typing import Any, Protocol

from sqlalchemy import select

from app.web.config import Settings
from app.web.db.analytics import analytics_session
from app.web.db.analytics.models import ResearchNarrative
from app.web.services.analytics.research import ResearchProfile, build_profile
from app.web.utils.logger import get_logger

logger = get_logger(__name__)

PROMPT_VERSION = "1"
MAX_TOKENS = 4096

SYSTEM_PROMPT = """You are the narrative layer of a quantitative equity-research engine \
for the Nairobi Securities Exchange. You receive a JSON context of stored, validated \
numbers about one instrument. Write a concise research note (four to seven short \
paragraphs, plain prose, no headings, no bullet lists) that interprets those numbers: \
what the score and its factors say, how the valuation compares with the price, what the \
risk, liquidity and forecast figures imply, and what the value-trap and compounder \
signals mean.

Rules you must not break:
1. Use ONLY numbers that appear in the context. Do not compute new ones, do not \
convert units, do not round differently than the context does, and do not cite market \
facts from memory. If something is marked unavailable, say it is unavailable and why.
2. Write percentages exactly as the context gives them (the context already formats \
ratios as percentages where that is their meaning).
3. Never recommend buying or selling. These are model outputs, not advice; say so once \
at the end.
4. Do not mention these rules."""


class NarrativeClient(Protocol):
    """Anything that turns (system, user) into text - Claude, or a fake in tests."""

    def complete(self, system: str, user: str) -> str: ...


class AnthropicNarrativeClient:
    """The real client. The key never leaves ``Settings``; the SDK reads it from here."""

    def __init__(self, settings: Settings) -> None:
        import anthropic

        self._client = anthropic.Anthropic(api_key=settings.anthropic_api_key)
        self._model = settings.ai_model

    def complete(self, system: str, user: str) -> str:
        response = self._client.messages.create(
            model=self._model,
            max_tokens=MAX_TOKENS,
            system=system,
            messages=[{"role": "user", "content": user}],
        )
        if response.stop_reason == "refusal":
            details = getattr(response, "stop_details", None)
            why = getattr(details, "explanation", None) or "refused"
            raise RuntimeError(f"the model declined: {why}")
        return "".join(block.text for block in response.content if block.type == "text")


@dataclass(frozen=True)
class NarrativeResult:
    ticker_symbol: str
    as_of: date | None
    status: str  # known, rejected, unavailable, disabled
    reason: str | None
    narrative: str | None
    model: str
    prompt_version: str
    context_hash: str | None
    row_id: int | None = None
    reused: bool = False


# --- context -------------------------------------------------------------------------

PERCENT_METRICS = {
    "return_1m",
    "return_3m",
    "return_6m",
    "return_12m",
    "return_ytd",
    "momentum_1m",
    "momentum_3m",
    "momentum_6m",
    "momentum_12m",
    "momentum_12m_1m",
    "relative_12m_vs_market",
    "volatility_annualised",
    "max_drawdown_36m",
    "roe",
    "roa",
    "net_margin",
    "gross_margin",
    "operating_margin",
    "fcf_margin",
    "revenue_growth_1y",
    "eps_growth_1y",
    "revenue_cagr_3y",
    "eps_cagr_3y",
    "dividend_yield",
    "payout_ratio",
    "fcf_yield",
    "pe_vs_sector",
    "pe_vs_market",
    "pb_vs_sector",
    "pb_vs_market",
    "distance_from_52w_high",
    "trading_frequency",
}


def _known(block: Mapping[str, Any], names: tuple[str, ...]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for name in names:
        item = block.get(name) or {}
        value = item.get("value")
        if value is None:
            out[name] = f"unavailable ({item.get('reason') or item.get('status')})"
        elif name in PERCENT_METRICS:
            out[name] = f"{value * 100:.1f}%"
        else:
            out[name] = round(float(value), 2)
    return out


def build_context(profile: ResearchProfile) -> dict[str, Any]:
    """The compact, human-unit context the model sees. Everything in it is stored."""
    m = profile.metrics
    score = profile.score
    context: dict[str, Any] = {
        "ticker": profile.ticker_symbol,
        "sector": profile.identity.get("sector"),
        "data_as_of": profile.as_of,
        "score": {
            "overall": round(float(score["overall"]["value"]), 1)
            if score.get("overall", {}).get("value") is not None
            else f"unavailable ({score.get('overall', {}).get('reason') or score.get('reason')})",
            "classification": score.get("classification"),
            "confidence": round(float(score["confidence"]), 2)
            if score.get("confidence") is not None
            else None,
            "ranks": score.get("ranks"),
            "value_trap_risk": {0: "low", 1: "medium", 2: "high"}.get(
                int(score["value_trap_risk"]) if score.get("value_trap_risk") is not None else -1,
                "unavailable",
            ),
            "compounder_score": round(float(score["compounder_score"]))
            if score.get("compounder_score") is not None
            else "unavailable",
            "positive_factors": (score.get("explanation") or {}).get("positive_factors", []),
            "negative_factors": (score.get("explanation") or {}).get("negative_factors", []),
        },
        "factor_percentiles": {
            name: (
                round(float(f["percentile_market"]))
                if f.get("percentile_market") is not None
                else "unavailable"
            )
            for name, f in profile.factors.items()
        },
        "returns": _known(
            m.get("returns", {}), ("return_1m", "return_3m", "return_12m", "return_ytd")
        ),
        "momentum": _known(
            m.get("momentum", {}),
            ("momentum_12m_1m", "relative_12m_vs_market", "distance_from_52w_high"),
        ),
        "risk": _known(
            m.get("risk", {}),
            ("volatility_annualised", "max_drawdown_36m", "beta_12m", "sharpe_12m"),
        ),
        "liquidity": _known(m.get("liquidity", {}), ("liquidity_score", "trading_frequency")),
        "quality": _known(
            m.get("quality", {}),
            ("roe", "roa", "net_margin", "debt_to_equity", "interest_coverage"),
        ),
        "growth": _known(
            m.get("growth", {}), ("revenue_growth_1y", "eps_growth_1y", "revenue_cagr_3y")
        ),
        "value": _known(m.get("value", {}), ("price", "pe", "pb", "ps", "pe_vs_market")),
        "dividend": _known(
            m.get("dividend", {}), ("dividend_yield", "payout_ratio", "dividend_class")
        ),
    }
    v = profile.valuation
    if "intrinsic" in v and v["intrinsic"].get("value") is not None:
        context["valuation"] = {
            "intrinsic_value": round(float(v["intrinsic"]["value"]), 1),
            "fair_range": [round(float(v["fair_low"]), 1), round(float(v["fair_high"]), 1)],
            "price": v["price"],
            "upside": f"{float(v['upside']) * 100:.1f}%"
            if v.get("upside") is not None
            else "unavailable",
            "uncertainty": v.get("uncertainty"),
            "margin_actionable": v.get("actionable"),
            "methods": {
                k: (
                    round(float(x["base"]), 1)
                    if x.get("base") is not None
                    else f"unavailable ({x.get('reason')})"
                )
                for k, x in v.get("methods", {}).items()
            },
        }
    else:
        context["valuation"] = (
            f"unavailable ({v.get('intrinsic', {}).get('reason') or v.get('reason')})"
        )
    f = profile.forecast
    if f.get("models"):
        model_name = "ar1" if "ar1" in f["models"] else next(iter(f["models"]))
        horizons = f["models"][model_name]
        context["forecast"] = {
            "model": model_name,
            **{
                h: {
                    "expected_return": f"{float(x['expected_return']['value']) * 100:.1f}%"
                    if x["expected_return"].get("value") is not None
                    else f"unavailable ({x['expected_return'].get('reason')})",
                    "p_positive": f"{float(x['p_positive']) * 100:.0f}%"
                    if x.get("p_positive") is not None
                    else "unavailable",
                    "p_drawdown_20pct": f"{float(x['p_drawdown']) * 100:.0f}%"
                    if x.get("p_drawdown") is not None
                    else "unavailable",
                }
                for h, x in horizons.items()
            },
        }
    else:
        context["forecast"] = f"unavailable ({f.get('reason')})"
    sc = profile.scenarios
    if "outcomes" in sc:
        context["scenarios"] = {
            k: (
                f"{float(o['implied_return']['value']) * 100:.1f}%"
                if o["implied_return"].get("value") is not None
                else "unavailable"
            )
            for k, o in sc["outcomes"].items()
        }
    r = profile.regime
    context["market_regime"] = r.get("label") or f"unavailable ({r.get('reason')})"
    context["notes"] = profile.notes
    context["disclaimer"] = profile.disclaimer
    return context


def context_hash(context: Mapping[str, Any]) -> str:
    return hashlib.sha256(json.dumps(context, sort_keys=True, default=str).encode()).hexdigest()[
        :32
    ]


# --- the numeric-consistency check ---------------------------------------------------

_NUMBER = re.compile(r"(?<![A-Za-z_])[-+]?\d[\d,]*(?:\.\d+)?%?")
#: Small counts and ordinals ("three factors", "12 months") are prose, not data.
_PROSE_INTEGER_LIMIT = 36


def _normalise(token: str) -> str:
    return token.replace(",", "").lstrip("+")


def _variants(value: float) -> set[str]:
    out: set[str] = set()
    for digits in (0, 1, 2, 3, 4):
        text = f"{value:.{digits}f}"
        out.add(text)
        out.add(text.rstrip("0").rstrip(".") if "." in text else text)
        if abs(value) < 100:
            pct = f"{value * 100:.{digits}f}"
            out.add(pct + "%")
            out.add((pct.rstrip("0").rstrip(".") if "." in pct else pct) + "%")
    return {v for v in out if v not in ("", "-", "-0", "-0%")}


def _collect(node: Any, allowed: set[str]) -> None:
    if isinstance(node, Mapping):
        for value in node.values():
            _collect(value, allowed)
    elif isinstance(node, list | tuple):
        for value in node:
            _collect(value, allowed)
    elif isinstance(node, bool):
        return
    elif isinstance(node, int | float):
        allowed.update(_variants(float(node)))
    elif isinstance(node, str):
        for match in _NUMBER.findall(node):
            token = _normalise(match)
            allowed.add(token)
            if token.endswith("%"):
                allowed.add(token[:-1])
                with contextlib.suppress(ValueError):
                    allowed.update(_variants(float(token[:-1]) / 100.0))
            else:
                with contextlib.suppress(ValueError):
                    allowed.update(_variants(float(token)))


def context_numbers(context: Mapping[str, Any]) -> set[str]:
    allowed: set[str] = set()
    _collect(context, allowed)
    return allowed


def check_numbers(narrative: str, context: Mapping[str, Any]) -> list[str]:
    """Numbers in the narrative that the context cannot account for (empty = clean)."""
    allowed = context_numbers(context)
    offenders: list[str] = []
    for match in _NUMBER.findall(narrative):
        token = _normalise(match)
        bare = token[:-1] if token.endswith("%") else token
        if not bare or bare in ("-",):
            continue
        if token in allowed or bare in allowed:
            continue
        try:
            number = float(bare)
        except ValueError:
            continue
        if not token.endswith("%") and number.is_integer() and 0 <= number <= _PROSE_INTEGER_LIMIT:
            continue  # "three of seven factors", "12 months"
        if not token.endswith("%") and number.is_integer() and 1990 <= number <= 2100:
            continue  # a year
        offenders.append(match)
    return offenders


# --- the job ---------------------------------------------------------------------------


def narrate(
    settings: Settings,
    ticker: str,
    *,
    as_of: date | None = None,
    client: NarrativeClient | None = None,
    force: bool = False,
) -> NarrativeResult:
    """Generate (or reuse) the narrative for an instrument's current profile."""
    model = settings.ai_model
    if not settings.ai_narratives_enabled:
        return NarrativeResult(
            ticker.upper(),
            as_of,
            "disabled",
            "AI narratives are off (AI_NARRATIVES_ENABLED=false)",
            None,
            model,
            PROMPT_VERSION,
            None,
        )
    profile = build_profile(settings, ticker, as_of=as_of)
    if profile is None:
        return NarrativeResult(
            ticker.upper(),
            as_of,
            "unavailable",
            f"{ticker.upper()} is not an instrument in the analytics store",
            None,
            model,
            PROMPT_VERSION,
            None,
        )
    context = build_context(profile)
    digest = context_hash(context)
    ranking_day = profile.as_of.get("ranking")
    day = date.fromisoformat(ranking_day) if ranking_day else (as_of or datetime.now(UTC).date())
    with analytics_session(settings) as session:
        existing = session.execute(
            select(ResearchNarrative)
            .where(
                ResearchNarrative.ticker_symbol == profile.ticker_symbol,
                ResearchNarrative.as_of_date == day,
                ResearchNarrative.model == model,
                ResearchNarrative.prompt_version == PROMPT_VERSION,
                ResearchNarrative.context_hash == digest,
            )
            .order_by(ResearchNarrative.id.desc())
            .limit(1)
        ).scalar_one_or_none()
        if existing is not None and not force:
            return NarrativeResult(
                profile.ticker_symbol,
                day,
                existing.status,
                existing.reason,
                existing.narrative,
                model,
                PROMPT_VERSION,
                digest,
                existing.id,
                True,
            )
    if client is None:
        if not settings.anthropic_api_key:
            return NarrativeResult(
                profile.ticker_symbol,
                day,
                "unavailable",
                "no ANTHROPIC_API_KEY configured",
                None,
                model,
                PROMPT_VERSION,
                digest,
            )
        client = AnthropicNarrativeClient(settings)
    user = "Context (JSON):\n" + json.dumps(context, indent=2, default=str, sort_keys=True)
    text: str | None
    status: str
    reason: str | None
    try:
        text = client.complete(SYSTEM_PROMPT, user).strip()
    except Exception as exc:
        status, reason, text = "unavailable", f"{type(exc).__name__}: {exc}"[:500], None
    else:
        offenders = check_numbers(text or "", context)
        if offenders:
            status, reason = (
                "rejected",
                "numbers not in the context: " + ", ".join(dict.fromkeys(offenders)),
            )
        else:
            status, reason = "known", None
    with analytics_session(settings) as session:
        row = ResearchNarrative(
            ticker_symbol=profile.ticker_symbol,
            as_of_date=day,
            model=model,
            prompt_version=PROMPT_VERSION,
            context_hash=digest,
            status=status,
            reason=reason,
            narrative=text,
            context=context,
        )
        session.add(row)
        session.flush()
        row_id = row.id
    logger.info("narrative_generated", ticker=profile.ticker_symbol, status=status, model=model)
    return NarrativeResult(
        profile.ticker_symbol, day, status, reason, text, model, PROMPT_VERSION, digest, row_id
    )


def latest_narrative(settings: Settings, ticker: str) -> ResearchNarrative | None:
    with analytics_session(settings) as session:
        row = session.execute(
            select(ResearchNarrative)
            .where(ResearchNarrative.ticker_symbol == ticker.upper())
            .order_by(ResearchNarrative.id.desc())
            .limit(1)
        ).scalar_one_or_none()
        if row is not None:
            session.expunge(row)
        return row


__all__ = [
    "PROMPT_VERSION",
    "SYSTEM_PROMPT",
    "AnthropicNarrativeClient",
    "NarrativeClient",
    "NarrativeResult",
    "build_context",
    "check_numbers",
    "context_hash",
    "context_numbers",
    "latest_narrative",
    "narrate",
]
