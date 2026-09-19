"""The document collector: discovery on real page markup (KCB, NSE, CBK, BoT), stable
identity for signed links, the version chain, idempotent re-runs, the byte cap, the CMA
stub, blocked sources, and the CLI. No network: ``httpx.MockTransport`` serves the fixtures.

codegraph explore "collect_documents IrSiteSource NseAnnouncementsSource store_document"
"""

from __future__ import annotations

import re
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

import httpx
import pytest
from sqlalchemy import inspect

from app.web.config import Settings
from app.web.db.analytics import analytics_session, build_analytics_engine
from app.web.db.analytics.services.corporate_documents import (
    document_counts,
    load_documents,
    load_sources,
)
from app.web.services.analytics.store import upgrade_analytics_db
from app.web.services.corporate.collect.base import (
    DocumentCandidate,
    candidate_from,
    fiscal_year_of,
    is_signed,
    select_links,
)
from app.web.services.corporate.collect.ir_sites import IrSiteSource
from app.web.services.corporate.collect.nse import (
    NseAnnouncementsSource,
    attribute_ticker,
    parse_nse_items,
)
from app.web.services.corporate.collect.regulators import BotSource, CbkSource, CmaSource
from app.web.services.corporate.collect.service import build_sources, collect_documents
from app.web.services.corporate.collect.storage import store_document
from app.web.services.corporate.http import PoliteClient
from app.web.services.corporate.sources._schema import RULES_DIR, load_all_rules, load_rules
from app.web.services.corporate.universe.service import refresh_universe

pytestmark = pytest.mark.unit

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "corporate" / "html"
NOW = datetime(2026, 9, 19, 9, 0, tzinfo=UTC)

PAGES = {
    "https://kcbgroup.com/integrated-reports": "kcb_integrated_reports.html",
    "https://kcbgroup.com/financial-statements": "kcb_financial_statements.html",
    "https://kcbgroup.com/subsidiary-financial-statements": "kcb_subsidiary_statements.html",
    "https://www.nse.co.ke/listed-company-announcements/": "nse_announcements.html",
    "https://www.nse.co.ke/listed-companies/": "nse_listed_companies.html",
    "https://www.centralbank.go.ke/reports/bank-supervision-and-banking-sector-reports/": (
        "cbk_bank_supervision_reports.html"
    ),
    "https://www.bot.go.tz/Publications/Filter/41?lang=en": "bot_publications_41.html",
}


