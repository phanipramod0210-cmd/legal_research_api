"""
app/db/database.py
Async SQLAlchemy engine, session factory, and dependency injection.
Uses connection pooling with health checks.
"""
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

from sqlalchemy import event, text
from sqlalchemy.exc import OperationalError
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import DeclarativeBase

from app.core.config import get_settings
from app.core.exceptions import DatabaseException
from app.core.logger import logger


settings = get_settings()


class Base(DeclarativeBase):
    """Declarative base for all ORM models."""
    pass


# ── Engine ───────────────────────────────────────────────────

def create_engine() -> AsyncEngine:
    return create_async_engine(
        str(settings.DATABASE_URL),
        pool_size=settings.DB_POOL_SIZE,
        max_overflow=settings.DB_MAX_OVERFLOW,
        pool_timeout=settings.DB_POOL_TIMEOUT,
        pool_pre_ping=True,          # verify connections before use
        pool_recycle=3600,           # recycle connections hourly
        echo=settings.DB_ECHO,
    )


engine: AsyncEngine = create_engine()

AsyncSessionFactory = async_sessionmaker(
    bind=engine,
    class_=AsyncSession,
    expire_on_commit=False,
    autocommit=False,
    autoflush=False,
)


# ── Dependency ───────────────────────────────────────────────

async def get_db() -> AsyncGenerator[AsyncSession, None]:
    """
    FastAPI dependency that yields an async DB session.
    Rolls back on error, always closes the session.
    """
    async with AsyncSessionFactory() as session:
        try:
            yield session
            await session.commit()
        except OperationalError as e:
            await session.rollback()
            logger.error("DB operational error", error=str(e))
            raise DatabaseException("session", str(e)) from e
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()


# ── Lifecycle ────────────────────────────────────────────────

async def connect_db() -> None:
    """Called at app startup — verify DB connectivity."""
    try:
        async with engine.begin() as conn:
            await conn.execute(text("SELECT 1"))
        logger.info("Database connection established", url=str(settings.DATABASE_URL))
    except Exception as e:
        logger.critical("Cannot connect to database", error=str(e))
        raise


async def disconnect_db() -> None:
    """Called at app shutdown — dispose connection pool."""
    await engine.dispose()
    logger.info("Database connection pool disposed")


@asynccontextmanager
async def get_db_context() -> AsyncGenerator[AsyncSession, None]:
    """Context manager for use outside of request handlers (e.g., scripts)."""
    async with AsyncSessionFactory() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()
