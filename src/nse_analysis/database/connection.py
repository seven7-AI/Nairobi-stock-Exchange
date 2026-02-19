"""Supabase connection management with retries and health checks."""

from __future__ import annotations

import random
import time
from collections.abc import Callable
from typing import Any, TypeVar

from supabase import Client, create_client

from nse_analysis.config import Settings
from nse_analysis.utils.exceptions import DatabaseConnectionError
from nse_analysis.utils.logger import get_logger

T = TypeVar("T")


class SupabaseConnection:
    """Wrapper around Supabase client with resilient query execution."""

    def __init__(self, settings: Settings, max_retries: int = 3, base_delay_seconds: float = 0.75):
        self._settings = settings
        self._max_retries = max_retries
        self._base_delay_seconds = base_delay_seconds
        self._logger = get_logger("nse_analysis.database.connection")
        self._client: Client = create_client(settings.supabase_url, settings.supabase_key)

    @property
    def client(self) -> Client:
        """Expose underlying Supabase client for advanced usage."""
        return self._client

    def execute_with_retry(self, operation: Callable[[], T], operation_name: str) -> T:
        """Execute operation with bounded exponential backoff + jitter."""
        errors: list[str] = []
        for attempt in range(1, self._max_retries + 1):
            try:
                result = operation()
                self._logger.info(
                    "supabase_operation_success",
                    operation=operation_name,
                    attempt=attempt,
                )
                return result
            except Exception as exc:  # noqa: BLE001
                error_message = f"{type(exc).__name__}: {exc}"
                errors.append(error_message)
                if attempt >= self._max_retries:
                    break
                delay = self._base_delay_seconds * (2 ** (attempt - 1))
                jitter = random.uniform(0.0, 0.25)
                sleep_for = delay + jitter
                self._logger.warning(
                    "supabase_operation_retry",
                    operation=operation_name,
                    attempt=attempt,
                    error=error_message,
                    retry_in_seconds=round(sleep_for, 2),
                )
                time.sleep(sleep_for)
        raise DatabaseConnectionError(
            f"Operation '{operation_name}' failed after {self._max_retries} attempts. Errors: {errors}"
        )

    def health_check(self, table_name: str) -> dict[str, Any]:
        """Run lightweight health check query."""
        def _query() -> Any:
            return self._client.table(table_name).select("*").limit(1).execute()

        response = self.execute_with_retry(_query, "health_check")
        data_rows = getattr(response, "data", [])
        return {"ok": True, "table": table_name, "sample_rows": len(data_rows)}
