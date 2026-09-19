"""GLEIF LEI lookups with a disk cache.

The Global LEI Foundation's public API (no key) is identifier *enrichment*: it
holds ~300 Kenyan LEIs, and KCB Group PLC and Equity Group Holdings have none, so
a miss is recorded as "checked, none found", never as "the entity does not exist".
Relationship (parent/child) endpoints are not called - they return ``NO_LEI`` for
the entities that matter here.

Probed 2026-09-19: ``filter[fulltext]`` with ``filter[entity.legalAddress.country]``
works; ``filter[registration.lastUpdateDate]=>YYYY-MM-DD`` returns the records
updated since that day (18 for KE since 2026-09-01).

    codegraph explore "GleifClient LeiRecord sync_gleif"
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any
from urllib.parse import urlencode

from app.web.services.corporate.http import PoliteClient
from app.web.utils.logger import get_logger

logger = get_logger("app.web.services.corporate.entities.gleif")

DEFAULT_BASE_URL = "https://api.gleif.org/api/v1"
_HEADERS = {"Accept": "application/vnd.api+json"}


@dataclass(frozen=True)
class LeiRecord:
    lei: str
    legal_name: str
    jurisdiction: str
    registered_as: str | None
    registration_status: str
    entity_status: str
    other_names: tuple[str, ...]
    last_update: str | None
    raw: dict[str, Any]

    @classmethod
    def from_api(cls, item: dict[str, Any]) -> LeiRecord:
        attributes = item.get("attributes") or {}
        entity = attributes.get("entity") or {}
        registration = attributes.get("registration") or {}
        legal_address = entity.get("legalAddress") or {}
        other = tuple(
            str(n.get("name"))
            for n in (entity.get("otherNames") or [])
            if isinstance(n, dict) and n.get("name")
        )
        return cls(
            lei=str(item.get("id") or attributes.get("lei") or "").upper(),
            legal_name=str((entity.get("legalName") or {}).get("name") or ""),
            jurisdiction=str(legal_address.get("country") or entity.get("jurisdiction") or "")[
                :2
            ].upper(),
            registered_as=entity.get("registeredAs"),
            registration_status=str(registration.get("status") or ""),
            entity_status=str(entity.get("status") or ""),
            other_names=other,
            last_update=registration.get("lastUpdateDate"),
            raw=item,
        )


@dataclass(frozen=True)
class GleifResponse:
    """What a lookup produced; ``records`` is empty on any failure with ``reason`` set."""

    records: tuple[LeiRecord, ...]
    status: str  # ok | not_found | cached | error
    reason: str | None = None
    fetched_at: datetime | None = None
    from_cache: bool = False


class GleifClient:
    def __init__(
        self,
        client: PoliteClient,
        cache_dir: Path,
        *,
        base_url: str = DEFAULT_BASE_URL,
        search_ttl: timedelta = timedelta(days=7),
        delta_ttl: timedelta = timedelta(days=1),
        now: Any = None,
    ) -> None:
        self._client = client
        self._cache_dir = cache_dir
        self._base_url = base_url.rstrip("/")
        self._search_ttl = search_ttl
        self._delta_ttl = delta_ttl
        self._now = now or (lambda: datetime.now(UTC))
        self.requests_made = 0
        self.cache_hits = 0

    # --- cache --------------------------------------------------------------------

    def _cache_path(self, url: str) -> Path:
        digest = hashlib.sha256(url.encode("utf-8")).hexdigest()
        return self._cache_dir / f"{digest}.json"

    def _cached(self, url: str, ttl: timedelta) -> dict[str, Any] | None:
        path = self._cache_path(url)
        if not path.is_file():
            return None
        try:
            entry = json.loads(path.read_text(encoding="utf-8"))
            fetched = datetime.fromisoformat(entry["fetched_at"])
        except (OSError, ValueError, KeyError):
            return None
        if self._now() - fetched > ttl:
            return None
        return entry

    def _store(self, url: str, status_code: int | None, body: Any) -> dict[str, Any]:
        entry = {"fetched_at": self._now().isoformat(), "status_code": status_code, "body": body}
        try:
            self._cache_dir.mkdir(parents=True, exist_ok=True)
            self._cache_path(url).write_text(json.dumps(entry), encoding="utf-8")
        except OSError as exc:
            logger.warning("gleif_cache_write_failed", error=type(exc).__name__)
        return entry

    def _get(self, url: str, ttl: timedelta) -> tuple[dict[str, Any] | None, str | None, bool]:
        """(entry, error reason, from_cache)."""
        entry = self._cached(url, ttl)
        if entry is not None:
            self.cache_hits += 1
            return entry, None, True
        result = self._client.get(url, headers=_HEADERS, max_bytes=20_000_000)
        self.requests_made += 1
        if result.status == "http_error" and result.status_code == 404:
            return self._store(url, 404, None), None, False
        if not result.ok:
            return None, f"{result.status}: {result.reason or 'no body'}", False
        try:
            body = result.json()
        except ValueError:
            return None, "GLEIF returned a body that is not JSON", False
        return self._store(url, result.status_code, body), None, False

    def _response(
        self, entry: dict[str, Any] | None, error: str | None, from_cache: bool
    ) -> GleifResponse:
        if entry is None:
            return GleifResponse((), "error", error)
        fetched = datetime.fromisoformat(entry["fetched_at"])
        body = entry.get("body")
        if entry.get("status_code") == 404 or body is None:
            return GleifResponse((), "not_found", "no such LEI record", fetched, from_cache)
        data = body.get("data")
        items = data if isinstance(data, list) else [data] if isinstance(data, dict) else []
        records = tuple(LeiRecord.from_api(item) for item in items if item.get("id"))
        return GleifResponse(records, "cached" if from_cache else "ok", None, fetched, from_cache)

    # --- lookups ------------------------------------------------------------------

    def by_lei(self, lei: str) -> GleifResponse:
        url = f"{self._base_url}/lei-records/{lei.strip().upper()}"
        return self._response(*self._get(url, self._search_ttl))

    def search(self, *, fulltext: str, country: str | None, page_size: int = 20) -> GleifResponse:
        params: dict[str, str] = {"filter[fulltext]": fulltext, "page[size]": str(page_size)}
        if country:
            params["filter[entity.legalAddress.country]"] = country.upper()
        url = f"{self._base_url}/lei-records?{urlencode(params)}"
        return self._response(*self._get(url, self._search_ttl))

    def updated_since(
        self, day: date, *, country: str, page_size: int = 200, max_pages: int = 10
    ) -> GleifResponse:
        """Records in ``country`` whose registration was updated after ``day``."""
        records: list[LeiRecord] = []
        fetched_at: datetime | None = None
        cached = True
        for page in range(1, max_pages + 1):
            params = {
                "filter[entity.legalAddress.country]": country.upper(),
                "filter[registration.lastUpdateDate]": f">{day.isoformat()}",
                "page[size]": str(page_size),
                "page[number]": str(page),
            }
            url = f"{self._base_url}/lei-records?{urlencode(params)}"
            entry, error, from_cache = self._get(url, self._delta_ttl)
            response = self._response(entry, error, from_cache)
            if response.status == "error":
                return response
            records.extend(response.records)
            fetched_at = response.fetched_at
            cached = cached and from_cache
            pagination = ((entry or {}).get("body") or {}).get("meta", {}).get("pagination", {})
            if page >= int(pagination.get("lastPage") or 1):
                break
        return GleifResponse(tuple(records), "cached" if cached else "ok", None, fetched_at, cached)


__all__ = ["DEFAULT_BASE_URL", "GleifClient", "GleifResponse", "LeiRecord"]
