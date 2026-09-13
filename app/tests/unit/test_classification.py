"""Classification: sector files (with their defects), taxonomy, builder, PIT lookup.

The sector files under NSE_DATA/ are the real ones; the builder runs on the
real-data fixture (12 instruments incl. lineage and delistings).

    codegraph explore "build_classifications read_sector_file ClassificationIndex"
"""

from __future__ import annotations

from datetime import date
from pathlib import Path

import pytest
from typer.testing import CliRunner

from app.web.config import Settings
from app.web.db.analytics import analytics_session
from app.web.db.analytics.services.classifications import (
    load_classifications,
    replace_classifications,
)
from app.web.services.analytics.classification import (
    CURATED,
    FINANCIAL_SECTORS,
    OPERATING_SECTORS,
    SECTORS,
    build_classifications,
    sector_code,
)
from app.web.services.analytics.classification.sector_files import (
    parse_sector_files,
    read_sector_file,
)
from app.web.services.analytics.classification.service import (
    NSE_DATA_DIR,
    classify_instruments,
    load_index,
)
from app.web.services.analytics.store import upgrade_analytics_db
from app.web.services.market_data.sources import NseScraperSource

pytestmark = pytest.mark.unit


# --- taxonomy ---------------------------------------------------------------------


def test_every_official_label_and_its_historical_spelling_resolve() -> None:
    assert sector_code("Banking") == "banking"
    assert sector_code("Telecommunication and Technology") == "telecommunication"
    assert sector_code("Telecommunication") == "telecommunication"
    assert sector_code("Energy & Petroleum") == "energy"
    assert sector_code("Real Estate Investment Trusts") == "reit"
    assert sector_code(" indices ") == "indices"
    assert sector_code("") is None
    assert sector_code(None) is None
    assert sector_code("Quantum Computing") is None  # unknown labels are refused, never guessed
    assert set(SECTORS) >= OPERATING_SECTORS >= FINANCIAL_SECTORS
    assert "indices" not in OPERATING_SECTORS


# --- sector files -------------------------------------------------------------------


def test_the_2023_24_file_section_header_defect_is_repaired() -> None:
    sector_file = read_sector_file(NSE_DATA_DIR / "NSE_data_stock_market_sectors_2023_2024.csv")
    by_code = {row.code: row for row in sector_file.rows}
    for code in ("KEGN", "KPLC", "KPLC-P4", "KPLC-P7", "TOTL", "UMME"):
        assert by_code[code].sector_code == "energy", code
        assert "section header" in (by_code[code].repair or "")
    # the rows after the section (Insurance...) are untouched
    assert by_code["BRIT"].sector_code == "insurance" and by_code["BRIT"].repair is None
    assert by_code["BAMB"].sector_code == "construction" and by_code["BAMB"].repair is None
    assert sector_file.skipped == ()


def test_the_2013_file_index_rows_are_indices() -> None:
    sector_file = read_sector_file(NSE_DATA_DIR / "NSE_data_stock_market_sectors_2013.csv")
    by_code = {row.code: row for row in sector_file.rows}
    assert by_code["^NASI"].sector_code == "indices"
    assert "index row" in (by_code["^NASI"].repair or "")
    assert by_code["SCOM"].sector_label == "Telecommunication and Technology"
    assert by_code["SCOM"].sector_code == "telecommunication"


def test_all_five_files_parse_with_nothing_skipped() -> None:
    files = parse_sector_files(NSE_DATA_DIR)
    assert [f.year for f in files] == [2013, 2020, 2021, 2022, 2023]
    assert all(f.skipped == () for f in files)
    assert all(len(f.rows) >= 62 for f in files)


def test_unknown_sector_rows_are_skipped_and_reported(tmp_path: Path) -> None:
    path = tmp_path / "NSE_data_stock_market_sectors_2019.csv"
    path.write_text(
        "SECTOR,CODE,NAME\nBanking,KCB,KCB Group\nSpace,MOON,Moon Ltd\n,BLANK,Blank Ltd\n"
    )
    sector_file = read_sector_file(path)
    assert [r.code for r in sector_file.rows] == ["KCB"]
    assert len(sector_file.skipped) == 2
    with pytest.raises(ValueError):
        read_sector_file(tmp_path / "other.csv")


