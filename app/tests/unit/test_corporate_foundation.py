"""The corporate layer's foundation: settings, its separately hashed config, country
normalisation, the polite HTTP client (no network - ``httpx.MockTransport``) and the
capability detector.

codegraph explore "CorporateConfig PoliteClient to_iso2 detect_capabilities"
"""

from __future__ import annotations

import json
import logging
from datetime import UTC, datetime
from pathlib import Path

import httpx
import pytest
from pydantic import ValidationError

from app.web.config import Settings
from app.web.db.analytics import analytics_session
from app.web.services.analytics.config import DEFAULT_CONFIG, register_calc_version
from app.web.services.analytics.store import upgrade_analytics_db
from app.web.services.corporate.config import (
    CALC_VERSION_NAME,
    DEFAULT_CORPORATE_CONFIG,
    CorporateConfig,
    register_corporate_version,
)
from app.web.services.corporate.countries import (
    HOME_COUNTRY,
    classify_segment_label,
    jurisdiction_from_name,
    region_for,
    to_iso2,
)
from app.web.services.corporate.extract.capabilities import Capabilities, detect_capabilities
from app.web.services.corporate.http import (
    FetchResult,
    PoliteClient,
    polite_client_from_settings,
    redacted_url,
)

pytestmark = pytest.mark.unit


# --- settings -----------------------------------------------------------------------


def test_corporate_settings_have_aliases_and_safe_defaults(tmp_path: Path) -> None:
    s = Settings(
        CORPORATE_DOCUMENTS_DIR=str(tmp_path / "docs"),
        CORPORATE_CACHE_DIR=str(tmp_path / "cache"),
        CORPORATE_HTTP_DELAY_SECONDS="5",
        CORPORATE_MAX_REQUESTS_PER_RUN="50",
    )
    assert s.corporate_documents_dir == tmp_path / "docs"
    assert s.corporate_cache_dir == tmp_path / "cache"
    assert s.corporate_http_delay_seconds == 5.0
    assert s.corporate_max_requests_per_run == 50
    assert s.corporate_ocr_enabled is False
    assert s.corporate_llm_cleanup_enabled is False
    assert s.corporate_gleif_base_url.startswith("https://api.gleif.org/")
    assert s.corporate_worldbank_base_url.startswith("https://api.worldbank.org/")


def test_llm_cleanup_is_forced_off_without_the_ai_layer() -> None:
    off = Settings(CORPORATE_LLM_CLEANUP_ENABLED="true")
    assert off.corporate_llm_cleanup_enabled is False
    still_off = Settings(CORPORATE_LLM_CLEANUP_ENABLED="true", AI_NARRATIVES_ENABLED="true")
    assert still_off.corporate_llm_cleanup_enabled is False
    on = Settings(
        CORPORATE_LLM_CLEANUP_ENABLED="true",
        AI_NARRATIVES_ENABLED="true",
        ANTHROPIC_API_KEY="placeholder-not-a-real-key",
    )
    assert on.corporate_llm_cleanup_enabled is True


def test_delay_below_half_a_second_is_rejected() -> None:
    with pytest.raises(ValueError):
        Settings(CORPORATE_HTTP_DELAY_SECONDS="0.1")


# --- config ---------------------------------------------------------------------------


def test_corporate_config_hash_is_stable_and_separate_from_analytics() -> None:
    assert CorporateConfig().config_hash() == DEFAULT_CORPORATE_CONFIG.config_hash()
    changed = CorporateConfig(fuzzy_accept=0.95)
    assert changed.config_hash() != DEFAULT_CORPORATE_CONFIG.config_hash()
    assert DEFAULT_CORPORATE_CONFIG.config_hash() != DEFAULT_CONFIG.config_hash()
    keys = list(json.loads(DEFAULT_CORPORATE_CONFIG.canonical_json()))
    assert keys == sorted(keys) and "version" in keys
    with pytest.raises(ValidationError):
        DEFAULT_CORPORATE_CONFIG.fuzzy_accept = 0.5  # type: ignore[misc]


def test_corporate_version_registers_under_its_own_name(tmp_path: Path) -> None:
    s = Settings(ANALYTICS_DB_PATH=str(tmp_path / "a.sqlite3"))
    upgrade_analytics_db(s.analytics_db_path)
    with analytics_session(s) as session:
        analytics = register_calc_version(session, DEFAULT_CONFIG)
        first = register_corporate_version(session, DEFAULT_CORPORATE_CONFIG)
        again = register_corporate_version(session, CorporateConfig())
        other = register_corporate_version(session, CorporateConfig(segment_sum_tolerance=0.02))
        assert first.id == again.id != other.id
        assert first.name == CALC_VERSION_NAME and analytics.name != CALC_VERSION_NAME
        assert first.config_json["fuzzy_accept"] == 0.92


