"""Point-in-time lookups over the classification rows.

codegraph explore "ClassificationIndex sector_for peers_for"
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import date

from app.web.db.analytics.models import Classification


@dataclass(frozen=True, slots=True)
class SectorAssignment:
    ticker_symbol: str
    sector_code: str
    sector_label: str
    industry: str | None
    valid_from: date
    valid_to: date | None
    source: str


class ClassificationIndex:
    """In-memory index built once per job from the ``classifications`` table."""

    def __init__(self, rows: Iterable[Classification]) -> None:
        self._by_ticker: dict[str, list[SectorAssignment]] = defaultdict(list)
        for row in rows:
            self._by_ticker[row.ticker_symbol].append(
                SectorAssignment(
                    row.ticker_symbol,
                    row.sector_code,
                    row.sector_label,
                    row.industry,
                    row.valid_from,
                    row.valid_to,
                    row.source,
                )
            )
        for stints in self._by_ticker.values():
            stints.sort(key=lambda s: s.valid_from)

    @property
    def tickers(self) -> list[str]:
        return sorted(self._by_ticker)

    def sector_for(self, ticker_symbol: str, as_of: date) -> SectorAssignment | None:
        """The stint covering ``as_of``; None before listing or when unclassified."""
        for stint in self._by_ticker.get(ticker_symbol.upper(), ()):
            if stint.valid_from <= as_of and (stint.valid_to is None or as_of <= stint.valid_to):
                return stint
        return None

    def peers_for(self, ticker_symbol: str, as_of: date, *, by: str = "sector") -> list[str]:
        """Tickers in the same sector (or ``by="industry"``) on ``as_of``, excluding itself."""
        own = self.sector_for(ticker_symbol, as_of)
        if own is None:
            return []
        peers = []
        for other in self._by_ticker:
            if other == ticker_symbol.upper():
                continue
            stint = self.sector_for(other, as_of)
            if stint is None:
                continue
            if by == "industry":
                if own.industry is not None and stint.industry == own.industry:
                    peers.append(other)
            elif stint.sector_code == own.sector_code:
                peers.append(other)
        return sorted(peers)

    def members(self, sector_code: str, as_of: date) -> list[str]:
        return sorted(
            t
            for t in self._by_ticker
            if (s := self.sector_for(t, as_of)) is not None and s.sector_code == sector_code
        )

    def history(self, ticker_symbol: str) -> list[SectorAssignment]:
        return list(self._by_ticker.get(ticker_symbol.upper(), ()))


__all__ = ["ClassificationIndex", "SectorAssignment"]
