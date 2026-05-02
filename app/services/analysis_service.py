"""
app/services/analysis_service.py
Orchestrates the full legal analysis pipeline:
  1. Deduplication via content hash (Redis cache → DB lookup)
  2. Persist analysis record
  3. Call LLM service
  4. Persist result + cache it
  5. Return structured response

This is the only layer that touches both Repository and LLM Service.
"""
import hashlib
import uuid
from typing import Any

from fastapi import UploadFile
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.exceptions import AnalysisNotFoundException, ScenarioTooShortException
from app.core.logger import logger
from app.db.redis_client import CacheKeys, CacheManager
from app.models.analysis import AnalysisStatus
from app.repositories.analysis_repository import AnalysisRepository
from app.schemas.analysis import (
    AnalysisSummary,
    AnalysisCreateRequest,
    AnalysisResponse,
    PaginatedAnalyses,
)
from app.services.file_service import FileService
from app.services.llm_service import LLMService


settings = get_settings()

_file_service = FileService()
_llm_service  = LLMService()


class AnalysisService:
    """
    Application service: coordinates all sub-services and repositories.
    Follows the Service-Repository pattern strictly.
    """

    def __init__(self, db: AsyncSession, cache: CacheManager) -> None:
        self._repo  = AnalysisRepository(db)
        self._cache = cache

    # ── Scenario Analysis ────────────────────────────────────

    async def create_scenario_analysis(
        self,
        request: AnalysisCreateRequest,
        api_key_id: uuid.UUID | None = None,
    ) -> AnalysisResponse:
        """Run a full legal analysis from a text scenario."""

        scenario = request.scenario.strip()

        if len(scenario) < 40:
            raise ScenarioTooShortException(len(scenario), 40)

        content_hash = self._hash(
            f"{scenario}:{request.jurisdiction}:{request.client_side}"
        )

        # 1. Check Redis cache
        cached = await self._cache.get(CacheKeys.analysis_hash(content_hash))
        if cached:
            logger.info("Cache HIT — returning cached analysis", hash=content_hash[:16])
            analysis = await self._repo.get_by_id(uuid.UUID(cached["id"]))
            return self._to_response(analysis)

        # 2. Check DB for deduplication
        existing = await self._repo.get_by_content_hash(content_hash)
        if existing:
            logger.info("DB dedup HIT", analysis_id=str(existing.id))
            await self._cache.set(
                CacheKeys.analysis_hash(content_hash),
                {"id": str(existing.id)},
                ttl=settings.REDIS_ANALYSIS_CACHE_TTL,
            )
            return self._to_response(existing)

        # 3. Create DB record
        analysis = await self._repo.create(
            jurisdiction=request.jurisdiction,
            legal_area=request.legal_area,
            client_side=request.client_side,
            source_type="scenario",
            scenario_text=scenario,
            content_hash=content_hash,
            api_key_id=api_key_id,
        )

        return await self._run_analysis(
            analysis_id=analysis.id,
            content=scenario,
            jurisdiction=request.jurisdiction,
            legal_area=request.legal_area,
            client_side=request.client_side,
            source_type="scenario",
            content_hash=content_hash,
        )

    # ── File Analysis ────────────────────────────────────────

    async def create_file_analysis(
        self,
        upload: UploadFile,
        jurisdiction: str,
        legal_area: str,
        client_side: str,
        extra_context: str = "",
        api_key_id: uuid.UUID | None = None,
    ) -> AnalysisResponse:
        """Run a full legal analysis from an uploaded case file."""

        # 1. Extract text from file
        extracted = await _file_service.validate_and_extract(upload)

        # Merge extra context
        content = extracted.raw_text
        if extra_context.strip():
            content += f"\n\nAdditional Context:\n{extra_context.strip()}"

        content_hash = self._hash(
            f"{extracted.content_hash}:{jurisdiction}:{client_side}"
        )

        # 2. Cache / dedup checks (same as scenario flow)
        cached = await self._cache.get(CacheKeys.analysis_hash(content_hash))
        if cached:
            logger.info("Cache HIT (file analysis)", hash=content_hash[:16])
            analysis = await self._repo.get_by_id(uuid.UUID(cached["id"]))
            return self._to_response(analysis)

        existing = await self._repo.get_by_content_hash(content_hash)
        if existing:
            return self._to_response(existing)

        # 3. Create DB record
        analysis = await self._repo.create(
            jurisdiction=jurisdiction,
            legal_area=legal_area,
            client_side=client_side,
            source_type="file",
            file_name=extracted.filename,
            file_size_bytes=extracted.size_bytes,
            extracted_text=extracted.raw_text,
            content_hash=content_hash,
            api_key_id=api_key_id,
        )

        return await self._run_analysis(
            analysis_id=analysis.id,
            content=content,
            jurisdiction=jurisdiction,
            legal_area=legal_area,
            client_side=client_side,
            source_type="file",
            content_hash=content_hash,
        )

    # ── Retrieval ────────────────────────────────────────────

    async def get_analysis(self, analysis_id: uuid.UUID) -> AnalysisResponse:
        """Retrieve a single analysis by ID (cache-first)."""

        cached = await self._cache.get(CacheKeys.analysis(str(analysis_id)))
        if cached:
            logger.debug("Cache HIT for analysis retrieval", analysis_id=str(analysis_id))
            analysis = await self._repo.get_by_id(analysis_id)
            return self._to_response(analysis)

        analysis = await self._repo.get_by_id(analysis_id)

        if analysis.status == AnalysisStatus.COMPLETED and analysis.result:
            await self._cache.set(
                CacheKeys.analysis(str(analysis_id)),
                {"id": str(analysis_id)},
                ttl=settings.REDIS_ANALYSIS_CACHE_TTL,
            )

        return self._to_response(analysis)

    async def list_analyses(
        self,
        api_key_id: uuid.UUID | None = None,
        status: str | None = None,
        jurisdiction: str | None = None,
        page: int = 1,
        page_size: int = 20,
    ) -> PaginatedAnalyses:
        items, total = await self._repo.list_analyses(
            api_key_id=api_key_id,
            status=status,
            jurisdiction=jurisdiction,
            page=page,
            page_size=page_size,
        )
        total_pages = (total + page_size - 1) // page_size

        summaries = []
        for a in items:
            case_title = None
            if a.result and isinstance(a.result, dict):
                case_title = a.result.get("caseTitle")
            summaries.append(
                AnalysisSummary(
                    id=a.id,
                    status=a.status,
                    jurisdiction=a.jurisdiction,
                    legal_area=a.legal_area,
                    client_side=a.client_side,
                    source_type=a.source_type,
                    case_title=case_title,
                    cache_hit=a.cache_hit,
                    processing_time_ms=a.processing_time_ms,
                    created_at=a.created_at,
                )
            )

        return PaginatedAnalyses(
            items=summaries,
            total=total,
            page=page,
            page_size=page_size,
            total_pages=total_pages,
        )

    async def get_stats(self) -> dict[str, Any]:
        return await self._repo.get_stats()

    # ── Internal pipeline ────────────────────────────────────

    async def _run_analysis(
        self,
        analysis_id: uuid.UUID,
        content: str,
        jurisdiction: str,
        legal_area: str,
        client_side: str,
        source_type: str,
        content_hash: str,
    ) -> AnalysisResponse:
        """Core pipeline: LLM call → persist → cache → return."""

        await self._repo.mark_processing(analysis_id)

        try:
            llm_result = await _llm_service.analyse(
                content=content,
                jurisdiction=jurisdiction,
                legal_area=legal_area,
                client_side=client_side,
                source_type=source_type,
            )

            analysis = await self._repo.mark_completed(
                analysis_id=analysis_id,
                result=llm_result.raw_result,
                processing_time_ms=llm_result.processing_time_ms,
                token_usage=llm_result.token_usage,
                llm_calls=llm_result.llm_calls,
            )

            # Cache the result
            await self._cache.set(
                CacheKeys.analysis_hash(content_hash),
                {"id": str(analysis_id)},
                ttl=settings.REDIS_ANALYSIS_CACHE_TTL,
            )

            return self._to_response(analysis)

        except Exception as e:
            await self._repo.mark_failed(analysis_id, str(e))
            raise

    # ── Helpers ──────────────────────────────────────────────

    @staticmethod
    def _hash(content: str) -> str:
        return hashlib.sha256(content.encode()).hexdigest()

    @staticmethod
    def _to_response(analysis: Any) -> AnalysisResponse:
        return AnalysisResponse.model_validate(analysis)
