"""A polite HTTP client for free public sources.

Company IR sites, the NSE's WordPress, regulators and GLEIF are shared, rate-limited
resources. This client spaces requests per host, backs off on 429/5xx (honouring
``Retry-After``), obeys ``robots.txt``, sends a conditional GET when a cached
validator exists, caps the bytes it will read, and stops at a per-run request
budget - recorded as an outcome, never raised as a failure.

Nothing here logs a full URL: signed download links (KCB's ``?signature=...``) are
credentials, so every logged URL has its query string stripped.

    codegraph explore "PoliteClient FetchResult redacted_url"
"""

from __future__ import annotations

import logging
import threading
import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime
from typing import Any, Literal
from urllib import robotparser
from urllib.parse import urlsplit, urlunsplit

import httpx

from app.web.utils.logger import get_logger

logger = get_logger("app.web.services.corporate.http")

FetchStatus = Literal[
    "ok", "not_modified", "too_large", "disallowed", "budget_exhausted", "http_error", "error"
]

#: Seconds to wait before each retry (attempt 1, 2, 3); ``Retry-After`` overrides.
DEFAULT_BACKOFF: tuple[float, ...] = (2.0, 8.0, 30.0)
MAX_RETRY_AFTER_SECONDS = 120.0
_RETRY_STATUSES = frozenset({429, 500, 502, 503, 504})


@dataclass(frozen=True)
class FetchResult:
    """What one request produced. ``content`` is empty unless ``status == "ok"``."""

    status: FetchStatus
    url: str
    status_code: int | None = None
    content: bytes = b""
    content_type: str | None = None
    etag: str | None = None
    last_modified: str | None = None
    content_length: int | None = None
    final_host: str | None = None
    reason: str | None = None
    attempts: int = 1

    @property
    def ok(self) -> bool:
        return self.status == "ok"

    def json(self) -> Any:
        import json

        return json.loads(self.content.decode("utf-8"))


@dataclass
class _HostState:
    last_request_at: float | None = None
    robots: robotparser.RobotFileParser | None = None
    robots_checked: bool = False
    lock: threading.Lock = field(default_factory=threading.Lock)


def redacted_url(url: str) -> str:
    """The URL without its query string or fragment - safe to log."""
    parts = urlsplit(url)
    return urlunsplit((parts.scheme, parts.netloc, parts.path, "", ""))


def _retry_after_seconds(value: str | None, now: datetime) -> float | None:
    if not value:
        return None
    try:
        return min(float(value), MAX_RETRY_AFTER_SECONDS)
    except ValueError:
        pass
    try:
        when = parsedate_to_datetime(value)
    except (TypeError, ValueError):
        return None
    if when.tzinfo is None:
        when = when.replace(tzinfo=UTC)
    return max(0.0, min((when - now).total_seconds(), MAX_RETRY_AFTER_SECONDS))


