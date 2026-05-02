"""
app/models/analysis.py
SQLAlchemy ORM models for the legal analysis domain.
"""
import uuid
from datetime import datetime
from enum import Enum as PyEnum

from sqlalchemy import (
    JSON,
    BigInteger,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    func,
)
from sqlalchemy.dialects.postgresql import ENUM, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.database import Base


class AnalysisStatus(str, PyEnum):
    PENDING    = "pending"
    PROCESSING = "processing"
    COMPLETED  = "completed"
    FAILED     = "failed"


class ClientSide(str, PyEnum):
    DEFENCE     = "defence"
    PROSECUTION = "prosecution"
    ADVISORY    = "advisory"


class Jurisdiction(str, PyEnum):
    INDIA  = "India"
    UK     = "United Kingdom"
    USA    = "United States"
    AUS    = "Australia"
    CAN    = "Canada"
    SGP    = "Singapore"
    UAE    = "UAE"
    EU     = "European Union"


# ─────────────────────────────────────────────────────────────

class Analysis(Base):
    """
    Core entity: one legal analysis request.
    Stores both the input and the full AI-generated result.
    """
    __tablename__ = "analyses"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    # Input
    scenario_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    file_name: Mapped[str | None]     = mapped_column(String(255), nullable=True)
    file_size_bytes: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    extracted_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    content_hash: Mapped[str | None]  = mapped_column(String(64), nullable=True, index=True)

    # Parameters
    jurisdiction: Mapped[str]  = mapped_column(String(50), nullable=False)
    legal_area: Mapped[str]    = mapped_column(String(100), nullable=False, default="Auto-detect")
    client_side: Mapped[str]   = mapped_column(String(20), nullable=False, default="defence")
    source_type: Mapped[str]   = mapped_column(String(20), nullable=False)  # 'scenario' | 'file'

    # Status
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, default=AnalysisStatus.PENDING, index=True
    )
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)

    # AI Result — stored as JSONB for queryability
    result: Mapped[dict | None]    = mapped_column(JSON, nullable=True)
    token_usage: Mapped[dict | None] = mapped_column(JSON, nullable=True)

    # Telemetry
    processing_time_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    cache_hit: Mapped[bool]                = mapped_column(default=False)
    llm_calls: Mapped[int]                 = mapped_column(default=0)

    # Ownership
    api_key_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("api_keys.id", ondelete="SET NULL"), nullable=True
    )

    # Timestamps
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), index=True
    )
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    # Relationships
    api_key: Mapped["APIKey | None"] = relationship("APIKey", back_populates="analyses")

    def __repr__(self) -> str:
        return f"<Analysis id={self.id} status={self.status} jurisdiction={self.jurisdiction}>"


class APIKey(Base):
    """
    API key entity for authentication and rate-limit tracking.
    """
    __tablename__ = "api_keys"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    key_hash: Mapped[str]    = mapped_column(String(128), unique=True, nullable=False, index=True)
    name: Mapped[str]        = mapped_column(String(100), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    is_active: Mapped[bool]  = mapped_column(default=True, index=True)

    # Quota tracking
    requests_today: Mapped[int]  = mapped_column(default=0)
    requests_total: Mapped[int]  = mapped_column(default=0)
    daily_limit: Mapped[int]     = mapped_column(default=100)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    expires_at: Mapped[datetime | None]   = mapped_column(DateTime(timezone=True), nullable=True)

    analyses: Mapped[list["Analysis"]] = relationship(
        "Analysis", back_populates="api_key", lazy="select"
    )

    def __repr__(self) -> str:
        return f"<APIKey id={self.id} name={self.name} active={self.is_active}>"
