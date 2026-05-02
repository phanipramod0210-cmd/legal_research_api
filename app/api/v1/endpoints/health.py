"""
app/api/v1/endpoints/health.py
Liveness and readiness health check endpoints.
Checks DB and Redis connectivity with latency reporting.
"""
import time

from fastapi import APIRouter, Depends
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.db.database import get_db
from app.db.redis_client import get_redis
from app.schemas.analysis import ComponentHealth, HealthResponse

router = APIRouter(tags=["Health"])
settings = get_settings()


@router.get("/health", response_model=HealthResponse, summary="Service health check")
async def health_check(db: AsyncSession = Depends(get_db)) -> HealthResponse:
    components: dict[str, ComponentHealth] = {}

    # ── Database ─────────────────────────────────────────────
    t0 = time.perf_counter()
    try:
        await db.execute(text("SELECT 1"))
        components["database"] = ComponentHealth(
            status="healthy",
            latency_ms=round((time.perf_counter() - t0) * 1000, 2),
        )
    except Exception as e:
        components["database"] = ComponentHealth(status="unhealthy", detail=str(e))

    # ── Redis ────────────────────────────────────────────────
    t0 = time.perf_counter()
    try:
        redis = get_redis()
        await redis.ping()
        components["redis"] = ComponentHealth(
            status="healthy",
            latency_ms=round((time.perf_counter() - t0) * 1000, 2),
        )
    except Exception as e:
        components["redis"] = ComponentHealth(status="unhealthy", detail=str(e))

    # ── LLM ──────────────────────────────────────────────────
    components["llm"] = ComponentHealth(
        status="configured",
        detail=f"Model: {settings.ANTHROPIC_MODEL}",
    )

    overall = (
        "healthy"
        if all(c.status in ("healthy", "configured") for c in components.values())
        else "degraded"
    )

    return HealthResponse(
        status=overall,
        version=settings.APP_VERSION,
        environment=settings.ENVIRONMENT,
        components=components,
    )


@router.get("/ready", summary="Kubernetes readiness probe")
async def readiness() -> dict:
    return {"ready": True}


@router.get("/live", summary="Kubernetes liveness probe")
async def liveness() -> dict:
    return {"alive": True}
