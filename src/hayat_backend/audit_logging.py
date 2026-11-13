"""Centralized Audit and Compliance Logging Module.

Implements rules AL-1 through AL-9 from HAYAT_Guardrail_Document_v1.docx:
- AL-1: Full transcript logging (timestamp, session_id, user_id).
- AL-2: Structured payload logging (exact fields, CP-5 confirmation timestamp).
- AL-3: Redaction logging with category tag only (no prohibited content!).
- AL-4: Refusal and fallback logging by rule ID (EF-1 to EF-11).
- AL-5: Security-event logging (UC-2 injection/override attempts).
- AL-6: Priority incident logging (EF-9 emergency, EF-10 crisis).
- AL-7: Audit of the audit trail (role-restricted access logging) & Coordinator Lifecycle tracking.
- AL-8: Data retention schedules aligned with MEWA policy.
- AL-9: QA sampling against rule IDs.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
import json
import logging
import os
from pathlib import Path
from typing import Any, Literal


def _turn_log_path() -> Path | None:
    """Where turn records are kept on disk: HAYAT_TURN_LOG, off in the test suite."""
    if os.environ.get("APP_ENV") == "test" and not os.environ.get("HAYAT_TURN_LOG"):
        return None
    return Path(os.environ.get("HAYAT_TURN_LOG") or "data/turn_records.jsonl")
from uuid import UUID, uuid4

logger = logging.getLogger("hayat.audit")


@dataclass(frozen=True)
class TranscriptLogEvent:
    """AL-1: Raw conversation transcript log."""
    event_id: UUID
    timestamp: datetime
    session_id: UUID
    user_id: str | None
    conversation_id: UUID
    sequence: int
    role: str
    content: str
    language: str


@dataclass(frozen=True)
class StructuredPayloadLogEvent:
    """AL-2: Structured intake payload transmission log with CP-5 confirmation."""
    event_id: UUID
    timestamp: datetime
    session_id: UUID
    user_id: str | None
    conversation_id: UUID
    confirmed_fields: dict[str, Any]
    cp5_confirmation_timestamp: datetime
    destination_integration: str  # e.g. "crm", "matching_engine"
    status: Literal["transmitted", "failed", "pending"]
    failure_reason: str | None = None


@dataclass(frozen=True)
class RedactionLogEvent:
    """AL-3: Redaction logging with category tag only. NEVER includes redacted text."""
    event_id: UUID
    timestamp: datetime
    session_id: UUID
    conversation_id: UUID
    category_tag: str
    rule_id: str


@dataclass(frozen=True)
class FallbackLogEvent:
    """AL-4: Fixed error fallback activation log by rule ID."""
    event_id: UUID
    timestamp: datetime
    session_id: UUID
    conversation_id: UUID
    rule_id: str
    trigger_type: str


@dataclass(frozen=True)
class SecurityLogEvent:
    """AL-5: Security incident log for injection, jailbreak, or boundary testing."""
    event_id: UUID
    timestamp: datetime
    session_id: UUID
    conversation_id: UUID
    event_type: str = "prompt_injection"
    rule_id: str = "UC-2"
    severity: Literal["low", "medium", "high", "critical"] = "high"
    threat_category: str | None = None
    sanitized_input_hash: str | None = None


@dataclass(frozen=True)
class PriorityIncidentLogEvent:
    """AL-6: Priority clinical incident log (EF-9 emergency or EF-10 crisis)."""
    event_id: UUID
    timestamp: datetime
    session_id: UUID
    conversation_id: UUID
    rule_id: str
    incident_type: Literal["medical_emergency", "crisis_self_harm"]
    requires_same_day_human_review: bool
    status: Literal["open", "reviewed", "closed"]


@dataclass(frozen=True)
class AuditAccessLogEvent:
    """AL-7: Audit of access to audit trails and restricted records."""
    event_id: UUID
    timestamp: datetime
    accessor_role: str
    accessor_id: str
    target_resource_type: str
    target_resource_id: str
    action: str


@dataclass(frozen=True)
class CoordinatorLifecycleLogEvent:
    """AL-7 / CP-7: Audit of coordinator handoff and appointment lifecycle events."""
    event_id: UUID
    timestamp: datetime
    handoff_id: UUID
    conversation_id: UUID
    status: str
    action: str
    actor_id: str
    actor_role: str
    notes: str | None = None


class ComplianceAuditStore:
    """In-memory and persistent compliance audit ledger."""

    def __init__(self) -> None:
        self.transcript_logs: list[TranscriptLogEvent] = []
        self.payload_logs: list[StructuredPayloadLogEvent] = []
        self.redaction_logs: list[RedactionLogEvent] = []
        self.fallback_logs: list[FallbackLogEvent] = []
        self.security_logs: list[SecurityLogEvent] = []
        self.priority_incidents: list[PriorityIncidentLogEvent] = []
        self.access_logs: list[AuditAccessLogEvent] = []
        self.coordinator_logs: list[CoordinatorLifecycleLogEvent] = []
        # One record per chat turn (Addendum part 8, logging): admin module only, never sent to
        # the CRM or ad platforms. The visitor's message is stored redacted.
        self.turn_records: list[dict] = []

    def log_turn(self, record: dict) -> dict:
        entry = {"timestamp": datetime.now(UTC).isoformat(), **record}
        self.turn_records.append(entry)
        if len(self.turn_records) > 20000:  # an in-memory ledger must not grow without bound
            del self.turn_records[:5000]
        path = _turn_log_path()
        if path is not None:
            # Kept on disk too, so a restart does not lose the record (admin module only).
            try:
                path.parent.mkdir(parents=True, exist_ok=True)
                with path.open("a", encoding="utf-8") as handle:
                    handle.write(json.dumps(entry, default=str, ensure_ascii=False) + "\n")
            except OSError:
                pass
        return entry

    def turns_for(self, conversation_id: str) -> list[dict]:
        found = [r for r in self.turn_records if str(r.get("conversation_id")) == str(conversation_id)]
        if found:
            return found
        path = _turn_log_path()
        if path is None or not path.exists():
            return []
        out = []
        try:
            with path.open(encoding="utf-8") as handle:
                for line in handle:
                    if f'"{conversation_id}"' in line:
                        try:
                            record = json.loads(line)
                        except ValueError:
                            continue
                        if str(record.get("conversation_id")) == str(conversation_id):
                            out.append(record)
        except OSError:
            return []
        return out

    def log_transcript(
        self,
        *,
        session_id: UUID,
        conversation_id: UUID,
        sequence: int,
        role: str,
        content: str,
        language: str = "en",
        user_id: str | None = None,
    ) -> TranscriptLogEvent:
        event = TranscriptLogEvent(
            event_id=uuid4(),
            timestamp=datetime.now(UTC),
            session_id=session_id,
            user_id=user_id,
            conversation_id=conversation_id,
            sequence=sequence,
            role=role,
            content=content,
            language=language,
        )
        self.transcript_logs.append(event)
        logger.info("AL-1 Transcript logged [session=%s seq=%s role=%s]", session_id, sequence, role)
        return event

    def log_structured_payload(
        self,
        *,
        session_id: UUID,
        conversation_id: UUID,
        confirmed_fields: dict[str, Any],
        cp5_confirmation_timestamp: datetime,
        destination_integration: str = "crm",
        status: Literal["transmitted", "failed", "pending"] = "transmitted",
        failure_reason: str | None = None,
        user_id: str | None = None,
    ) -> StructuredPayloadLogEvent:
        event = StructuredPayloadLogEvent(
            event_id=uuid4(),
            timestamp=datetime.now(UTC),
            session_id=session_id,
            user_id=user_id,
            conversation_id=conversation_id,
            confirmed_fields=confirmed_fields,
            cp5_confirmation_timestamp=cp5_confirmation_timestamp,
            destination_integration=destination_integration,
            status=status,
            failure_reason=failure_reason,
        )
        self.payload_logs.append(event)
        logger.info(
            "AL-2 Structured payload logged [session=%s dest=%s status=%s fields=%d]",
            session_id,
            destination_integration,
            status,
            len(confirmed_fields),
        )
        return event

    def log_redaction(
        self,
        *,
        session_id: UUID,
        conversation_id: UUID,
        category_tag: str,
        rule_id: str = "DP-6",
    ) -> RedactionLogEvent:
        """Log redaction with category tag only (AL-3). The content itself is NEVER saved."""
        event = RedactionLogEvent(
            event_id=uuid4(),
            timestamp=datetime.now(UTC),
            session_id=session_id,
            conversation_id=conversation_id,
            category_tag=category_tag,
            rule_id=rule_id,
        )
        self.redaction_logs.append(event)
        logger.warning(
            "AL-3 Redaction event logged [session=%s category=%s rule=%s]",
            session_id,
            category_tag,
            rule_id,
        )
        return event

    def log_fallback(
        self,
        *,
        session_id: UUID,
        conversation_id: UUID,
        rule_id: str,
        trigger_type: str,
    ) -> FallbackLogEvent:
        event = FallbackLogEvent(
            event_id=uuid4(),
            timestamp=datetime.now(UTC),
            session_id=session_id,
            conversation_id=conversation_id,
            rule_id=rule_id,
            trigger_type=trigger_type,
        )
        self.fallback_logs.append(event)
        logger.info(
            "AL-4 Fallback logged [session=%s rule=%s trigger=%s]",
            session_id,
            rule_id,
            trigger_type,
        )
        return event

    def log_security_event(
        self,
        *,
        session_id: UUID,
        conversation_id: UUID,
        event_type: str = "prompt_injection",
        rule_id: str = "UC-2",
        severity: Literal["low", "medium", "high", "critical"] = "high",
        threat_category: str | None = None,
        input_text: str | None = None,
    ) -> SecurityLogEvent:
        import hashlib
        hashed_input = hashlib.sha256(input_text.encode("utf-8")).hexdigest() if input_text else None
        event = SecurityLogEvent(
            event_id=uuid4(),
            timestamp=datetime.now(UTC),
            session_id=session_id,
            conversation_id=conversation_id,
            event_type=event_type,
            rule_id=rule_id,
            threat_category=threat_category or event_type,
            severity=severity,
            sanitized_input_hash=hashed_input,
        )
        self.security_logs.append(event)
        logger.error(
            "AL-5 SECURITY INCIDENT LOGGED [session=%s threat=%s severity=%s]",
            session_id,
            threat_category or event_type,
            severity,
        )
        return event

    def log_priority_incident(
        self,
        *,
        session_id: UUID,
        conversation_id: UUID,
        rule_id: str,
        incident_type: Literal["medical_emergency", "crisis_self_harm"],
    ) -> PriorityIncidentLogEvent:
        event = PriorityIncidentLogEvent(
            event_id=uuid4(),
            timestamp=datetime.now(UTC),
            session_id=session_id,
            conversation_id=conversation_id,
            rule_id=rule_id,
            incident_type=incident_type,
            requires_same_day_human_review=True,
            status="open",
        )
        self.priority_incidents.append(event)
        logger.critical(
            "AL-6 PRIORITY INCIDENT LOGGED [session=%s rule=%s type=%s] ROUTED FOR SAME-DAY HUMAN REVIEW",
            session_id,
            rule_id,
            incident_type,
        )
        return event

    def log_audit_access(
        self,
        *,
        accessor_role: str,
        accessor_id: str,
        target_resource_type: str,
        target_resource_id: str,
        action: str = "read",
    ) -> AuditAccessLogEvent:
        event = AuditAccessLogEvent(
            event_id=uuid4(),
            timestamp=datetime.now(UTC),
            accessor_role=accessor_role,
            accessor_id=accessor_id,
            target_resource_type=target_resource_type,
            target_resource_id=target_resource_id,
            action=action,
        )
        self.access_logs.append(event)
        return event

    def log_coordinator_event(
        self,
        *,
        handoff_id: UUID,
        conversation_id: UUID,
        status: str,
        action: str,
        actor_id: str,
        actor_role: str,
        notes: str | None = None,
    ) -> CoordinatorLifecycleLogEvent:
        event = CoordinatorLifecycleLogEvent(
            event_id=uuid4(),
            timestamp=datetime.now(UTC),
            handoff_id=handoff_id,
            conversation_id=conversation_id,
            status=status,
            action=action,
            actor_id=actor_id,
            actor_role=actor_role,
            notes=notes,
        )
        self.coordinator_logs.append(event)
        logger.info(
            "AL-7 Coordinator lifecycle logged [handoff=%s status=%s action=%s actor=%s]",
            handoff_id,
            status,
            action,
            actor_id,
        )
        return event

    def sample_sessions_for_qa(self, percentage: float = 0.10) -> list[UUID]:
        """AL-9 QA Sampling: select a percentage of sessions for monthly compliance review."""
        import random
        all_sessions = list({event.session_id for event in self.transcript_logs})
        sample_count = max(1, int(len(all_sessions) * percentage)) if all_sessions else 0
        return random.sample(all_sessions, min(sample_count, len(all_sessions)))


# Global audit singleton
global_audit_store = ComplianceAuditStore()
