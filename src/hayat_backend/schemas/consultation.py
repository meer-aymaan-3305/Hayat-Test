from datetime import datetime
from enum import StrEnum
from uuid import UUID

from pydantic import Field

from .common import ContractModel


class PreferredContactMethod(StrEnum):
    PHONE = "phone"
    WHATSAPP = "whatsapp"
    EMAIL = "email"


class ConsultationStatus(StrEnum):
    PENDING = "pending"
    CONFIRMED = "confirmed"
    CANCELLED = "cancelled"


class ConsultationDetails(ContractModel):
    name: str = Field(min_length=2, max_length=200)
    phone_number: str = Field(min_length=7, max_length=30)
    email: str | None = Field(default=None, max_length=320)
    preferred_contact_method: PreferredContactMethod = PreferredContactMethod.PHONE
    care_category: str = Field(min_length=2, max_length=100)
    procedure_or_service: str | None = Field(default=None, max_length=200)
    destination_preference: str | None = Field(default=None, max_length=100)
    preferred_timing: str | None = Field(default=None, max_length=200)
    budget_range: str | None = Field(default=None, max_length=100)
    companions_or_accessibility: str | None = Field(default=None, max_length=500)
    preferred_dates_times: str | None = Field(default=None, max_length=500)
    timezone: str | None = Field(default=None, max_length=100)


class OTPStartRequest(ContractModel):
    conversation_id: UUID
    phone_number: str = Field(min_length=7, max_length=30)
    recaptcha_token: str | None = Field(default=None, max_length=10_000)


class OTPStartResponse(ContractModel):
    challenge_id: str
    expires_in_seconds: int = Field(default=300, ge=1)


class OTPVerifyRequest(ContractModel):
    conversation_id: UUID
    challenge_id: str = Field(min_length=1, max_length=200)
    code: str | None = Field(default=None, min_length=4, max_length=10)
    firebase_id_token: str | None = Field(default=None, min_length=20, max_length=10_000)


class ConsultationCreate(ConsultationDetails):
    conversation_id: UUID
    consent_policy_version: str = Field(min_length=1, max_length=50)


class ConsultationResponse(ConsultationCreate):
    id: UUID
    status: ConsultationStatus
    phone_verified: bool
    submitted_at: datetime
