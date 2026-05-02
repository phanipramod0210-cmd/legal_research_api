"""
app/repositories/analysis_repository.py
Data access layer for Analysis entities.
Service-Repository pattern: services call this, never raw SQLAlchemy.
"""
import uuid
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import desc, func, select, update
from sqlalchemy.exc import IntegrityError, OperationalError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import AnalysisNotFoundException, DatabaseException
from app.core.logger import logger
from app.models.analysis import Analysis, AnalysisStatus


class AnalysisRepository:
    """CRUD + query operations for Analysis model."""

    def __init__(self, db: AsyncSession) -> None:
        self._db = db

    # ── Create ───────────────────────────────────────────────

    async def create(
        self,
        jurisdiction: str,
        legal_area: str,
        client_side: str,
        source_type: str,
        scenario_text: str | None = None,
        file_name: str | None = None,
        file_size_bytes: int | None = None,
        extracted_text: str | None = None,
        content_hash: str | None = None,
        api_key_id: uuid.UUID | None = None,
    ) -> Analysis:
        try:
            analysis = Analysis(
                jurisdiction=jurisdiction,
                legal_area=legal_area,
                client_side=client_side,
                source_type=source_type,
                scenario_text=scenario_text,
                file_name=file_name,
                file_size_bytes=file_size_bytes,
                extracted_text=extracted_text,
                content_hash=content_hash,
                status=AnalysisStatus.PENDING,
                api_key_id=api_key_id,
            )
            self._db.add(analysis)
            await self._db.flush()
            logger.info("Analysis created", analysis_id=str(analysis.id))
            return analysis
        except IntegrityError as e:
            await self._db.rollback()
            raise DatabaseException("create_analysis", str(e)) from e

    # ── Read ─────────────────────────────────────────────────

    async def get_by_id(self, analysis_id: uuid.UUID) -> Analysis:
        stmt = select(Analysis).where(Analysis.id == analysis_id)
        result = await self._db.execute(stmt)
        analysis = result.scalar_one_or_none()
        if analysis is None:
            raise AnalysisNotFoundException(str(analysis_id))
        return analysis

    async def get_by_content_hash(self, content_hash: str) -> Analysis | None:
        """Retrieve a completed analysis by content hash for deduplication."""
        stmt = (
            select(Analysis)
            .where(
                Analysis.content_hash == content_hash,
                Analysis.status == AnalysisStatus.COMPLETED,
            )
            .order_by(desc(Analysis.created_at))
            .limit(1)
        )
        result = await self._db.execute(stmt)
        return result.scalar_one_or_none()

    async def list_analyses(
        self,
        api_key_id: uuid.UUID | None = None,
        status: str | None = None,
        jurisdiction: str | None = None,
        page: int = 1,
        page_size: int = 20,
    ) -> tuple[list[Analysis], int]:
        """Paginated list with optional filters. Returns (items, total_count)."""
        stmt = select(Analysis)
        count_stmt = select(func.count()).select_from(Analysis)

        if api_key_id:
            stmt = stmt.where(Analysis.api_key_id == api_key_id)
            count_stmt = count_stmt.where(Analysis.api_key_id == api_key_id)
        if status:
            stmt = stmt.where(Analysis.status == status)
            count_stmt = count_stmt.where(Analysis.status == status)
        if jurisdiction:
            stmt = stmt.where(Analysis.jurisdiction == jurisdiction)
            count_stmt = count_stmt.where(Analysis.jurisdiction == jurisdiction)

        total = (await self._db.execute(count_stmt)).scalar_one()

        offset = (page - 1) * page_size
        stmt = stmt.order_by(desc(Analysis.created_at)).offset(offset).limit(page_size)
        items = (await self._db.execute(stmt)).scalars().all()

        return list(items), total

    # ── Update ───────────────────────────────────────────────

    async def mark_processing(self, analysis_id: uuid.UUID) -> None:
        await self._db.execute(
            update(Analysis)
            .where(Analysis.id == analysis_id)
            .values(status=AnalysisStatus.PROCESSING, updated_at=func.now())
        )

    async def mark_completed(
        self,
        analysis_id: uuid.UUID,
        result: dict[str, Any],
        processing_time_ms: int,
        token_usage: dict[str, int],
        cache_hit: bool = False,
        llm_calls: int = 1,
    ) -> Analysis:
        try:
            await self._db.execute(
                update(Analysis)
                .where(Analysis.id == analysis_id)
                .values(
                    status=AnalysisStatus.COMPLETED,
                    result=result,
                    processing_time_ms=processing_time_ms,
                    token_usage=token_usage,
                    cache_hit=cache_hit,
                    llm_calls=llm_calls,
                    completed_at=datetime.now(timezone.utc),
                    updated_at=func.now(),
                )
            )
            logger.info(
                "Analysis completed",
                analysis_id=str(analysis_id),
                processing_ms=processing_time_ms,
                cache_hit=cache_hit,
            )
            return await self.get_by_id(analysis_id)
        except OperationalError as e:
            raise DatabaseException("mark_completed", str(e)) from e

    async def mark_failed(self, analysis_id: uuid.UUID, error_message: str) -> None:
        await self._db.execute(
            update(Analysis)
            .where(Analysis.id == analysis_id)
            .values(
                status=AnalysisStatus.FAILED,
                error_message=error_message,
                updated_at=func.now(),
            )
        )
        logger.warning("Analysis failed", analysis_id=str(analysis_id), error=error_message)

    # ── Stats ────────────────────────────────────────────────

    async def get_stats(self) -> dict[str, Any]:
        stats_stmt = select(
            func.count().label("total"),
            func.count().filter(Analysis.status == "completed").label("completed"),
            func.count().filter(Analysis.status == "failed").label("failed"),
            func.count().filter(Analysis.cache_hit.is_(True)).label("cache_hits"),
            func.avg(Analysis.processing_time_ms).label("avg_processing_ms"),
        )
        result = (await self._db.execute(stats_stmt)).one()
        return {
            "total": result.total,
            "completed": result.completed,
            "failed": result.failed,
            "cache_hits": result.cache_hits,
            "cache_hit_rate": round(result.cache_hits / result.total, 3) if result.total else 0,
            "avg_processing_ms": round(result.avg_processing_ms or 0),
        }
