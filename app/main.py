"""
app/main.py
FastAPI application factory.
Wires together: routers, middleware, lifespan, exception handlers.
"""
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware

from app.api.v1.endpoints import analysis, health
from app.core.config import get_settings
from app.core.exceptions import register_exception_handlers
from app.core.logger import logger
from app.db.database import connect_db, disconnect_db
from app.db.redis_client import connect_redis, disconnect_redis
from app.utils.middleware import RequestLoggingMiddleware

settings = get_settings()


# ── Lifespan ─────────────────────────────────────────────────

@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """Startup and shutdown lifecycle."""
    logger.info(
        "Starting LexAI Pro API",
        version=settings.APP_VERSION,
        environment=settings.ENVIRONMENT,
    )
    await connect_db()
    await connect_redis()
    logger.info("All services connected — API ready")

    yield  # Application runs here

    logger.info("Shutting down LexAI Pro API")
    await disconnect_db()
    await disconnect_redis()
    logger.info("Shutdown complete")


# ── App Factory ──────────────────────────────────────────────

def create_app() -> FastAPI:
    app = FastAPI(
        title=settings.APP_NAME,
        version=settings.APP_VERSION,
        description=(
            "## LexAI Pro — AI-Powered Legal Intelligence API\n\n"
            "Analyse legal scenarios or uploaded case files to retrieve:\n"
            "- Applicable acts, sections, and statutes\n"
            "- Relevant case law precedents\n"
            "- Smart defence strategies\n"
            "- Possible legal outcomes with likelihood scores\n\n"
            "**Powered by Anthropic Claude.**"
        ),
        docs_url="/docs" if not settings.is_production else None,
        redoc_url="/redoc" if not settings.is_production else None,
        openapi_url="/openapi.json" if not settings.is_production else None,
        lifespan=lifespan,
    )

    # ── Middleware ────────────────────────────────────────────
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.CORS_ORIGINS,
        allow_credentials=True,
        allow_methods=["GET", "POST", "PUT", "DELETE"],
        allow_headers=["*"],
    )
    app.add_middleware(GZipMiddleware, minimum_size=1000)
    app.add_middleware(RequestLoggingMiddleware)

    # ── Exception Handlers ────────────────────────────────────
    register_exception_handlers(app)

    # ── Routers ───────────────────────────────────────────────
    app.include_router(health.router)
    app.include_router(analysis.router, prefix="/api/v1")

    return app


app = create_app()
