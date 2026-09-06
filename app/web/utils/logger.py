"""Structured logging with credential redaction.

**Nothing in this service may emit a credential.** Supabase keys, JWTs and
refresh tokens, password hashes, connector API keys, and session cookies are
all redacted here rather than at each call site, because relying on every
caller to remember is how one eventually leaks.

Redaction is by key name and by value shape: a field whose *name* looks
sensitive is masked, and so is a value that looks like a bearer token even
under an innocuous key.

    codegraph explore "EventLogger redact_value get_logger configure_logging"
"""

from __future__ import annotations

import json
import logging
import re
from pathlib import Path
from typing import Any

REDACTED = "***REDACTED***"

#: Substrings that mark a field name as sensitive.
SENSITIVE_KEY_PARTS: frozenset[str] = frozenset(
    {
        "password",
        "passwd",
        "secret",
        "token",
        "authorization",
        "api_key",
        "apikey",
        "access_key",
        "private_key",
        "credential",
        "supabase_key",
        "jwt",
        "session",
        "cookie",
        "hashed",
        "salt",
        "signature",
    }
)

#: Value shapes that are sensitive regardless of the key they appear under.
SENSITIVE_VALUE_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"^Bearer\s+\S+", re.IGNORECASE),
    re.compile(r"^ey[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\.?"),  # JWT
    re.compile(r"^sb[a-z]?_[A-Za-z0-9_-]{16,}"),  # Supabase key
    re.compile(r"^\$2[aby]\$\d{2}\$"),  # bcrypt hash
)

MAX_REDACTION_DEPTH = 6


def _is_sensitive_key(key: str) -> bool:
    lowered = key.lower()
    return any(part in lowered for part in SENSITIVE_KEY_PARTS)


def _is_sensitive_value(value: str) -> bool:
    return any(pattern.match(value) for pattern in SENSITIVE_VALUE_PATTERNS)


def redact_value(value: Any, *, depth: int = 0) -> Any:
    """Recursively mask sensitive fields in a log payload."""
    if depth >= MAX_REDACTION_DEPTH:
        return value
    if isinstance(value, dict):
        return {
            key: REDACTED if _is_sensitive_key(str(key)) else redact_value(item, depth=depth + 1)
            for key, item in value.items()
        }
    if isinstance(value, (list, tuple)):
        return [redact_value(item, depth=depth + 1) for item in value]
    if isinstance(value, str) and _is_sensitive_value(value):
        return REDACTED
    return value


def redact_event(payload: dict[str, Any]) -> dict[str, Any]:
    """Redact a whole event payload."""
    result = redact_value(payload)
    return result if isinstance(result, dict) else {"event": "redaction_failed"}


def configure_logging(log_file: Path, log_level: str = "INFO") -> None:
    """Configure stdlib logging outputs for production use."""
    log_file.parent.mkdir(parents=True, exist_ok=True)
    level = getattr(logging, log_level.upper(), logging.INFO)
    logging.basicConfig(
        level=level,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
        handlers=[
            logging.StreamHandler(),
            logging.FileHandler(log_file, encoding="utf-8"),
        ],
    )


class EventLogger:
    """Event-style logging wrapper. Every payload passes through redaction."""

    def __init__(self, logger: logging.Logger):
        self._logger = logger

    def _emit(self, level: int, event: str, **kwargs: object) -> None:
        payload = redact_event({"event": event, **kwargs})
        self._logger.log(level, json.dumps(payload, default=str))

    def debug(self, event: str, **kwargs: object) -> None:
        self._emit(logging.DEBUG, event, **kwargs)

    def info(self, event: str, **kwargs: object) -> None:
        self._emit(logging.INFO, event, **kwargs)

    def warning(self, event: str, **kwargs: object) -> None:
        self._emit(logging.WARNING, event, **kwargs)

    def error(self, event: str, **kwargs: object) -> None:
        self._emit(logging.ERROR, event, **kwargs)

    def exception(self, event: str, **kwargs: object) -> None:
        payload = redact_event({"event": event, **kwargs})
        self._logger.exception(json.dumps(payload, default=str))


def get_logger(name: str) -> EventLogger:
    """Return namespaced event logger."""
    return EventLogger(logging.getLogger(name))


__all__ = [
    "REDACTED",
    "EventLogger",
    "configure_logging",
    "get_logger",
    "redact_event",
    "redact_value",
]
