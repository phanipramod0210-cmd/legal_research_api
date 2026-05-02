"""
app/schemas/analysis.py
Pydantic v2 schemas for all API request/response payloads.
Strict validation with business-rule constraints.
"""
import uuid
from datetime import datetime
from enum import Enum
from typing import Annotated, Any

from pydantic import BaseModel, Field, field_validator, model_validator


# ── Enums ────────────────────────────────────────────────────

class JurisdictionEnum(str, Enum):
    INDIA  = "India"
    UK     = "United Kingdom"
    USA    = "United States"
    AUS    = "Australia"
    CAN    = "Canada"
    SGP    = "Singapore"
    UAE    = "UAE"
    EU     = "European Union"


class LegalAreaEnum(str, Enum):
    AUTO          = "Auto-detect"
    CRIMINAL      = "Criminal Law"
    CIVIL         = "Civil Law"
    FAMILY        = "Family Law"
    CONTRACT      = "Contract Law"
    CORPORATE     = "Corporate Law"
    PROPERTY      = "Property Law"
    LABOUR        = "Labour & Employment"
    CONSTITUTIONAL= "Constitutional Law"
    CONSUMER      = "Consumer Protection"
    IP            = "Intellectual Property"
    TORT          = "Tort Law"


class ClientSideEnum(str, Enum):
    DEFENCE     = "Defence"
    PROSECUTION = "Prosecution"
    ADVISORY    = "Advisory"


class AnalysisStatusEnum(str, Enum):
    PENDING    = "pending"
    PROCESSING = "processing"
    COMPLETED  = "completed"
    FAILED     = "failed"


# ── Request Schemas ──────────────────────────────────────────

class AnalysisCreateRequest(BaseModel):
    """Body for POST /analyses (scenario-based analysis)."""

    scenario: Annotated[str, Field(min_length=40, max_length=10000)]
    jurisdiction: JurisdictionEnum = JurisdictionEnum.INDIA
    legal_area: LegalAreaEnum = LegalAreaEnum.AUTO
    client_side: ClientSideEnum = ClientSideEnum.DEFENCE

    @field_validator("scenario")
    @classmethod
    def strip_scenario(cls, v: str) -> str:
        return v.strip()

    model_config = {
        "json_schema_extra": {
            "example": {
                "scenario": (
                    "My client is a factory worker employed for 11 years who sustained "
                    "a severe hand injury due to an unguarded machine press. The employer "
                    "ignored multiple safety warnings from inspectors. The employer is "
                    "now threatening termination without compensation."
                ),
                "jurisdiction": "India",
                "legal_area": "Labour & Employment",
                "client_side": "Defence",
            }
        }
    }


# ── Sub-schemas for AI Result ─────────────────────────────────

class ApplicableLaw(BaseModel):
    name: str
    year: str | None = None
    relevance: str


class ApplicableSection(BaseModel):
    act: str
    section: str
    provision: str


class CaseLaw(BaseModel):
    citation: str
    court: str
    principle: str


class DefencePillar(BaseModel):
    title: str
    argument: str
    legal_basis: str | None = None
    strength: Annotated[int, Field(ge=0, le=100)] = 70


class KeyArgument(BaseModel):
    argument: str
    legal_hook: str | None = None


class SmartDefence(BaseModel):
    overview: str
    pillars: list[DefencePillar] = []
    key_arguments: list[KeyArgument] = []
    prosecution_counters: list[str] = []
    evidence_required: list[str] = []
    procedural_moves: list[str] = []


class PossibleOutcome(BaseModel):
    type: Annotated[str, Field(pattern=r"^(favorable|adverse|neutral)$")]
    outcome: str
    likelihood: Annotated[int, Field(ge=0, le=100)]
    basis: str


class AnalysisResult(BaseModel):
    """Structured output from the Claude analysis."""
    case_title: str
    legal_areas: list[str]
    scenario_summary: str
    jurisdiction: str
    source_type: str
    applicable_laws: list[ApplicableLaw] = []
    applicable_sections: list[ApplicableSection] = []
    relevant_case_laws: list[CaseLaw] = []
    smart_defence: SmartDefence
    possible_outcomes: list[PossibleOutcome] = []
    litigation_strategy: list[str] = []
    immediate_actions: list[str] = []
    key_risks: list[str] = []


# ── Response Schemas ─────────────────────────────────────────

class TokenUsage(BaseModel):
    input_tokens: int = 0
    output_tokens: int = 0
    total_tokens: int = 0


class AnalysisResponse(BaseModel):
    """Full analysis response returned to clients."""
    id: uuid.UUID
    status: AnalysisStatusEnum
    jurisdiction: str
    legal_area: str
    client_side: str
    source_type: str
    result: AnalysisResult | None = None
    cache_hit: bool = False
    processing_time_ms: int | None = None
    token_usage: TokenUsage | None = None
    created_at: datetime
    completed_at: datetime | None = None
    error_message: str | None = None

    model_config = {"from_attributes": True}


class AnalysisSummary(BaseModel):
    """Lightweight summary for listing endpoints."""
    id: uuid.UUID
    status: AnalysisStatusEnum
    jurisdiction: str
    legal_area: str
    client_side: str
    source_type: str
    case_title: str | None = None
    cache_hit: bool
    processing_time_ms: int | None
    created_at: datetime

    model_config = {"from_attributes": True}


class PaginatedAnalyses(BaseModel):
    items: list[AnalysisSummary]
    total: int
    page: int
    page_size: int
    total_pages: int


# ── API Key Schemas ───────────────────────────────────────────

class APIKeyCreateRequest(BaseModel):
    name: Annotated[str, Field(min_length=3, max_length=100)]
    description: str | None = None
    daily_limit: Annotated[int, Field(ge=1, le=10000)] = 100


class APIKeyResponse(BaseModel):
    id: uuid.UUID
    name: str
    description: str | None
    is_active: bool
    requests_today: int
    requests_total: int
    daily_limit: int
    created_at: datetime
    last_used_at: datetime | None

    model_config = {"from_attributes": True}


class APIKeyCreatedResponse(APIKeyResponse):
    """Only returned on creation — includes the raw key."""
    raw_key: str


# ── Health ────────────────────────────────────────────────────

class ComponentHealth(BaseModel):
    status: str
    latency_ms: float | None = None
    detail: str | None = None


class HealthResponse(BaseModel):
    status: str
    version: str
    environment: str
    components: dict[str, ComponentHealth]
