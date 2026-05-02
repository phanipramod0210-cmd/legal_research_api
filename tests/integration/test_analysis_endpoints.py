"""
tests/integration/test_analysis_endpoints.py
Integration tests using httpx AsyncClient.
Mocks the LLM service to avoid real API calls.
"""
import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from app.main import app
from app.services.llm_service import LLMAnalysisResult

MOCK_LLM_RESULT = {
    "caseTitle": "Worker Injury Claim",
    "legalAreas": ["Labour Law"],
    "scenarioSummary": "Factory worker injured by unguarded machinery.",
    "jurisdiction": "India",
    "sourceType": "scenario",
    "applicableLaws": [
        {"name": "Employees' Compensation Act", "year": "1923", "relevance": "Mandates compensation."}
    ],
    "applicableSections": [
        {"act": "ECA 1923", "section": "Sec 3 — Employer Liability", "provision": "Employer liable for accidental injury."}
    ],
    "relevantCaseLaws": [
        {"citation": "National Insurance Co. v Swaran Singh, SC 2004", "court": "Supreme Court of India", "principle": "Establishes strict liability."}
    ],
    "smartDefence": {
        "overview": "Strong case: documented inspector warnings prove employer negligence.",
        "pillars": [
            {"title": "Employer Negligence", "argument": "Prior warnings ignored.", "legalBasis": "Sec 3 ECA", "strength": 85}
        ],
        "keyArguments": [
            {"argument": "Inspector reports prove prior knowledge.", "legalHook": "Sec 3 ECA 1923"}
        ],
        "prosecutionCounters": ["Worker bypassed safety protocol."],
        "evidenceRequired": ["Inspector reports", "Medical records", "PF slips"],
        "proceduralMoves": ["File claim before Commissioner."],
    },
    "possibleOutcomes": [
        {"type": "favorable", "outcome": "Full compensation awarded.", "likelihood": 75, "basis": "Strong negligence evidence."},
        {"type": "adverse", "outcome": "Partial reduction for contributory negligence.", "likelihood": 20, "basis": "Employer argues worker fault."},
        {"type": "neutral", "outcome": "Negotiated settlement.", "likelihood": 50, "basis": "Mediation route."},
    ],
    "litigationStrategy": ["File before Labour Commissioner.", "Seek interim relief."],
    "immediateActions": ["Preserve all medical records."],
    "keyRisks": ["Statute of limitations — file within 2 years."],
}


@pytest.fixture
def mock_llm_result():
    return LLMAnalysisResult(
        raw_result=MOCK_LLM_RESULT,
        token_usage={"input_tokens": 500, "output_tokens": 800, "total_tokens": 1300},
        processing_time_ms=1200,
        llm_calls=1,
    )


@pytest_asyncio.fixture
async def client():
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as ac:
        yield ac


class TestHealthEndpoints:
    async def test_liveness(self, client: AsyncClient) -> None:
        response = await client.get("/live")
        assert response.status_code == 200
        assert response.json()["alive"] is True

    async def test_readiness(self, client: AsyncClient) -> None:
        response = await client.get("/ready")
        assert response.status_code == 200
        assert response.json()["ready"] is True


class TestAnalysisEndpoints:
    async def test_create_scenario_analysis_success(
        self, client: AsyncClient, mock_llm_result
    ) -> None:
        with (
            patch("app.services.analysis_service.AnalysisService.create_scenario_analysis") as mock_svc,
        ):
            mock_response = MagicMock()
            mock_response.id = uuid.uuid4()
            mock_response.status = "completed"
            mock_response.jurisdiction = "India"
            mock_response.legal_area = "Labour & Employment"
            mock_response.client_side = "Defence"
            mock_response.source_type = "scenario"
            mock_response.cache_hit = False
            mock_response.processing_time_ms = 1200
            mock_response.model_dump = lambda: {"id": str(mock_response.id), "status": "completed"}
            mock_svc.return_value = mock_response

            response = await client.post(
                "/api/v1/analyses",
                json={
                    "scenario": "A factory worker was injured by an unguarded machine press. "
                                "The employer had been warned multiple times by the factory inspector "
                                "but failed to install safety guards.",
                    "jurisdiction": "India",
                    "legal_area": "Labour & Employment",
                    "client_side": "Defence",
                },
            )
        assert response.status_code == 201

    async def test_scenario_too_short_rejected(self, client: AsyncClient) -> None:
        response = await client.post(
            "/api/v1/analyses",
            json={
                "scenario": "Short",
                "jurisdiction": "India",
            },
        )
        assert response.status_code == 422

    async def test_invalid_jurisdiction_rejected(self, client: AsyncClient) -> None:
        response = await client.post(
            "/api/v1/analyses",
            json={
                "scenario": "A" * 100,
                "jurisdiction": "Mars",
            },
        )
        assert response.status_code == 422

    async def test_get_analysis_not_found(self, client: AsyncClient) -> None:
        fake_id = uuid.uuid4()
        with patch("app.services.analysis_service.AnalysisService.get_analysis") as mock_get:
            from app.core.exceptions import AnalysisNotFoundException
            mock_get.side_effect = AnalysisNotFoundException(str(fake_id))
            response = await client.get(f"/api/v1/analyses/{fake_id}")
        assert response.status_code == 404
        assert response.json()["error"]["code"] == "ANALYSIS_NOT_FOUND"

    async def test_list_analyses_pagination(self, client: AsyncClient) -> None:
        with patch("app.services.analysis_service.AnalysisService.list_analyses") as mock_list:
            from app.schemas.analysis import PaginatedAnalyses
            mock_list.return_value = PaginatedAnalyses(
                items=[], total=0, page=1, page_size=20, total_pages=0
            )
            response = await client.get("/api/v1/analyses?page=1&page_size=20")
        assert response.status_code == 200
        data = response.json()
        assert "items" in data
        assert "total" in data
