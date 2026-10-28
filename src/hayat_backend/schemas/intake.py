from datetime import datetime
from uuid import UUID

from enum import StrEnum
from typing import Any
from uuid import UUID

from pydantic import Field

from .common import ContractModel, new_id, now_utc


class IntakeData(ContractModel):
    goals: list[str] = Field(default_factory=list, max_length=20)
    symptoms: list[str] = Field(default_factory=list, max_length=50)
    constraints: list[str] = Field(default_factory=list, max_length=50)
    answers: dict[str, str] = Field(default_factory=dict)


class CaseFacts(ContractModel):
    id: UUID = Field(default_factory=new_id)
    conversation_id: UUID
    facts: IntakeData
    captured_at: datetime = Field(default_factory=now_utc)
    version: int = Field(default=1, ge=1)


class FactStatus(StrEnum):
    CONFIRMED = "confirmed"
    INFERRED = "inferred"
    UNKNOWN = "unknown"
    REQUIRES_CLARIFICATION = "requires_clarification"


class FactValue(ContractModel):
    field_name: str = Field(min_length=1, max_length=100)
    value: Any | None = None
    status: FactStatus
    source_message_id: UUID | None = None
    confidence: float | None = Field(default=None, ge=0, le=1)
    captured_at: datetime = Field(default_factory=now_utc)
    extraction_version: str = "facts_v1"


class PersonaReadyProfile(ContractModel):
    schema_version: str = "personaProfile_v1"
    conversation_id: UUID
    facts: list[FactValue] = Field(default_factory=list, max_length=200)
    generated_at: datetime = Field(default_factory=now_utc)


class ConsultationProgress(ContractModel):
    required_fields: list[str] = Field(default_factory=list, max_length=20)
    collected_fields: list[str] = Field(default_factory=list, max_length=20)
    missing_fields: list[str] = Field(default_factory=list, max_length=20)
    consent_granted: bool = False
    phone_verified: bool = False
    request_status: str | None = None
