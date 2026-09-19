"""The canonical company universe: NSE page parsing on real markup, the listing-status
rules case by case, the builder's per-field sourcing over the fixture scraper database,
idempotent re-runs, and the migration.

codegraph explore "build_universe listing_status parse_listed_companies refresh_universe"
"""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any

import httpx
import pytest
from sqlalchemy import inspect

from app.web.config import Settings
from app.web.db.analytics import analytics_session, build_analytics_engine
from app.web.db.analytics.services.corporate_companies import (
    SightingRow,
    load_companies,
    load_company,
    record_sightings,
    sightings_for,
    source_runs,
)
from app.web.services.analytics.store import upgrade_analytics_db
from app.web.services.corporate.config import DEFAULT_CORPORATE_CONFIG
from app.web.services.corporate.http import PoliteClient
from app.web.services.corporate.universe.builder import (
    PageHistory,
    PriorCompany,
    UniverseInputs,
    build_universe,
    match_listings,
    page_symbol_key,
)
from app.web.services.corporate.universe.nse_page import (
    clean_name,
    dedupe_listings,
    parse_listed_companies,
)
from app.web.services.corporate.universe.rules import (
    Announcement,
    StatusEvidence,
    listing_status,
)
from app.web.services.corporate.universe.service import refresh_universe

pytestmark = pytest.mark.unit

FIXTURE_HTML = (
    Path(__file__).resolve().parents[1]
    / "fixtures"
    / "corporate"
    / "html"
    / "nse_listed_companies.html"
)
TODAY = date(2026, 9, 19)
CONFIG = DEFAULT_CORPORATE_CONFIG


# --- NSE page ---------------------------------------------------------------------------


def test_page_parser_reads_symbol_isin_website_and_sector_from_real_markup() -> None:
    listings = parse_listed_companies(FIXTURE_HTML.read_text())
    by_symbol = dedupe_listings(listings)
    assert len(listings) == 12 and len(by_symbol) == 10  # the page repeats EQTY and COOP
    kcb = by_symbol["KCB"]
    assert kcb.name == "KCB Group Ltd" and kcb.name_raw == "KCB Group Ltd Ord 1.00"
    assert kcb.isin == "KE0000000315" and kcb.website == "https://kcbgroup.com/"
    assert kcb.sector_heading == "BANKING"
    assert (
        by_symbol["KPLC"].website is None
        and by_symbol["KPLC"].name == "Kenya Power & Lighting Co Ltd"
    )
    assert by_symbol["SKL.O0000"].isin is None
    assert by_symbol["SCOM"].sector_heading == "TELECOMMUNICATION AND TECHNOLOGY"
    assert by_symbol["ARM"].symbol == "ARM"  # still on the page although it no longer trades


@pytest.mark.parametrize(
    ("raw", "clean"),
    [
        ("KCB Group Ltd Ord 1.00", "KCB Group Ltd"),
        ("Kakuzi Ord.5.00", "Kakuzi"),
        ("Stanbic Holdings Plc. ord.5.00", "Stanbic Holdings Plc."),
        ("Crown Paints Kenya PLC. 0rd 5.00", "Crown Paints Kenya PLC."),
        ("Kapchorua Tea Co. Ltd Ord Ord 5.00 AIMS", "Kapchorua Tea Co. Ltd"),
        ("Flame Tree Group Holdings Ltd Ord 0.825", "Flame Tree Group Holdings Ltd"),
        ("Nation Media Group Ord. 2.50", "Nation Media Group"),
        ("NCBA Group PLC", "NCBA Group PLC"),
    ],
)
def test_par_value_suffixes_are_stripped(raw: str, clean: str) -> None:
    assert clean_name(raw) == clean


def test_page_symbols_drop_share_class_codes() -> None:
    assert page_symbol_key("SKL.O0000") == "SKL" and page_symbol_key("kcb") == "KCB"


# --- status rules -----------------------------------------------------------------------


def _evidence(**kw: object) -> StatusEvidence:
    base: dict[str, Any] = {
        "ticker_symbol": "X",
        "today": TODAY,
        "on_page": False,
        "page_runs_missing": 0,
        "page_runs_total": 0,
        "first_observation": date(2007, 1, 2),
        "last_observation": None,
    }
    base.update(kw)
    return StatusEvidence(**base)