# --- countries ------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("label", "code"),
    [
        ("Kenya", "KE"),
        ("KE", "KE"),
        ("ke", "KE"),
        ("Republic of Uganda", "UG"),
        ("Tanzania", "TZ"),
        ("United Republic of Tanzania", "TZ"),
        ("DRC", "CD"),
        ("DR Congo", "CD"),
        ("Democratic Republic of Congo", "CD"),
        ("Democratic Republic of the Congo", "CD"),
        ("Congo (Kinshasa)", "CD"),
        ("South Sudan", "SS"),
        ("Sudan", "SD"),
        ("Ethiopia", "ET"),
        ("Mauritius", "MU"),
        ("UK", "GB"),
        ("United Kingdom", "GB"),
        ("Côte d'Ivoire", None),
        ("Rest of East Africa", None),
        ("", None),
        (None, None),
    ],
)
def test_to_iso2_normalises_report_spellings_and_never_guesses(
    label: str | None, code: str | None
) -> None:
    assert to_iso2(label) == code


def test_region_labels_are_regional_only_and_know_whether_home_is_inside() -> None:
    rest = classify_segment_label("Rest of East Africa")
    assert rest.kind == "region" and rest.disclosure == "regional_only"
    assert rest.key == "rest_of_east_africa" and rest.home_included is False
    other = classify_segment_label("Other")
    assert other.kind == "region" and other.home_included is True
    assert region_for("International Business") is not None
    kenya = classify_segment_label("Kenya")
    assert kenya.kind == "country" and kenya.disclosure == "disclosed"
    assert kenya.home_included is True and HOME_COUNTRY == "KE"
    unknown = classify_segment_label("Treasury & Capital Markets")
    assert unknown.kind == "unknown" and unknown.disclosure == "not_disclosed"
    assert unknown.key == "treasury_and_capital_markets"


@pytest.mark.parametrize(
    ("name", "code"),
    [
        ("KCB Bank Tanzania Limited", "TZ"),
        ("Equity Bank (Uganda) Ltd", "UG"),
        ("KCB Bank South Sudan Limited", "SS"),
        ("National Bank of Kenya", "KE"),
        ("Safaricom Telecommunications Ethiopia PLC", "ET"),
        ("Jubilee Holdings Limited", None),
        ("Trust Merchant Bank SA", None),
    ],
)
def test_jurisdiction_is_read_from_the_name_or_left_unknown(name: str, code: str | None) -> None:
    assert jurisdiction_from_name(name) == code


# --- polite client --------------------------------------------------------------------


class _Clock:
    def __init__(self) -> None:
        self.now = 1000.0
        self.slept: list[float] = []

    def __call__(self) -> float:
        return self.now

    def sleep(self, seconds: float) -> None:
        self.slept.append(seconds)
        self.now += seconds


def _client(handler, *, delay: float = 3.0, **kw) -> tuple[PoliteClient, _Clock]:
    clock = _Clock()
    client = PoliteClient(
        delay_seconds=delay,
        transport=httpx.MockTransport(handler),
        sleep=clock.sleep,
        clock=clock,
        now=lambda: datetime(2026, 9, 19, tzinfo=UTC),
        respect_robots=False,
        **kw,
    )
    return client, clock


def test_requests_to_one_host_are_spaced_and_carry_the_user_agent() -> None:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, content=b"x")

    client, clock = _client(handler, user_agent="nse-be test", contact_email="ops@example.org")
    a = client.get("https://a.example/one")
    b = client.get("https://a.example/two")
    c = client.get("https://b.example/three")
    assert a.ok and b.ok and c.ok
    assert clock.slept == [3.0]  # only the second request to a.example waited
    assert all(r.headers["User-Agent"] == "nse-be test; contact: ops@example.org" for r in seen)
    assert client.requests_made == 3


def test_backoff_on_503_honours_retry_after_then_succeeds() -> None:
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        if calls["n"] == 1:
            return httpx.Response(503, headers={"Retry-After": "7"})
        if calls["n"] == 2:
            return httpx.Response(429)
        return httpx.Response(200, content=b"done")

    client, clock = _client(handler, delay=1.0)
    result = client.get("https://a.example/doc.pdf")
    assert result.ok and result.content == b"done" and result.attempts == 3
    assert 7.0 in clock.slept  # Retry-After
    assert 8.0 in clock.slept  # second retry uses the backoff table (attempt 2 -> 8 s)


def test_persistent_5xx_is_an_http_error_outcome_not_an_exception() -> None:
    client, _ = _client(lambda r: httpx.Response(502), delay=1.0, retries=2)
    result = client.get("https://a.example/x")
    assert result.status == "http_error" and result.status_code == 502 and result.attempts == 3
    assert "502" in (result.reason or "")


def test_transport_errors_are_retried_then_reported() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("boom", request=request)

    client, _ = _client(handler, delay=1.0, retries=1)
    result = client.get("https://a.example/x")
    assert result.status == "error" and "ConnectError" in (result.reason or "")


