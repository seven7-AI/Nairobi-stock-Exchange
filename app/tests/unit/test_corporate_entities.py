"""Legal entities: name normalisation, the resolver ladder (must-merge / must-not-merge),
the bitemporal writer on a synthetic restatement chain, the GLEIF client on recorded real
responses, and the sync that enriches the universe.

codegraph explore "resolve append_and_close GleifClient sync_gleif"
"""

from __future__ import annotations

import json
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

import httpx
import pytest
from sqlalchemy import select

from app.web.config import Settings
from app.web.db.analytics import analytics_session
from app.web.db.analytics.models import CorporateEntity, CorporateRelationship
from app.web.db.analytics.services.corporate_companies import load_company
from app.web.db.analytics.services.corporate_entities import (
    create_entity,
    entities_for_group,
    find_listed,
    relationship_versions,
    relationships_current,
)
from app.web.services.analytics.store import upgrade_analytics_db
from app.web.services.corporate.bitemporal import (
    VersionedWrite,
    append_and_close,
    as_known_on,
    as_of,
    close_valid_time,
    content_hash,
    current,
    version_key,
)
from app.web.services.corporate.config import DEFAULT_CORPORATE_CONFIG
from app.web.services.corporate.entities.gleif import GleifClient, LeiRecord
from app.web.services.corporate.entities.normalise import (
    canonical_key,
    distinguishing_difference,
    normalise,
    token_set_ratio,
)
from app.web.services.corporate.entities.resolver import EntityMention, resolve
from app.web.services.corporate.entities.service import (
    ensure_listed_entities,
    match_record,
    sync_gleif,
)
from app.web.services.corporate.http import PoliteClient
from app.web.services.corporate.universe.service import refresh_universe

pytestmark = pytest.mark.unit

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "corporate"
GLEIF = FIXTURES / "gleif"
CONFIG = DEFAULT_CORPORATE_CONFIG
NOW = datetime(2026, 9, 19, 8, 0, tzinfo=UTC)


# --- normalisation ------------------------------------------------------------------


@pytest.mark.parametrize(
    ("raw", "norm"),
    [
        ("KCB Bank Kenya Limited", "kcb bank kenya"),
        ("KCB Bank Kenya Ltd.", "kcb bank kenya"),
        ("EAST AFRICAN BREWERIES PLC", "east african breweries"),
        ("I&M Holdings Ltd", "i and m holdings"),
        ("Equity Bank (Uganda) Ltd", "equity bank uganda"),
        ("Trust Merchant Bank S.A.", "trust merchant bank"),
        ("Safaricom Public Limited Company", "safaricom"),
        ("Jubilee Insurance Company of Kenya Limited", "jubilee insurance company of kenya"),
    ],
)
def test_normalise_strips_one_legal_suffix_and_keeps_country_words(raw: str, norm: str) -> None:
    assert normalise(raw) == norm


def test_canonical_key_and_similarity() -> None:
    assert canonical_key("KCB Bank Kenya Ltd", "ke") == "kcb bank kenya|KE"
    assert token_set_ratio("KCB Bank Kenya Limited", "KCB Bank Kenya Ltd") == 1.0
    assert token_set_ratio("Ltd", "") == 0.0
    assert distinguishing_difference("Jubilee Insurance Company", "Jubilee Health Insurance") == {
        "health"
    }
    assert distinguishing_difference("KCB Bank Kenya", "KCB Bank Tanzania") == {"kenya", "tanzania"}


# --- resolver ---------------------------------------------------------------------------


@pytest.fixture
def store(tmp_path: Path, fixture_settings: Settings) -> Settings:
    settings = fixture_settings.model_copy(
        update={
            "analytics_db_path": tmp_path / "corp.sqlite3",
            "corporate_cache_dir": tmp_path / "cache",
        }
    )
    upgrade_analytics_db(settings.analytics_db_path)
    return settings