class PoliteClient:
    """Synchronous, per-host rate-limited, budgeted HTTP client.

    ``transport``, ``sleep`` and ``clock`` are injectable so tests run against
    ``httpx.MockTransport`` with no real waiting.
    """

    def __init__(
        self,
        *,
        delay_seconds: float = 3.0,
        timeout_seconds: float = 30.0,
        user_agent: str = "nse-be corporate collector",
        contact_email: str = "",
        max_bytes: int = 60_000_000,
        max_requests: int = 300,
        respect_robots: bool = True,
        retries: int = 3,
        backoff: tuple[float, ...] = DEFAULT_BACKOFF,
        transport: httpx.BaseTransport | None = None,
        sleep: Callable[[float], None] = time.sleep,
        clock: Callable[[], float] = time.monotonic,
        now: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        self.delay_seconds = delay_seconds
        self.max_bytes = max_bytes
        self.max_requests = max_requests
        self.respect_robots = respect_robots
        self.retries = retries
        self.backoff = backoff
        self._sleep = sleep
        self._clock = clock
        self._now = now
        agent = user_agent if not contact_email else f"{user_agent}; contact: {contact_email}"
        self.user_agent = agent
        # httpx logs every request URL at INFO, query string included - which for a
        # signed download link is the credential. Only our redacted lines are logged.
        for name in ("httpx", "httpcore"):
            logging.getLogger(name).setLevel(logging.WARNING)
        self._client = httpx.Client(
            transport=transport,
            timeout=timeout_seconds,
            follow_redirects=True,
            headers={"User-Agent": agent, "Accept": "*/*"},
        )
        self._hosts: dict[str, _HostState] = {}
        self._hosts_lock = threading.Lock()
        self._requests_made = 0
        self._count_lock = threading.Lock()

    # --- public -------------------------------------------------------------------

    @property
    def requests_made(self) -> int:
        return self._requests_made

    @property
    def budget_remaining(self) -> int:
        return max(0, self.max_requests - self._requests_made)

    def close(self) -> None:
        self._client.close()

    def __enter__(self) -> PoliteClient:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    def get(
        self,
        url: str,
        *,
        etag: str | None = None,
        last_modified: str | None = None,
        max_bytes: int | None = None,
        headers: Mapping[str, str] | None = None,
    ) -> FetchResult:
        """GET with conditional headers, a byte cap and retries."""
        extra: dict[str, str] = dict(headers or {})
        if etag:
            extra["If-None-Match"] = etag
        if last_modified:
            extra["If-Modified-Since"] = last_modified
        return self._request("GET", url, extra, max_bytes or self.max_bytes)

    def head(self, url: str, *, headers: Mapping[str, str] | None = None) -> FetchResult:
        """HEAD: validators and length only, so a large unchanged file is not re-read."""
        return self._request("HEAD", url, dict(headers or {}), 0)

    # --- internals ----------------------------------------------------------------

    def _host(self, url: str) -> _HostState:
        host = urlsplit(url).netloc.lower()
        with self._hosts_lock:
            state = self._hosts.get(host)
            if state is None:
                state = self._hosts[host] = _HostState()
            return state

    def _take_budget(self) -> bool:
        with self._count_lock:
            if self._requests_made >= self.max_requests:
                return False
            self._requests_made += 1
            return True

    def _wait_for_host(self, state: _HostState) -> None:
        if state.last_request_at is not None:
            elapsed = self._clock() - state.last_request_at
            if elapsed < self.delay_seconds:
                self._sleep(self.delay_seconds - elapsed)
        state.last_request_at = self._clock()

    def _allowed(self, url: str, state: _HostState) -> bool:
        if not self.respect_robots:
            return True
        if not state.robots_checked:
            state.robots_checked = True
            parts = urlsplit(url)
            robots_url = urlunsplit((parts.scheme, parts.netloc, "/robots.txt", "", ""))
            parser = robotparser.RobotFileParser()
            try:
                self._wait_for_host(state)
                response = self._client.get(robots_url)
            except httpx.HTTPError as exc:
                logger.info("robots_unreachable", host=parts.netloc, error=type(exc).__name__)
                return True
            if response.status_code >= 400:
                # No robots file (or a broken one): the web's convention is "allowed".
                return True
            parser.parse(response.text.splitlines())
            state.robots = parser
        if state.robots is None:
            return True
        return state.robots.can_fetch(self.user_agent, url) or state.robots.can_fetch("*", url)

    def _request(
        self, method: str, url: str, headers: dict[str, str], max_bytes: int
    ) -> FetchResult:
        safe_url = redacted_url(url)
        if not self._take_budget():
            logger.info("request_budget_exhausted", url=safe_url, budget=self.max_requests)
            return FetchResult(
                "budget_exhausted",
                url,
                reason=f"per-run request budget of {self.max_requests} exhausted",
            )
        state = self._host(url)
        with state.lock:
            if not self._allowed(url, state):
                logger.info("robots_disallowed", url=safe_url)
                return FetchResult("disallowed", url, reason="robots.txt disallows this path")
            attempts = 0
            last_error: str | None = None
            last_code: int | None = None
            while attempts < 1 + self.retries:
                attempts += 1
                self._wait_for_host(state)
                try:
                    result = self._once(method, url, headers, max_bytes, attempts)
                except httpx.HTTPError as exc:
                    last_error = f"{type(exc).__name__}: {exc}"[:200]
                    logger.warning(
                        "request_failed", url=safe_url, attempt=attempts, error=last_error
                    )
                    result = None
                if result is not None and result.status_code not in _RETRY_STATUSES:
                    return result
                if result is not None:
                    last_code = result.status_code
                    retry_after = _retry_after_seconds(result.reason, self._now())
                else:
                    retry_after = None
                if attempts > self.retries:
                    break
                wait = retry_after
                if wait is None:
                    wait = self.backoff[min(attempts - 1, len(self.backoff) - 1)]
                logger.info(
                    "request_retry",
                    url=safe_url,
                    attempt=attempts,
                    status_code=last_code,
                    wait_seconds=wait,
                )
                self._sleep(wait)
            reason = (
                f"HTTP {last_code} after {attempts} attempts"
                if last_code is not None
                else last_error or "request failed"
            )
            status: FetchStatus = "http_error" if last_code is not None else "error"
            return FetchResult(status, url, status_code=last_code, reason=reason, attempts=attempts)

    def _once(
        self, method: str, url: str, headers: dict[str, str], max_bytes: int, attempt: int
    ) -> FetchResult:
        safe_url = redacted_url(url)
        with self._client.stream(method, url, headers=headers) as response:
            code = response.status_code
            final_host = urlsplit(str(response.url)).netloc or None
            etag = response.headers.get("ETag")
            last_modified = response.headers.get("Last-Modified")
            content_type = response.headers.get("Content-Type")
            length_header = response.headers.get("Content-Length")
            content_length = (
                int(length_header) if length_header and length_header.isdigit() else None
            )
            common = {
                "status_code": code,
                "etag": etag,
                "last_modified": last_modified,
                "content_type": content_type,
                "content_length": content_length,
                "final_host": final_host,
                "attempts": attempt,
            }
            if code in _RETRY_STATUSES:
                # ``reason`` carries Retry-After so the loop can honour it.
                retry_after = response.headers.get("Retry-After")
                return FetchResult("http_error", url, reason=retry_after, **common)
            if code == 304:
                return FetchResult("not_modified", url, **common)
            if code >= 400:
                logger.info("request_http_error", url=safe_url, status_code=code)
                return FetchResult("http_error", url, reason=f"HTTP {code}", **common)
            if method == "HEAD":
                return FetchResult("ok", url, **common)
            if content_length is not None and content_length > max_bytes:
                return FetchResult(
                    "too_large",
                    url,
                    reason=f"Content-Length {content_length} exceeds cap {max_bytes}",
                    **common,
                )
            chunks: list[bytes] = []
            total = 0
            for chunk in response.iter_bytes():
                total += len(chunk)
                if total > max_bytes:
                    logger.info("request_too_large", url=safe_url, cap=max_bytes)
                    return FetchResult(
                        "too_large", url, reason=f"body exceeded cap {max_bytes}", **common
                    )
                chunks.append(chunk)
            logger.info("request_ok", url=safe_url, status_code=code, bytes=total)
            return FetchResult("ok", url, content=b"".join(chunks), **common)


def polite_client_from_settings(settings: Any, **overrides: Any) -> PoliteClient:
    """Build the client the collectors use, from ``Settings`` (duck-typed for tests)."""
    options: dict[str, Any] = {
        "delay_seconds": settings.corporate_http_delay_seconds,
        "timeout_seconds": settings.corporate_http_timeout_seconds,
        "user_agent": settings.corporate_user_agent,
        "contact_email": settings.corporate_contact_email,
        "max_bytes": settings.corporate_max_document_bytes,
        "max_requests": settings.corporate_max_requests_per_run,
    }
    options.update(overrides)
    return PoliteClient(**options)


__all__ = [
    "DEFAULT_BACKOFF",
    "FetchResult",
    "FetchStatus",
    "PoliteClient",
    "polite_client_from_settings",
    "redacted_url",
]
