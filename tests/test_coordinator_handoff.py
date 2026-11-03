"""End-to-End Tests for Coordinator-Led Consultation & Appointment Handoff.

Governed by: HAYAT_Guardrail_Document_v1.docx (Version 1.0, CP-1 through CP-8, HB-1 through HB-10).
"""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID, uuid4
import pytest
from fastapi.testclient import TestClient

from hayat_backend.chat_service import ChatService
from hayat_backend.config import Settings
from hayat_backend.coordinator_service import (
    CoordinatorHandoffError,
    CoordinatorHandoffService,
)
from hayat_backend.llm import ChatModel
from hayat_backend.main import create_app
from hayat_backend.memory_store import MemoryStore
from hayat_backend.otp import SyntheticOTPProvider
from hayat_backend.policy_engine import (
    CP1_OPENING_EN,
    CP1_OPENING_AR,
    EF_SCRIPTS_EN,
    EF_SCRIPTS_AR,
    global_policy_engine,
)
from hayat_backend.schemas.appendix_a import AppendixAIntakePayload
from hayat_backend.schemas.coordinator import (
    CoordinatorAssignRequest,
    CoordinatorProgressRequest,
    CoordinatorRole,
    HandoffStatus,
)
from hayat_backend.audit_logging import global_audit_store


class MockChatModel(ChatModel):
    def __init__(self, canned_response: str = "I can help with that."):
        self.canned_response = canned_response

    async def generate(self, messages, system_prompt=None, response_schema=None) -> str:
        return self.canned_response


def _setup_app(settings: Settings | None = None):
    app_settings = settings or Settings(policy_addendum_1_1_approved=False)
    store = MemoryStore()
    llm = MockChatModel()
    coord_service = CoordinatorHandoffService(store, settings=app_settings)
    chat_service = ChatService(store, llm, coordinator_service=coord_service)
    app = create_app(SyntheticOTPProvider(), store=store, chat_service=chat_service)
    client = TestClient(app)

    res = client.post("/v1/sessions/guest", json={"locale": "en"}).json()
    sid = res["session_id"]
    token = res["session_token"]
    headers = {"X-Session-ID": sid, "X-Session-Token": token}
    c_res = client.post("/v1/conversations", headers={"X-Session-Token": token}, json={"guest_session_id": sid}).json()
    cid = c_res["id"]
    return client, headers, sid, token, cid, store, chat_service, coord_service


def test_initial_greeting_and_intent_classification():
    """CP-1: Initial greeting exactness and natural journey selection."""
    client, headers, sid, token, cid, store, _, _ = _setup_app()

    # Initial greeting via conversation endpoint
    msgs = client.get(f"/v1/conversations/{cid}/messages", headers=headers).json()["messages"]
    assert len(msgs) == 1
    assert msgs[0]["content"].startswith("Welcome! I'm Hayat")

    # Intent 1: Medical Treatment
    r1 = client.post("/v1/chat", headers=headers, json={"conversation_id": cid, "message": "I am interested in medical treatment."}).json()
    conv = store.get_conversation(UUID(sid), UUID(cid))
    assert conv.case_facts.get("customer_category") == "medical_treatment"
    assert conv.case_facts.get("trip_type") == "medical"

    # Intent 2: Arabic Greeting
    res_ar = client.post("/v1/sessions/guest", json={"locale": "ar"}).json()
    c_ar = client.post("/v1/conversations", headers={"X-Session-Token": res_ar["session_token"]}, json={"guest_session_id": res_ar["session_id"]}).json()
    msgs_ar = client.get(f"/v1/conversations/{c_ar['id']}/messages", headers={"X-Session-ID": res_ar["session_id"], "X-Session-Token": res_ar["session_token"]}).json()["messages"]
    assert msgs_ar[0]["content"].startswith("مرحباً! أنا حياة")


def test_multifield_extraction_and_contextual_followup():
    """Extract multiple permitted fields from a single compound message without repeating questions."""
    client, headers, sid, token, cid, store, _, _ = _setup_app()

    compound = "I need knee surgery in Germany within the next two months."
    r = client.post("/v1/chat", headers=headers, json={"conversation_id": cid, "message": compound}).json()

    conv = store.get_conversation(UUID(sid), UUID(cid))
    assert conv.case_facts.get("procedure_or_service") in ("knee surgery", "Knee surgery")
    assert conv.case_facts.get("preferred_destination") == "Germany"
    assert conv.case_facts.get("travel_dates_flexibility") == "within the next two months"

    # Next question must NOT ask for procedure or destination again
    next_question = r.get("follow_up_question") or ""
    assert "knee" not in next_question.lower()
    assert "germany" not in next_question.lower()


