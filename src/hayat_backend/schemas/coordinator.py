"""Data models and contracts for coordinator-led consultation handoff.

Governed by: HAYAT_Guardrail_Document_v1.docx (CP-2, CP-5, CP-7, HB-8).
Appointments are strictly coordinated and confirmed by authorized human coordinators.
"""

from __future__ import annotations

from datetime import datetime, timezone
from enum import StrEnum
from typing import Any
from uuid import UUID, uuid4

from pydantic import Field

from .common import ContractModel


class HandoffStatus(StrEnum):
    """Authoritative lifecycle statuses for coordinator handoff."""

    AWAITING_REGISTRATION = "awaiting_registration"
    AWAITING_COORDINATOR = "awaiting_coordinator"
    COORDINATOR_ASSIGNED = "coordinator_assigned"
    CONTACT_PENDING = "contact_pending"
    COORDINATOR_CONTACTED = "coordinator_contacted"
    APPOINTMENT_COORDINATION = "appointment_coordination"
    APPOINTMENT_CONFIRMED = "appointment_confirmed"
    HANDOFF_CLOSED = "handoff_closed"


class CoordinatorRole(StrEnum):
    """Authorized human coordinator roles at Trawellcare."""

    WELLNESS_CURATOR = "wellness_curator"
    CASE_MANAGER = "case_manager"
    LEAD_COORDINATOR = "lead_coordinator"


class CoordinatorHandoff(ContractModel):
    """Persistent handoff record tracking coordinator workflow progress."""

    id: UUID = Field(default_factory=uuid4)
    conversation_id: UUID
    session_id: UUID
    status: HandoffStatus = HandoffStatus.AWAITING_REGISTRATION
    assigned_coordinator_id: str | None = None
    assigned_coordinator_name: str | None = None
    coordinator_role: str | None = None
    case_summary: dict[str, Any] = Field(default_factory=dict)
    contact_channel: str | None = None
    user_contact_authorized: bool = False
    cp5_consent_verified: bool = False
    registered_user_verified: bool = False
    appointment_details: dict[str, Any] | None = None
    coordinator_notes: list[str] = Field(default_factory=list)
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class CoordinatorAssignRequest(ContractModel):
    """Request to assign an authorized human coordinator to a case."""

    coordinator_id: str = Field(min_length=2, max_length=100)
    coordinator_name: str = Field(min_length=2, max_length=200)
    role: CoordinatorRole = CoordinatorRole.CASE_MANAGER
    notes: str | None = Field(default=None, max_length=1000)


class CoordinatorProgressRequest(ContractModel):
    """Request by an authorized coordinator to update handoff lifecycle status."""

    status: HandoffStatus
    notes: str | None = Field(default=None, max_length=1000)
    contact_channel_used: str | None = Field(default=None, max_length=50)


class AppointmentConfirmationRequest(ContractModel):
    """Confirmation request requiring authorized human credentials (HB-8)."""

    coordinator_id: str = Field(min_length=2, max_length=100)
    coordinator_name: str = Field(min_length=2, max_length=200)
    appointment_time: str = Field(min_length=5, max_length=100)
    provider_or_clinic: str = Field(min_length=2, max_length=200)
    mode: str = Field(default="video_consultation", max_length=50)
    notes: str | None = Field(default=None, max_length=1000)


class HandoffStatusResponse(ContractModel):
    """Publicly visible handoff status response."""

    id: UUID
    conversation_id: UUID
    status: HandoffStatus
    assigned_coordinator_name: str | None = None
    coordinator_role: str | None = None
    appointment_confirmed: bool = False
    appointment_details: dict[str, Any] | None = None
    updated_at: datetime