def _mention(name: str, juris: str | None = None, **kw: object) -> EntityMention:
    return EntityMention(name=name, jurisdiction=juris, group_ticker="KCB", **kw)  # type: ignore[arg-type]


def test_ladder_creates_then_matches_exact_name_and_never_merges_sisters(store: Settings) -> None:
    with analytics_session(store) as session:
        first = resolve(session, _mention("KCB Bank Kenya Limited", "KE"), CONFIG, now=NOW)
        assert first.created and first.method == "new" and first.confidence == 0.85
        again = resolve(session, _mention("KCB Bank Kenya Ltd", "KE"), CONFIG, now=NOW)
        assert again.entity_id == first.entity_id and again.method == "legal_name_exact"
        tanzania = resolve(session, _mention("KCB Bank Tanzania Limited"), CONFIG, now=NOW)
        assert tanzania.created and tanzania.jurisdiction == "TZ"  # read from the name
        assert tanzania.entity_id != first.entity_id
        # Same jurisdiction, distinguishing token differs -> not merged.
        group = resolve(session, _mention("KCB Group PLC", "KE"), CONFIG, now=NOW)
        assert group.created and group.entity_id != first.entity_id
        rows = session.execute(select(CorporateEntity)).scalars().all()
        assert {r.resolution_method for r in rows} == {"new"}
        assert all(r.confidence for r in rows)


@pytest.mark.parametrize(
    ("a", "b"),
    [
        ("KCB Bank Kenya Ltd", "KCB Bank Tanzania Ltd"),
        ("Equity Bank (Uganda) Ltd", "Equity Bank (Rwanda) PLC"),
        ("Jubilee Insurance Company of Kenya Ltd", "Jubilee Health Insurance Ltd"),
        ("Safaricom PLC", "Safaricom Telecommunications Ethiopia PLC"),
        ("NCBA Bank Kenya PLC", "NCBA Bank Uganda Ltd"),
    ],
)
def test_must_not_merge(store: Settings, a: str, b: str) -> None:
    with analytics_session(store) as session:
        one = resolve(session, _mention(a, "KE"), CONFIG, now=NOW)
        two = resolve(session, _mention(b, "KE"), CONFIG, now=NOW)
        assert one.entity_id != two.entity_id
        assert not two.queued or two.method == "provisional"


def test_fuzzy_matches_only_within_jurisdiction_and_group(store: Settings) -> None:
    with analytics_session(store) as session:
        base = resolve(session, _mention("National Bank of Kenya Limited", "KE"), CONFIG, now=NOW)
        reordered = resolve(session, _mention("Bank of Kenya, National Ltd", "KE"), CONFIG, now=NOW)
        assert reordered.entity_id == base.entity_id and reordered.method == "fuzzy"
        assert 0.8 < reordered.confidence < 1.0
        # A mangled suffix scores below the fence: provisional with the candidate recorded.
        typo = resolve(session, _mention("National Bank of Kenya Limitd", "KE"), CONFIG, now=NOW)
        assert typo.method == "provisional" and typo.candidates[0][0] == base.entity_id
        other_group = resolve(
            session,
            EntityMention("Bank of Kenya, National Ltd", "KE", group_ticker="EQTY"),
            CONFIG,
            now=NOW,
        )
        assert other_group.entity_id != base.entity_id  # fuzzy never crosses a group
        other_juris = resolve(
            session, _mention("Bank of Kenya, National Ltd", "UG"), CONFIG, now=NOW
        )
        assert other_juris.entity_id != base.entity_id


