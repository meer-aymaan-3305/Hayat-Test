"""Signature Wellness Programmes Schema Specification.

This module defines data structures for Trawellcare's Signature Wellness Programmes
(HAYAT-100, AAfiya, FFounders) as a separate service category from the medical-travel
intake workflow governed by Appendix A.
"""

from __future__ import annotations

from datetime import UTC, datetime
from enum import Enum
from typing import Any
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field


class ProgrammeId(str, Enum):
    HAYAT_100 = "hayat_100"
    AAFIYA = "aafiya"
    FFOUNDERS = "ffounders"


class ProgrammeStage(str, Enum):
    DISCOVERY = "discovery"
    PROGRAMME_SELECTED = "programme_selected"
    PREFERENCE_COLLECTION = "preference_collection"
    DESTINATION_PREFERENCE = "destination_preference"
    TRAVEL_PERIOD = "travel_period"
    EXPERIENCE_PREFERENCES = "experience_preferences"
    GROUP_PREFERENCES = "group_preferences"
    OPTIONAL_BUDGET = "optional_budget"
    SUMMARY_REVIEW = "summary_review"
    REGISTRATION_CONSENT = "registration_consent"
    REGISTRATION_PENDING = "registration_pending"
    REGISTERED_INTEREST = "registered_interest"
    COORDINATOR_HANDOFF = "coordinator_handoff"


class EnquiryStatus(str, Enum):
    DRAFT = "draft"
    SUBMITTED = "submitted"
    ASSIGNED = "assigned"
    PROPOSAL_EXPLORING = "proposal_exploring"
    CLOSED = "closed"


class RegistrationStatus(str, Enum):
    UNREGISTERED = "unregistered"
    INTEREST_REGISTERED = "interest_registered"


class ContactConsentStatus(str, Enum):
    PENDING = "pending"
    GRANTED = "granted"
    REFUSED = "refused"


class ProgrammeFAQ(BaseModel):
    model_config = ConfigDict(frozen=True)
    question: str
    answer: str


class ProgrammeDetail(BaseModel):
    model_config = ConfigDict(frozen=True)
    programme_id: ProgrammeId
    name: str
    tagline: str
    focus: str
    philosophy: str
    duration_total_days: int = 7
    retreat_days: int = 5
    travel_days: int = 2
    intended_audience: list[str]
    distinguishing_themes: list[str]
    proposed_experiences: dict[str, list[str]]
    pricing_model: str = "Individually curated; no fixed package price"
    candidate_destinations: list[str] = [
        "United States",
        "Spain",
        "Japan",
        "Singapore",
        "India",
        "United Arab Emirates",
        "Other / Undecided",
    ]
    faqs: list[ProgrammeFAQ] = []


class SignatureProgrammeEnquiry(BaseModel):
    """Enquiry preference record for Signature Wellness Programmes.

    Maintains strict data separation from Appendix A medical intake.
    Contains non-clinical retreat preferences and interest registration.
    """

    model_config = ConfigDict(extra="forbid")

    enquiry_id: UUID = Field(default_factory=uuid4)
    conversation_id: UUID
    session_id: UUID
    current_stage: ProgrammeStage = ProgrammeStage.DISCOVERY
    reference_code: str | None = None
    interested_programmes: list[str] = Field(default_factory=list)
    primary_programme: str | None = None
    destination_preference: str | None = None
    preferred_region: str | None = None
    preferred_travel_period: str | None = None
    preferred_month: str | None = None
    expected_experience: str | None = None
    activity_interests: list[str] = Field(default_factory=list)
    group_participation: bool = False
    group_size: int | None = None
    budget_range: str | None = None
    preferred_contact_method: str | None = None
    enquiry_status: EnquiryStatus = EnquiryStatus.DRAFT
    contact_consent_status: ContactConsentStatus = ContactConsentStatus.PENDING
    registration_status: RegistrationStatus = RegistrationStatus.UNREGISTERED
    assigned_coordinator_id: str | None = None
    coordinator_notes: list[str] = Field(default_factory=list)
    lead_name: str | None = None
    lead_phone: str | None = None
    lead_email: str | None = None
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class SignatureProgrammeEnquiryCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    conversation_id: UUID
    session_id: UUID
    current_stage: ProgrammeStage = ProgrammeStage.DISCOVERY
    reference_code: str | None = None
    interested_programmes: list[str] = Field(default_factory=list)
    primary_programme: str | None = None
    destination_preference: str | None = None
    preferred_region: str | None = None
    preferred_travel_period: str | None = None
    preferred_month: str | None = None
    expected_experience: str | None = None
    activity_interests: list[str] = Field(default_factory=list)
    group_participation: bool = False
    group_size: int | None = None
    budget_range: str | None = None
    preferred_contact_method: str | None = None


class SignatureProgrammeEnquiryUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    current_stage: ProgrammeStage | None = None
    reference_code: str | None = None
    interested_programmes: list[str] | None = None
    primary_programme: str | None = None
    destination_preference: str | None = None
    preferred_region: str | None = None
    preferred_travel_period: str | None = None
    preferred_month: str | None = None
    expected_experience: str | None = None
    activity_interests: list[str] | None = None
    group_participation: bool | None = None
    group_size: int | None = None
    budget_range: str | None = None
    preferred_contact_method: str | None = None
    enquiry_status: EnquiryStatus | None = None
    contact_consent_status: ContactConsentStatus | None = None
    registration_status: RegistrationStatus | None = None
    assigned_coordinator_id: str | None = None
    coordinator_notes: list[str] | None = None
    lead_name: str | None = None
    lead_phone: str | None = None
    lead_email: str | None = None


class SignatureProgrammeRegistrationRequest(BaseModel):
    """Payload for registering interest with contact details via secure portal."""

    model_config = ConfigDict(extra="forbid")

    full_name: str | None = None
    phone_number: str | None = None
    email: str | None = None
    contact_consent: bool = True
    preferred_contact_method: str = "phone"


class SignatureProgrammeEnquiryResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    enquiry: SignatureProgrammeEnquiry
    summary_text: str
    coordinator_assigned: bool = False