def test_listed_needs_recent_trading_not_just_the_page() -> None:
    on_page = listing_status(_evidence(on_page=True, page_runs_total=1), CONFIG)
    assert on_page.status == "unknown" and on_page.reason.startswith("on the NSE")
    stale_page = listing_status(
        _evidence(on_page=True, last_observation=date(2024, 12, 31), previous_status="listed"),
        CONFIG,
    )
    assert stale_page.status == "listed" and stale_page.reason.startswith("kept: on the NSE")
    new = listing_status(
        _evidence(
            on_page=True,
            first_observation=TODAY - timedelta(days=20),
            last_observation=TODAY - timedelta(days=1),
        ),
        CONFIG,
    )
    assert new.status == "newly_listed" and "first observation" in new.reason
    traded = listing_status(
        _evidence(last_observation=TODAY - timedelta(days=5), previous_status="listed"), CONFIG
    )
    assert traded.status == "listed" and str(TODAY - timedelta(days=5)) in traded.reason
    assert traded.first_listed == date(2007, 1, 2)


def test_archive_names_are_delisted_with_the_cut_over_as_evidence() -> None:
    decision = listing_status(_evidence(last_observation=date(2012, 12, 31)), CONFIG)
    assert decision.status == "delisted" and decision.delisted_on == date(2012, 12, 31)
    assert "archive cut-over" in decision.reason


def test_delisting_by_absence_needs_both_page_runs_and_days() -> None:
    stale = TODAY - timedelta(days=90)
    both = listing_status(
        _evidence(page_runs_missing=3, page_runs_total=5, last_observation=stale), CONFIG
    )
    assert both.status == "delisted" and both.delisted_on == stale
    few_runs = listing_status(
        _evidence(
            page_runs_missing=2, page_runs_total=5, last_observation=stale, previous_status="listed"
        ),
        CONFIG,
    )
    assert few_runs.status == "listed" and few_runs.reason.startswith("kept:")
    recent = listing_status(
        _evidence(
            page_runs_missing=4,
            page_runs_total=5,
            last_observation=TODAY - timedelta(days=40),
            previous_status="listed",
        ),
        CONFIG,
    )
    assert recent.status == "listed"
    nothing_known = listing_status(
        _evidence(page_runs_missing=1, page_runs_total=1, last_observation=stale), CONFIG
    )
    assert nothing_known.status == "unknown" and "not on the NSE page" in nothing_known.reason


def test_suspension_only_from_an_announcement_and_lifted_by_one() -> None:
    notice = Announcement(
        "announcement", "X", date(2026, 9, 1), "Suspension of trading in X shares"
    )
    suspended = listing_status(
        _evidence(
            on_page=True, page_runs_total=2, previous_status="listed", announcements=(notice,)
        ),
        CONFIG,
    )
    assert suspended.status == "suspended" and "2026-09-01" in suspended.reason
    lift = Announcement("announcement", "X", date(2026, 9, 10), "Lifting of suspension of X shares")
    resumed = listing_status(
        _evidence(
            on_page=True,
            page_runs_total=2,
            previous_status="suspended",
            last_observation=TODAY - timedelta(days=2),
            announcements=(notice, lift),
        ),
        CONFIG,
    )
    assert resumed.status == "listed"
    delist = Announcement("circular", "X", date(2026, 9, 12), "Delisting of X from the NSE")
    gone = listing_status(
        _evidence(on_page=True, last_observation=TODAY, announcements=(delist,)), CONFIG
    )
    assert gone.status == "delisted" and gone.delisted_on == date(2026, 9, 12)


def test_a_previously_delisted_company_that_trades_again_is_listed() -> None:
    decision = listing_status(
        _evidence(
            previous_status="delisted",
            previous_delisted_on=date(2020, 1, 1),
            last_observation=TODAY - timedelta(days=3),
        ),
        CONFIG,
    )
    assert decision.status == "listed"


# --- builder ----------------------------------------------------------------------------


