"""Redis cache service.

Used for the read-heavy, slow-changing things: instrument lists, indicator
snapshots, organization settings. Never for anything that must survive a
restart, and never for credentials.
"""

from __future__ import annotations

import json
from typing import Any

from redis.asyncio import Redis, from_url

from app.web.config import Settings
from app.web.utils.logger import get_logger

logger = get_logger("app.web.services.redis")

DEFAULT_TTL_SECONDS = 300


class RedisService:
    """Thin async wrapper with JSON helpers and namespaced keys."""

    def __init__(self, client: Redis, namespace: str = "nse") -> None:
        self._client = client
        self._namespace = namespace

    @classmethod
    def from_settings(cls, settings: Settings) -> RedisService:
        client: Redis = from_url(settings.redis_url, decode_responses=True)
        return cls(client=client, namespace=settings.app_name)

    @property
    def client(self) -> Redis:
        return self._client

    def key(self, *parts: str) -> str:
        return ":".join((self._namespace, *parts))

    async def get_json(self, *parts: str) -> Any | None:
        raw = await self._client.get(self.key(*parts))
        if raw is None:
            return None
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            logger.warning("redis_cache_decode_failed", key=self.key(*parts))
            return None

    async def set_json(
        self, value: Any, *parts: str, ttl_seconds: int = DEFAULT_TTL_SECONDS
    ) -> None:
        await self._client.set(self.key(*parts), json.dumps(value, default=str), ex=ttl_seconds)

    async def delete(self, *parts: str) -> None:
        await self._client.delete(self.key(*parts))

    async def ping(self) -> bool:
        try:
            return bool(await self._client.ping())
        except Exception:
            logger.warning("redis_ping_failed")
            return False

    async def close(self) -> None:
        await self._client.aclose()


__all__ = ["DEFAULT_TTL_SECONDS", "RedisService"]