def test_field_corrections():
    """Ensure user can correct previously supplied details while retaining others."""
    client, headers, sid, token, cid, store, _, _ = _setup_app()

    client.post("/v1/chat", headers=headers, json={"conversation_id": cid, "message": "I need cardiology in India."})
    conv = store.get_conversation(UUID(sid), UUID(cid))
    assert conv.case_facts.get("procedure_or_service") == "Cardiology"
    assert conv.case_facts.get("preferred_destination") == "India"

    # Correction: change destination to Thailand
    client.post("/v1/chat", headers=headers, json={"conversation_id": cid, "message": "Actually, change my destination to Thailand."})
    conv = store.get_conversation(UUID(sid), UUID(cid))
    assert conv.case_facts.get("preferred_destination") == "Thailand"
    assert conv.case_facts.get("procedure_or_service") == "Cardiology"


def test_contextual_non_clinical_suggestions():
    """Suggest relevant Appendix A non-clinical options without ranking doctors or clinics."""
    client, headers, sid, token, cid, store, _, _ = _setup_app()

    r = client.post("/v1/chat", headers=headers, json={"conversation_id": cid, "message": "I need dental implants in India within the next three months."}).json()
    suggestions = r.get("suggestions", [])
    assert len(suggestions) > 0

    labels = [s["label"].lower() for s in suggestions]
    # Check that concierge/logistics options are present
    assert any("accommodation" in l or "transfer" in l or "translation" in l or "review" in l for l in labels)

    # Must never rank hospitals or promise specific doctors
    for s in suggestions:
        assert "rank" not in s["label"].lower()
        assert "best doctor" not in s["label"].lower()


def test_summary_generation_distinguishes_collected_from_missing():
    """Generate readable consultation summary showing collected vs missing optional preferences."""
    client, headers, sid, token, cid, store, _, _ = _setup_app()

    # Provide core details
    client.post("/v1/chat", headers=headers, json={"conversation_id": cid, "message": "I want cardiology in Germany in June."})

    # Ask for summary
    r = client.post("/v1/chat", headers=headers, json={"conversation_id": cid, "message": "Can you show me a summary of my preferences so far?"}).json()
    reply = r["reply"]

    # Must display collected details
    assert "Cardiology" in reply or "cardiology" in reply
    assert "Germany" in reply
    # Must explicitly mention optional preferences not yet specified
    assert "Optional preferences not yet specified" in reply
    # Must explain how to make corrections
    assert "change" in reply.lower() or "correct" in reply.lower()
    # Must ask for confirmation
    assert "confirm" in reply.lower()


def test_cp5_consent_and_refusal_variants():
    """CP-5: Explicit confirmation is required before transmission."""
    client, headers, sid, token, cid, store, _, coord_service = _setup_app()

    # Initial preferences
    client.post("/v1/chat", headers=headers, json={"conversation_id": cid, "message": "I want wellness detox in India."})
    conv = store.get_conversation(UUID(sid), UUID(cid))
    assert getattr(conv, "cp5_confirmed_at", None) is None

    # Set state to awaiting_consent before evaluating refusal
    conv.state = "awaiting_consent"

    # Negative consent
    r_neg = client.post("/v1/chat", headers=headers, json={"conversation_id": cid, "message": "No, do not share my details with anyone."}).json()
    conv = store.get_conversation(UUID(sid), UUID(cid))
    assert getattr(conv, "cp5_confirmed_at", None) is None
    assert "will not share" in r_neg["reply"].lower()

    # Affirmative consent
    conv.state = "awaiting_consent"
    r_aff = client.post("/v1/chat", headers=headers, json={"conversation_id": cid, "message": "Yes, I confirm and agree to share these details."}).json()
    conv = store.get_conversation(UUID(sid), UUID(cid))
    assert conv.cp5_confirmed_at is not None
    assert "securely prepared" in r_aff["reply"].lower()


