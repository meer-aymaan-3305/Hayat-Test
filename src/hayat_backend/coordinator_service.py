"""Coordinator Handoff and Human Appointment Coordination Service.

Governed by: HAYAT_Guardrail_Document_v1.docx (CP-2, CP-5, CP-7, HB-8, DP-7).
Hayat is strictly an intake and routing assistant.
All consultations, scheduling, and appointment confirmations are executed by authorized human coordinators.
Autonomous appointment creation or booking by the chatbot is strictly forbidden.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from uuid import UUID, uuid4

from .audit_logging import ComplianceAuditStore, global_audit_store
from .config import Settings, get_settings
from .schemas.appendix_a import PERMITTED_FIELD_NAMES
from .schemas.coordinator import (
    CoordinatorHandoff,
    CoordinatorRole,
    HandoffStatus,
)


class CoordinatorHandoffError(RuntimeError):
    """Raised when coordinator handoff invariants or policy gates are violated."""


class CoordinatorHandoffService:
    """Manages the lifecycle of coordinator handoffs with strict compliance gates."""

    def __init__(
        self,
        store: Any,
        settings: Settings | None = None,
        audit_store: ComplianceAuditStore | None = None,
    ) -> None:
        self.store = store
        self.settings = settings or get_settings()
        self.audit_store = audit_store or global_audit_store

    def is_consultation_ready(self, conversation: Any) -> bool:
        """Check if sufficient permitted Appendix A facts are present for handoff."""
        facts = getattr(conversation, "case_facts", {})
        has_category = bool(
            facts.get("service_procedure_category")
            or facts.get("procedure_or_service")
            or facts.get("wellness_programme_or_goal")
            or facts.get("care_category")
            or facts.get("customer_category")
        )
        has_destination = bool(
            facts.get("preferred_destination")
            or facts.get("destination_preference")
        )
        has_timing = bool(
            facts.get("travel_dates_flexibility")
            or facts.get("preferred_timing")
            or facts.get("preferred_dates_times")
        )
        return has_category and (has_destination or has_timing)

    def prepare_case_summary(self, conversation: Any) -> dict[str, Any]:
        """Extract only permitted Appendix A fields for coordinator view (DP-1, DP-7)."""
        facts = getattr(conversation, "case_facts", {})
        summary: dict[str, Any] = {}
        for k, v in facts.items():
            if not isinstance(v, dict) and k in PERMITTED_FIELD_NAMES and v not in (None, ""):
                summary[k] = v
        # Map any standard legacy fields to permitted names if not present
        if "service_procedure_category" not in summary:
            cat = facts.get("procedure_or_service") or facts.get("wellness_programme_or_goal")
            if cat:
                summary["service_procedure_category"] = str(cat)
        if "trip_type" not in summary:
            trip = facts.get("customer_category") or facts.get("care_category")
            if trip:
                summary["trip_type"] = "wellness" if "wellness" in str(trip).lower() else "medical"
        if "preferred_destination" not in summary and facts.get("destination_preference"):
            summary["preferred_destination"] = str(facts["destination_preference"])
        if "travel_dates_flexibility" not in summary:
            timing = facts.get("preferred_timing") or facts.get("preferred_dates_times")
            if timing:
                summary["travel_dates_flexibility"] = str(timing)
        return summary

    def build_lead_card(self, conversation: Any, lead: Any, contact_authorized: bool) -> dict[str, Any]:
        """Organised enquiry card so a coordinator can understand and call the visitor.

        Contact details are released only when contact is authorised (Addendum 1.1
        approved and the phone verified); until then the card says so."""
        facts = getattr(conversation, "case_facts", {})

        def pick(*names: str) -> Any:
            for name in names:
                value = facts.get(name)
                if value in (None, ""):
                    for section in facts.values():
                        if isinstance(section, dict) and section.get(name) not in (None, ""):
                            value = section[name]
                            break
                if value not in (None, ""):
                    return value
            return None

        category = pick("customer_category", "care_category", "trip_type")
        category_text = str(category or "").lower()
        lead_category = (
            "wellness" if "wellness" in category_text
            else "medical" if category_text else "general"
        )
        from .reference import enquiry_reference

        card: dict[str, Any] = {
            "reference": enquiry_reference(conversation),
            "lead_category": lead_category,
            "service_or_goal": pick("procedure_or_service", "wellness_programme_or_goal"),
            "preferred_destination": pick("destination_preference", "preferred_destination"),
            "preferred_timing": pick("preferred_timing", "preferred_dates_times"),
            "budget": pick("budget_range", "total_budget_range"),
            "travellers": pick("travellers_count"),
            "accommodation_preference": pick("accommodation_preference"),
            "current_country": pick("current_country"),
            "medical_reports_available": pick("medical_reports_available"),
            "preferred_callback_time": pick("callback_time"),
            "additional_requests": pick("additional_requests"),
            "phone_verified": bool(lead and lead.phone_verified),
        }
        if self.settings.collect_diagnosis:
            card["existing_diagnosis_stated_by_visitor"] = pick("condition_context_for_advisor")
        if contact_authorized:
            card["visitor_name"] = pick("name")
            card["phone_number"] = pick("phone_number")
            card["email"] = pick("email")
        else:
            card["contact_details"] = "Withheld until contact capture is approved (Addendum 1.1)."
        messages = getattr(conversation, "messages", [])
        card["conversation_history"] = [
            {"role": m.role, "content": m.content} for m in messages
        ]
        return {k: v for k, v in card.items() if v not in (None, "")}

    def initiate_handoff(
        self,
        *,
        conversation: Any,
        session_id: UUID,
    ) -> CoordinatorHandoff:
        """Initiate or update a coordinator handoff record adhering to Policy Addendum 1.1."""
        cid = conversation.id
        existing = self.store.get_handoff_for_conversation(cid)
        if existing and existing.status in (
            HandoffStatus.APPOINTMENT_CONFIRMED,
            HandoffStatus.HANDOFF_CLOSED,
        ):
            return existing

        case_summary = self.prepare_case_summary(conversation)

        # CP-5 & DP-2: Verify explicit confirmation was recorded
        has_consent = bool(
            getattr(conversation, "cp5_confirmed_at", None)
            or self.store.has_valid_consent(session_id, "consultation_processing")
        )

        lead = self.store.lead_for(cid)
        is_registered = bool(lead and lead.phone_verified)
        contact_channel = lead.details.preferred_contact_method if lead else "phone"

        # Check Policy Addendum 1.1 approval for contact authorization
        contact_authorized = self.settings.policy_addendum_1_1_approved and is_registered

        if not contact_authorized:
            initial_status = HandoffStatus.AWAITING_REGISTRATION
        elif not existing or existing.status == HandoffStatus.AWAITING_REGISTRATION:
            initial_status = HandoffStatus.AWAITING_COORDINATOR
        else:
            initial_status = existing.status

        if self.settings.extended_intake:
            case_summary["lead_card"] = self.build_lead_card(conversation, lead, contact_authorized)

        handoff = CoordinatorHandoff(
            id=existing.id if existing else uuid4(),
            conversation_id=cid,
            session_id=session_id,
            status=initial_status,
            assigned_coordinator_id=existing.assigned_coordinator_id if existing else None,
            assigned_coordinator_name=existing.assigned_coordinator_name if existing else None,
            coordinator_role=existing.coordinator_role if existing else None,
            case_summary=case_summary,
            contact_channel=contact_channel,
            user_contact_authorized=contact_authorized,
            cp5_consent_verified=has_consent,
            registered_user_verified=is_registered,
            appointment_details=existing.appointment_details if existing else None,
            coordinator_notes=existing.coordinator_notes if existing else [],
            updated_at=datetime.now(UTC),
        )

        saved = self.store.save_coordinator_handoff(handoff)
        self.audit_store.log_coordinator_event(
            handoff_id=saved.id,
            conversation_id=cid,
            status=saved.status.value,
            action="initiate_handoff" if not existing else "update_handoff",
            actor_id="system_handoff_service",
            actor_role="system",
            notes=f"Consent: {has_consent}; ContactAuth: {contact_authorized}; Status: {saved.status.value}",
        )
        return saved

    def assign_coordinator(
        self,
        *,
        handoff_id: UUID,
        coordinator_id: str,
        coordinator_name: str,
        role: CoordinatorRole = CoordinatorRole.CASE_MANAGER,
        notes: str | None = None,
        actor_id: str | None = None,
        actor_role: str | None = None,
    ) -> CoordinatorHandoff:
        """Assign an authorized human coordinator to the case."""
        handoff = self.store.get_coordinator_handoff(handoff_id)
        if not handoff:
            raise CoordinatorHandoffError(f"Handoff {handoff_id} not found.")

        handoff.assigned_coordinator_id = coordinator_id
        handoff.assigned_coordinator_name = coordinator_name
        handoff.coordinator_role = role.value
        handoff.status = HandoffStatus.COORDINATOR_ASSIGNED
        handoff.updated_at = datetime.now(UTC)
        if notes:
            handoff.coordinator_notes.append(f"Assignment [{coordinator_id}]: {notes}")

        saved = self.store.save_coordinator_handoff(handoff)
        self.audit_store.log_coordinator_event(
            handoff_id=saved.id,
            conversation_id=saved.conversation_id,
            status=saved.status.value,
            action="assign_coordinator",
            actor_id=actor_id or coordinator_id,
            actor_role=actor_role or role.value,
            notes=notes,
        )
        return saved

    def update_progress(
        self,
        *,
        handoff_id: UUID,
        status: HandoffStatus,
        coordinator_id: str,
        coordinator_role: str = "case_manager",
        notes: str | None = None,
        contact_channel_used: str | None = None,
    ) -> CoordinatorHandoff:
        """Update case progress (must be initiated by an authorized coordinator)."""
        handoff = self.store.get_coordinator_handoff(handoff_id)
        if not handoff:
            raise CoordinatorHandoffError(f"Handoff {handoff_id} not found.")

        # HB-8: Autonomous confirmation strictly forbidden
        if status == HandoffStatus.APPOINTMENT_CONFIRMED:
            raise CoordinatorHandoffError(
                "Appointments cannot be confirmed via generic progress update. "
                "Use confirm_appointment with coordinator authorization (HB-8)."
            )

        handoff.status = status
        handoff.updated_at = datetime.now(UTC)
        if contact_channel_used:
            handoff.contact_channel = contact_channel_used
        if notes:
            handoff.coordinator_notes.append(f"Progress [{coordinator_id}]: {notes}")

        saved = self.store.save_coordinator_handoff(handoff)
        self.audit_store.log_coordinator_event(
            handoff_id=saved.id,
            conversation_id=saved.conversation_id,
            status=saved.status.value,
            action="update_progress",
            actor_id=coordinator_id,
            actor_role=coordinator_role,
            notes=notes,
        )
        return saved

    def confirm_appointment(
        self,
        *,
        handoff_id: UUID,
        coordinator_id: str,
        coordinator_name: str,
        appointment_time: str,
        provider_or_clinic: str,
        mode: str = "video_consultation",
        notes: str | None = None,
        actor_role: str | None = None,
    ) -> CoordinatorHandoff:
        """Confirm an appointment. Strictly requires human coordinator credentials (HB-8)."""
        if not coordinator_id or not coordinator_name:
            raise PermissionError(
                "Autonomous appointment confirmation is prohibited under HB-8. "
                "An authorized human coordinator credential is required."
            )

        handoff = self.store.get_coordinator_handoff(handoff_id)
        if not handoff:
            raise CoordinatorHandoffError(f"Handoff {handoff_id} not found.")

        handoff.status = HandoffStatus.APPOINTMENT_CONFIRMED
        handoff.appointment_details = {
            "coordinator_id": coordinator_id,
            "coordinator_name": coordinator_name,
            "appointment_time": appointment_time,
            "provider_or_clinic": provider_or_clinic,
            "mode": mode,
            "confirmed_at": datetime.now(UTC).isoformat(),
            "notes": notes,
        }
        handoff.updated_at = datetime.now(UTC)
        if notes:
            handoff.coordinator_notes.append(f"Appointment Confirmed [{coordinator_id}]: {notes}")

        saved = self.store.save_coordinator_handoff(handoff)
        self.audit_store.log_coordinator_event(
            handoff_id=saved.id,
            conversation_id=saved.conversation_id,
            status=saved.status.value,
            action="confirm_appointment",
            actor_id=coordinator_id,
            actor_role=actor_role or "authorized_human_coordinator",
            notes=f"Confirmed for {appointment_time} at {provider_or_clinic}",
        )
        return saved