def _inputs(fixture_source, listings, **kw):
    base = {
        "instruments": fixture_source.fetch_instruments(),
        "aliases": fixture_source.fetch_instrument_aliases(),
        "spans": fixture_source.fetch_observation_spans(),
        "profiles": {},
        "listings": listings,
        "page_history": {},
        "prior": {},
        "sectors": None,
        "today": TODAY,
    }
    base.update(kw)
    return UniverseInputs(**base)


def test_builder_sources_every_field_and_skips_indices(fixture_source) -> None:
    listings = dedupe_listings(parse_listed_companies(FIXTURE_HTML.read_text()))
    report = build_universe(_inputs(fixture_source, listings), CONFIG)
    by_ticker = {r.ticker_symbol: r for r in report.records}
    assert set(by_ticker) == {
        "ABSA",
        "ACCS",
        "EQTY",
        "KCB",
        "KEGN",
        "KENO",
        "KPC",
        "NCBA",
        "SCOM",
        "SKL",
    }
    kcb = by_ticker["KCB"]
    assert kcb.isin == "KE0000000315" and kcb.field_sources["isin"]["source"] == "nse_listed_page"
    assert (
        kcb.legal_name == "KCB Group Ltd" and kcb.field_sources["legal_name"]["confidence"] == 0.7
    )
    assert kcb.canonical_name == "KCB Group Plc"
    assert kcb.website == "https://kcbgroup.com/"
    assert kcb.home_country == "KE" and kcb.field_sources["home_country"]["source"] == "assumed"
    assert kcb.listing_status == "listed" and kcb.confidence == 0.5
    assert kcb.exchange_ids == {"NSE": "KCB"}
    for record in report.records:
        for name in (
            "ticker_symbol",
            "canonical_name",
            "legal_name",
            "home_country",
            "listing_status",
        ):
            assert name in record.field_sources, (record.ticker_symbol, name)
    # SKL is listed on the page as SKL.O0000 - matched through the share-class rule.
    assert (
        by_ticker["SKL"].isin is None and by_ticker["SKL"].website == "https://flametreebrands.com/"
    )
    # ARM and KPLC are on the page but not in the 12-instrument fixture.
    assert {listing.symbol for listing, _ in report.unmatched_listings} == {"ARM", "KPLC", "COOP"}


def test_builder_uses_profile_country_website_and_aliases(fixture_source) -> None:
    profiles = {
        "SCOM": {"country": "Kenya", "website": "https://www.safaricom.co.ke"},
        "KCB": {"country": "Republic of Kenya"},
    }
    report = build_universe(_inputs(fixture_source, {}, profiles=profiles), CONFIG)
    by_ticker = {r.ticker_symbol: r for r in report.records}
    scom = by_ticker["SCOM"]
    assert (
        scom.home_country == "KE"
        and scom.field_sources["home_country"]["source"] == "stockanalysis_profile"
    )
    assert scom.website == "https://www.safaricom.co.ke"
    assert by_ticker["KCB"].confidence == 0.6  # legal name from the scraper without the page
    absa = by_ticker["ABSA"]
    assert [h["ticker"] for h in absa.name_history] == ["BBK"]
    assert absa.name_history[0]["reason"] == "rebrand"
    assert [h["ticker"] for h in by_ticker["NCBA"].name_history] == ["NIC"]


def test_builder_statuses_from_the_fixture_history(fixture_source) -> None:
    listings = dedupe_listings(parse_listed_companies(FIXTURE_HTML.read_text()))
    report = build_universe(_inputs(fixture_source, listings), CONFIG)
    by_ticker = {r.ticker_symbol: r for r in report.records}
    assert by_ticker["ACCS"].listing_status == "delisted"
    assert by_ticker["ACCS"].delisted_on == date(2012, 12, 31)
    keno = by_ticker["KENO"]  # last traded 2019-10-11, not on the page, first page run
    assert keno.listing_status == "unknown" and "2019-10-11" in keno.status_reason
    assert by_ticker["KEGN"].listing_status == "listed"  # traded this month, not on the page
    assert report.status_changes["ACCS"] == (None, "delisted")