def test_byte_cap_stops_the_download_by_header_and_by_body() -> None:
    def by_header(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, headers={"Content-Length": "999"}, content=b"a" * 999)

    def by_body(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=b"a" * 999)

    client, _ = _client(by_header, max_bytes=100)
    assert client.get("https://a.example/big").status == "too_large"
    client, _ = _client(by_body, max_bytes=100)
    result = client.get("https://a.example/big")
    assert result.status == "too_large" and result.content == b""
    small = _client(by_body, max_bytes=100)[0].get("https://a.example/big", max_bytes=2000)
    assert small.ok and len(small.content) == 999


def test_conditional_get_returns_not_modified() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.headers.get("If-None-Match") == '"v1"':
            return httpx.Response(304)
        return httpx.Response(200, content=b"new", headers={"ETag": '"v1"'})

    client, _ = _client(handler)
    first = client.get("https://a.example/r.pdf")
    assert first.ok and first.etag == '"v1"'
    second = client.get("https://a.example/r.pdf", etag=first.etag)
    assert second.status == "not_modified" and second.content == b""


def test_head_reads_validators_without_a_body() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.method == "HEAD"
        return httpx.Response(200, headers={"Content-Length": "123", "Last-Modified": "x"})

    client, _ = _client(handler)
    result = client.head("https://a.example/r.pdf")
    assert result.ok and result.content_length == 123 and result.last_modified == "x"


def test_request_budget_ends_cleanly() -> None:
    client, _ = _client(lambda r: httpx.Response(200, content=b"x"), max_requests=2)
    assert client.get("https://a.example/1").ok
    assert client.get("https://a.example/2").ok
    third = client.get("https://a.example/3")
    assert third.status == "budget_exhausted" and client.budget_remaining == 0
    assert "budget" in (third.reason or "")


def test_robots_disallow_is_respected_and_missing_robots_allows() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/robots.txt":
            if request.url.host == "strict.example":
                return httpx.Response(200, text="User-agent: *\nDisallow: /private/\n")
            return httpx.Response(404)
        return httpx.Response(200, content=b"ok")

    clock = _Clock()
    client = PoliteClient(
        delay_seconds=1.0, transport=httpx.MockTransport(handler), sleep=clock.sleep, clock=clock
    )
    assert client.get("https://strict.example/private/x.pdf").status == "disallowed"
    assert client.get("https://strict.example/public/x.pdf").ok
    assert client.get("https://open.example/private/x.pdf").ok


def test_logs_never_carry_a_signed_query_string(caplog: pytest.LogCaptureFixture) -> None:
    logging.getLogger("httpx").setLevel(logging.INFO)  # as a fresh process would have it
    client, _ = _client(lambda r: httpx.Response(200, content=b"x"))
    url = "https://kcb.example/download/abc?signature=SECRETSIG123&expires=1"
    with caplog.at_level(logging.INFO):
        assert client.get(url).ok
    assert "SECRETSIG123" not in caplog.text and "signature=" not in caplog.text
    assert logging.getLogger("httpx").level == logging.WARNING  # the library's own URL log is off
    assert redacted_url(url) == "https://kcb.example/download/abc"


def test_client_is_built_from_settings() -> None:
    s = Settings(CORPORATE_HTTP_DELAY_SECONDS="4", CORPORATE_MAX_REQUESTS_PER_RUN="12")
    transport = httpx.MockTransport(lambda r: httpx.Response(200))
    client = polite_client_from_settings(s, transport=transport)
    assert client.delay_seconds == 4.0 and client.max_requests == 12
    assert client.user_agent == s.corporate_user_agent
    client.close()


def test_fetch_result_json_helper() -> None:
    result = FetchResult("ok", "u", content=b'{"a": 1}')
    assert result.json() == {"a": 1}


# --- capabilities ---------------------------------------------------------------------


def test_capabilities_report_what_is_missing_and_why() -> None:
    caps = detect_capabilities()
    assert caps.pymupdf and caps.pdfplumber  # runtime dependencies of this repo
    stages = caps.stages()
    assert stages["pymupdf_text"] == (True, "")
    assert stages["ocr"] == (False, "CORPORATE_OCR_ENABLED is false")
    assert stages["llm_cleanup"][0] is False
    if not caps.ghostscript:
        assert "ghostscript" in stages["camelot"][1]


def test_ocr_needs_the_flag_and_every_binary() -> None:
    base: dict[str, bool] = {
        "pymupdf": True,
        "pdfplumber": True,
        "camelot": False,
        "pytesseract": True,
        "ghostscript": False,
        "tesseract": True,
        "poppler": True,
        "ocrmypdf": False,
        "llm_cleanup": False,
    }
    assert Capabilities(ocr_enabled=True, **base).ocr is True
    assert Capabilities(ocr_enabled=False, **base).ocr is False
    missing = Capabilities(ocr_enabled=True, **{**base, "poppler": False})
    assert missing.ocr is False and "poppler" in missing.stages()["ocr"][1]
