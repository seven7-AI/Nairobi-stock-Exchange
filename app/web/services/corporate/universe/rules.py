"""Listing-status rules: pure functions over evidence.

A status is a conclusion from sightings and observations, never from silence
alone: a company is ``delisted`` only when the NSE page has stopped naming it for
several runs *and* it has not traded for weeks (or an announcement says so), and
``suspended`` only when an announcement says so. Everything short of that stays at
the previous status with a reason, or ``unknown`` with the evidence listed.

    codegraph explore "listing_status StatusEvidence StatusDecision"
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date

from app.web.services.corporate.config import CorporateConfig

#: The archive's own cut-over: names last seen on this date were delisted before
#: the 2013 sector files begin; the scraper carries them for history only.
ARCHIVE_CUTOVER = date(2012, 12, 31)

_SUSPEND = re.compile(r"\bsuspen(?:d|ded|sion)\b", re.I)
_DELIST = re.compile(r"\bdelist(?:ed|ing)?\b", re.I)
_LIFT = re.compile(r"\b(?:lift(?:ed|ing)?|resum(?:e|ed|ption))\b", re.I)


@dataclass(frozen=True)
class Announcement:
    """An exchange notice naming the company (from C9's event collector; empty until then)."""

    kind: str
    ticker_symbol: str
    announced_on: date
    title: str
    url: str | None = None


@dataclass(frozen=True)
class StatusEvidence:
    ticker_symbol: str
    today: date
    #: Whether the latest NSE page run named the company.
    on_page: bool
    #: Distinct NSE page runs since the company was last named on it (0 when on_page).
    page_runs_missing: int
    #: Distinct NSE page runs recorded in total (rules need at least a few to conclude).
    page_runs_total: int
    first_observation: date | None
    last_observation: date | None
    previous_status: str | None = None
    previous_delisted_on: date | None = None
    announcements: tuple[Announcement, ...] = field(default_factory=tuple)


@dataclass(frozen=True)
class StatusDecision:
    status: str
    reason: str
    delisted_on: date | None = None
    first_listed: date | None = None


def _days_since(day: date | None, today: date) -> int | None:
    return None if day is None else (today - day).days


def listing_status(evidence: StatusEvidence, config: CorporateConfig) -> StatusDecision:
    """Decide the listing status from the evidence, most authoritative rule first."""
    e = evidence
    first_listed = e.first_observation
    notices = sorted(e.announcements, key=lambda a: a.announced_on)

    # 1. Announcements are the only source that can suspend, and the strongest that delists.
    for notice in reversed(notices):
        if _DELIST.search(notice.title):
            return StatusDecision(
                "delisted",
                f"delisting announcement {notice.announced_on}: {notice.title[:120]}",
                delisted_on=notice.announced_on,
                first_listed=first_listed,
            )
        if _SUSPEND.search(notice.title) and not _LIFT.search(notice.title):
            return StatusDecision(
                "suspended",
                f"suspension announcement {notice.announced_on}: {notice.title[:120]}",
                first_listed=first_listed,
            )
        if _LIFT.search(notice.title):
            break  # a lift ends the suspension; fall through to the trading evidence

    # 2. Archive-era names: last traded on the 2012 cut-over and never seen since.
    if e.last_observation is not None and e.last_observation <= ARCHIVE_CUTOVER and not e.on_page:
        return StatusDecision(
            "delisted",
            f"last observation {e.last_observation} (archive cut-over); not on the NSE page",
            delisted_on=e.last_observation,
            first_listed=first_listed,
        )

    since_trade = _days_since(e.last_observation, e.today)
    recently_traded = since_trade is not None and since_trade <= config.listed_observation_days

    # 3. Listed: traded recently. The page alone never lists - it still names
    #    companies that stopped trading years ago.
    page = "on the NSE listed-companies page" if e.on_page else "not on the NSE page"
    if recently_traded:
        traded = f"last observation {e.last_observation}"
        since_first = _days_since(e.first_observation, e.today)
        is_new = since_first is not None and since_first <= config.newly_listed_days
        status = "newly_listed" if is_new else "listed"
        if is_new:
            traded += f"; first observation {e.first_observation}"
        return StatusDecision(status, f"{page}; {traded}", first_listed=first_listed)

    # 4. Delisted by absence: gone from the page for N runs AND untraded for M days.
    if (
        e.page_runs_missing >= config.delist_missing_runs
        and since_trade is not None
        and since_trade >= config.delist_missing_days
    ):
        return StatusDecision(
            "delisted",
            f"absent from the NSE page for at least {config.delist_missing_runs} runs; "
            f"last observation {e.last_observation}",
            delisted_on=e.last_observation,
            first_listed=first_listed,
        )

    # 5. Not enough evidence to conclude: keep what we had, say why.
    detail = f"{page}; " + (
        f"last observation {e.last_observation}"
        if e.last_observation is not None
        else "no observation"
    )
    if e.previous_status in ("listed", "newly_listed", "suspended"):
        return StatusDecision(
            e.previous_status,
            f"kept: {detail}; fewer than {config.delist_missing_runs} runs or "
            f"{config.delist_missing_days} days without trading",
            first_listed=first_listed,
        )
    if e.previous_status == "delisted":
        return StatusDecision(
            "delisted",
            f"kept: {detail}",
            delisted_on=e.previous_delisted_on,
            first_listed=first_listed,
        )
    return StatusDecision("unknown", detail, first_listed=first_listed)


__all__ = ["ARCHIVE_CUTOVER", "Announcement", "StatusDecision", "StatusEvidence", "listing_status"]