def test_contact_data_separation():
    """Verify that contact details are strictly segregated from Appendix A intake payload (DP-7)."""
    payload_dict = {
        "service_procedure_category": "Orthopedics",
        "trip_type": "medical",
        "preferred_destination": "Germany",
        "travel_dates_flexibility": "next month",
        "total_budget_range": "$10,000",
    }
    payload = AppendixAIntakePayload.model_validate(payload_dict)
    assert payload.service_procedure_category == "Orthopedics"

    # Attempting to inject name or phone into AppendixAIntakePayload must raise ValidationError
    with pytest.raises(Exception):
        AppendixAIntakePayload.model_validate({**payload_dict, "name": "Jane Doe"})

    with pytest.raises(Exception):
        AppendixAIntakePayload.model_validate({**payload_dict, "phone_number": "+971501234567"})


def test_disabled_contact_workflow_before_policy_approval():
    """When policy_addendum_1_1_approved is False, user_contact_authorized is False."""
    settings = Settings(policy_addendum_1_1_approved=False)
    client, headers, sid, token, cid, store, _, coord_service = _setup_app(settings)

    client.post("/v1/chat", headers=headers, json={"conversation_id": cid, "message": "I want knee surgery in Germany."})
    conv = store.get_conversation(UUID(sid), UUID(cid))
    conv.state = "awaiting_consent"

    # User confirms CP-5
    client.post("/v1/chat", headers=headers, json={"conversation_id": cid, "message": "Yes, I confirm my details."})

    handoff = store.get_handoff_for_conversation(UUID(cid))
    assert handoff is not None
    assert handoff.user_contact_authorized is False
    assert handoff.status == HandoffStatus.AWAITING_REGISTRATION


def test_coordinator_assignment_and_progress_workflow():
    """Coordinator handoff lifecycle through coordinator endpoints."""
    settings = Settings(policy_addendum_1_1_approved=True)
    client, headers, sid, token, cid, store, _, coord_service = _setup_app(settings)

    client.post("/v1/chat", headers=headers, json={"conversation_id": cid, "message": "I need cardiology in India."})
    conv = store.get_conversation(UUID(sid), UUID(cid))
    conv.state = "awaiting_consent"
    client.post("/v1/chat", headers=headers, json={"conversation_id": cid, "message": "Yes, I confirm."})

    handoff = store.get_handoff_for_conversation(UUID(cid))
    assert handoff is not None

    # Step 1: Assign coordinator
    assign_payload = {
        "coordinator_id": "coord_404",
        "coordinator_name": "Sarah Jenkins",
        "role": "case_manager",
        "notes": "Assigned for cardiology intake coordination.",
    }
    r_assign = client.post(f"/v1/coordinator/handoffs/{handoff.id}/assign", json=assign_payload)
    assert r_assign.status_code == 200
    assert r_assign.json()["status"] == HandoffStatus.COORDINATOR_ASSIGNED
    assert r_assign.json()["assigned_coordinator_id"] == "coord_404"

    # Step 2: Update progress to coordinator_contacted
    prog_payload = {
        "status": "coordinator_contacted",
        "notes": "Discussed timing preferences with user via phone.",
        "contact_channel_used": "phone",
    }
    r_prog = client.post(
        f"/v1/coordinator/handoffs/{handoff.id}/progress",
        headers={"X-Coordinator-ID": "coord_404"},
        json=prog_payload,
    )
    assert r_prog.status_code == 200
    assert r_prog.json()["status"] == HandoffStatus.COORDINATOR_CONTACTED


