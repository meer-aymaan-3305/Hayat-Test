from datetime import datetime
from enum import StrEnum
from uuid import UUID

from pydantic import Field

from .common import ContractModel, new_id, now_utc


class ConsentType(StrEnum):
    TERMS = "terms"
    PRIVACY = "privacy"
    HEALTH_DATA = "health_data"
    CONSULTATION_PROCESSING = "consultation_processing"


class ConsentCreate(ContractModel):
    guest_session_id: UUID
    consent_type: ConsentType
    granted: bool
    policy_version: str = Field(min_length=1, max_length=50)


class ConsentRecord(ConsentCreate):
    id: UUID = Field(default_factory=new_id)
    recorded_at: datetime = Field(default_factory=now_utc)
