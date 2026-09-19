"""Loader and validator for the per-company IR rule files (``sources/<TICKER>.yaml``).

A rule file says which pages of a company's investor-relations site list which
kinds of documents, and how to read a document's title and fiscal year from a
link. Rules are data so that adding a company is a YAML file, not code.

    codegraph explore "load_rules IrRules PageRule"
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.web.db.analytics.models.corporate_document import DOCUMENT_KINDS

RULES_DIR = Path(__file__).resolve().parent


class PageRule(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    url: str
    kind: str
    #: Regex on the link href (absolute), e.g. ``/download/`` or ``\\.pdf$``.
    href_pattern: str | None = None
    #: Regex on the link text, e.g. ``Integrated Report``.
    text_pattern: str | None = None
    exclude_text: str | None = None
    #: Regex with a ``fy`` group on the link text; default = first 20xx in the text.
    fiscal_year_pattern: str | None = None
    #: Fiscal-year end for ``period_end`` (month, day); omit when the kind is interim.
    period_end_month: int | None = Field(default=None, ge=1, le=12)
    period_end_day: int | None = Field(default=None, ge=1, le=31)
    notes: str | None = None

    @field_validator("kind")
    @classmethod
    def _known_kind(cls, value: str) -> str:
        if value not in DOCUMENT_KINDS:
            raise ValueError(f"unknown document kind {value!r}; one of {DOCUMENT_KINDS}")
        return value


class IrRules(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    ticker: str
    ir_url: str
    base_url: str
    pages: tuple[PageRule, ...] = ()
    news_pages: tuple[str, ...] = ()
    enabled: bool = True
    notes: str | None = None

    @property
    def source_name(self) -> str:
        return f"ir:{self.ticker.upper()}"


def load_rules(path: Path) -> IrRules:
    data: dict[str, Any] = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    return IrRules.model_validate(data)


def load_all_rules(directory: Path = RULES_DIR) -> dict[str, IrRules]:
    """ticker -> rules, for every ``<TICKER>.yaml`` in the directory (``_*.yaml`` skipped)."""
    rules: dict[str, IrRules] = {}
    for path in sorted(directory.glob("*.yaml")):
        if path.name.startswith("_"):
            continue
        loaded = load_rules(path)
        rules[loaded.ticker.upper()] = loaded
    return rules


__all__ = ["RULES_DIR", "IrRules", "PageRule", "load_all_rules", "load_rules"]