def test_near_miss_is_provisional_and_queued(store: Settings) -> None:
    with analytics_session(store) as session:
        base = resolve(session, _mention("Kenya Commercial Bank Rwanda Ltd", "RW"), CONFIG, now=NOW)
        near = resolve(session, _mention("Kenya Commercial Bank Rwanda SA", "RW"), CONFIG, now=NOW)
        assert near.entity_id == base.entity_id  # suffix only: exact after normalisation
        close = resolve(
            session, _mention("Kenya Commercial Bank of Rwanda Ltd", "RW"), CONFIG, now=NOW
        )
        assert close.method in {"fuzzy", "provisional"}
        if close.method == "provisional":
            assert close.queued and close.candidates and close.candidates[0][0] == base.entity_id
            row = session.get(CorporateEntity, close.entity_id)
            assert row is not None and row.evidence["reason"].startswith("near miss")


def test_no_jurisdiction_is_zz_and_queued_never_kenya(store: Settings) -> None:
    with analytics_session(store) as session:
        result = resolve(session, _mention("Trust Merchant Bank SA"), CONFIG, now=NOW)
        assert result.queued and result.jurisdiction == "ZZ" and result.method == "provisional"
        row = session.get(CorporateEntity, result.entity_id)
        assert row is not None and row.jurisdiction == "ZZ" and row.confidence == 0.5
        again = resolve(session, _mention("Trust Merchant Bank SA"), CONFIG, now=NOW)
        assert again.entity_id == result.entity_id and not again.created


def test_lei_beats_name_and_registration_beats_exact_name(store: Settings) -> None:
    with analytics_session(store) as session:
        row = create_entity(
            session,
            canonical_key="safaricom|KE",
            legal_name="Safaricom PLC",
            jurisdiction="KE",
            entity_type="listed",
            resolution_method="curated",
            confidence=1.0,
            evidence={},
            lei="984500A80B648A7B9717",
            registration_number="C.8/2002",
            group_ticker="SCOM",
            now=NOW,
        )
        by_lei = resolve(
            session,
            EntityMention("Some Other Name", "UG", lei="984500a80b648a7b9717"),
            CONFIG,
            now=NOW,
        )
        assert by_lei.entity_id == row.id and by_lei.method == "lei" and by_lei.confidence == 1.0
        by_reg = resolve(
            session,
            EntityMention("Safaricom Limited", "KE", registration_number="C.8/2002"),
            CONFIG,
            now=NOW,
        )
        assert by_reg.entity_id == row.id and by_reg.method == "registration"
        by_exchange = resolve(
            session, EntityMention("X", "KE", exchange_id=("NSE", "SCOM")), CONFIG, now=NOW
        )
        assert by_exchange.created  # no exchange id stored yet -> new entity, not a guess


# --- bitemporal ---------------------------------------------------------------------


def _rel_values(
    parent: int, child: int, pct: float | None, effective_from: date, **kw: object
) -> dict:
    values: dict = {
        "parent_entity_id": parent,
        "child_entity_id": child,
        "relationship_type": "subsidiary",
        "ownership_pct_value": pct,
        "ownership_pct_status": "known" if pct is not None else "missing",
        "ownership_pct_reason": None if pct is not None else "not stated",
        "ownership_basis": "direct",
        "principal_activity": "Banking",
        "country": "TZ",
        "period_end": date(effective_from.year, 12, 31),
        "effective_from": effective_from,
        "effective_to": None,
        "source_kind": "document",
        "source_id": 1,
        "confidence": 0.9,
        "provenance": {"page": 187},
    }
    values.update(kw)
    return values


def _write(values: dict) -> VersionedWrite:
    key = version_key(
        values["parent_entity_id"], values["child_entity_id"], values["relationship_type"]
    )
    hashed = {
        k: values[k]
        for k in (
            "ownership_pct_value",
            "ownership_pct_status",
            "ownership_basis",
            "principal_activity",
            "country",
            "effective_from",
            "effective_to",
        )
    }
    return VersionedWrite(key, content_hash(hashed), values)