def test_a_section_ends_at_the_next_real_sector(tmp_path: Path) -> None:
    path = tmp_path / "NSE_data_stock_market_sectors_2030.csv"
    path.write_text(
        "Sector,Stock_code,Stock_name\n"
        "Construction and Allied,BAMB,Bamburi\n"
        "Construction and Allied,Energy and Petroleum,\n"
        "Construction and Allied,KEGN,KenGen\n"
        "Insurance,BRIT,Britam\n"
        "Construction and Allied,PORT,Portland\n"
    )
    rows = {r.code: r.sector_code for r in read_sector_file(path).rows}
    assert rows == {
        "BAMB": "construction",
        "KEGN": "energy",
        "BRIT": "insurance",
        "PORT": "construction",
    }


# --- builder on the real-data fixture --------------------------------------------


@pytest.fixture(scope="module")
def report(fixture_source: NseScraperSource):
    return build_classifications(fixture_source, NSE_DATA_DIR)


def test_every_fixture_instrument_is_classified(report) -> None:
    assert report.unclassified == ()
    assert report.tickers == {
        "KCB",
        "EQTY",
        "SCOM",
        "KEGN",
        "ABSA",
        "NCBA",
        "KENO",
        "ACCS",
        "KPC",
        "SKL",
        "^NASI",
        "^N20I",
    }
    assert report.skipped_rows == ()


def test_lineage_is_resolved_to_the_canonical_ticker(report) -> None:
    absa = [r for r in report.records if r.ticker_symbol == "ABSA"]
    assert absa and absa[0].sector_code == "banking"
    assert absa[0].valid_from == date(2007, 1, 2)  # ABSA's first observation as BBK
    assert "carried back" in absa[0].evidence
    assert not any(r.ticker_symbol == "BBK" for r in report.records)
    ncba = [r for r in report.records if r.ticker_symbol == "NCBA"]
    assert ncba and ncba[0].sector_code == "banking"


def test_curated_entries_cover_the_instruments_no_file_lists(report) -> None:
    accs = [r for r in report.records if r.ticker_symbol == "ACCS"]
    assert accs and accs[0].source == "curated" and accs[0].sector_code == "telecommunication"
    assert "AccessKenya" in accs[0].evidence
    kpc = [r for r in report.records if r.ticker_symbol == "KPC"]
    assert kpc and kpc[0].sector_code == "energy"
    assert kpc[0].valid_from >= date(2026, 1, 1)  # a 2026 listing is not classified back to 2007
    assert len(CURATED) == 16


def test_indices_and_a_delisted_stock(report) -> None:
    nasi = [r for r in report.records if r.ticker_symbol == "^NASI"]
    assert nasi and nasi[0].sector_code == "indices"
    keno = [r for r in report.records if r.ticker_symbol == "KENO"]
    assert keno and keno[0].sector_code == "energy" and keno[0].valid_to is None


def test_industry_comes_from_the_stockanalysis_profile(report) -> None:
    kcb = [r for r in report.records if r.ticker_symbol == "KCB"]
    assert kcb[0].industry == "Commercial Banks"
    assert "industry 'Commercial Banks' from stockanalysis" in kcb[0].evidence
    accs = [r for r in report.records if r.ticker_symbol == "ACCS"]
    assert accs[0].industry is None  # delisted in 2012: no profile ever scraped


def test_energy_sector_survives_the_2023_file_defect(report) -> None:
    kegn = [r for r in report.records if r.ticker_symbol == "KEGN"]
    assert [(r.sector_code, r.valid_to) for r in kegn] == [("energy", None)]
    assert "section header" in kegn[0].evidence or "carried back" in kegn[0].evidence


def test_build_is_deterministic(fixture_source: NseScraperSource, report) -> None:
    again = build_classifications(fixture_source, NSE_DATA_DIR)
    assert again.records == report.records


# --- a reclassification produces two stints ----------------------------------------


def test_a_sector_change_between_files_becomes_two_validity_ranges(
    tmp_path: Path, fixture_source: NseScraperSource
) -> None:
    (tmp_path / "NSE_data_stock_market_sectors_2013.csv").write_text(
        "SECTOR,CODE,NAME\nInvestment,KCB,KCB\n"
    )
    (tmp_path / "NSE_data_stock_market_sectors_2020.csv").write_text(
        "SECTOR,CODE,NAME\nBanking,KCB,KCB\n"
    )
    (tmp_path / "NSE_data_stock_market_sectors_2022.csv").write_text(
        "SECTOR,CODE,NAME\nBanking,KCB,KCB\n"
    )
    report = build_classifications(fixture_source, tmp_path)
    kcb = [r for r in report.records if r.ticker_symbol == "KCB"]
    assert [(r.sector_code, r.valid_from, r.valid_to) for r in kcb] == [
        ("investment", date(2007, 1, 2), date(2019, 12, 31)),
        ("banking", date(2020, 1, 1), None),
    ]


