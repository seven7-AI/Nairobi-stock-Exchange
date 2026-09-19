"""Discover and fetch documents from every registered source: the one call the CLI
and the weekly job make.

Idempotent by construction: a candidate whose latest stored version answers 304,
or whose bytes hash to the stored sha, is ``unchanged``; new bytes at a known
identity are a new version; nothing is ever deleted. Discovery and fetching are
bounded by the request budget and ``corporate_max_documents_per_run``, and a
source that fails records its health instead of failing the run.

    codegraph explore "collect_documents build_sources CollectResult"
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from app.web.config import Settings
from app.web.db.analytics import analytics_session
from app.web.db.analytics.services.corporate_companies import load_companies
from app.web.db.analytics.services.corporate_documents import (
    add_document_version,
    document_by_sha,
    latest_document_for,
    record_source_health,
    upsert_source,
)
from app.web.services.corporate.collect.base import DocumentCandidate, DocumentSource
from app.web.services.corporate.collect.ir_sites import IrSiteSource
from app.web.services.corporate.collect.nse import NseAnnouncementsSource
from app.web.services.corporate.collect.regulators import BotSource, CbkSource, CmaSource
from app.web.services.corporate.collect.storage import store_document
from app.web.services.corporate.http import PoliteClient, polite_client_from_settings
from app.web.services.corporate.sources._schema import RULES_DIR, load_all_rules
from app.web.utils.logger import get_logger

logger = get_logger("app.web.services.corporate.collect")

REGULATOR_FOLDER = "regulator"


@dataclass(frozen=True)
class CollectResult:
    sources: int
    discovered: int
    fetched: int
    unchanged: int
    new_versions: int
    too_large: int
    failed: int
    skipped_budget: int
    dry_run: bool
    health: dict[str, tuple[str, str]] = field(default_factory=dict)
    fetched_titles: tuple[str, ...] = field(default_factory=tuple)
    failures: tuple[str, ...] = field(default_factory=tuple)


def build_sources(
    names: dict[str, str], *, rules_dir: Path = RULES_DIR, only: set[str] | None = None
) -> list[DocumentSource]:
    """Every registered source: one IR source per rule file, the NSE, CBK, BoT, CMA."""
    sources: list[DocumentSource] = []
    for rules in load_all_rules(rules_dir).values():
        sources.append(IrSiteSource(rules))
    sources.append(NseAnnouncementsSource(names))
    sources.extend([CbkSource(), BotSource(), CmaSource()])
    if only:
        wanted = {o.lower() for o in only}
        sources = [
            s
            for s in sources
            if s.name.lower() in wanted
            or s.kind.lower() in wanted
            or (s.ticker_symbol or "").lower() in wanted
        ]
    return sources


def _folder_for(candidate: DocumentCandidate) -> str:
    return candidate.ticker_symbol or REGULATOR_FOLDER


def collect_documents(
    settings: Settings,
    *,
    tickers: list[str] | None = None,
    sources: list[str] | None = None,
    client: PoliteClient | None = None,
    dry_run: bool = False,
    max_documents: int | None = None,
    rules_dir: Path = RULES_DIR,
    now: datetime | None = None,
) -> CollectResult:
    stamp = now or datetime.now(UTC)
    own_client = client is None
    http = client or polite_client_from_settings(settings)
    cap = max_documents if max_documents is not None else settings.corporate_max_documents_per_run
    wanted_tickers = {t.upper() for t in tickers} if tickers else None
    counts = {
        "discovered": 0,
        "fetched": 0,
        "unchanged": 0,
        "new_versions": 0,
        "too_large": 0,
        "failed": 0,
        "skipped_budget": 0,
    }
    health: dict[str, tuple[str, str]] = {}
    fetched_titles: list[str] = []
    failures: list[str] = []
    try:
        with analytics_session(settings) as session:
            names = {c.ticker_symbol: c.canonical_name for c in load_companies(session)}
            registry = build_sources(
                names,
                rules_dir=rules_dir,
                only=set(sources) | (wanted_tickers or set()) if sources else None,
            )
            if wanted_tickers and not sources:
                registry = [
                    s
                    for s in registry
                    if s.ticker_symbol in wanted_tickers or s.ticker_symbol is None
                ]
            for source in registry:
                upsert_source(
                    session,
                    name=source.name,
                    kind=source.kind,
                    base_url=source.base_url,
                    ticker_symbol=source.ticker_symbol,
                    rules_path=(
                        str(rules_dir / f"{source.ticker_symbol}.yaml")
                        if source.kind == "ir"
                        else None
                    ),
                    now=stamp,
                )
            for source in registry:
                candidates, status = source.discover(http)
                health[source.name] = (status.status, status.detail)
                record_source_health(
                    session, source.name, status=status.status, detail=status.detail, now=stamp
                )
                for candidate in candidates:
                    # A ticker filter keeps that company's documents and the regulator
                    # reports; the exchange's unattributed items are left for a full run.
                    if (
                        wanted_tickers
                        and candidate.ticker_symbol not in wanted_tickers
                        and (candidate.ticker_symbol is not None or source.kind == "exchange")
                    ):
                        continue
                    counts["discovered"] += 1
                    if dry_run:
                        continue
                    if counts["fetched"] + counts["new_versions"] >= cap:
                        counts["skipped_budget"] += 1
                        continue
                    _collect_one(
                        session,
                        settings,
                        source,
                        candidate,
                        http,
                        stamp,
                        counts,
                        fetched_titles,
                        failures,
                    )
    finally:
        if own_client:
            http.close()
    logger.info("corporate_documents_collected", dry_run=dry_run, **counts)
    return CollectResult(
        sources=len(health),
        dry_run=dry_run,
        health=health,
        fetched_titles=tuple(fetched_titles),
        failures=tuple(failures),
        **counts,
    )


def _collect_one(
    session: Any,
    settings: Settings,
    source: DocumentSource,
    candidate: DocumentCandidate,
    http: PoliteClient,
    stamp: datetime,
    counts: dict[str, int],
    fetched_titles: list[str],
    failures: list[str],
) -> None:
    identity = candidate.identity_url
    previous = latest_document_for(session, candidate.source, identity)
    fetched = source.fetch(
        candidate,
        http,
        etag=previous.http_etag if previous else None,
        last_modified=previous.http_last_modified if previous else None,
    )
    if fetched.status == "not_modified" and previous is not None:
        previous.last_seen_at = stamp
        counts["unchanged"] += 1
        return
    if fetched.status == "too_large":
        counts["too_large"] += 1
        failures.append(f"{candidate.title[:60]}: {fetched.reason}")
        return
    if fetched.status == "budget_exhausted":
        counts["skipped_budget"] += 1
        return
    if fetched.status != "ok":
        counts["failed"] += 1
        failures.append(f"{candidate.title[:60]}: {fetched.status} {fetched.reason or ''}".strip())
        return
    stored = store_document(
        settings.corporate_documents_dir, _folder_for(candidate), fetched.content
    )
    if previous is not None and previous.sha256 == stored.sha256:
        previous.last_seen_at = stamp
        previous.http_etag = fetched.etag or previous.http_etag
        previous.http_last_modified = fetched.last_modified or previous.http_last_modified
        counts["unchanged"] += 1
        return
    if not stored.is_pdf:
        counts["failed"] += 1
        failures.append(
            f"{candidate.title[:60]}: not a PDF ({fetched.content_type or 'unknown type'}, "
            f"{stored.size} bytes)"
        )
        return
    same_bytes_elsewhere = document_by_sha(session, stored.sha256)
    add_document_version(
        session,
        previous=previous,
        values={
            "ticker_symbol": candidate.ticker_symbol,
            "source": candidate.source,
            "kind": candidate.kind,
            "title": candidate.title,
            "url": identity,
            "final_url_host": fetched.final_host,
            "period_end": candidate.period_end,
            "fiscal_year": candidate.fiscal_year,
            "published_on": candidate.published_on,
            "sha256": stored.sha256,
            "bytes": stored.size,
            "path": stored.relative_path,
            "content_type": fetched.content_type,
            "retrieved_at": stamp,
            "last_seen_at": stamp,
            "http_etag": fetched.etag,
            "http_last_modified": fetched.last_modified,
            "parse_status": "pending",
            "notes": {
                "signed_link": candidate.signed,
                "page_url": candidate.page_url,
                **({"same_bytes_as": same_bytes_elsewhere.id} if same_bytes_elsewhere else {}),
                **candidate.hints,
            },
        },
    )
    if previous is None:
        counts["fetched"] += 1
    else:
        counts["new_versions"] += 1
    fetched_titles.append(candidate.title[:80])


__all__ = ["REGULATOR_FOLDER", "CollectResult", "build_sources", "collect_documents"]
