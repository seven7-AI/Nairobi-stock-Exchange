#!/usr/bin/env python3
"""Build the real-data test fixture from the live scraper database.

The analytics engines are tested against **real NSE data**, not synthetic rows:
``app/tests/fixtures/nse_fixture.sqlite3.gz`` is a slice of
``~/nse-stock-scraper/data/nse_scraper.sqlite3`` with the scraper's exact schema and a
deliberately varied set of instruments:

    KCB, EQTY   banks, full 2007->today history, statements captured (Dec year end)
    SCOM        telecom, March year end, half-yearly reporter
    KEGN        energy, June year end, half-yearly reporter
    ABSA        BBK -> ABSA lineage (alias rows resolved), suspected 2011 split
    NCBA        NIC -> NCBA lineage
    KENO        delisted 2019-10-11 - a survivor-bias case
    ACCS        delisted 2012-12-31, one of the 16 unclassified ordinaries
    KPC, SKL    thin listings (25 / 37 observations, zero-volume days)
    ^NASI, ^N20I  the benchmarks (2008-> / 2007-> to 2024-12-31)

Usage (from the repo root; the live database is opened read-only):

    uv run python scripts/build_test_fixture.py
    uv run python scripts/build_test_fixture.py --source /path/to/nse_scraper.sqlite3

The manifest next to the fixture records the source path, its sha256, the row
counts per table and the build time, so a test failure can be traced to a data
change rather than a code change.

    codegraph explore "build_test_fixture fixture_db conftest"
"""

from __future__ import annotations

import argparse
import gzip
import hashlib
import json
import sqlite3
import sys
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FIXTURE_DIR = ROOT / "app" / "tests" / "fixtures"
FIXTURE_GZ = FIXTURE_DIR / "nse_fixture.sqlite3.gz"
MANIFEST = FIXTURE_DIR / "nse_fixture.json"

TICKERS = (
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
)

#: table -> column that carries the canonical ticker (None: copy whole table)
TABLES: dict[str, str | None] = {
    "instruments": "ticker_symbol",
    "instrument_aliases": "canonical_ticker",
    "stock_observations": "ticker_symbol",
    "stock_observation_conflicts": "ticker_symbol",
    "import_runs": None,
    "financial_statements": "ticker_symbol",
    "fundamental_snapshots": "ticker_symbol",
    "stockanalysis_stocks": "ticker_symbol",
}


def sha256_of(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def build(source: Path, target: Path) -> dict[str, int]:
    if target.exists():
        target.unlink()
    live = sqlite3.connect(f"file:{source}?mode=ro", uri=True)
    out = sqlite3.connect(target)
    try:
        # Same DDL as the live file, so the read path is exercised unchanged.
        ddl = live.execute(
            "SELECT sql FROM sqlite_master WHERE sql IS NOT NULL AND type IN ('table','index') "
            "AND name NOT LIKE 'sqlite_%' ORDER BY CASE type WHEN 'table' THEN 0 ELSE 1 END, name"
        ).fetchall()
        for (statement,) in ddl:
            out.execute(statement)
        counts: dict[str, int] = {}
        placeholders = ",".join("?" * len(TICKERS))
        for table, column in TABLES.items():
            exists = live.execute(
                "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (table,)
            ).fetchone()
            if not exists:
                counts[table] = 0
                continue
            if column is None:
                rows = live.execute(f"SELECT * FROM {table}").fetchall()
            else:
                rows = live.execute(
                    f"SELECT * FROM {table} WHERE {column} IN ({placeholders})", TICKERS
                ).fetchall()
            if rows:
                width = len(rows[0])
                out.executemany(f"INSERT INTO {table} VALUES ({','.join('?' * width)})", rows)
            counts[table] = len(rows)
        out.commit()
        out.execute("VACUUM")
    finally:
        out.close()
        live.close()
    return counts


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument(
        "--source",
        type=Path,
        default=Path.home() / "nse-stock-scraper" / "data" / "nse_scraper.sqlite3",
        help="the live scraper database (opened read-only)",
    )
    args = parser.parse_args(argv)
    if not args.source.exists():
        print(f"source database not found: {args.source}", file=sys.stderr)
        return 1

    FIXTURE_DIR.mkdir(parents=True, exist_ok=True)
    raw = FIXTURE_DIR / "nse_fixture.sqlite3"
    counts = build(args.source, raw)
    with raw.open("rb") as src, gzip.open(FIXTURE_GZ, "wb", compresslevel=9) as dst:
        dst.write(src.read())
    raw_sha = sha256_of(raw)
    raw.unlink()

    manifest = {
        "built_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "source": str(args.source),
        "source_sha256": sha256_of(args.source),
        "fixture_sha256": raw_sha,
        "tickers": list(TICKERS),
        "rows": counts,
    }
    MANIFEST.write_text(json.dumps(manifest, indent=2) + "\n")
    print(json.dumps(manifest, indent=2))
    print(f"wrote {FIXTURE_GZ} ({FIXTURE_GZ.stat().st_size / 1024:.0f} KB)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
