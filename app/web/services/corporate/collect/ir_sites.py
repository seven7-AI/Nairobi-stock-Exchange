"""Company investor-relations sites, driven by ``sources/<TICKER>.yaml``.

codegraph explore "IrSiteSource load_all_rules select_links"
"""

from __future__ import annotations

from app.web.services.corporate.collect.base import (
    DocumentCandidate,
    FetchedDocument,
    SourceHealth,
    candidate_from,
    fetch_document,
    is_challenge_page,
    select_links,
)
from app.web.services.corporate.http import PoliteClient
from app.web.services.corporate.sources._schema import IrRules


class IrSiteSource:
    kind = "ir"
    ticker_symbol: str | None

    def __init__(self, rules: IrRules) -> None:
        self.rules = rules
        self.name = rules.source_name
        self.base_url = rules.base_url
        self.ticker_symbol = rules.ticker.upper()

    def discover(self, client: PoliteClient) -> tuple[list[DocumentCandidate], SourceHealth]:
        if not self.rules.enabled:
            return [], SourceHealth(self.name, "disabled", self.rules.notes or "disabled in rules")
        found: list[DocumentCandidate] = []
        failures: list[str] = []
        pages_ok = 0
        for page in self.rules.pages:
            result = client.get(page.url, max_bytes=5_000_000)
            if not result.ok:
                failures.append(f"{page.url}: {result.status} {result.reason or ''}".strip())
                continue
            html = result.content.decode("utf-8", errors="replace")
            if is_challenge_page(html):
                failures.append(f"{page.url}: 403-equivalent (bot-protection challenge page)")
                continue
            pages_ok += 1
            for href, text in select_links(
                html,
                page.url,
                href_pattern=page.href_pattern,
                text_pattern=page.text_pattern,
                exclude_text=page.exclude_text,
            ):
                found.append(
                    candidate_from(
                        source=self.name,
                        ticker_symbol=self.ticker_symbol,
                        kind=page.kind,
                        page_url=page.url,
                        href=href,
                        text=text,
                        fiscal_year_pattern=page.fiscal_year_pattern,
                        period_end_month=page.period_end_month,
                        period_end_day=page.period_end_day,
                    )
                )
        if pages_ok == 0 and self.rules.pages:
            blocked = any("403" in f or "disallowed" in f for f in failures)
            status = "blocked" if blocked else "down"
            return [], SourceHealth(self.name, status, "; ".join(failures)[:500])
        if failures:
            return found, SourceHealth(self.name, "degraded", "; ".join(failures)[:500])
        if not found:
            return [], SourceHealth(
                self.name,
                "degraded",
                f"{pages_ok} pages fetched but no matching links (layout changed?)",
            )
        return found, SourceHealth(self.name, "ok", f"{len(found)} links on {pages_ok} pages")

    def fetch(
        self,
        candidate: DocumentCandidate,
        client: PoliteClient,
        *,
        etag: str | None,
        last_modified: str | None,
    ) -> FetchedDocument:
        return fetch_document(candidate, client, etag=etag, last_modified=last_modified)


__all__ = ["IrSiteSource"]