def test_human_appointment_confirmation_enforces_coordinator_credentials():
    """HB-8: Appointments must be coordinated and confirmed by an authorized human."""
    client, headers, sid, token, cid, store, _, coord_service = _setup_app()

    client.post("/v1/chat", headers=headers, json={"conversation_id": cid, "message": "I need dental in Turkey."})
    conv = store.get_conversation(UUID(sid), UUID(cid))
    conv.state = "awaiting_consent"
    client.post("/v1/chat", headers=headers, json={"conversation_id": cid, "message": "Yes, I confirm."})
    handoff = store.get_handoff_for_conversation(UUID(cid))

    # Autonomous confirmation attempt via progress endpoint must fail
    bad_prog = client.post(
        f"/v1/coordinator/handoffs/{handoff.id}/progress",
        json={"status": "appointment_confirmed"},
    )
    assert bad_prog.status_code == 400

    # Human confirmation with coordinator credentials succeeds
    confirm_payload = {
        "coordinator_id": "coord_99",
        "coordinator_name": "Marcus Vance",
        "appointment_time": "2026-11-20 14:00 UTC",
        "provider_or_clinic": "Istanbul Dental Excellence Center",
        "mode": "video_consultation",
        "notes": "Initial video consultation with lead surgeon confirmed.",
    }
    r_conf = client.post(f"/v1/coordinator/handoffs/{handoff.id}/confirm-appointment", json=confirm_payload)
    assert r_conf.status_code == 200
    data = r_conf.json()
    assert data["status"] == HandoffStatus.APPOINTMENT_CONFIRMED
    assert data["appointment_details"]["coordinator_id"] == "coord_99"
    assert data["appointment_details"]["provider_or_clinic"] == "Istanbul Dental Excellence Center"

    # Client can inspect verified handoff status
    status_resp = client.get(f"/v1/conversations/{cid}/handoff", headers=headers).json()
    assert status_resp["status"] == HandoffStatus.APPOINTMENT_CONFIRMED
    assert status_resp["appointment_confirmed"] is True


def test_emergency_and_crisis_lock_persistence():
    """HB-10: Persistent emergency lockout surviving turns and reloads."""
    client, headers, sid, token, cid, store, _, _ = _setup_app()

    # Emergency prompt
    r1 = client.post("/v1/chat", headers=headers, json={"conversation_id": cid, "message": "I have severe crushing chest pain."}).json()
    assert r1["reply"] == EF_SCRIPTS_EN["EF-9"]

    # Next turn must remain locked
    r2 = client.post("/v1/chat", headers=headers, json={"conversation_id": cid, "message": "Can you give me directions?"}).json()
    assert r2["reply"] == EF_SCRIPTS_EN["EF-9"]

    conv = store.get_conversation(UUID(sid), UUID(cid))
    assert conv.emergency_locked is True


def test_exact_fallback_responses():
    """EF-1 through EF-11 verbatim adherence."""
    assert len(EF_SCRIPTS_EN) == 11
    assert len(EF_SCRIPTS_AR) == 11
    for rule_id in [f"EF-{i}" for i in range(1, 12)]:
        assert rule_id in EF_SCRIPTS_EN
        assert rule_id in EF_SCRIPTS_AR
        assert len(EF_SCRIPTS_EN[rule_id]) > 10
        assert len(EF_SCRIPTS_AR[rule_id]) > 10
    # Spot-check verbatim key phrases from governing document
    assert "not able to interpret symptoms" in EF_SCRIPTS_EN["EF-1"].lower()
    assert "specialist will need to review" in EF_SCRIPTS_EN["EF-2"].lower()
    assert "don't choose or recommend" in EF_SCRIPTS_EN["EF-3"].lower()
    assert "999 in Oman" in EF_SCRIPTS_EN["EF-9"]


def test_audit_logging_coordinator_lifecycle():
    """AL-7: Verify coordinator lifecycle events are recorded in audit store."""
    client, headers, sid, token, cid, store, _, coord_service = _setup_app()

    client.post("/v1/chat", headers=headers, json={"conversation_id": cid, "message": "I want oncology in Singapore."})
    conv = store.get_conversation(UUID(sid), UUID(cid))
    conv.state = "awaiting_consent"
    client.post("/v1/chat", headers=headers, json={"conversation_id": cid, "message": "Yes, I confirm."})

    handoff = store.get_handoff_for_conversation(UUID(cid))
    coord_service.assign_coordinator(
        handoff_id=handoff.id,
        coordinator_id="coord_audit_1",
        coordinator_name="Audit Coordinator",
        role=CoordinatorRole.CASE_MANAGER,
        notes="Audit assignment test",
    )

    events = [e for e in global_audit_store.coordinator_logs if e.handoff_id == handoff.id]
    assert len(events) >= 2
    actions = [e.action for e in events]
    assert "initiate_handoff" in actions or "update_handoff" in actions
    assert "assign_coordinator" in actions