# --- persistence + point-in-time lookup -------------------------------------------


@pytest.fixture
def settings(tmp_path: Path, fixture_source: NseScraperSource) -> Settings:
    s = Settings(
        ANALYTICS_DB_PATH=str(tmp_path / "a.sqlite3"),
        NSE_SCRAPER_DB_PATH=str(fixture_source.database_path),
        NSE_SCRAPER_PATH=str(fixture_source.database_path.parent),
    )
    upgrade_analytics_db(s.analytics_db_path)
    return s


def test_classify_persists_and_is_idempotent(
    settings: Settings, fixture_source: NseScraperSource
) -> None:
    first = classify_instruments(settings, fixture_source)
    assert first.unclassified == () and first.rows_written == first.tickers == 12
    second = classify_instruments(settings, fixture_source)
    assert second.rows_written == first.rows_written
    with analytics_session(settings) as session:
        rows = load_classifications(session)
        assert len(rows) == 12
        assert len({r.ticker_symbol for r in rows}) == first.tickers
        kcb = next(r for r in rows if r.ticker_symbol == "KCB")
        assert kcb.covers(date(2015, 6, 1)) and not kcb.covers(date(2006, 12, 31))


def test_point_in_time_lookup_and_peers(
    settings: Settings, fixture_source: NseScraperSource
) -> None:
    classify_instruments(settings, fixture_source)
    index = load_index(settings)
    assert index.sector_for("KCB", date(2015, 6, 1)).sector_code == "banking"  # type: ignore[union-attr]
    assert index.sector_for("kcb", date(2006, 6, 1)) is None  # before the timeline
    assert index.sector_for("NOPE", date(2020, 1, 1)) is None
    assert index.peers_for("KCB", date(2024, 12, 31)) == ["ABSA", "EQTY", "NCBA"]
    assert index.peers_for("KCB", date(2024, 12, 31), by="industry") == ["ABSA", "EQTY", "NCBA"]
    assert index.members("energy", date(2018, 1, 1)) == ["KEGN", "KENO"]
    assert "KENO" in index.members(
        "energy", date(2024, 1, 1)
    )  # classification does not know delistings
    assert index.history("ABSA")[0].source.startswith("sector_file")


def test_a_reclassification_is_invisible_before_it_happened(settings: Settings) -> None:
    from app.web.services.analytics.classification.builder import ClassificationRecord

    records = [
        ClassificationRecord(
            "XYZ",
            "investment",
            "Investment",
            None,
            date(2007, 1, 1),
            date(2019, 12, 31),
            "sector_file:2013",
            "test",
        ),
        ClassificationRecord(
            "XYZ", "banking", "Banking", None, date(2020, 1, 1), None, "sector_file:2020", "test"
        ),
    ]
    with analytics_session(settings) as session:
        replace_classifications(session, records)
    index = load_index(settings)
    assert index.sector_for("XYZ", date(2019, 12, 31)).sector_code == "investment"  # type: ignore[union-attr]
    assert index.sector_for("XYZ", date(2020, 1, 1)).sector_code == "banking"  # type: ignore[union-attr]


def test_cli_classify(settings: Settings, monkeypatch: pytest.MonkeyPatch) -> None:
    from app.cli.main import app
    from app.web.config import get_settings

    monkeypatch.setenv("ANALYTICS_DB_PATH", str(settings.analytics_db_path))
    monkeypatch.setenv("NSE_SCRAPER_DB_PATH", str(settings.scraper_database_path))
    monkeypatch.setenv("NSE_SCRAPER_PATH", str(settings.nse_scraper_path))
    get_settings.cache_clear()
    try:
        result = CliRunner().invoke(app, ["analytics", "classify"])
        assert result.exit_code == 0, result.output
        assert "12 rows for 12 instruments" in result.output
    finally:
        get_settings.cache_clear()