def test_append_and_close_restatement_chain_is_queryable_both_ways(store: Settings) -> None:
    t1 = NOW
    t2 = NOW + timedelta(days=30)
    t3 = NOW + timedelta(days=60)
    with analytics_session(store) as session:
        parent = create_entity(
            session,
            canonical_key="kcb group|KE",
            legal_name="KCB Group PLC",
            jurisdiction="KE",
            entity_type="listed",
            resolution_method="curated",
            confidence=1.0,
            evidence={},
            now=NOW,
        )
        child = create_entity(
            session,
            canonical_key="kcb bank tanzania|TZ",
            legal_name="KCB Bank Tanzania Ltd",
            jurisdiction="TZ",
            entity_type="subsidiary",
            resolution_method="new",
            confidence=0.85,
            evidence={},
            now=NOW,
        )
        first_values = _rel_values(parent.id, child.id, 100.0, date(2016, 1, 1))
        outcome, v1 = append_and_close(session, CorporateRelationship, _write(first_values), now=t1)
        assert outcome == "inserted"
        # Same assertion again from the same document: no-op.
        outcome, same = append_and_close(
            session, CorporateRelationship, _write(first_values), now=t2
        )
        assert outcome == "noop" and same.id == v1.id
        # Same value from a later document: corroborated, new current version.
        corroborate = _rel_values(parent.id, child.id, 100.0, date(2016, 1, 1), source_id=2)
        outcome, v2 = append_and_close(session, CorporateRelationship, _write(corroborate), now=t2)
        assert outcome == "superseded" and v2.id != v1.id
        # A restated percentage from a third document.
        restated = _rel_values(parent.id, child.id, 99.9, date(2016, 1, 1), source_id=3)
        outcome, v3 = append_and_close(session, CorporateRelationship, _write(restated), now=t3)
        assert outcome == "superseded"

        versions = relationship_versions(session, v1.version_key)
        assert [v.id for v in versions] == [v1.id, v2.id, v3.id]
        assert versions[0].supersession_reason == "corroborated"
        assert versions[0].superseded_by_id == v2.id and versions[0].superseded_at == t2
        assert versions[1].supersession_reason == "restated" and versions[1].superseded_at == t3
        assert versions[2].superseded_at is None
        # Old rows keep their values: only transaction time was closed.
        assert (
            versions[0].ownership_pct_value == 100.0 and versions[0].content_hash == v1.content_hash
        )
        assert versions[1].content_hash == v1.content_hash  # same content, different source

        # What did we believe on t2 + 1 day? v2 (100 %). Today? v3 (99.9 %).
        believed = (
            session.execute(
                as_known_on(
                    select(CorporateRelationship).where(
                        CorporateRelationship.version_key == v1.version_key
                    ),
                    CorporateRelationship,
                    t2 + timedelta(days=1),
                )
            )
            .scalars()
            .all()
        )
        assert [r.id for r in believed] == [v2.id]
        now_rows = relationships_current(session, parent.id)
        assert [r.id for r in now_rows] == [v3.id] and now_rows[0].ownership_pct_value == 99.9
        # Valid time: nothing held before 2016.
        assert relationships_current(session, parent.id, on=date(2015, 12, 31)) == []
        assert [r.id for r in relationships_current(session, parent.id, on=date(2018, 12, 31))] == [
            v3.id
        ]


