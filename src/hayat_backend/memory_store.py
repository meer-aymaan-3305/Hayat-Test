"""In-memory repository used for local development and unit tests.

Production persistence is provided by the Supabase migration/repository
boundary; this store makes the API runnable without external credentials.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
import hashlib
import secrets
from typing import Any
from uuid import UUID, uuid4

from .schemas.consultation import ConsultationDetails, ConsultationStatus, PreferredContactMethod
from .schemas.coordinator import CoordinatorHandoff, HandoffStatus
from .schemas.programme import (
    ContactConsentStatus,
    EnquiryStatus,
    RegistrationStatus,
    SignatureProgrammeEnquiry,
)
from .schemas.intake import ConsultationProgress, FactValue, PersonaReadyProfile
from .audit_logging import ComplianceAuditStore, global_audit_store


@dataclass
class Session:
    id: UUID
    token_hash: str
    expires_at: datetime
    user_id: str | None = None
    locale: str = "en"


@dataclass
class Message:
    id: UUID
    conversation_id: UUID
    role: str
    content: str
    language: str
    sequence: int
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))


@dataclass
class Conversation:
    id: UUID
    session_id: UUID
    messages: list[Message] = field(default_factory=list)
    case_facts: dict[str, object] = field(default_factory=dict)
    consultation_id: UUID | None = None
    state: str = "requested"
    fact_history: list[dict[str, object]] = field(default_factory=list)
    summary: str = ""
    emergency_locked: bool = False
    crisis_locked: bool = False
    cp5_confirmed_at: datetime | None = None
    confirmed_appendix_a: dict[str, Any] | None = None
    persona_name: str | None = None
    persona_status: str = "UNRESOLVED"


@dataclass
class Lead:
    id: UUID
    conversation_id: UUID
    details: ConsultationDetails
    phone_verified: bool = False
    firebase_uid: str | None = None


@dataclass
class Consultation:
    id: UUID
    lead_id: UUID
    conversation_id: UUID
    details: ConsultationDetails
    consent_policy_version: str
    status: ConsultationStatus = ConsultationStatus.PENDING
    submitted_at: datetime = field(default_factory=lambda: datetime.now(UTC))


def _as_uuid(val: Any) -> UUID:
    return val if isinstance(val, UUID) else UUID(str(val))


class MemoryStore:
    def __init__(self, session_ttl_hours: int = 24) -> None:
        self._sessions: dict[UUID, Session] = {}
        self._conversations: dict[UUID, Conversation] = {}
        self._session_ttl = timedelta(hours=session_ttl_hours)
        self._consents: dict[UUID, list[dict[str, object]]] = {}
        self._leads: dict[UUID, Lead] = {}
        self._consultations: dict[UUID, Consultation] = {}
        self._handoffs: dict[UUID, CoordinatorHandoff] = {}
        self._programme_enquiries: dict[UUID, SignatureProgrammeEnquiry] = {}
        self._otp_challenges: dict[str, tuple[UUID, str]] = {}
        self._idempotent_chat: dict[tuple[UUID, str], dict[str, object]] = {}
        self.audit_store: ComplianceAuditStore = global_audit_store

    def create_guest_session(self, locale: str = "en") -> tuple[Session, str]:
        raw_token = secrets.token_urlsafe(32)
        session = Session(
            id=uuid4(),
            token_hash=self.hash_token(raw_token),
            expires_at=datetime.now(UTC) + self._session_ttl,
            locale=locale if locale in {"en", "ar"} else "en",
        )
        self._sessions[session.id] = session
        return session, raw_token

    @staticmethod
    def hash_token(raw_token: str) -> str:
        return hashlib.sha256(raw_token.encode("utf-8")).hexdigest()

    def authorize(self, session_id: UUID | str, raw_token: str) -> Session:
        sid = _as_uuid(session_id)
        session = self._sessions.get(sid)
        if (
            session is None
            or session.expires_at <= datetime.now(UTC)
            or not secrets.compare_digest(session.token_hash, self.hash_token(raw_token))
        ):
            raise PermissionError("Invalid or expired session.")
        return session

    def get_session(self, session_id: UUID | str) -> Session:
        sid = _as_uuid(session_id)
        session = self._sessions.get(sid)
        if session is None:
            raise PermissionError("Invalid or expired session.")
        return session

    def create_conversation(self, session_id: UUID | str) -> Conversation:
        sid = _as_uuid(session_id)
        conversation = Conversation(id=uuid4(), session_id=sid)
        self._conversations[conversation.id] = conversation
        return conversation

    def get_conversation(self, session_id: UUID | str, conversation_id: UUID | str) -> Conversation:
        sid = _as_uuid(session_id)
        cid = _as_uuid(conversation_id)
        conversation = self._conversations.get(cid)
        if conversation is None or conversation.session_id != sid:
            raise PermissionError("Conversation does not belong to this session.")
        return conversation

    def append_message(
        self, conversation: Conversation, role: str, content: str, language: str
    ) -> Message:
        message = Message(
            id=uuid4(),
            conversation_id=conversation.id,
            role=role,
            content=content,
            language=language,
            sequence=len(conversation.messages) + 1,
        )
        conversation.messages.append(message)
        return message

    def set_conversation_state(self, conversation: Conversation, state: str) -> None:
        conversation.state = state

    def cached_chat(self, conversation_id: UUID | str, client_message_id: str | None) -> dict[str, object] | None:
        if not client_message_id:
            return None
        return self._idempotent_chat.get((_as_uuid(conversation_id), client_message_id))

    def cache_chat(self, conversation_id: UUID | str, client_message_id: str | None, result: dict[str, object]) -> None:
        if client_message_id:
            self._idempotent_chat[(_as_uuid(conversation_id), client_message_id)] = result

    def save_fact_updates(
        self, conversation: Conversation, facts: list[FactValue]
    ) -> PersonaReadyProfile:
        if not facts:
            return self.persona_profile(conversation)
        conversation.fact_history.append(
            {
                "version": len(conversation.fact_history) + 1,
                "facts": [fact.model_dump(mode="json") for fact in facts],
            }
        )
        for fact in facts:
            conversation.case_facts[fact.field_name] = fact.value
            self._sync_structured_fact(conversation.case_facts, fact.field_name, fact.value)
        return self.persona_profile(conversation)

    def persona_profile(self, conversation: Conversation) -> PersonaReadyProfile:
        latest: dict[str, dict[str, object]] = {}
        for version in conversation.fact_history:
            for fact in version["facts"]:  # type: ignore[union-attr]
                latest[fact["field_name"]] = fact  # type: ignore[index]
        return PersonaReadyProfile(
            conversation_id=conversation.id,
            facts=[
                FactValue.model_validate(fact) for fact in latest.values()
                if fact.get("value") not in (None, "")
                and (not conversation.case_facts or fact.get("field_name") in conversation.case_facts)
            ],
        )

    def record_consent(self, session_id: UUID | str, payload: dict[str, object]) -> dict[str, object]:
        sid = _as_uuid(session_id)
        record = {"id": uuid4(), **payload}
        self._consents.setdefault(sid, []).append(record)
        return record

    def has_valid_consent(self, session_id: UUID | str, consent_type: str) -> bool:
        sid = _as_uuid(session_id)
        records = self._consents.get(sid, [])
        return any(
            record.get("consent_type") == consent_type and record.get("granted") is True
            for record in records
        )

    def consultation_progress(self, conversation: Conversation) -> ConsultationProgress:
        category = (
            conversation.case_facts.get("customer_category")
            or conversation.case_facts.get("care_category")
        )
        if category == "wellness":
            required = [
                "name", "phone_number", "care_category",
                "wellness_programme_or_goal", "destination_preference", "preferred_timing",
            ]
        else:
            required = [
                "name", "phone_number", "care_category",
                "procedure_or_service", "destination_preference", "preferred_timing",
            ]
        collected = [field for field in required if self._fact_present(conversation, field)]
        lead = self.lead_for(conversation.id)
        return ConsultationProgress(
            required_fields=required,
            collected_fields=collected,
            missing_fields=[field for field in required if field not in collected],
            consent_granted=self.has_valid_consent(
                conversation.session_id, "consultation_processing"
            ),
            phone_verified=bool(lead and lead.phone_verified),
            request_status=(
                self._consultations[conversation.consultation_id].status.value
                if conversation.consultation_id in self._consultations else None
            ),
        )

    @staticmethod
    def _fact_present(conversation: Conversation, field: str) -> bool:
        facts = getattr(conversation, "case_facts", {})
        if field == "preferred_timing":
            if facts.get("preferred_timing") not in (None, "") or facts.get("preferred_dates_times") not in (None, ""):
                return True
            return any(
                isinstance(v, dict) and (v.get("preferred_timing") or v.get("preferred_dates_times"))
                for v in facts.values()
            )
        if field == "care_category":
            if facts.get("care_category") not in (None, "") or facts.get("customer_category") not in (None, ""):
                return True
            return any(
                isinstance(v, dict) and (v.get("care_category") or v.get("customer_category"))
                for v in facts.values()
            )
        if field in facts and facts[field] not in (None, ""):
            return True
        return any(
            isinstance(value, dict) and value.get(field) not in (None, "")
            for value in facts.values()
        )

    @staticmethod
    def _sync_structured_fact(case_facts: dict[str, Any], field_name: str, value: Any) -> None:
        case_facts["schema_version"] = "caseFacts_v1"
        if field_name in {"name", "phone_number", "email", "preferred_contact_method"}:
            contact = case_facts.setdefault("contact", {})
            if isinstance(contact, dict):
                contact[field_name] = value
        elif field_name in {
            "care_category", "customer_category", "procedure_or_service",
            "wellness_programme_or_goal", "destination_preference",
            "preferred_timing", "budget_range", "treatment_objective"
        }:
            needs = case_facts.setdefault("needs", {})
            if isinstance(needs, dict):
                needs[field_name] = value
        elif field_name in {"preferred_dates_times", "timezone"}:
            consultation = case_facts.setdefault("consultation", {})
            if isinstance(consultation, dict):
                consultation[field_name] = value

    @staticmethod
    def _sync_lead_to_case_facts(conversation: Conversation, details: ConsultationDetails) -> None:
        cid = conversation.id
        facts = conversation.case_facts
        facts["schema_version"] = "caseFacts_v1"
        facts["conversation_id"] = str(cid)
        contact = facts.setdefault("contact", {})
        if isinstance(contact, dict):
            contact.update({
                "name": details.name,
                "phone_number": details.phone_number,
                "email": details.email,
                "preferred_contact_method": details.preferred_contact_method,
            })
        needs = facts.setdefault("needs", {})
        if isinstance(needs, dict):
            needs.update({
                "care_category": details.care_category,
                "procedure_or_service": details.procedure_or_service,
                "destination_preference": details.destination_preference,
                "preferred_timing": details.preferred_timing,
                "budget_range": details.budget_range,
                "companions_or_accessibility": details.companions_or_accessibility,
            })
        consultation = facts.setdefault("consultation", {})
        if isinstance(consultation, dict):
            consultation.update({
                "preferred_dates_times": details.preferred_dates_times,
                "timezone": details.timezone,
            })
        for k, v in [
            ("name", details.name),
            ("phone_number", details.phone_number),
            ("email", details.email),
            ("care_category", details.care_category),
            ("procedure_or_service", details.procedure_or_service),
            ("destination_preference", details.destination_preference),
            ("preferred_timing", details.preferred_timing),
            ("preferred_dates_times", details.preferred_dates_times),
            ("timezone", details.timezone),
        ]:
            if v and (k not in facts or not facts[k]):
                facts[k] = v

    def upsert_lead(self, conversation_id: UUID | str, details: ConsultationDetails) -> Lead:
        cid = _as_uuid(conversation_id)
        existing = next(
            (lead for lead in self._leads.values() if lead.conversation_id == cid),
            None,
        )
        if existing:
            existing.details = details
            conversation = self._conversations.get(cid)
            if conversation:
                self._sync_lead_to_case_facts(conversation, details)
            return existing
        lead = Lead(uuid4(), cid, details)
        self._leads[lead.id] = lead
        conversation = self._conversations.get(cid)
        if conversation:
            self._sync_lead_to_case_facts(conversation, details)
        return lead

    def lead_for(self, conversation_id: UUID | str) -> Lead | None:
        cid = _as_uuid(conversation_id)
        return next(
            (lead for lead in self._leads.values() if lead.conversation_id == cid),
            None,
        )

    def set_phone_verified(self, conversation_id: UUID | str, firebase_uid: str | None = None) -> None:
        cid = _as_uuid(conversation_id)
        lead = self.lead_for(cid)
        if lead:
            lead.phone_verified = True
            lead.firebase_uid = firebase_uid
            conversation = self._conversations.get(cid)
            if conversation:
                conversation.state = "awaiting_consent"

    def create_otp_challenge(self, conversation_id: UUID | str, challenge_id: str) -> None:
        cid = _as_uuid(conversation_id)
        self._otp_challenges[challenge_id] = (cid, challenge_id)

    def valid_otp_challenge(self, conversation_id: UUID | str, challenge_id: str) -> bool:
        cid = _as_uuid(conversation_id)
        return self._otp_challenges.get(challenge_id, (None, None))[0] == cid

    def create_consultation(
        self, conversation: Conversation, details: ConsultationDetails, policy_version: str
    ) -> Consultation:
        lead = self.upsert_lead(conversation.id, details)
        if not lead.phone_verified:
            raise PermissionError("Phone verification is required.")
        if conversation.consultation_id:
            return self._consultations[conversation.consultation_id]
        consultation = Consultation(uuid4(), lead.id, conversation.id, details, policy_version)
        self._consultations[consultation.id] = consultation
        conversation.consultation_id = consultation.id
        conversation.state = "pending_coordinator_confirmation"
        return consultation

    def save_coordinator_handoff(self, handoff: CoordinatorHandoff) -> CoordinatorHandoff:
        self._handoffs[handoff.id] = handoff
        return handoff

    def get_coordinator_handoff(self, handoff_id: UUID | str) -> CoordinatorHandoff | None:
        hid = _as_uuid(handoff_id)
        return self._handoffs.get(hid)

    def get_handoff_for_conversation(self, conversation_id: UUID | str) -> CoordinatorHandoff | None:
        cid = _as_uuid(conversation_id)
        return next((h for h in self._handoffs.values() if h.conversation_id == cid), None)

    def save_programme_enquiry(self, enquiry: SignatureProgrammeEnquiry) -> SignatureProgrammeEnquiry:
        self._programme_enquiries[enquiry.enquiry_id] = enquiry
        return enquiry

    def get_programme_enquiry(self, enquiry_id: UUID | str) -> SignatureProgrammeEnquiry | None:
        try:
            eid = _as_uuid(enquiry_id)
            return self._programme_enquiries.get(eid)
        except (ValueError, TypeError):
            return self.get_programme_enquiry_by_reference_code(str(enquiry_id))

    def get_programme_enquiry_by_reference_code(self, reference_code: str) -> SignatureProgrammeEnquiry | None:
        code = reference_code.strip().upper()
        return next(
            (e for e in self._programme_enquiries.values() if e.reference_code and e.reference_code.upper() == code),
            None,
        )

    def get_programme_enquiry_for_conversation(self, conversation_id: UUID | str) -> SignatureProgrammeEnquiry | None:
        cid = _as_uuid(conversation_id)
        return next((e for e in self._programme_enquiries.values() if e.conversation_id == cid), None)

    def upsert_programme_enquiry(
        self,
        conversation_id: UUID | str,
        session_id: UUID | str,
        updates: dict[str, Any],
    ) -> SignatureProgrammeEnquiry:
        cid = _as_uuid(conversation_id)
        sid = _as_uuid(session_id)
        existing = self.get_programme_enquiry_for_conversation(cid)
        if existing is None:
            enquiry = SignatureProgrammeEnquiry(
                conversation_id=cid,
                session_id=sid,
                **updates,
            )
        else:
            data = existing.model_dump()
            data.update(updates)
            data["updated_at"] = datetime.now(UTC)
            enquiry = SignatureProgrammeEnquiry.model_validate(data)
        self.save_programme_enquiry(enquiry)
        return enquiry

    def export_conversation(self, conversation: Conversation) -> dict[str, object]:
        return {
            "schema_version": "conversation_v1",
            "conversation_id": str(conversation.id),
            "messages": [
                {
                    "id": str(message.id),
                    "role": message.role,
                    "content": message.content,
                    "language": message.language,
                    "sequence": message.sequence,
                    "created_at": message.created_at.isoformat(),
                }
                for message in conversation.messages
            ],
            "case_facts": conversation.case_facts,
            "persona_profile": self.persona_profile(conversation).model_dump(mode="json"),
            "conversation_state": conversation.state,
            "consultation": (
                {
                    "id": str(consultation.id),
                    "status": consultation.status,
                    "submitted_at": consultation.submitted_at.isoformat(),
                }
                if (consultation := self._consultations.get(conversation.consultation_id))
                else None
            ),
            "coordinator_handoff": (
                handoff.model_dump(mode="json")
                if (handoff := self.get_handoff_for_conversation(conversation.id))
                else None
            ),
            "programme_enquiry": (
                enquiry.model_dump(mode="json")
                if (enquiry := self.get_programme_enquiry_for_conversation(conversation.id))
                else None
            ),
        }
