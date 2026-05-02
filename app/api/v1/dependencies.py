"""
app/api/v1/dependencies.py
FastAPI dependency injection providers.
Handles: session scoping, cache injection, auth, rate limiting.
"""
import uuid
from typing import Annotated

from fastapi import Depends, Header, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.exceptions import RateLimitExceededException
from app.core.logger import logger
from app.db.database import get_db
from app.db.redis_client import CacheKeys, CacheManager, get_redis
from app.services.analysis_service import AnalysisService

settings = get_settings()


# ── Cache ────────────────────────────────────────────────────

def get_cache() -> CacheManager:
    return CacheManager(get_redis())


# ── Service ──────────────────────────────────────────────────

def get_analysis_service(
    db: Annotated[AsyncSession, Depends(get_db)],
    cache: Annotated[CacheManager, Depends(get_cache)],
) -> AnalysisService:
    """Inject a fully-wired AnalysisService per request."""
    return AnalysisService(db=db, cache=cache)


# ── Auth (API Key) ───────────────────────────────────────────

async def get_optional_api_key_id(
    x_api_key: Annotated[str | None, Header(alias="X-API-Key")] = None,
    db: AsyncSession = Depends(get_db),
    cache: CacheManager = Depends(get_cache),
) -> uuid.UUID | None:
    """
    Optional API key authentication.
    Returns the API key's UUID if valid, else None.
    In a full production build this would validate against the APIKey table.
    """
    if not x_api_key:
        return None

    # Cache lookup to avoid DB hit on every request
    cache_key = f"apikey:{x_api_key[:16]}"
    cached_id = await cache.get(cache_key)
    if cached_id:
        return uuid.UUID(cached_id["id"])

    # DB lookup (stub — extend with real APIKey repo in production)
    # from app.repositories.api_key_repository import APIKeyRepository
    # key_id = await APIKeyRepository(db).validate(x_api_key)
    # if key_id:
    #     await cache.set(cache_key, {"id": str(key_id)}, ttl=300)
    #     return key_id

    return None


# ── Rate Limiting ─────────────────────────────────────────────

def rate_limit(endpoint: str):
    """
    Factory that returns a per-endpoint rate-limit dependency.
    Uses Redis sliding window via INCR + EXPIRE.
    Limit config comes from settings (e.g. '10/minute').
    """
    limits = {
        "analysis": settings.RATE_LIMIT_ANALYSIS,
        "upload":   settings.RATE_LIMIT_UPLOAD,
        "global":   settings.RATE_LIMIT_GLOBAL,
    }
    limit_str = limits.get(endpoint, "30/minute")
    count_str, period_str = limit_str.split("/")
    max_calls = int(count_str)
    period_seconds = {"second": 1, "minute": 60, "hour": 3600}.get(period_str, 60)

    async def _rate_limit_dependency(
        request: Request,
        cache: CacheManager = Depends(get_cache),
        x_api_key: Annotated[str | None, Header(alias="X-API-Key")] = None,
    ) -> None:
        # Use API key if present, else fall back to client IP
        identifier = x_api_key or request.client.host if request.client else "unknown"
        key = CacheKeys.rate_limit(identifier, endpoint)

        current = await cache.incr_with_ttl(key, period_seconds)
        if current > max_calls:
            ttl = await cache.get_ttl(key)
            logger.warning(
                "Rate limit exceeded",
                identifier=identifier[:8] + "...",
                endpoint=endpoint,
                count=current,
                limit=max_calls,
            )
            raise RateLimitExceededException(limit_str, retry_after=ttl)

    return _rate_limit_dependency