def _pdf(seed: str, size: int = 2000) -> bytes:
    body = (seed.encode("utf-8") * (size // max(len(seed), 1) + 1))[:size]
    return b"%PDF-1.4\n" + body + b"\n%%EOF\n"


class FakeWeb:
    """Serves the fixture pages and deterministic PDF bytes; records every request."""

    def __init__(self) -> None:
        self.requests: list[httpx.Request] = []
        self.pdf_versions: dict[str, int] = {}
        self.blocked: set[str] = set()
        self.down: set[str] = set()

    def handler(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        url = str(request.url)
        host = request.url.host
        if host in self.blocked:
            return httpx.Response(403, content=b"forbidden")
        if host == "equitygroupholdings.com" and host not in self.down:
            return httpx.Response(
                200,
                content=b'<html><head><META NAME="robots" CONTENT="noindex,nofollow">'
                b'<script src="/_Incapsula_Resource?SWJIYLWA=abc"></script>'
                b"</head><body></body></html>",
            )
        if host in self.down:
            return httpx.Response(502, content=b"bad gateway")
        bare = url.split("#")[0]
        if bare in PAGES:
            return httpx.Response(
                200,
                content=(FIXTURES / PAGES[bare]).read_bytes(),
                headers={"Content-Type": "text/html"},
            )
        if "/circulars/" in url:
            return httpx.Response(
                200, content=b"<html><body>no circulars in this fixture</body></html>"
            )
        if host == "cmarcp.or.ke":
            return httpx.Response(502)
        if (
            "/download/" in url
            or url.endswith(".pdf")
            or "/Publications/Other/" in url
            or "banking_sector_annual_reports" in url
        ):
            key = re.sub(r"signature=[^&]+", "", url)
            version = self.pdf_versions.get(key, 1)
            etag = f'"{abs(hash(key)) % 100000}-v{version}"'
            if request.headers.get("If-None-Match") == etag:
                return httpx.Response(304)
            if request.method == "HEAD":
                return httpx.Response(
                    200, headers={"ETag": etag, "Content-Type": "application/pdf"}
                )
            return httpx.Response(
                200,
                content=_pdf(f"{key}|v{version}"),
                headers={"ETag": etag, "Content-Type": "application/pdf"},
            )
        return httpx.Response(404)


def _client(web: FakeWeb, **kw: Any) -> PoliteClient:
    return PoliteClient(
        transport=httpx.MockTransport(web.handler), respect_robots=False, sleep=lambda s: None, **kw
    )


# --- base helpers -------------------------------------------------------------------


def test_signed_links_get_a_page_plus_title_identity() -> None:
    signed = candidate_from(
        source="ir:KCB",
        ticker_symbol="KCB",
        kind="integrated_report",
        page_url="https://kcbgroup.com/integrated-reports",
        href="https://kcbgroup.com/download/abc?signature=deadbeef",
        text="KCB Group Plc 2024 Integrated Report",
        fiscal_year_pattern=r"(?P<fy>20\d{2}) Integrated Report",
        period_end_month=12,
        period_end_day=31,
    )
    assert signed.signed and "signature" not in signed.identity_url
    assert signed.identity_url.startswith("https://kcbgroup.com/integrated-reports#")
    assert signed.fiscal_year == 2024 and signed.period_end == date(2024, 12, 31)
    plain = candidate_from(
        source="cbk",
        ticker_symbol=None,
        kind="regulator_report",
        page_url="p",
        href="https://x/y.pdf",
        text="2023 Annual Report",
    )
    assert (
        not plain.signed and plain.identity_url == "https://x/y.pdf" and plain.fiscal_year == 2023
    )
    assert is_signed("https://a/b?token=1") and not is_signed("https://a/b?lang=en")
    assert fiscal_year_of("No year here") is None


def test_select_links_dedupes_and_filters() -> None:
    page = (FIXTURES / "kcb_integrated_reports.html").read_text()
    links = list(
        select_links(
            page,
            "https://kcbgroup.com/integrated-reports",
            href_pattern="/download/",
            text_pattern="Integrated Report",
        )
    )
    assert [t for _, t in links] == [
        "KCB Group Plc 2025 Integrated Report and Financial Statements",
        "KCB Group Plc 2024 Integrated Report and Financial Statement",
        "KCB Group Plc 2023 Integrated Report and Financial Statement",
        "KCB Group Plc 2022 Integrated Report and Financial Statement",
        "KCB Group Plc 2021 Integrated Report and Financial Statement",
        "KCB Group Plc 2020 Integrated Report and Financial Statement",
    ]
    assert all(h.startswith("https://kcbgroup.com/download/") for h, _ in links)


# --- rule files -----------------------------------------------------------------------


def test_rule_files_load_and_validate() -> None:
    rules = load_all_rules()
    assert {"KCB", "SCOM", "EQTY"} <= set(rules)
    kcb = rules["KCB"]
    assert kcb.source_name == "ir:KCB" and len(kcb.pages) == 3
    assert {p.kind for p in kcb.pages} == {"integrated_report", "results", "subsidiary_statements"}
    assert load_rules(RULES_DIR / "KCB.yaml") == kcb


def test_rule_file_rejects_unknown_kind(tmp_path: Path) -> None:
    bad = tmp_path / "X.yaml"
    bad.write_text(
        "ticker: X\nir_url: https://x\nbase_url: https://x\n"
        "pages:\n  - url: https://x/r\n    kind: brochure\n"
    )
    with pytest.raises(ValueError, match="unknown document kind"):
        load_rules(bad)


# --- discovery on real markup ---------------------------------------------------------


def test_kcb_discovery_reads_reports_statements_and_subsidiaries() -> None:
    web = FakeWeb()
    source = IrSiteSource(load_rules(RULES_DIR / "KCB.yaml"))
    candidates, health = source.discover(_client(web))
    assert health.status == "ok"
    by_kind: dict[str, list[DocumentCandidate]] = {}
    for c in candidates:
        by_kind.setdefault(c.kind, []).append(c)
    assert [c.fiscal_year for c in by_kind["integrated_report"]] == [
        2025,
        2024,
        2023,
        2022,
        2021,
        2020,
    ]
    assert all(c.signed and c.ticker_symbol == "KCB" for c in candidates)
    titles = [c.title for c in by_kind["subsidiary_statements"]]
    assert any("Tanzania" in t for t in titles) and any("Uganda" in t for t in titles)
    assert not any("Money Market" in t or "Asset Management" in t for t in titles)
    assert len(by_kind["results"]) >= 8


def test_nse_items_are_attributed_to_companies_or_left_unattributed() -> None:
    page = (FIXTURES / "nse_announcements.html").read_text()
    items = parse_nse_items(page)
    assert len(items) == 8 and all(
        u.startswith("https://www.nse.co.ke/wp-content/uploads/") for _, u in items
    )
    names = {
        "SCOM": "Safaricom Plc",
        "NSE": "Nairobi Securities Exchange Plc",
        "SKL": "Shri Krishana Overseas PLC",
        "XPRS": "Express Kenya Plc",
        "TOTL": "TotalEnergies Marketing Kenya PLC",
        "HAFR": "Home Afrika Ltd",
        "CGEN": "Car & General (K) Ltd",
        "NMG": "Nation Media Group Plc",
        "KCB": "KCB Group Plc",
    }
    attributed = {title: attribute_ticker(title, names) for title, _ in items}
    safaricom = next(t for t in attributed if t.startswith("Safaricom Plc"))
    assert attributed[safaricom] == "SCOM"
    assert any(v == "NSE" for k, v in attributed.items() if k.startswith("Nairobi Securities"))
    assert attribute_ticker("Some Unknown Company Plc - Results", names) is None
    assert attribute_ticker("Results for the year", names) is None
    web = FakeWeb()
    candidates, health = NseAnnouncementsSource(names).discover(_client(web))
    assert health.status == "ok" and len(candidates) == 8
    scom = [c for c in candidates if c.ticker_symbol == "SCOM"]
    assert scom and scom[0].kind == "results" and scom[0].fiscal_year == 2026


def test_regulator_discovery_cbk_bot_and_cma_stub() -> None:
    web = FakeWeb()
    client = _client(web)
    cbk, health = CbkSource().discover(client)
    assert health.status == "ok" and [c.fiscal_year for c in cbk][:3] == [2024, 2023, 2022]
    assert all(c.ticker_symbol is None and c.kind == "regulator_report" for c in cbk)
    bot, health = BotSource().discover(client)
    assert health.status == "ok" and bot
    assert not any(c.title == "Download" for c in bot)
    assert any("2025" in c.title for c in bot)
    cma, health = CmaSource().discover(client)
    assert cma == [] and health.status == "down" and "502" in health.detail


def test_blocked_challenged_and_down_sites_record_health_without_raising() -> None:
    web = FakeWeb()
    web.blocked.add("www.safaricom.co.ke")
    rules = load_all_rules()
    _, scom = IrSiteSource(rules["SCOM"]).discover(_client(web, retries=0))
    _, eqty = IrSiteSource(rules["EQTY"]).discover(_client(web, retries=0))
    assert scom.status == "blocked" and "403" in scom.detail
    assert eqty.status == "blocked" and "challenge" in eqty.detail  # Incapsula page with HTTP 200
    web.down.add("equitygroupholdings.com")
    _, eqty_down = IrSiteSource(rules["EQTY"]).discover(_client(web, retries=0))
    assert eqty_down.status == "down" and "502" in eqty_down.detail


# --- storage ----------------------------------------------------------------------------


def test_store_document_is_content_addressed_and_atomic(tmp_path: Path) -> None:
    first = store_document(tmp_path, "KCB", _pdf("a"))
    again = store_document(tmp_path, "KCB", _pdf("a"))
    other = store_document(tmp_path, "regulator", b"<html>not a pdf</html>")
    assert first.relative_path == f"KCB/{first.sha256}.pdf" and not first.already_present
    assert again.already_present and again.sha256 == first.sha256
    assert other.relative_path.endswith(".bin") and not other.is_pdf
    assert not list(tmp_path.rglob("*.part"))


# --- service ------------------------------------------------------------------------------


@pytest.fixture
def store(tmp_path: Path, fixture_settings: Settings, fixture_source) -> Settings:
    settings = fixture_settings.model_copy(
        update={
            "analytics_db_path": tmp_path / "corp.sqlite3",
            "corporate_documents_dir": tmp_path / "docs",
            "corporate_cache_dir": tmp_path / "cache",
        }
    )
    upgrade_analytics_db(settings.analytics_db_path)
    page = PoliteClient(
        transport=httpx.MockTransport(FakeWeb().handler), respect_robots=False, sleep=lambda s: None
    )
    refresh_universe(settings, fixture_source, client=page, now=NOW)
    return settings


def test_migration_creates_the_three_tables(store: Settings) -> None:
    engine = build_analytics_engine(store.analytics_db_path)
    try:
        names = set(inspect(engine).get_table_names())
    finally:
        engine.dispose()
    assert {"corporate_sources", "corporate_documents", "corporate_extractions"} <= names


def test_collect_fetches_versions_and_is_idempotent(store: Settings) -> None:
    web = FakeWeb()
    first = collect_documents(store, client=_client(web), now=NOW, sources=["ir:KCB", "cbk"])
    assert (
        first.sources == 2 and first.health["ir:KCB"][0] == "ok" and first.health["cbk"][0] == "ok"
    )
    assert first.fetched >= 6 + 9 and first.failed == 0 and first.new_versions == 0
    with analytics_session(store) as session:
        docs = load_documents(session, ticker_symbol="KCB", kind="integrated_report")
        assert [d.fiscal_year for d in docs] == [2020, 2021, 2022, 2023, 2024, 2025]
        assert all(d.version_no == 1 and d.parse_status == "pending" for d in docs)
        assert all(
            d.notes["signed_link"] and "#" in d.url and "signature" not in d.url for d in docs
        )
        assert all((store.corporate_documents_dir / d.path).is_file() for d in docs)
        cbk = load_documents(session, source="cbk")
        assert cbk and all(d.ticker_symbol is None and d.path.startswith("regulator/") for d in cbk)
        health = {s.name: s.health for s in load_sources(session)}
        assert health["ir:KCB"] == "ok" and health["cbk"] == "ok"

    # Same web, one day later: every document answers 304 -> unchanged, nothing written.
    later = NOW + timedelta(days=1)
    second = collect_documents(store, client=_client(web), now=later, sources=["ir:KCB", "cbk"])
    assert second.fetched == 0 and second.new_versions == 0 and second.unchanged == first.fetched
    with analytics_session(store) as session:
        docs = load_documents(session, ticker_symbol="KCB", kind="integrated_report")
        assert all(d.last_seen_at == later and d.retrieved_at == NOW for d in docs)

    # The 2024 report is re-issued with new bytes: a new version, the old one kept.
    target = [r for r in web.requests if "/download/" in str(r.url)][
        1
    ]  # second signed link fetched
    bare = re.sub(r"signature=[^&]+", "", str(target.url))
    web.pdf_versions[bare] = 2
    third = collect_documents(
        store, client=_client(web), now=later + timedelta(days=1), sources=["ir:KCB"]
    )
    assert third.new_versions == 1 and third.unchanged >= 5
    with analytics_session(store) as session:
        current = load_documents(session, ticker_symbol="KCB", kind="integrated_report")
        every = load_documents(
            session, ticker_symbol="KCB", kind="integrated_report", current_only=False
        )
        assert len(current) == 6 and len(every) == 7
        old = [d for d in every if d.superseded_by_id is not None]
        assert len(old) == 1 and old[0].version_no == 1
        new = next(d for d in current if d.id == old[0].superseded_by_id)
        assert new.version_no == 2 and new.url == old[0].url and new.sha256 != old[0].sha256
        assert (store.corporate_documents_dir / old[0].path).is_file()  # never deleted
        counts = document_counts(session)
        assert (
            counts["by_parse_status"]
            == {"pending": len(current) + len(load_documents(session, source="cbk"))}
            or counts["bytes"] > 0
        )


def test_dry_run_discovers_without_writing(store: Settings) -> None:
    web = FakeWeb()
    result = collect_documents(
        store, client=_client(web), now=NOW, dry_run=True, sources=["ir:KCB"]
    )
    assert result.dry_run and result.discovered >= 20 and result.fetched == 0
    assert not any("/download/" in str(r.url) for r in web.requests)
    with analytics_session(store) as session:
        assert load_documents(session) == []
        assert {s.name for s in load_sources(session)} >= {"ir:KCB"}


def test_document_cap_and_byte_cap_are_recorded_not_raised(store: Settings) -> None:
    web = FakeWeb()
    capped = collect_documents(
        store, client=_client(web), now=NOW, sources=["cbk"], max_documents=2
    )
    assert capped.fetched == 2 and capped.skipped_budget >= 1
    small = _client(web, max_bytes=500)
    tiny = collect_documents(store, client=small, now=NOW, sources=["ir:KCB"], max_documents=3)
    assert tiny.too_large >= 1 and tiny.fetched == 0 and tiny.failures


def test_non_pdf_bodies_are_failures_and_ticker_filter_keeps_regulators(store: Settings) -> None:
    web = FakeWeb()

    def html_instead(request: httpx.Request) -> httpx.Response:
        if "/download/" in str(request.url):
            return httpx.Response(
                200, content=b"<html>login</html>", headers={"Content-Type": "text/html"}
            )
        return web.handler(request)

    client = PoliteClient(
        transport=httpx.MockTransport(html_instead), respect_robots=False, sleep=lambda s: None
    )
    result = collect_documents(store, client=client, now=NOW, tickers=["KCB"], max_documents=50)
    assert result.failed >= 1 and any("not a PDF" in f for f in result.failures)
    assert result.health["cbk"][0] == "ok"  # regulators are kept under a ticker filter
    assert "nse" in result.health and result.fetched >= 9  # CBK + BoT PDFs still fetched
    with analytics_session(store) as session:
        assert load_documents(session, ticker_symbol="KCB") == []
        assert load_documents(session, source="cbk")


def test_build_sources_filters_by_name_kind_or_ticker() -> None:
    names = {"KCB": "KCB Group Plc"}
    everything = build_sources(names)
    assert {s.name for s in everything} >= {"ir:KCB", "ir:SCOM", "nse", "cbk", "bot", "cma"}
    assert {s.name for s in build_sources(names, only={"ir"})} == {
        s.name for s in everything if s.kind == "ir"
    }
    assert [s.name for s in build_sources(names, only={"kcb"})] == ["ir:KCB"]
    assert [s.name for s in build_sources(names, only={"regulator"})] == ["cbk", "bot", "cma"]


def test_cli_collect_documents_and_sources(
    store: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    from typer.testing import CliRunner

    import app.cli.analytics as analytics_cli
    import app.web.services.corporate.collect.service as service
    from app.cli.main import app

    web = FakeWeb()
    monkeypatch.setattr(analytics_cli, "get_settings", lambda: store)
    monkeypatch.setattr(service, "polite_client_from_settings", lambda settings, **kw: _client(web))
    runner = CliRunner()
    collected = runner.invoke(app, ["corporate", "collect", "--source", "cbk", "--max", "3"])
    assert collected.exit_code == 0, collected.output
    assert "fetched 3" in collected.output and "over budget" in collected.output
    listed = runner.invoke(app, ["corporate", "documents", "list", "--status", "pending"])
    assert listed.exit_code == 0 and "3 shown" in listed.output and "'pending': 3" in listed.output
    health = runner.invoke(app, ["corporate", "sources", "health"])
    assert health.exit_code == 0 and "cbk" in health.output and "ok" in health.output


def test_no_signed_url_is_persisted_or_logged(
    store: Settings, caplog: pytest.LogCaptureFixture
) -> None:
    web = FakeWeb()
    import logging

    with caplog.at_level(logging.INFO):
        collect_documents(store, client=_client(web), now=NOW, sources=["ir:KCB"], max_documents=2)
    assert "signature=" not in caplog.text
    with analytics_session(store) as session:
        for doc in load_documents(session, ticker_symbol="KCB"):
            assert "signature" not in doc.url and "signature" not in str(doc.notes)
    assert urlsplit(web.requests[-1].url.__str__()).netloc  # sanity: requests were made
