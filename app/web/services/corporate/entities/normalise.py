"""Legal-name normalisation and similarity.

Two names are the same entity when they differ only in a legal-form suffix,
punctuation or case - never when they differ in a country word or a token that
distinguishes sister companies ("KCB Bank Kenya" vs "KCB Bank Tanzania", "Jubilee
Insurance" vs "Jubilee Health Insurance").

    codegraph explore "normalise canonical_key token_set_ratio DISTINGUISHING"
"""

from __future__ import annotations

import re
import unicodedata
from difflib import SequenceMatcher

from app.web.services.corporate.countries import COUNTRY_TOKENS

#: Legal-form suffixes, longest first; exactly one is stripped from the end.
LEGAL_SUFFIXES: tuple[str, ...] = (
    "public limited company",
    "company limited",
    "co limited",
    "co ltd",
    "limited",
    "ltd",
    "plc",
    "incorporated",
    "inc",
    "llc",
    "sa",
    "sarl",
    "s a",
    "corporation",
    "corp",
    "co",
    "ag",
    "nv",
    "bv",
    "gmbh",
    "pty",
    "pvt",
)

#: Tokens that tell sister companies apart; a fuzzy match may never differ in one.
DISTINGUISHING: frozenset[str] = (
    frozenset(
        {
            "health",
            "life",
            "general",
            "asset",
            "assets",
            "capital",
            "insurance",
            "assurance",
            "reinsurance",
            "re",
            "bank",
            "securities",
            "investment",
            "investments",
            "holdings",
            "group",
            "pension",
            "microfinance",
            "leasing",
            "foundation",
            "trust",
            "medical",
            "properties",
            "property",
            "finance",
            "financial",
            "telecommunications",
            "telecom",
            "money",
            "mobile",
            "international",
            "east",
            "west",
            "north",
            "south",
            "africa",
            "central",
        }
    )
    | COUNTRY_TOKENS
)

_NON_ALNUM = re.compile(r"[^a-z0-9 ]+")
_SPACES = re.compile(r"\s+")
_DIGITS = re.compile(r"^\d+$")


def normalise(name: str) -> str:
    """NFKD -> ascii, lower, ``&`` -> ``and``, punctuation out, one legal suffix off."""
    text = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode("ascii")
    text = text.lower().replace("&", " and ")
    text = _NON_ALNUM.sub(" ", text)
    text = _SPACES.sub(" ", text).strip()
    for suffix in LEGAL_SUFFIXES:
        if text.endswith(" " + suffix):
            text = text[: -len(suffix) - 1].rstrip()
            break
    return text


def canonical_key(name: str, jurisdiction: str) -> str:
    return f"{normalise(name)}|{jurisdiction.upper()}"


def tokens(name: str) -> frozenset[str]:
    return frozenset(t for t in normalise(name).split() if t)


def distinguishing_difference(a: str, b: str) -> frozenset[str]:
    """Tokens in exactly one of the names that tell sister companies apart."""
    diff = tokens(a) ^ tokens(b)
    return frozenset(t for t in diff if t in DISTINGUISHING or _DIGITS.match(t))


def token_set_ratio(a: str, b: str) -> float:
    """Similarity in [0, 1] over sorted token sets, robust to word order and suffixes."""
    ta, tb = tokens(a), tokens(b)
    if not ta or not tb:
        return 0.0
    if ta == tb:
        return 1.0
    joined_a, joined_b = " ".join(sorted(ta)), " ".join(sorted(tb))
    sequence = SequenceMatcher(None, joined_a, joined_b).ratio()
    jaccard = len(ta & tb) / len(ta | tb)
    return max(sequence, jaccard)


__all__ = [
    "DISTINGUISHING",
    "LEGAL_SUFFIXES",
    "canonical_key",
    "distinguishing_difference",
    "normalise",
    "token_set_ratio",
    "tokens",
]