def test_close_valid_time_is_a_new_version_not_an_update(store: Settings) -> None:
    with analytics_session(store) as session:
        parent = create_entity(
            session,
            canonical_key="p|KE",
            legal_name="P",
            jurisdiction="KE",
            entity_type="listed",
            resolution_method="curated",
            confidence=1.0,
            evidence={},
            now=NOW,
        )
        child = create_entity(
            session,
            canonical_key="c|UG",
            legal_name="C",
            jurisdiction="UG",
            entity_type="subsidiary",
            resolution_method="new",
            confidence=0.85,
            evidence={},
            now=NOW,
        )
        _, v1 = append_and_close(
            session,
            CorporateRelationship,
            _write(_rel_values(parent.id, child.id, 60.0, date(2010, 1, 1))),
            now=NOW,
        )
        v2 = close_valid_time(
            session,
            CorporateRelationship,
            v1,
            effective_to=date(2021, 6, 30),
            now=NOW + timedelta(days=1),
            source_kind="event",
            source_id=None,
            confidence=0.8,
            provenance={"event": "disposal"},
        )
        assert v2.id != v1.id and v2.effective_to == date(2021, 6, 30)
        session.refresh(v1)
        assert v1.effective_to is None and v1.supersession_reason == "closed"
        assert v1.superseded_by_id == v2.id
        stmt = current(
            select(CorporateRelationship).where(
                CorporateRelationship.parent_entity_id == parent.id
            ),
            CorporateRelationship,
        )
        held_2018 = (
            session.execute(as_of(stmt, CorporateRelationship, date(2018, 12, 31))).scalars().all()
        )
        held_2022 = (
            session.execute(as_of(stmt, CorporateRelationship, date(2022, 1, 1))).scalars().all()
        )
        assert [r.id for r in held_2018] == [v2.id] and held_2022 == []


def test_look_ahead_rows_added_later_do_not_change_an_earlier_belief(store: Settings) -> None:
    with analytics_session(store) as session:
        parent = create_entity(
            session,
            canonical_key="p2|KE",
            legal_name="P2",
            jurisdiction="KE",
            entity_type="listed",
            resolution_method="curated",
            confidence=1.0,
            evidence={},
            now=NOW,
        )
        child = create_entity(
            session,
            canonical_key="c2|RW",
            legal_name="C2",
            jurisdiction="RW",
            entity_type="subsidiary",
            resolution_method="new",
            confidence=0.85,
            evidence={},
            now=NOW,
        )
        _, v1 = append_and_close(
            session,
            CorporateRelationship,
            _write(_rel_values(parent.id, child.id, 50.0, date(2019, 1, 1))),
            now=NOW,
        )
        query = as_known_on(
            select(CorporateRelationship).where(
                CorporateRelationship.parent_entity_id == parent.id
            ),
            CorporateRelationship,
            NOW + timedelta(hours=1),
        )
        before = [(r.id, r.ownership_pct_value) for r in session.execute(query).scalars()]
        append_and_close(
            session,
            CorporateRelationship,
            _write(_rel_values(parent.id, child.id, 75.0, date(2019, 1, 1), source_id=9)),
            now=NOW + timedelta(days=10),
        )
        after = [(r.id, r.ownership_pct_value) for r in session.execute(query).scalars()]
        assert before == after == [(v1.id, 50.0)]


# --- GLEIF client on recorded responses ---------------------------------------------


def _gleif_transport() -> httpx.MockTransport:
    def handler(request: httpx.Request) -> httpx.Response:
        parts = urlsplit(str(request.url))
        query = parse_qs(parts.query)
        if parts.path.endswith("/lei-records/984500A80B648A7B9717"):
            return httpx.Response(200, content=(GLEIF / "lei-safaricom.json").read_bytes())
        if parts.path.endswith("/lei-records/254900R1865V3E1ESD47"):
            return httpx.Response(200, content=(GLEIF / "lei-kcb-bank-kenya.json").read_bytes())
        if parts.path.endswith("/lei-records/254900XXXXXXXXXXXXXX"):
            return httpx.Response(404, content=(GLEIF / "missing.json").read_bytes())
        if "filter[registration.lastUpdateDate]" in query:
            if (query.get("page[number]") or ["1"])[0] == "1":
                return httpx.Response(
                    200, content=(GLEIF / "delta-ke-2026-09-01.json").read_bytes()
                )
            return httpx.Response(
                200, json={"data": [], "meta": {"pagination": {"total": 18, "lastPage": 4}}}
            )
        text = (query.get("filter[fulltext]") or [""])[0].lower()
        country = (query.get("filter[entity.legalAddress.country]") or [""])[0]
        table = {
            ("kcb", "KE"): "search-kcb.json",
            ("kcb group", "KE"): "search-kcb.json",
            ("kcb bank", "TZ"): "search-kcb-tz.json",
            ("equity group holdings", "KE"): "search-equity.json",
            ("equity bank", "UG"): "search-equity-ug.json",
            ("ncba group", "KE"): "search-ncba-ke.json",
            ("east african breweries", "KE"): "search-eabl-ke.json",
        }
        name = table.get((text, country))
        if name is None:
            return httpx.Response(
                200, json={"data": [], "meta": {"pagination": {"total": 0, "lastPage": 1}}}
            )
        return httpx.Response(200, content=(GLEIF / name).read_bytes())

    return httpx.MockTransport(handler)


