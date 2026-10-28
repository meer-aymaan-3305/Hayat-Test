from datetime import datetime
from enum import StrEnum
from uuid import UUID

from pydantic import Field

from .common import ContractModel, new_id, now_utc


class ConversationStatus(StrEnum):
    ACTIVE = "active"
    CLOSED = "closed"


class ConversationState(StrEnum):
    EXPLORING = "exploring"
    DISCOVERING_NEEDS = "discovering_needs"
    ANSWERING_QUESTIONS = "answering_questions"
    OFFERING_CONSULTATION = "offering_consultation"
    COLLECTING_DETAILS = "collecting_details"
    AWAITING_CONSENT = "awaiting_consent"
    READY_FOR_SUBMISSION = "ready_for_submission"
    REQUESTED = "requested"
    AWAITING_DETAILS = "awaiting_details"
    AWAITING_VERIFICATION = "awaiting_verification"
    PENDING_COORDINATOR_CONFIRMATION = "pending_coordinator_confirmation"
    CONFIRMED = "confirmed"
    CANCELLED = "cancelled"
    ESCALATED = "escalated"
    COMPLETED = "completed"


class ConversationCreate(ContractModel):
    guest_session_id: UUID
    title: str | None = Field(default=None, max_length=200)


class Conversation(ConversationCreate):
    id: UUID = Field(default_factory=new_id)
    status: ConversationStatus = ConversationStatus.ACTIVE
    created_at: datetime = Field(default_factory=now_utc)
    updated_at: datetime = Field(default_factory=now_utc)
