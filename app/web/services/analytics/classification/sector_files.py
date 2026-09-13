"""Reading the NSE sector files under ``NSE_DATA/``.

Five yearly snapshots - ``NSE_data_stock_market_sectors_{2013,2020,2021,2022,2023_2024}.csv``
- each a ``SECTOR, CODE, NAME`` list (the 2022+ files spell the header
``Sector, Stock_code, Stock_name``; the 2021 file starts with a BOM). They carry no
prices, only membership, and they disagree with each other in three known ways
that are repaired here with the evidence recorded on every row:

1. **Section-header rows.** The 2023/24 file has ``Construction and Allied,Energy and
   Petroleum,`` - a heading row whose CODE cell is itself a sector name and whose
   NAME is empty. Every row after it until the next real sector belongs to *that*
   sector (KEGN, KPLC, KPLC-P4, KPLC-P7, TOTL, UMME are Energy and Petroleum, not
   Construction). The rule is general: any row shaped like that switches the
   running sector.
2. **Indices labelled with their own code** in the 2013 file (``^NASI,^NASI,...``);
   they are the ``indices`` sector.
3. **Blank sector cells** in the 2013/2020 files; those rows are skipped and
   reported, never guessed.

    codegraph explore "read_sector_file SectorFileRow parse_sector_files"
"""

from __future__ import annotations

import csv
import re
from dataclasses import dataclass
from pathlib import Path

from app.web.services.analytics.classification.taxonomy import sector_code

FILE_PATTERN = re.compile(
    r"NSE_data_stock_market_sectors_(?P<year>\d{4})(?:_(?P<year2>\d{4}))?\.csv$"
)


@dataclass(frozen=True, slots=True)
class SectorFileRow:
    """One membership row after repair."""

    file_year: int
    file_name: str
    code: str
    name: str
    sector_label: str
    sector_code: str
    #: Non-empty when a repair rule changed what the file literally says.
    repair: str | None = None


@dataclass(frozen=True, slots=True)
class SectorFile:
    path: Path
    year: int
    rows: tuple[SectorFileRow, ...]
    skipped: tuple[str, ...]


def file_year(path: Path) -> int | None:
    match = FILE_PATTERN.search(path.name)
    return int(match.group("year")) if match else None


def read_sector_file(path: Path) -> SectorFile:
    year = file_year(path)
    if year is None:
        raise ValueError(f"not a sector file: {path.name}")
    rows: list[SectorFileRow] = []
    skipped: list[str] = []
    # An open section from a heading row: (the sector it opened, the defective printed
    # label the rows under it carry). Closed by the first row printed differently.
    section: tuple[str, str] | None = None
    with path.open(encoding="utf-8-sig", newline="") as handle:
        reader = csv.reader(handle)
        if next(reader, None) is None:
            return SectorFile(path, year, (), ())
        for raw in reader:
            if len(raw) < 2:
                continue
            printed = raw[0].strip()
            code = raw[1].strip().upper()
            name = raw[2].strip() if len(raw) > 2 else ""
            if not code:
                continue
            # Rule 1: a heading row - the CODE cell is a sector name and NAME is empty.
            if not name and sector_code(code) is not None:
                section = (code, printed)
                continue
            label, repair = printed, None
            if section is not None:
                opened_sector, defective_printed = section
                if printed == defective_printed and not code.startswith("^"):
                    label = opened_sector
                    repair = f"section header '{opened_sector}' overrides printed '{printed}'"
                else:
                    section = None
            resolved = sector_code(label)
            if resolved is None and code.startswith("^"):
                # Rule 2: indices printed with their own code as the sector.
                label, resolved = "Indices", "indices"
                repair = f"index row printed with sector '{printed}'"
            if resolved is None:
                skipped.append(f"{path.name}: {code} has unknown sector '{printed}'")
                continue
            rows.append(SectorFileRow(year, path.name, code, name, label, resolved, repair))
    return SectorFile(path, year, tuple(rows), tuple(skipped))


def parse_sector_files(directory: Path) -> list[SectorFile]:
    """Every sector file in ``directory``, oldest first."""
    files = sorted(
        (p for p in directory.glob("NSE_data_stock_market_sectors_*.csv") if file_year(p)),
        key=lambda p: file_year(p) or 0,
    )
    return [read_sector_file(path) for path in files]


__all__ = [
    "FILE_PATTERN",
    "SectorFile",
    "SectorFileRow",
    "file_year",
    "parse_sector_files",
    "read_sector_file",
]
