"""
app/db/redis_client.py
Redis connection pool, cache helpers, and rate-limit support.
Wraps the redis-py async client with typed helpers.
"""
import json
from typing import Any

import redis.asyncio as aioredis
from redis.asyncio import ConnectionPool, Redis
from redis.exceptions import ConnectionError as RedisConnectionError
from redis.exceptions import RedisError

from app.core.config import get_settings
from app.core.logger import logger


settings = get_settings()

_pool: ConnectionPool | None = None
_client: Redis | None = None


def get_redis_pool() -> ConnectionPool:
    global _pool
    if _pool is None:
        _pool = aioredis.ConnectionPool.from_url(
            str(settings.REDIS_URL),
            max_connections=20,
            socket_timeout=5,
            socket_connect_timeout=5,
            retry_on_timeout=True,
            health_check_interval=30,
            decode_responses=True,
        )
    return _pool


def get_redis() -> Redis:
    global _client
    if _client is None:
        _client = aioredis.Redis(connection_pool=get_redis_pool())
    return _client


# ── Lifecycle ────────────────────────────────────────────────

async def connect_redis() -> None:
    try:
        client = get_redis()
        await client.ping()
        logger.info("Redis connection established", url=str(settings.REDIS_URL))
    except RedisConnectionError as e:
        logger.critical("Cannot connect to Redis", error=str(e))
        raise


async def disconnect_redis() -> None:
    global _pool, _client
    if _client:
        await _client.aclose()
        _client = None
    if _pool:
        await _pool.aclose()
        _pool = None
    logger.info("Redis connection closed")


# ── Cache Helpers ────────────────────────────────────────────

class CacheManager:
    """High-level cache operations with JSON serialisation."""

    def __init__(self, client: Redis) -> None:
        self._r = client

    async def get(self, key: str) -> Any | None:
        try:
            raw = await self._r.get(key)
            if raw is None:
                return None
            return json.loads(raw)
        except RedisError as e:
            logger.warning("Cache GET failed", key=key, error=str(e))
            return None  # Degrade gracefully — don't block on cache miss

    async def set(self, key: str, value: Any, ttl: int | None = None) -> bool:
        try:
            serialised = json.dumps(value, default=str)
            if ttl:
                await self._r.setex(key, ttl, serialised)
            else:
                await self._r.set(key, serialised)
            return True
        except RedisError as e:
            logger.warning("Cache SET failed", key=key, error=str(e))
            return False

    async def delete(self, key: str) -> bool:
        try:
            result = await self._r.delete(key)
            return bool(result)
        except RedisError as e:
            logger.warning("Cache DELETE failed", key=key, error=str(e))
            return False

    async def exists(self, key: str) -> bool:
        try:
            return bool(await self._r.exists(key))
        except RedisError:
            return False

    async def incr_with_ttl(self, key: str, ttl: int) -> int:
        """Atomic increment + set TTL on first call. Used for rate limiting."""
        pipe = self._r.pipeline()
        await pipe.incr(key)
        await pipe.expire(key, ttl)
        results = await pipe.execute()
        return int(results[0])

    async def get_ttl(self, key: str) -> int:
        """Return TTL in seconds, or -1 if key does not exist."""
        try:
            return await self._r.ttl(key)
        except RedisError:
            return -1

    async def keys_by_pattern(self, pattern: str) -> list[str]:
        """Return all keys matching a pattern (use with caution in prod)."""
        try:
            return await self._r.keys(pattern)
        except RedisError:
            return []


# ── Key Builders ─────────────────────────────────────────────

class CacheKeys:
    """Centralised cache key schema to avoid typos."""

    @staticmethod
    def analysis(analysis_id: str) -> str:
        return f"analysis:{analysis_id}"

    @staticmethod
    def analysis_hash(content_hash: str) -> str:
        """Dedup: same scenario text → same result."""
        return f"analysis_hash:{content_hash}"

    @staticmethod
    def rate_limit(api_key: str, endpoint: str) -> str:
        return f"rate:{api_key}:{endpoint}"

    @staticmethod
    def user_analyses(user_id: str) -> str:
        return f"user:{user_id}:analyses"

    @staticmethod
    def health() -> str:
        return "health:ping"