def _gleif(tmp_path: Path, transport: httpx.MockTransport | None = None) -> GleifClient:
    client = PoliteClient(
        transport=transport or _gleif_transport(), respect_robots=False, sleep=lambda s: None
    )
    return GleifClient(client, tmp_path / "gleif", now=lambda: NOW)


def test_by_lei_search_and_404_on_recorded_responses(tmp_path: Path) -> None:
    api = _gleif(tmp_path)
    scom = api.by_lei("984500A80B648A7B9717")
    assert scom.status == "ok" and len(scom.records) == 1
    record = scom.records[0]
    assert record.legal_name == "Safaricom PLC" and record.jurisdiction == "KE"
    assert record.registered_as == "C.8/2002" and record.registration_status == "ISSUED"
    kcb = api.search(fulltext="kcb", country="KE")
    assert [r.legal_name for r in kcb.records] == [
        "KCB Investment Bank Limited",
        "KCB Bank Kenya Limited",
    ]
    assert kcb.records[0].registration_status == "LAPSED"
    ncba = api.search(fulltext="ncba group", country="KE")
    assert {r.registration_status for r in ncba.records} == {"RETIRED", "ISSUED"}
    missing = api.by_lei("254900XXXXXXXXXXXXXX")
    assert missing.status == "not_found" and missing.records == ()
    assert api.search(fulltext="equity group holdings", country="KE").records == ()


def test_cache_hit_avoids_a_request_and_expires(tmp_path: Path) -> None:
    api = _gleif(tmp_path)
    api.by_lei("984500A80B648A7B9717")
    again = api.by_lei("984500A80B648A7B9717")
    assert again.from_cache and again.status == "cached" and api.requests_made == 1
    assert api.cache_hits == 1
    later = GleifClient(
        PoliteClient(transport=_gleif_transport(), respect_robots=False, sleep=lambda s: None),
        tmp_path / "gleif",
        now=lambda: NOW + timedelta(days=8),
    )
    assert not later.by_lei("984500A80B648A7B9717").from_cache and later.requests_made == 1


def test_updated_since_walks_the_delta_page(tmp_path: Path) -> None:
    api = _gleif(tmp_path)
    delta = api.updated_since(date(2026, 9, 1), country="KE")
    assert delta.status == "ok" and len(delta.records) == 5  # page 1 recorded; pages 2-4 empty
    assert api.requests_made == 4  # walked every page the pagination announced
    assert all(r.jurisdiction == "KE" for r in delta.records)
    assert delta.records[0].last_update and delta.records[0].last_update > "2026-09-01"


def test_errors_are_outcomes(tmp_path: Path) -> None:
    api = _gleif(tmp_path, httpx.MockTransport(lambda r: httpx.Response(503)))
    api._client.retries = 0
    response = api.search(fulltext="kcb", country="KE")
    assert response.status == "error" and "503" in (response.reason or "")


def test_lei_record_parses_the_recorded_shape() -> None:
    item = json.loads((GLEIF / "lei-kcb-bank-kenya.json").read_text())["data"]
    record = LeiRecord.from_api(item)
    assert record.lei == "254900R1865V3E1ESD47" and record.registered_as == "CPR/2015/185698"
    assert record.legal_name == "KCB Bank Kenya Limited" and record.other_names == ()


