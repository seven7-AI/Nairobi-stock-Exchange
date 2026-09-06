"""Logging configuration."""

from __future__ import annotations

import json
import logging
from pathlib import Path


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
    """Thin wrapper to keep event-style logging API."""

    def __init__(self, logger: logging.Logger):
        self._logger = logger

    def info(self, event: str, **kwargs: object) -> None:
        payload = {"event": event, **kwargs}
        self._logger.info(json.dumps(payload, default=str))

    def warning(self, event: str, **kwargs: object) -> None:
        payload = {"event": event, **kwargs}
        self._logger.warning(json.dumps(payload, default=str))

    def error(self, event: str, **kwargs: object) -> None:
        payload = {"event": event, **kwargs}
        self._logger.error(json.dumps(payload, default=str))


def get_logger(name: str) -> EventLogger:
    """Return namespaced event logger."""
    return EventLogger(logging.getLogger(name))
