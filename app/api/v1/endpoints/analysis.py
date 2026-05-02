"""
app/api/v1/endpoints/analysis.py
REST endpoints for legal analysis operations.
Wires FastAPI → AnalysisService → Repository → LLM.
"""
import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, File, Form, Query, UploadFile, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.dependencies import get_analysis_service, get_optional_api_key_id, rate_limit
from app.core.logger import logger
from app.db.database import get_db
from app.schemas.analysis import (
    AnalysisCreateRequest,
    AnalysisResponse,
    JurisdictionEnum,
    LegalAreaEnum,
    ClientSideEnum,
    PaginatedAnalyses,
)
from app.services.analysis_service import AnalysisService

router = APIRouter(prefix="/analyses", tags=["Legal Analysis"])


# ── POST /analyses  (scenario) ───────────────────────────────

@router.post(
    "",
    response_model=AnalysisResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Analyse a legal scenario",
    description=(
        "Submit a plain-text legal scenario. Returns applicable laws, relevant precedents, "
        "smart defence strategy, and possible outcomes. Results are cached for 24 hours."
    ),
)
async def create_scenario_analysis(
    request: AnalysisCreateRequest,
    service: Annotated[AnalysisService, Depends(get_analysis_service)],
    api_key_id: Annotated[uuid.UUID | None, Depends(get_optional_api_key_id)],
    _rl: Annotated[None, Depends(rate_limit("analysis"))],
) -> AnalysisResponse:
    logger.info(
        "Scenario analysis request",
        jurisdiction=request.jurisdiction,
        legal_area=request.legal_area,
        client_side=request.client_side,
        scenario_len=len(request.scenario),
    )
    return await service.create_scenario_analysis(request, api_key_id=api_key_id)


# ── POST /analyses/upload  (file) ────────────────────────────

@router.post(
    "/upload",
    response_model=AnalysisResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Analyse an uploaded case file",
    description=(
        "Upload a PDF, DOCX, DOC, TXT, or RTF case file (max 10MB). "
        "Optionally provide extra context. Returns the same structured analysis as the scenario endpoint."
    ),
)
async def create_file_analysis(
    service: Annotated[AnalysisService, Depends(get_analysis_service)],
    api_key_id: Annotated[uuid.UUID | None, Depends(get_optional_api_key_id)],
    _rl: Annotated[None, Depends(rate_limit("upload"))],
    file: UploadFile = File(..., description="Case document (PDF/DOCX/TXT/RTF, max 10MB)"),
    jurisdiction: JurisdictionEnum = Form(default=JurisdictionEnum.INDIA),
    legal_area: LegalAreaEnum = Form(default=LegalAreaEnum.AUTO),
    client_side: ClientSideEnum = Form(default=ClientSideEnum.DEFENCE),
    extra_context: str = Form(default="", max_length=2000),
) -> AnalysisResponse:
    logger.info(
        "File analysis request",
        filename=file.filename,
        content_type=file.content_type,
        jurisdiction=jurisdiction,
        client_side=client_side,
    )
    return await service.create_file_analysis(
        upload=file,
        jurisdiction=jurisdiction,
        legal_area=legal_area,
        client_side=client_side,
        extra_context=extra_context,
        api_key_id=api_key_id,
    )


# ── GET /analyses  (list) ────────────────────────────────────

@router.get(
    "",
    response_model=PaginatedAnalyses,
    summary="List analyses",
)
async def list_analyses(
    service: Annotated[AnalysisService, Depends(get_analysis_service)],
    api_key_id: Annotated[uuid.UUID | None, Depends(get_optional_api_key_id)],
    jurisdiction: JurisdictionEnum | None = Query(default=None),
    status: str | None = Query(default=None, pattern=r"^(pending|processing|completed|failed)$"),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
) -> PaginatedAnalyses:
    return await service.list_analyses(
        api_key_id=api_key_id,
        status=status,
        jurisdiction=jurisdiction,
        page=page,
        page_size=page_size,
    )


# ── GET /analyses/{id} ───────────────────────────────────────

@router.get(
    "/{analysis_id}",
    response_model=AnalysisResponse,
    summary="Get a single analysis by ID",
)
async def get_analysis(
    analysis_id: uuid.UUID,
    service: Annotated[AnalysisService, Depends(get_analysis_service)],
) -> AnalysisResponse:
    return await service.get_analysis(analysis_id)


# ── GET /analyses/stats ──────────────────────────────────────

@router.get(
    "/meta/stats",
    summary="Platform-wide analysis statistics",
)
async def get_stats(
    service: Annotated[AnalysisService, Depends(get_analysis_service)],
) -> dict:
    return await service.get_stats()
