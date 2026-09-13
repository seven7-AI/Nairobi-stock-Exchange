"""Build the point-in-time classification table for every instrument.

Inputs, in order of authority:

1. The NSE sector files (``sector_files.py``) - yearly membership snapshots. A
   ticker's stint in a sector runs from the first file that lists it there to the
   file that lists it elsewhere. The earliest file (2013) is carried back to the
   instrument's first observation: the NSE did not re-file anyone between 2007 and
   2013 that we have evidence of, and the assumption is written on the row.
2. ``CURATED`` - instruments that appear in **no** sector file. Sixteen of them:
   ten delisted before the 2013 file and six listed after the 2023/24 file (four on
   the alternative/REIT segments). Each carries the evidence it was classified on.
3. Instrument type - indices are ``indices``; ETF/REIT types map to their sector.

Industry comes from the stockanalysis profile (``fundamental_snapshots`` view
``profile``, falling back to the per-ticker ``stockanalysis_stocks`` row) and is
applied to every stint of the ticker.

Everything is resolved through ``instrument_aliases`` so a 2013 row for ``BBK``
becomes a stint of ``ABSA``.

    codegraph explore "build_classifications ClassificationRecord CURATED"
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any

from app.web.services.analytics.classification.sector_files import (
    SectorFile,
    parse_sector_files,
)
from app.web.services.analytics.classification.taxonomy import sector_code, sector_label
from app.web.services.market_data.sources.nse_scraper import NseScraperSource
from app.web.utils.logger import get_logger

logger = get_logger(__name__)

#: The first trading day in the canonical timeline; nothing is classified before it.
TIMELINE_START = date(2007, 1, 1)

#: ticker -> (sector code, evidence). Instruments absent from every sector file.
CURATED: dict[str, tuple[str, str]] = {
    "ACCS": (
        "telecommunication",
        "AccessKenya Group: ISP/data carrier, listed 2007 on the Alternative Investment "
        "Market; NSE 2007-2012 listing under Telecommunication & Technology.",
    ),
    "BAUM": (
        "commercial_services",
        "A. Baumann & Co: distribution/trading house; NSE 2007-2012 listing under "
        "Commercial & Services.",
    ),
    "BERG": (
        "manufacturing",
        "Crown Berger Kenya (paints), renamed Crown Paints (CRWN) in 2013; NSE listing "
        "under Industrial & Allied / Manufacturing.",
    ),
    "CITY": (
        "investment",
        "City Trust Ltd: investment holding company (later I&M Holdings); NSE 2007-2012 "
        "listing under Finance & Investment.",
    ),
    "CMC": (
        "automobiles",
        "CMC Holdings: motor vehicle dealer; NSE listing under Automobiles & "
        "Accessories, delisted 2013 after acquisition by Al-Futtaim.",
    ),
    "ICDC": (
        "investment",
        "ICDC Investment Co, renamed Centum Investment (CTUM) in 2011; NSE listing "
        "under Investment.",
    ),
    "MASH": (
        "automobiles",
        "Marshalls (East Africa): motor vehicle assembler/dealer; NSE listing under "
        "Automobiles & Accessories.",
    ),
    "PAFR": (
        "insurance",
        "Pan Africa Insurance Holdings, renamed Sanlam Kenya (SLAM) in 2015; NSE "
        "listing under Insurance.",
    ),
    "REA": (
        "agricultural",
        "Rea Vipingo Plantations: sisal estates; NSE listing under Agricultural, delisted 2015.",
    ),
    "UTK": (
        "agricultural",
        "Unilever Tea Kenya: tea estates; NSE listing under Agricultural, delisted 2010.",
    ),
    "KPC": (
        "energy",
        "Kenya Pipeline Company PLC: petroleum pipeline operator, listed 2025; NSE "
        "Energy & Petroleum.",
    ),
    "FMLY": (
        "banking",
        "Family Bank Limited: commercial bank, listed 2025 by introduction; NSE Banking.",
    ),
    "AMAC": (
        "agricultural",
        "Africa Mega Agricorp Plc: agribusiness, listed 2025 on the SME segment; NSE Agricultural.",
    ),
    "SKL": (
        "commercial_services",
        "Shri Krishana Overseas PLC: rice/commodity trader, listed 2025 on the SME "
        "segment; NSE Commercial & Services.",
    ),
    "TRFC": (
        "reit",
        "Trific USD I-REIT: income real-estate investment trust; NSE REIT segment.",
    ),
    "ALP": (
        "reit",
        "ALP Industrial Real Estate Investment Trust; NSE REIT segment.",
    ),
}

#: instrument_type -> sector code when no file or curated entry applies.
TYPE_SECTORS = {"index": "indices", "etf": "etf", "reit": "reit"}


@dataclass(frozen=True, slots=True)
class ClassificationRecord:
    ticker_symbol: str
    sector_code: str
    sector_label: str
    industry: str | None
    valid_from: date
    valid_to: date | None
    source: str
    evidence: str


@dataclass(frozen=True, slots=True)
class BuildReport:
    records: tuple[ClassificationRecord, ...]
    unclassified: tuple[str, ...]
    skipped_rows: tuple[str, ...]

    @property
    def tickers(self) -> set[str]:
        return {r.ticker_symbol for r in self.records}


def _first_seen(instrument: dict[str, Any], spans: dict[str, tuple[date, date, int]]) -> date:
    """When the instrument first traded: the master's date, else its first observation.

    Scraper-era listings (2025-2026) carry no ``first_seen_date`` in the master; their
    first observation is the honest start, not the 2007 start of the timeline.
    """
    raw = instrument.get("first_seen_date")
    if raw:
        return max(date.fromisoformat(str(raw)[:10]), TIMELINE_START)
    span = spans.get(str(instrument["ticker_symbol"]))
    if span is not None:
        return max(span[0], TIMELINE_START)
    return TIMELINE_START


def _stints_from_files(
    canonical: str,
    source_codes: set[str],
    files: list[SectorFile],
    first_seen: date,
) -> list[ClassificationRecord]:
    """Membership per file year -> validity ranges, oldest first."""
    per_year: list[tuple[int, str, str, str, str | None]] = []  # (year, code, label, file, repair)
    for sector_file in files:
        for row in sector_file.rows:
            if row.code in source_codes:
                per_year.append(
                    (sector_file.year, row.sector_code, row.sector_label, row.file_name, row.repair)
                )
                break
    if not per_year:
        return []
    stints: list[ClassificationRecord] = []
    current: tuple[int, str, str, str, str | None] | None = None
    for entry in per_year:
        if current is None:
            current = entry
            continue
        if entry[1] != current[1]:
            year, code, label, file_name, repair = current
            stints.append(
                _stint(
                    canonical,
                    code,
                    label,
                    file_name,
                    repair,
                    _stint_start(stints, year, first_seen),
                    date(entry[0] - 1, 12, 31),
                    year,
                )
            )
            current = entry
    assert current is not None
    year, code, label, file_name, repair = current
    stints.append(
        _stint(
            canonical,
            code,
            label,
            file_name,
            repair,
            _stint_start(stints, year, first_seen),
            None,
            year,
        )
    )
    return stints


def _stint_start(previous: list[ClassificationRecord], year: int, first_seen: date) -> date:
    if previous:
        return date(year, 1, 1)
    return first_seen


def _stint(
    ticker: str,
    code: str,
    label: str,
    file_name: str,
    repair: str | None,
    start: date,
    end: date | None,
    file_year: int,
) -> ClassificationRecord:
    evidence = f"listed under '{label}' in {file_name}"
    if repair:
        evidence += f" ({repair})"
    if start < date(2013, 1, 1):
        evidence += "; carried back to the first observation - no earlier sector file exists"
    return ClassificationRecord(
        ticker,
        code,
        sector_label(code),
        None,
        start,
        end,
        f"sector_file:{file_year}",
        evidence,
    )


def _industry_by_ticker(source: NseScraperSource, tickers: list[str]) -> dict[str, tuple[str, str]]:
    """ticker -> (industry, evidence) from the profile snapshots, else the latest row."""
    industries: dict[str, tuple[str, str]] = {}
    latest_rows = {row["ticker_symbol"]: row for row in source.fetch_latest_rows(limit=5000)}
    for ticker in tickers:
        snapshots = source.fetch_fundamental_snapshots(ticker, view="profile")
        for snapshot in reversed(snapshots):
            industry = (snapshot.get("metrics") or {}).get("industry")
            if industry:
                industries[ticker] = (
                    str(industry),
                    f"stockanalysis profile snapshot {snapshot['snapshot_date']}",
                )
                break
        if ticker in industries:
            continue
        row = latest_rows.get(ticker) or {}
        profile = row.get("profile_metrics") or {}
        if profile.get("industry"):
            industries[ticker] = (
                str(profile["industry"]),
                f"stockanalysis_stocks profile scraped {str(row.get('scraped_at'))[:10]}",
            )
    return industries


def build_classifications(source: NseScraperSource, nse_data_dir: Path) -> BuildReport:
    """Classify every instrument the scraper knows. Pure apart from the reads."""
    files = parse_sector_files(nse_data_dir)
    skipped = tuple(item for sector_file in files for item in sector_file.skipped)
    instruments = source.fetch_instruments()
    aliases = source.fetch_instrument_aliases()
    spans = source.fetch_observation_spans()
    codes_for: dict[str, set[str]] = {}
    for alias in aliases:
        codes_for.setdefault(alias["canonical_ticker"], set()).add(alias["source_ticker"])
    industries = _industry_by_ticker(source, [i["ticker_symbol"] for i in instruments])

    records: list[ClassificationRecord] = []
    unclassified: list[str] = []
    for instrument in instruments:
        ticker = instrument["ticker_symbol"]
        first_seen = _first_seen(instrument, spans)
        source_codes = {ticker} | codes_for.get(ticker, set())
        stints = _stints_from_files(ticker, source_codes, files, first_seen)
        if not stints and ticker in CURATED:
            code, evidence = CURATED[ticker]
            stints = [
                ClassificationRecord(
                    ticker, code, sector_label(code), None, first_seen, None, "curated", evidence
                )
            ]
        if not stints and instrument.get("instrument_type") in TYPE_SECTORS:
            code = TYPE_SECTORS[str(instrument["instrument_type"])]
            stints = [
                ClassificationRecord(
                    ticker,
                    code,
                    sector_label(code),
                    None,
                    first_seen,
                    None,
                    "instrument_type",
                    f"instrument_type={instrument['instrument_type']} in the scraper's "
                    "instrument master",
                )
            ]
        if not stints and instrument.get("sector") and sector_code(str(instrument["sector"])):
            code = sector_code(str(instrument["sector"])) or ""
            stints = [
                ClassificationRecord(
                    ticker,
                    code,
                    sector_label(code),
                    None,
                    first_seen,
                    None,
                    "scraper_instruments",
                    f"instruments.sector='{instrument['sector']}' from "
                    f"{instrument.get('sector_source')}",
                )
            ]
        if not stints:
            unclassified.append(ticker)
            continue
        industry = industries.get(ticker)
        for stint in stints:
            evidence = stint.evidence + (
                f"; industry '{industry[0]}' from {industry[1]}" if industry else ""
            )
            records.append(
                ClassificationRecord(
                    stint.ticker_symbol,
                    stint.sector_code,
                    stint.sector_label,
                    industry[0] if industry else None,
                    stint.valid_from,
                    stint.valid_to,
                    stint.source,
                    evidence,
                )
            )

    logger.info(
        "classifications_built",
        instruments=len(instruments),
        records=len(records),
        unclassified=unclassified,
        skipped=len(skipped),
    )
    return BuildReport(tuple(records), tuple(unclassified), skipped)


__all__ = [
    "CURATED",
    "TIMELINE_START",
    "TYPE_SECTORS",
    "BuildReport",
    "ClassificationRecord",
    "build_classifications",
]
