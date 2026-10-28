"""Synchronous Supabase repository implementing the MemoryStore contract.

The service-role key is only used on the server.  This module never logs or
returns configuration values; the only raw secret returned by the repository
is the one-time guest token at session creation.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
import hashlib
import logging
import secrets
from typing import Any
from uuid import UUID, uuid4

from postgrest.exceptions import APIError
from supabase import Client, create_client

from .config import Settings
from .memory_store import Conversation, Lead, Message, Session, Consultation, MemoryStore
from .schemas.consultation import ConsultationDetails, ConsultationStatus
from .schemas.intake import ConsultationProgress, FactValue, PersonaReadyProfile

logger = logging.getLogger("hayat.supabase")


def _uuid(value: Any) -> UUID:
    return value if isinstance(value, UUID) else UUID(str(value))


def _row(response: Any) -> dict[str, Any]:
    data = getattr(response, "data", None) or []
    if isinstance(data, dict):
        return data
    if not data:
        raise LookupError("Supabase returned no row.")
    return data[0]


def _is_missing_schema_error(exc: APIError) -> bool:
    """Identify rollout-time errors for columns/tables from a pending migration."""
    return exc.code in {"42703", "42P01", "PGRST204"}


class SupabaseStore:
    """Repository with the same synchronous methods as :class:`MemoryStore`."""

    def __init__(self, client: Client, session_ttl_hours: int = 24) -> None:
        self.client = client
        self._session_ttl = timedelta(hours=session_ttl_hours)
        self._idempotent_chat: dict[tuple[UUID, str], dict[str, object]] = {}

    @staticmethod
    def hash_token(raw_token: str) -> str:
        return hashlib.sha256(raw_token.encode("utf-8")).hexdigest()

    def create_guest_session(self, locale: str = "en") -> tuple[Session, str]:
        raw_token = secrets.token_urlsafe(32)
        session = Session(
            id=uuid4(),
            token_hash=self.hash_token(raw_token),
            expires_at=datetime.now(UTC) + self._session_ttl,
            locale=locale if locale in {"en", "ar"} else "en",
        )
        self.client.table("guest_sessions").insert({
            "id": str(session.id),
            "token_hash": session.token_hash,
            "locale": session.locale,
            "expires_at": session.expires_at.isoformat(),
        }).execute()
        return session, raw_token

    def authorize(self, session_id: UUID, raw_token: str) -> Session:
        response = (
            self.client.table("guest_sessions")
            .select("id,token_hash,locale,expires_at,owner_id")
            .eq("id", str(session_id))
            .eq("token_hash", self.hash_token(raw_token))
            .gt("expires_at", datetime.now(UTC).isoformat())
            .maybe_single()
            .execute()
        )
        data = getattr(response, "data", None)
        if not data or not secrets.compare_digest(
            str(data["token_hash"]), self.hash_token(raw_token)
        ):
            raise PermissionError("Invalid or expired session.")
        return self._session(data)

    def get_session(self, session_id: UUID) -> Session:
        response = self.client.table("guest_sessions").select(
            "id,token_hash,locale,expires_at,owner_id"
        ).eq("id", str(session_id)).maybe_single().execute()
        data = getattr(response, "data", None)
        if not data:
            raise PermissionError("Invalid or expired session.")
        return self._session(data)

    @staticmethod
    def _session(data: dict[str, Any]) -> Session:
        expires = data["expires_at"]
        if isinstance(expires, str):
            expires = datetime.fromisoformat(expires.replace("Z", "+00:00"))
        return Session(_uuid(data["id"]), str(data["token_hash"]), expires,
                       data.get("owner_id"), data.get("locale", "en"))

    def create_conversation(self, session_id: UUID) -> Conversation:
        self.get_session(session_id)
        data = _row(self.client.table("conversations").insert({
            "guest_session_id": str(session_id),
        }).execute())
        return Conversation(_uuid(data["id"]), session_id)

    def get_conversation(self, session_id: UUID, conversation_id: UUID) -> Conversation:
        response = self.client.table("conversations").select(
            "id,guest_session_id"
        ).eq("id", str(conversation_id)).eq(
            "guest_session_id", str(session_id)
        ).maybe_single().execute()
        data = getattr(response, "data", None)
        if not data:
            raise PermissionError("Conversation does not belong to this session.")
        message_rows = self.client.table("messages").select(
            "id,conversation_id,role,content,language,sequence,created_at"
        ).eq("conversation_id", str(conversation_id)).order("sequence").execute().data or []
        facts = self.client.table("case_facts").select("id,facts").eq(
            "conversation_id", str(conversation_id)
        ).order("version", desc=True).limit(1).execute().data or []
        consultation = self.client.table("consultation_requests").select(
            "id"
        ).eq("conversation_id", str(conversation_id)).limit(1).execute().data or []
        conversation = Conversation(_uuid(data["id"]), session_id)
        conversation.messages = [self._message(row) for row in message_rows]
        case_facts_id = facts[0].get("id") if facts else None
        conversation.case_facts = (facts[0].get("facts") or {}) if facts else {}
        conversation.consultation_id = _uuid(consultation[0]["id"]) if consultation else None
        try:
            state = self.client.table("conversations").select("state").eq(
                "id", str(conversation_id)
            ).maybe_single().execute().data
        except APIError as exc:
            if not _is_missing_schema_error(exc):
                raise
            logger.warning(
                "Hayat orchestration migration is pending; using legacy conversation state."
            )
            state = None
        conversation.state = (state or {}).get("state", "requested")
        try:
            versions_query = self.client.table("case_fact_versions").select(
                "version,facts"
            )
            if case_facts_id:
                versions = versions_query.eq(
                    "case_facts_id", str(case_facts_id)
                ).order("version").execute().data or []
            else:
                versions = []
        except APIError as exc:
            if not _is_missing_schema_error(exc):
                raise
            logger.warning(
                "Hayat fact-version migration is pending; persona fact history is unavailable."
            )
            versions = []
        conversation.fact_history = versions
        return conversation

    def set_conversation_state(self, conversation: Conversation, state: str) -> None:
        try:
            self.client.table("conversations").update({"state": state}).eq(
                "id", str(conversation.id)
            ).execute()
        except APIError as exc:
            if not _is_missing_schema_error(exc):
                raise
        conversation.state = state

    def cached_chat(self, conversation_id: UUID, client_message_id: str | None) -> dict[str, object] | None:
        if not client_message_id:
            return None
        return self._idempotent_chat.get((conversation_id, client_message_id))

    def cache_chat(self, conversation_id: UUID, client_message_id: str | None, result: dict[str, object]) -> None:
        if client_message_id:
            self._idempotent_chat[(conversation_id, client_message_id)] = result

    def consultation_progress(self, conversation: Conversation) -> ConsultationProgress:
        facts = getattr(conversation, "case_facts", {})
        category = facts.get("customer_category") or facts.get("care_category")
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
        collected = [
            field for field in required
            if self._fact_present(conversation, field)
        ]
        lead = self.lead_for(conversation.id)
        return ConsultationProgress(
            required_fields=required,
            collected_fields=collected,
            missing_fields=[field for field in required if field not in collected],
            consent_granted=self.has_valid_consent(
                conversation.session_id, "consultation_processing"
            ),
            phone_verified=bool(lead and lead.phone_verified),
            request_status=self._consultation_status(conversation.consultation_id),
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

    def _consultation_status(self, consultation_id: UUID | None) -> str | None:
        if not consultation_id:
            return None
        result = self.client.table("consultation_requests").select("status").eq(
            "id", str(consultation_id)
        ).maybe_single().execute()
        data = getattr(result, "data", None) if result is not None else None
        return str(data["status"]) if data and data.get("status") else None

    @staticmethod
    def _message(data: dict[str, Any]) -> Message:
        created = data.get("created_at")
        if isinstance(created, str):
            created = datetime.fromisoformat(created.replace("Z", "+00:00"))
        return Message(_uuid(data["id"]), _uuid(data["conversation_id"]),
                       data["role"], data["content"], data.get("language", "en"),
                       int(data["sequence"]), created or datetime.now(UTC))

    def append_message(self, conversation: Conversation, role: str, content: str,
                       language: str) -> Message:
        existing = self.client.table("messages").select("sequence").eq(
            "conversation_id", str(conversation.id)
        ).order("sequence", desc=True).limit(1).execute().data or []
        sequence = int(existing[0]["sequence"]) + 1 if existing else 1
        data = _row(self.client.table("messages").insert({
            "conversation_id": str(conversation.id), "role": role,
            "content": content, "language": language, "sequence": sequence,
        }).execute())
        message = self._message({**data, "sequence": data.get("sequence", sequence),
                                 "language": data.get("language", language)})
        conversation.messages.append(message)
        return message

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

    def save_fact_updates(
        self, conversation: Conversation, facts: list[FactValue]
    ) -> PersonaReadyProfile:
        if not facts:
            return self.persona_profile(conversation)
        version_facts = [fact.model_dump(mode="json") for fact in facts]
        conversation.fact_history.append({"version": 0, "facts": version_facts})
        for fact in facts:
            conversation.case_facts[fact.field_name] = fact.value
            self._sync_structured_fact(conversation.case_facts, fact.field_name, fact.value)
        snapshot = {
            "conversation_id": str(conversation.id),
            "facts": conversation.case_facts,
            "version": 1,
        }
        rpc_builder = getattr(self.client, "rpc", None)
        try:
            if rpc_builder is None:
                raise APIError({"message": "RPC is unavailable", "code": "PGRST202"})
            rpc = rpc_builder("hayat_upsert_case_facts", {
                "p_conversation_id": str(conversation.id),
                "p_facts": conversation.case_facts,
                "p_changed_facts": version_facts,
            }).execute()
            version = int(getattr(rpc, "data", 1) or 1)
            payload = {"version": version, "facts": version_facts}
            conversation.fact_history[-1] = payload
            snapshot["version"] = version
            return self.persona_profile(conversation)
        except APIError as exc:
            if exc.code not in {"PGRST202", "42883"}:
                raise
        current_case_facts = self.client.table("case_facts").select(
            "id,version"
        ).eq("conversation_id", str(conversation.id)).order(
            "version", desc=True
        ).limit(1).execute().data or []
        if isinstance(current_case_facts, dict):
            current_case_facts = [current_case_facts]
        case_facts_id = current_case_facts[0]["id"] if current_case_facts else None
        try:
            previous = self.client.table("case_fact_versions").select("version").eq(
                "case_facts_id", str(case_facts_id)
            ).order("version", desc=True).limit(1).execute().data or []
        except APIError as exc:
            if not _is_missing_schema_error(exc):
                raise
            previous = []
        version = int(previous[0]["version"]) + 1 if previous else 1
        payload = {"version": version, "facts": version_facts}
        conversation.fact_history[-1] = payload
        snapshot["version"] = version
        try:
            self.client.table("case_facts").upsert(
                snapshot, on_conflict="conversation_id"
            ).execute()
        except APIError:
            raise
        if not case_facts_id:
            current_case_facts = self.client.table("case_facts").select(
                "id"
            ).eq("conversation_id", str(conversation.id)).maybe_single().execute()
            case_facts_id = getattr(current_case_facts, "data", None)
            if isinstance(case_facts_id, dict):
                case_facts_id = case_facts_id.get("id")
        try:
            if case_facts_id:
                self.client.table("case_fact_versions").insert({
                    "case_facts_id": str(case_facts_id), **payload
                }).execute()
        except APIError as exc:
            if not _is_missing_schema_error(exc):
                raise
        return self.persona_profile(conversation)

    @staticmethod
    def persona_profile(conversation: Conversation) -> PersonaReadyProfile:
        latest: dict[str, dict[str, object]] = {}
        for version in conversation.fact_history:
            for fact in version.get("facts", []):
                latest[fact["field_name"]] = fact
        return PersonaReadyProfile(
            conversation_id=conversation.id,
            facts=[
                FactValue.model_validate(fact) for fact in latest.values()
                if fact.get("value") not in (None, "")
                and (not conversation.case_facts or fact.get("field_name") in conversation.case_facts)
            ],
        )

    def record_consent(self, session_id: UUID, payload: dict[str, object]) -> dict[str, object]:
        data = _row(self.client.table("consent_records").insert({
            "guest_session_id": str(session_id), **payload,
        }).execute())
        return data

    def has_valid_consent(self, session_id: UUID, consent_type: str) -> bool:
        try:
            rows = self.client.table("consent_records").select("granted").eq(
                "guest_session_id", str(session_id)
            ).eq("consent_type", consent_type).eq("granted", True).limit(1).execute().data or []
        except APIError as exc:
            if not _is_missing_schema_error(exc):
                raise
            logger.warning(
                "Hayat consent migration is pending; treating consultation consent as unavailable."
            )
            return False
        return bool(rows)

    @staticmethod
    def _facts(conversation_id: UUID, details: ConsultationDetails) -> dict[str, object]:
        values = details.model_dump(mode="json")
        return {
            "schema_version": "caseFacts_v1", "conversation_id": str(conversation_id),
            "contact": {key: values[key] for key in ("name", "phone_number", "email", "preferred_contact_method")},
            "needs": {key: values[key] for key in ("care_category", "procedure_or_service", "destination_preference", "preferred_timing", "budget_range", "companions_or_accessibility")},
            "consultation": {key: values[key] for key in ("preferred_dates_times", "timezone")},
            "missing_inputs": [],
        }

    def upsert_lead(self, conversation_id: UUID, details: ConsultationDetails) -> Lead:
        values = details.model_dump(mode="json")
        result = self.client.table("leads").select("*").eq(
            "conversation_id", str(conversation_id)
        ).maybe_single().execute()
        existing = getattr(result, "data", None) if result is not None else None
        payload = {
            "conversation_id": str(conversation_id), "name": details.name,
            "phone_number": details.phone_number, "phone_verified": bool(existing and existing.get("phone_verified")),
            "email": details.email, "preferred_contact_method": values["preferred_contact_method"],
            "care_category": details.care_category, "details": values,
        }
        if existing:
            data = _row(self.client.table("leads").update(payload).eq("id", existing["id"]).execute())
        else:
            data = _row(self.client.table("leads").insert(payload).execute())
        current = self.client.table("case_facts").select("conversation_id,facts,version").eq(
            "conversation_id", str(conversation_id)
        ).maybe_single().execute()
        current_data = getattr(current, "data", None)
        if not current_data:
            self.client.table("case_facts").upsert(
                {
                    "conversation_id": str(conversation_id),
                    "facts": self._facts(conversation_id, details),
                    "version": 1,
                },
                on_conflict="conversation_id",
            ).execute()
        else:
            merged_facts = current_data.get("facts") or {}
            lead_facts = self._facts(conversation_id, details)
            merged_facts["schema_version"] = "caseFacts_v1"
            if isinstance(merged_facts.get("contact"), dict) and isinstance(lead_facts.get("contact"), dict):
                merged_facts["contact"].update(lead_facts["contact"])
            else:
                merged_facts["contact"] = lead_facts["contact"]
            if isinstance(merged_facts.get("needs"), dict) and isinstance(lead_facts.get("needs"), dict):
                merged_facts["needs"].update(lead_facts["needs"])
            else:
                merged_facts["needs"] = lead_facts["needs"]
            if isinstance(merged_facts.get("consultation"), dict) and isinstance(lead_facts.get("consultation"), dict):
                merged_facts["consultation"].update(lead_facts["consultation"])
            else:
                merged_facts["consultation"] = lead_facts["consultation"]
            self.client.table("case_facts").update({
                "facts": merged_facts,
            }).eq("conversation_id", str(conversation_id)).execute()
        return Lead(_uuid(data["id"]), conversation_id, details, bool(data.get("phone_verified")))

    def lead_for(self, conversation_id: UUID) -> Lead | None:
        result = self.client.table("leads").select("*").eq(
            "conversation_id", str(conversation_id)
        ).maybe_single().execute()
        data = getattr(result, "data", None) if result is not None else None
        if not data:
            return None
        return Lead(_uuid(data["id"]), conversation_id,
                    ConsultationDetails.model_validate(data.get("details") or data),
                    bool(data.get("phone_verified")), data.get("firebase_uid"))

    def set_phone_verified(self, conversation_id: UUID, firebase_uid: str | None = None) -> None:
        self.client.table("leads").update({
            "phone_verified": True, "firebase_uid": firebase_uid
        }).eq(
            "conversation_id", str(conversation_id)
        ).execute()
        try:
            self.client.table("conversations").update({"state": "awaiting_consent"}).eq(
                "id", str(conversation_id)
            ).execute()
        except APIError as exc:
            if not _is_missing_schema_error(exc):
                raise

    def create_otp_challenge(self, conversation_id: UUID, challenge_id: str) -> None:
        lead = self.lead_for(conversation_id)
        if lead:
            self.client.table("phone_verifications").insert({
                "lead_id": str(lead.id), "provider_challenge_id": challenge_id,
                "status": "pending",
            }).execute()

    def valid_otp_challenge(self, conversation_id: UUID, challenge_id: str) -> bool:
        lead = self.lead_for(conversation_id)
        if not lead:
            return False
        rows = self.client.table("phone_verifications").select("id").eq(
            "lead_id", str(lead.id)
        ).eq("provider_challenge_id", challenge_id).eq("status", "pending").limit(1).execute().data or []
        return bool(rows)

    def create_consultation(self, conversation: Conversation, details: ConsultationDetails,
                            policy_version: str) -> Consultation:
        lead = self.upsert_lead(conversation.id, details)
        if not lead.phone_verified:
            raise PermissionError("Phone verification is required.")
        if conversation.consultation_id:
            return self._consultation(conversation.consultation_id, lead, details, policy_version)
        data = _row(self.client.table("consultation_requests").insert({
            "lead_id": str(lead.id), "conversation_id": str(conversation.id),
            "consent_policy_version": policy_version,
            "preferred_dates_times": details.preferred_dates_times,
            "timezone": details.timezone,
        }).execute())
        conversation.consultation_id = _uuid(data["id"])
        try:
            self.client.table("conversations").update({
                "state": "pending_coordinator_confirmation"
            }).eq("id", str(conversation.id)).execute()
        except APIError as exc:
            if not _is_missing_schema_error(exc):
                raise
        return self._consultation(conversation.consultation_id, lead, details, policy_version, data)

    @staticmethod
    def _consultation(cid: UUID, lead: Lead, details: ConsultationDetails,
                      policy: str, data: dict[str, Any] | None = None) -> Consultation:
        data = data or {}
        submitted = data.get("submitted_at")
        if isinstance(submitted, str):
            submitted = datetime.fromisoformat(submitted.replace("Z", "+00:00"))
        return Consultation(cid, lead.id, lead.conversation_id, details, policy,
                            ConsultationStatus(data.get("status", "pending")),
                            submitted or datetime.now(UTC))

    def export_conversation(self, conversation: Conversation) -> dict[str, object]:
        if not conversation.messages:
            conversation = self.get_conversation(conversation.session_id, conversation.id)
        consultation = None
        if conversation.consultation_id:
            row = self.client.table("consultation_requests").select(
                "id,status,submitted_at"
            ).eq("id", str(conversation.consultation_id)).maybe_single().execute().data
            if row:
                consultation = {"id": str(row["id"]), "status": row["status"],
                                "submitted_at": row["submitted_at"]}
        return {
            "schema_version": "conversation_v1", "conversation_id": str(conversation.id),
            "messages": [{"id": str(m.id), "role": m.role, "content": m.content,
                          "language": m.language, "sequence": m.sequence,
                          "created_at": m.created_at.isoformat()} for m in conversation.messages],
            "case_facts": conversation.case_facts,
            "persona_profile": self.persona_profile(conversation).model_dump(mode="json"),
            "conversation_state": conversation.state,
            "consultation": consultation,
        }


def create_store(settings: Settings) -> MemoryStore | SupabaseStore:
    """Select durable persistence only when both server-side settings exist."""
    configured_url = settings.supabase_url and not settings.supabase_url.lower().startswith(
        ("your_", "replace_", "changeme")
    )
    configured_key = (
        settings.supabase_service_role_key
        and not settings.supabase_service_role_key.get_secret_value().lower().startswith(
            ("your_", "replace_", "changeme")
        )
    )
    if configured_url and configured_key:
        client = create_client(settings.supabase_url,
                               settings.supabase_service_role_key.get_secret_value())
        return SupabaseStore(client)
    from .memory_store import MemoryStore
    return MemoryStore()