def test_match_record_exact_beats_near_and_fences_sisters() -> None:
    api_records = (
        LeiRecord("1", "KCB Investment Bank Limited", "KE", "x", "LAPSED", "ACTIVE", (), None, {}),
        LeiRecord("2", "KCB Bank Kenya Limited", "KE", "y", "ISSUED", "ACTIVE", (), None, {}),
    )
    record, how, conf = match_record("KCB Bank Kenya Ltd", api_records)
    assert record is not None and record.lei == "2" and how == "exact" and conf == 1.0
    assert match_record("KCB Group PLC", api_records)[0] is None
    retired = (
        LeiRecord("3", "NIC Bank Kenya PLC", "KE", None, "RETIRED", "INACTIVE", (), None, {}),
    )
    assert match_record("NIC Bank Kenya PLC", retired)[0] is None
    near = (
        LeiRecord(
            "4", "East African Breweries PLC", "KE", "C.5/34", "ISSUED", "ACTIVE", (), None, {}
        ),
    )
    assert match_record("East African Breweries Ltd", near)[1] == "exact"


# --- sync over the fixture universe -----------------------------------------------------


def _universe(store: Settings, fixture_source) -> None:
    html = (FIXTURES / "html" / "nse_listed_companies.html").read_bytes()
    page = PoliteClient(
        transport=httpx.MockTransport(lambda r: httpx.Response(200, content=html)),
        respect_robots=False,
        sleep=lambda s: None,
    )
    refresh_universe(store, fixture_source, client=page, now=NOW)


def test_sync_enriches_matches_and_records_misses(store: Settings, fixture_source) -> None:
    _universe(store, fixture_source)
    api = _gleif(store.corporate_cache_dir)
    result = sync_gleif(store, gleif=api, now=NOW)
    assert result.companies == 10 and result.entities_created == 10
    # None of the fixture companies has an exact GLEIF record in the recorded searches:
    # "kcb group" finds KCB Bank Kenya / KCB Investment Bank, "ncba group" finds NCBA
    # *Bank* Kenya, "equity group holdings" finds nothing.
    assert result.matched == 0 and result.unmatched == 10 and result.errors == ()
    with analytics_session(store) as session:
        scom = load_company(session, "SCOM")
        assert (
            scom is not None and scom.lei is None
        )  # "safaricom" search is not in the recorded set
        kcb = load_company(session, "KCB")
        assert kcb is not None and kcb.lei is None
        assert (
            kcb.field_sources["lei"]["source"] == "gleif"
            and kcb.field_sources["lei"]["confidence"] == 0.0
        )
        assert "no LEI record matches" in kcb.field_sources["lei"]["evidence"]
        ncba = load_company(session, "NCBA")
        assert (
            ncba is not None and ncba.lei is None
        )  # NCBA *Bank* Kenya is the subsidiary, not the group
        listed = find_listed(session, "KCB")
        assert listed is not None and listed.entity_type == "listed"
        assert listed.identifiers["gleif_checked_at"] == "2026-09-19"
        assert (
            listed.identifiers["exchange"] == {"NSE": "KCB"}
            and listed.identifiers["isin"] == "KE0000000315"
        )
        assert not [c for c in session.execute(select(CorporateEntity)).scalars() if c.lei]
    # Second run: everything cached, nothing changes.
    again = sync_gleif(store, gleif=api, now=NOW + timedelta(hours=1))
    assert again.matched == 0 and again.unmatched == 10 and again.entities_created == 0
    assert again.requests == api.requests_made and api.cache_hits > 0


