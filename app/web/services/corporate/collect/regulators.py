"""Regulator publications: CBK and Bank of Tanzania supervision reports; CMA stub.

Regulator reports have no ticker (they describe the sector); they are collected as
``regulator_report`` documents for cross-checks (branch counts, subsidiaries by
bank) in later phases. Bank of Uganda is a JavaScript application and is
registered disabled; the CMA resource centre returns 502 (probed 2026-09-19) and
its adapter records that as ``down`` without raising.

    codegraph explore "CbkSource BotSource CmaSource"
"""

from __future__ import annotations

from app.web.services.corporate.collect.base import (
    DocumentCandidate,
    FetchedDocument,
    SourceHealth,
    candidate_from,
    fetch_document,
    select_links,
)
from app.web.services.corporate.http import PoliteClient


class _AnchorListSource:
    """A page whose matching anchors are the documents."""

    kind = "regulator"
    ticker_symbol: str | None = None
    name = ""
    base_url = ""
    page_url = ""
    href_pattern: str | None = None
    text_pattern: str | None = None
    exclude_text: str | None = None
    document_kind = "regulator_report"
    fiscal_year_pattern: str | None = None
    period_end = (12, 31)
    detail = ""

    def discover(self, client: PoliteClient) -> tuple[list[DocumentCandidate], SourceHealth]:
        result = client.get(self.page_url, max_bytes=5_000_000)
        if not result.ok:
            status = "blocked" if result.status_code == 403 else "down"
            return [], SourceHealth(
                self.name, status, f"{result.status}: {result.reason or ''}".strip()
            )
        page = result.content.decode("utf-8", errors="replace")
        found = [
            candidate_from(
                source=self.name,
                ticker_symbol=None,
                kind=self.document_kind,
                page_url=self.page_url,
                href=href,
                text=text,
                fiscal_year_pattern=self.fiscal_year_pattern,
                period_end_month=self.period_end[0],
                period_end_day=self.period_end[1],
            )
            for href, text in select_links(
                page,
                self.page_url,
                href_pattern=self.href_pattern,
                text_pattern=self.text_pattern,
                exclude_text=self.exclude_text,
            )
        ]
        # One candidate per fiscal year: a "Download" duplicate of the same file is dropped.
        by_url: dict[str, DocumentCandidate] = {}
        for candidate in found:
            current = by_url.get(candidate.url)
            if current is None or (current.fiscal_year is None and candidate.fiscal_year):
                by_url[candidate.url] = candidate
        candidates = list(by_url.values())
        if not candidates:
            return [], SourceHealth(self.name, "degraded", "page fetched but no report links found")
        return candidates, SourceHealth(
            self.name, "ok", f"{len(candidates)} reports; {self.detail}"
        )

    def fetch(
        self,
        candidate: DocumentCandidate,
        client: PoliteClient,
        *,
        etag: str | None,
        last_modified: str | None,
    ) -> FetchedDocument:
        return fetch_document(candidate, client, etag=etag, last_modified=last_modified)


class CbkSource(_AnchorListSource):
    name = "cbk"
    base_url = "https://www.centralbank.go.ke"
    page_url = "https://www.centralbank.go.ke/reports/bank-supervision-and-banking-sector-reports/"
    href_pattern = r"/uploads/banking_sector_annual_reports/"
    text_pattern = r"Annual Report|BSD"
    detail = "Bank Supervision Annual Reports"


class BotSource(_AnchorListSource):
    name = "bot"
    base_url = "https://www.bot.go.tz"
    page_url = "https://www.bot.go.tz/Publications/Filter/41?lang=en"
    href_pattern = r"/Publications/Other/Banking Supervision Annual Reports/en/"
    text_pattern = r"Supervision Annual Report|^20\d{2}$"
    exclude_text = r"^Download$"
    detail = "Banking / Financial Sector Supervision Annual Reports"


class CmaSource:
    """Capital Markets Authority resource centre - a stub until it is reachable."""

    kind = "regulator"
    name = "cma"
    base_url = "https://cmarcp.or.ke"
    page_url = "https://cmarcp.or.ke/"
    ticker_symbol: str | None = None

    def discover(self, client: PoliteClient) -> tuple[list[DocumentCandidate], SourceHealth]:
        result = client.get(self.page_url, max_bytes=2_000_000)
        if not result.ok:
            return [], SourceHealth(
                self.name,
                "down",
                f"{result.status}: {result.reason or ''} - issuer filings are not collected "
                "until the resource centre answers".strip(),
            )
        return [], SourceHealth(
            self.name, "degraded", "reachable, but no issuer-filing listing is parsed yet"
        )

    def fetch(
        self,
        candidate: DocumentCandidate,
        client: PoliteClient,
        *,
        etag: str | None,
        last_modified: str | None,
    ) -> FetchedDocument:
        return fetch_document(candidate, client, etag=etag, last_modified=last_modified)


__all__ = ["BotSource", "CbkSource", "CmaSource"]