def test_prior_state_is_kept_and_histories_append(fixture_source) -> None:
    prior = {
        "KENO": PriorCompany(
            "listed", None, (), ({"status": "listed", "recorded": "2026-01-01"},), {}
        ),
        "KCB": PriorCompany(
            "listed",
            None,
            (),
            (),
            {"legal_name": {"source": "gleif", "confidence": 1.0, "evidence": "LEI"}},
            lei="254900TESTLEI0000000",
            legal_name="KCB Group PLC",
        ),
    }
    page_history = {"KENO": PageHistory(False, 2, 4)}
    report = build_universe(
        _inputs(fixture_source, {}, prior=prior, page_history=page_history), CONFIG
    )
    by_ticker = {r.ticker_symbol: r for r in report.records}
    keno = by_ticker["KENO"]
    assert keno.listing_status == "listed" and keno.status_reason.startswith("kept:")
    assert len(keno.status_history) == 1  # unchanged status appends nothing
    kcb = by_ticker["KCB"]
    assert kcb.legal_name == "KCB Group PLC" and kcb.lei == "254900TESTLEI0000000"
    assert kcb.field_sources["legal_name"]["source"] == "gleif"  # a better source is not out-ranked


def test_match_listings_by_alias_and_unique_name() -> None:
    from app.web.services.corporate.universe.nse_page import NseListing

    instruments = [
        {"ticker_symbol": "ABSA", "company_name": "ABSA Bank Kenya Plc"},
        {"ticker_symbol": "EQTY", "company_name": "Equity Group Holdings Plc"},
    ]
    aliases = [{"source_ticker": "BBK", "canonical_ticker": "ABSA"}]
    listings = {
        "BBK": NseListing("Barclays", "Barclays", "BBK", None, None, None),
        "EGH": NseListing(
            "Equity Group Holdings", "Equity Group Holdings", "EGH", None, None, None
        ),
        "ZZZ": NseListing("Nobody Ltd", "Nobody Ltd", "ZZZ", None, None, None),
    }
    matched, unmatched = match_listings(listings, instruments, aliases)
    assert matched["ABSA"][1].confidence == 0.95 and matched["EQTY"][1].confidence == 0.8
    assert [listing.symbol for listing, _ in unmatched] == ["ZZZ"]


# --- service + store --------------------------------------------------------------------


@pytest.fixture
def store(tmp_path: Path, fixture_settings: Settings) -> Settings:
    settings = fixture_settings.model_copy(update={"analytics_db_path": tmp_path / "corp.sqlite3"})
    upgrade_analytics_db(settings.analytics_db_path)
    return settings


def _page_client() -> PoliteClient:
    html = FIXTURE_HTML.read_bytes()

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/listed-companies/"
        return httpx.Response(200, content=html, headers={"Content-Type": "text/html"})

    return PoliteClient(
        transport=httpx.MockTransport(handler), respect_robots=False, sleep=lambda s: None
    )


def test_migration_creates_the_two_tables(store: Settings) -> None:
    engine = build_analytics_engine(store.analytics_db_path)
    try:
        names = set(inspect(engine).get_table_names())
    finally:
        engine.dispose()
    assert {"corporate_companies", "corporate_sightings"} <= names


def test_refresh_is_idempotent_and_records_sightings(store: Settings, fixture_source) -> None:
    t0 = datetime(2026, 9, 19, 6, 0, tzinfo=UTC)
    first = refresh_universe(store, fixture_source, client=_page_client(), now=t0)
    assert first.companies == 10 and first.created == 10 and first.updated == 0
    assert first.page.startswith("fetched 12 blocks") and first.sightings_recorded > 10
    assert first.status_changes["KCB"] == (None, "listed")
    assert any(line.startswith("ARM") for line in first.unmatched_listings)
    assert any("no classifications" in w for w in first.warnings)

    second = refresh_universe(
        store, fixture_source, client=_page_client(), now=t0 + timedelta(days=1)
    )
    assert (second.created, second.updated, second.unchanged) == (0, 0, 10)
    assert second.status_changes == {}

    with analytics_session(store) as session:
        assert len(source_runs(session, "nse_listed_page")) == 2
        kcb = load_company(session, "KCB")
        assert kcb is not None and kcb.isin == "KE0000000315"
        assert kcb.listing_status == "listed"
        assert kcb.first_seen_at == t0 and kcb.last_seen_at == t0 + timedelta(days=1)
        assert kcb.updated_at == t0  # nothing changed on the second run
        assert len(kcb.status_history) == 1
        kinds = {s.source for s in sightings_for(session, "KCB")}
        assert kinds == {"scraper_instruments", "nse_listed_page"}
        absa = load_company(session, "ABSA")
        assert absa is not None and absa.name_history[0]["ticker"] == "BBK"
        assert len(load_companies(session, status="delisted")) == 1  # ACCS