def test_exact_match_writes_lei_legal_name_and_registration(
    store: Settings, fixture_source
) -> None:
    _universe(store, fixture_source)
    with analytics_session(store) as session:
        company = load_company(session, "KEGN")
        assert company is not None
        company.legal_name = (
            "East African Breweries Ltd"  # pretend: exercise the exact path on real JSON
        )
    api = _gleif(store.corporate_cache_dir)
    result = sync_gleif(store, tickers=["KEGN"], gleif=api, now=NOW)
    assert result.matched == 1
    with analytics_session(store) as session:
        company = load_company(session, "KEGN")
        assert company is not None
        assert company.lei == "984500BEE8483EAED424" and company.registration_number == "C.5/34"
        assert company.legal_name == "EAST AFRICAN BREWERIES PLC"
        assert company.field_sources["legal_name"] == {
            "source": "gleif",
            "confidence": 1.0,
            "evidence": company.field_sources["lei"]["evidence"],
        }
        entity = find_listed(session, "KEGN")
        assert entity is not None and entity.lei == "984500BEE8483EAED424"
        assert entity.resolution_method == "lei" and entity.confidence == 1.0
        assert entity.identifiers["gleif"]["registration_status"] == "ISSUED"
        # A later universe rebuild keeps the GLEIF legal name (higher-ranked source).
    _universe(store, fixture_source)
    with analytics_session(store) as session:
        company = load_company(session, "KEGN")
        assert company is not None and company.legal_name == "EAST AFRICAN BREWERIES PLC"
        assert company.lei == "984500BEE8483EAED424"


def test_ensure_listed_entities_is_idempotent(store: Settings, fixture_source) -> None:
    _universe(store, fixture_source)
    with analytics_session(store) as session:
        from app.web.db.analytics.services.corporate_companies import load_companies

        companies = load_companies(session)
        first, created = ensure_listed_entities(session, companies, now=NOW)
        second, created_again = ensure_listed_entities(session, companies, now=NOW)
        assert created == 10 and created_again == 0
        assert {t: e.id for t, e in first.items()} == {t: e.id for t, e in second.items()}
        assert len(entities_for_group(session, "KCB")) == 1


def test_cli_gleif_sync_and_entities_show(
    store: Settings, fixture_source, monkeypatch: pytest.MonkeyPatch
) -> None:
    from typer.testing import CliRunner

    import app.cli.analytics as analytics_cli
    import app.web.services.corporate.entities.service as service
    from app.cli.main import app

    _universe(store, fixture_source)
    monkeypatch.setattr(analytics_cli, "get_settings", lambda: store)
    monkeypatch.setattr(
        service,
        "polite_client_from_settings",
        lambda settings, **kw: PoliteClient(
            transport=_gleif_transport(), respect_robots=False, sleep=lambda s: None
        ),
    )
    runner = CliRunner()
    synced = runner.invoke(app, ["corporate", "gleif", "sync", "--ticker", "KCB"])
    assert synced.exit_code == 0, synced.output
    assert "1 companies" in synced.output and "no LEI 1" in synced.output
    shown = runner.invoke(app, ["corporate", "entities", "show", "KCB"])
    assert (
        shown.exit_code == 0 and "entities under KCB" in shown.output and "listed" in shown.output
    )


# --- real data ----------------------------------------------------------------------------


@pytest.mark.realdata
def test_live_gleif_cache_dir_is_used(live_source, tmp_path: Path) -> None:
    """No network: the live universe gets listed entities and the recorded GLEIF answers."""
    settings = Settings(
        ANALYTICS_DB_PATH=str(tmp_path / "live.sqlite3"),
        NSE_SCRAPER_DB_PATH=str(live_source.database_path),
        CORPORATE_CACHE_DIR=str(tmp_path / "cache"),
    )
    upgrade_analytics_db(settings.analytics_db_path)
    refresh_universe(settings, live_source, network=False, now=NOW)
    result = sync_gleif(settings, gleif=_gleif(tmp_path), now=NOW)
    assert result.companies >= 79 and result.entities_created == result.companies
    assert result.errors == ()