def test_page_absence_accumulates_runs_and_no_network_uses_stored_sightings(
    store: Settings, fixture_source
) -> None:
    t0 = datetime(2026, 9, 19, 6, 0, tzinfo=UTC)
    refresh_universe(store, fixture_source, client=_page_client(), now=t0)
    # Three later page runs that no longer name KENO (or anyone else from the fixture page).
    with analytics_session(store) as session:
        for n in (1, 2, 3):
            record_sightings(
                session,
                [SightingRow("ZZZ", "nse_listed_page", {"name": "Someone Else"})],
                seen_at=t0 + timedelta(days=n),
            )
    result = refresh_universe(store, fixture_source, network=False, now=t0 + timedelta(days=4))
    assert result.page == "not fetched (--no-network)"
    with analytics_session(store) as session:
        keno = load_company(session, "KENO")
        assert keno is not None and keno.listing_status == "delisted"
        assert keno.delisted_on == date(2019, 10, 11)
        assert "absent from the NSE page for at least 3 runs" in (keno.status_reason or "")
        kcb = load_company(session, "KCB")
        # KCB traded this month, so three page absences do not delist it.
        assert kcb is not None and kcb.listing_status == "listed"


def test_page_fetch_failure_is_a_warning_not_a_failure(store: Settings, fixture_source) -> None:
    client = PoliteClient(
        transport=httpx.MockTransport(lambda r: httpx.Response(503)),
        respect_robots=False,
        sleep=lambda s: None,
        retries=0,
    )
    result = refresh_universe(store, fixture_source, client=client)
    assert result.companies == 10 and result.page.startswith("http_error")
    assert any("listed-companies page" in w for w in result.warnings)


def test_cli_universe_build_show_and_diff(store: Settings, monkeypatch: pytest.MonkeyPatch) -> None:
    from typer.testing import CliRunner

    import app.cli.analytics as analytics_cli
    from app.cli.main import app
    from app.web.config import get_settings

    get_settings.cache_clear()
    monkeypatch.setattr(analytics_cli, "get_settings", lambda: store)
    runner = CliRunner()
    built = runner.invoke(app, ["corporate", "universe", "build", "--no-network"])
    assert built.exit_code == 0, built.output
    assert "10 companies" in built.output
    shown = runner.invoke(app, ["corporate", "universe", "show", "KCB"])
    assert (
        shown.exit_code == 0 and "KCB Group Plc" in shown.output and "field sources" in shown.output
    )
    diff = runner.invoke(app, ["corporate", "universe", "diff"])
    assert diff.exit_code == 0 and "status change" in diff.output
    listed = runner.invoke(app, ["corporate", "universe", "show"])
    assert listed.exit_code == 0 and "corporate universe" in listed.output


# --- real data --------------------------------------------------------------------------


@pytest.mark.realdata
def test_live_universe_covers_every_listed_company(live_source, tmp_path: Path) -> None:
    settings = Settings(
        ANALYTICS_DB_PATH=str(tmp_path / "live.sqlite3"),
        NSE_SCRAPER_DB_PATH=str(live_source.database_path),
    )
    upgrade_analytics_db(settings.analytics_db_path)
    result = refresh_universe(settings, live_source, client=_page_client())
    assert result.companies >= 79
    with analytics_session(settings) as session:
        kcb = load_company(session, "KCB")
        absa = load_company(session, "ABSA")
        assert kcb is not None and kcb.isin == "KE0000000315"
        assert absa is not None and "BBK" in {h["ticker"] for h in absa.name_history}
        assert len(load_companies(session, status="delisted")) >= 10  # the 2012 archive names
        for row in load_companies(session):
            assert row.field_sources["listing_status"]["evidence"]
            assert row.home_country and len(row.home_country) == 2
