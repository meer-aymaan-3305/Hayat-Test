"""Comprehensive Test Suite for Signature Wellness Programmes.

Governing specifications:
- docs/knowledge/signature_programmes.md
- HAYAT_Guardrail_Document_v1.docx (Version 1.0)

Verifies:
1. Knowledge Base & RAG Retrieval (HAYAT-100, AAfiya, FFounders)
2. Approved Introductory Pitch & Natural Discovery
3. Wellness Goal / Longevity Intent Identifies HAYAT-100 without Repetition
4. Contextual State Machine Progression (Focus -> Dest -> Timing -> Group -> Budget -> Summary -> Register)
5. Multi-Programme Interest Handling
6. Pricing Restrictions & Claim Boundaries (Individually curated, no invented rates)
7. All Official Potential Destinations (USA, Spain, Japan, Singapore, India, UAE, Undecided)
8. Optional Question Skipping without Friction
9. Programme Switching in-Conversation
10. Registration of Interest Lifecycle (Free, non-binding, reference code, coordinator handoff)
11. Policy Addendum 1.1: Contact Collection Restrictions in Chat
12. Strict Data Separation from Appendix A & CRM Transmission
13. Category Switching (Medical Travel <-> Signature Programmes)
14. UTF-8 Encoding & Special Character Integrity
15. FastAPI REST Endpoints for Programme Enquiries
"""

import anyio
from uuid import uuid4
import pytest
from fastapi.testclient import TestClient

from hayat_backend.main import create_app
from hayat_backend.memory_store import MemoryStore
from hayat_backend.programmes_catalog import (
    ALL_THREE_INTEREST_EN,
    DATES_EXPLANATION_EN,
    DESTINATIONS_EXPLANATION_EN,
    PRICING_EXPLANATION_EN,
    PROGRAMMES_CATALOG,
    REGISTRATION_DECLINED_EN,
    SIGNATURE_PROGRAMMES_INTRO_EN,
    ProgrammeId,
)
from hayat_backend.rag import InMemoryRetriever
from hayat_backend.schemas.programme import (
    ContactConsentStatus,
    EnquiryStatus,
    ProgrammeStage,
    RegistrationStatus,
    SignatureProgrammeEnquiry,
)


@pytest.fixture
def store():
    return MemoryStore()


@pytest.fixture
def client(store):
    return TestClient(create_app(store=store))


def _start_session(client):
    session = client.post("/v1/sessions/guest").json()
    conv = client.post(
        "/v1/conversations",
        headers={"X-Session-Token": session["session_token"]},
        json={"guest_session_id": session["session_id"]},
    ).json()
    headers = {
        "X-Session-ID": session["session_id"],
        "X-Session-Token": session["session_token"],
    }
    return session, conv, headers


# =============================================================================
# 1. Knowledge Base and RAG Retrieval
# =============================================================================

def test_signature_programmes_retrieval():
    retriever = InMemoryRetriever()

    async def _run():
        # HAYAT-100
        h100_chunks = await retriever.retrieve("Tell me about the HAYAT-100 longevity retreat")
        assert any("HAYAT-100" in c.text for c in h100_chunks)
        assert any("longevity" in c.text.lower() for c in h100_chunks)

        # AAfiya
        aafiya_chunks = await retriever.retrieve("What is AAfiya women's wellness retreat?")
        assert any("AAfiya" in c.text for c in aafiya_chunks)
        assert any("women" in c.text.lower() for c in aafiya_chunks)

        # FFounders
        ffounders_chunks = await retriever.retrieve("Tell me about FFounders executive wellness")
        assert any("FFounders" in c.text for c in ffounders_chunks)
        assert any("executive" in c.text.lower() for c in ffounders_chunks)

        # Pricing
        pricing_chunks = await retriever.retrieve("How much does a signature wellness retreat cost?")
        assert any("individually curated" in c.text.lower() or "pricing" in c.text.lower() for c in pricing_chunks)

    anyio.run(_run)


def test_programmes_catalog_contents():
    assert len(PROGRAMMES_CATALOG) == 3
    assert ProgrammeId.HAYAT_100 in PROGRAMMES_CATALOG
    assert ProgrammeId.AAFIYA in PROGRAMMES_CATALOG
    assert ProgrammeId.FFOUNDERS in PROGRAMMES_CATALOG

    h100 = PROGRAMMES_CATALOG[ProgrammeId.HAYAT_100]
    assert h100.duration_total_days == 7
    assert h100.retreat_days == 5
    assert h100.travel_days == 2
    assert "Spain" in h100.candidate_destinations
    assert "Other / Undecided" in h100.candidate_destinations

    aafiya = PROGRAMMES_CATALOG[ProgrammeId.AAFIYA]
    assert aafiya.duration_total_days == 7
    assert "women" in aafiya.focus.lower()

    ffounders = PROGRAMMES_CATALOG[ProgrammeId.FFOUNDERS]
    assert ffounders.duration_total_days == 7
    assert "founders" in ffounders.focus.lower()


# =============================================================================
# 2. Approved Introductory Pitch & Natural Discovery
# =============================================================================

def test_approved_introductory_pitch_verbatim(client):
    _, conv, headers = _start_session(client)

    res = client.post(
        "/v1/chat",
        headers=headers,
        json={
            "conversation_id": conv["id"],
            "message": "What are your signature wellness programmes?",
        },
    ).json()

    assert "We have three signature wellness experiences" in res["reply"]
    assert "HAYAT-100 focuses on longevity and healthy ageing." in res["reply"]
    assert "AAfiya is a women's fitness and wellness experience." in res["reply"]
    assert "FFounders is an executive fitness and wellness retreat" in res["reply"]
    assert "Each programme is designed as a seven-day experience" in res["reply"]
    assert "May I ask which of these interests you most?" in res["reply"]
    assert res["service_category"] == "signature_programmes"


# =============================================================================
# 3. Wellness Goal / Longevity Intent Identifies HAYAT-100 without Repetition
# =============================================================================

def test_longevity_intent_identifies_hayat_100_naturally(client):
    """Visitor says 'I want healthy ageing and longevity' -> Hayat identifies HAYAT-100.

    Must NOT ask again which programme interests them.
    """
    _, conv, headers = _start_session(client)

    res = client.post(
        "/v1/chat",
        headers=headers,
        json={"conversation_id": conv["id"], "message": "I want healthy ageing and longevity."},
    ).json()

    # Confirms natural transition to HAYAT-100
    assert "HAYAT-100" in res["reply"]
    assert "relevant to what you're exploring" in res["reply"].lower() or "designed around longevity" in res["reply"].lower()
    assert "What interests you most about healthy ageing" in res["reply"]
    # Does NOT ask generic repeated intro question
    assert "May I ask which of these interests you most?" not in res["reply"]
    assert res["programme_enquiry"]["primary_programme"] == "hayat_100"


# =============================================================================
# 4. Contextual State Machine Progression (Full Conditional Stages)
# =============================================================================

def test_conversational_state_machine_full_journey(client):
    """Traces full progression: Programme -> Focus -> Dest -> Timing -> Group -> Budget -> Summary -> Register."""
    _, conv, headers = _start_session(client)

    # 1. Programme Selection
    r1 = client.post(
        "/v1/chat",
        headers=headers,
        json={"conversation_id": conv["id"], "message": "I want healthy ageing and longevity."},
    ).json()
    assert r1["programme_enquiry"]["primary_programme"] == "hayat_100"

    # 2. Activity / Focus
    r2 = client.post(
        "/v1/chat",
        headers=headers,
        json={"conversation_id": conv["id"], "message": "I want to focus on guided fitness, strength and mobility."},
    ).json()
    assert "destination" in r2["reply"].lower()
    assert "Guided fitness & mobility" in r2["programme_enquiry"]["activity_interests"]
    assert r2["programme_enquiry"]["current_stage"] == "destination_preference"

    # 3. Destination Preference (Spain)
    r3 = client.post(
        "/v1/chat",
        headers=headers,
        json={"conversation_id": conv["id"], "message": "I prefer Spain."},
    ).json()
    assert r3["programme_enquiry"]["destination_preference"] == "Spain"
    assert "month or travel period" in r3["reply"].lower()
    assert r3["programme_enquiry"]["current_stage"] == "travel_period"

    # 4. Travel Timing (Next 3 months)
    r4 = client.post(
        "/v1/chat",
        headers=headers,
        json={"conversation_id": conv["id"], "message": "I prefer the next 3 months."},
    ).json()
    assert "Next 3 Months" in r4["programme_enquiry"]["preferred_travel_period"]
    assert "individually" in r4["reply"].lower() or "spouse" in r4["reply"].lower()
    assert r4["programme_enquiry"]["current_stage"] == "group_preferences"

    # 5. Group Participation (Solo)
    r5 = client.post(
        "/v1/chat",
        headers=headers,
        json={"conversation_id": conv["id"], "message": "I plan to attend individually as a solo retreat."},
    ).json()
    assert "budget" in r5["reply"].lower()
    assert r5["programme_enquiry"]["current_stage"] == "optional_budget"

    # 6. Optional Budget (Evaluate proposals first)
    r6 = client.post(
        "/v1/chat",
        headers=headers,
        json={"conversation_id": conv["id"], "message": "I would like to explore tailored proposals first."},
    ).json()
    assert "summary of your retreat preferences" in r6["reply"].lower()
    assert "HAYAT-100" in r6["reply"]
    assert "Spain" in r6["reply"]
    assert r6["programme_enquiry"]["current_stage"] == "summary_review"

    # 7. Registration of Interest Confirmation
    r7 = client.post(
        "/v1/chat",
        headers=headers,
        json={"conversation_id": conv["id"], "message": "Yes, please register my interest."},
    ).json()
    assert "successfully registered" in r7["reply"].lower()
    assert "free and non-binding" in r7["reply"].lower()
    assert "ENQ-" in r7["reply"]
    assert r7["programme_enquiry"]["registration_status"] == "interest_registered"
    assert r7["programme_enquiry"]["enquiry_status"] == "submitted"


# =============================================================================
# 5. Multi-Programme Interest Handling
# =============================================================================

def test_interest_in_all_three_programmes(client):
    _, conv, headers = _start_session(client)

    res = client.post(
        "/v1/chat",
        headers=headers,
        json={"conversation_id": conv["id"], "message": "I am interested in all three programmes."},
    ).json()

    assert "Each programme offers a different experience" in res["reply"]
    assert "Is there one you'd currently prioritise?" in res["reply"]
    enq = res["programme_enquiry"]
    assert set(enq["interested_programmes"]) == {"hayat_100", "aafiya", "ffounders"}


# =============================================================================
# 6. Pricing and Claim Boundaries (No Invented Rates)
# =============================================================================

def test_pricing_inquiry_does_not_quote_assumed_price(client):
    _, conv, headers = _start_session(client)

    res = client.post(
        "/v1/chat",
        headers=headers,
        json={"conversation_id": conv["id"], "message": "How much does HAYAT-100 cost?"},
    ).json()

    reply = res["reply"]
    assert "individually curated" in reply.lower()
    assert "no fixed package price" in reply.lower()
    assert "tailored proposal" in reply.lower()

    # Never invents arbitrary price points or medical guarantees
    assert "$5,000" not in reply
    assert "$10,000" not in reply
    assert "anti-ageing guaranteed" not in reply.lower()


# =============================================================================
# 7. Potential Destinations Support (All 6 Markets + Undecided)
# =============================================================================

@pytest.mark.parametrize("destination", [
    "Spain", "Japan", "United States", "UAE", "Singapore", "India"
])
def test_all_potential_destinations_accepted(client, destination):
    _, conv, headers = _start_session(client)

    # Put in programme mode
    client.post("/v1/chat", headers=headers, json={"conversation_id": conv["id"], "message": "Tell me about HAYAT-100."})

    res = client.post(
        "/v1/chat",
        headers=headers,
        json={"conversation_id": conv["id"], "message": f"I prefer {destination}."},
    ).json()

    expected = "United Arab Emirates" if destination == "UAE" else destination
    assert (
        expected.lower() in res["programme_enquiry"]["destination_preference"].lower()
        or destination.lower() in res["programme_enquiry"]["destination_preference"].lower()
    )


def test_destination_undecided_accepted(client):
    _, conv, headers = _start_session(client)
    client.post("/v1/chat", headers=headers, json={"conversation_id": conv["id"], "message": "Tell me about AAfiya."})

    res = client.post(
        "/v1/chat",
        headers=headers,
        json={"conversation_id": conv["id"], "message": "I am open to exploring any suitable destination."},
    ).json()

    assert "Undecided" in res["programme_enquiry"]["destination_preference"] or "Open" in res["programme_enquiry"]["destination_preference"]


# =============================================================================
# 8. Optional Question Skipping without Friction
# =============================================================================

def test_skipping_optional_questions_advances_smoothly(client):
    _, conv, headers = _start_session(client)

    # Start with AAfiya
    client.post("/v1/chat", headers=headers, json={"conversation_id": conv["id"], "message": "Tell me about AAfiya."})

    # Skip destination
    r1 = client.post(
        "/v1/chat",
        headers=headers,
        json={"conversation_id": conv["id"], "message": "I am flexible on destination, no preference."},
    ).json()
    assert "month or travel period" in r1["reply"].lower()

    # Skip timing
    r2 = client.post(
        "/v1/chat",
        headers=headers,
        json={"conversation_id": conv["id"], "message": "I'm flexible on timing, skip for now."},
    ).json()
    assert "individually" in r2["reply"].lower() or "spouse" in r2["reply"].lower()


# =============================================================================
# 9. Programme Switching in-Conversation
# =============================================================================

def test_switching_programmes_in_conversation(client):
    _, conv, headers = _start_session(client)

    # Start with HAYAT-100
    r1 = client.post(
        "/v1/chat",
        headers=headers,
        json={"conversation_id": conv["id"], "message": "Tell me about HAYAT-100."},
    ).json()
    assert r1["programme_enquiry"]["primary_programme"] == "hayat_100"

    # Switch to FFounders
    r2 = client.post(
        "/v1/chat",
        headers=headers,
        json={"conversation_id": conv["id"], "message": "Actually, switch to FFounders executive retreat."},
    ).json()
    assert "FFounders" in r2["reply"]
    assert r2["programme_enquiry"]["primary_programme"] == "ffounders"


# =============================================================================
# 10. Registration of Interest & Policy Addendum 1.1 Enforcement
# =============================================================================

def test_registration_does_not_solicit_or_scrape_contact_in_chat(client):
    """Under Policy Addendum 1.1, in-chat contact data collection is disabled."""
    _, conv, headers = _start_session(client)

    client.post("/v1/chat", headers=headers, json={"conversation_id": conv["id"], "message": "Tell me about HAYAT-100 in Spain."})

    # User registers interest
    res = client.post(
        "/v1/chat",
        headers=headers,
        json={"conversation_id": conv["id"], "message": "Yes, please register my interest."},
    ).json()

    reply = res["reply"]
    # Successfully registers interest with reference code
    assert "registered" in reply.lower()
    assert "ENQ-" in reply
    assert "free and non-binding" in reply.lower()
    # Does not demand phone number or OTP
    assert "please send otp" not in reply.lower()
    assert "enter verification code" not in reply.lower()


# =============================================================================
# 11. Strict Data Separation from Appendix A & CRM Transmission
# =============================================================================

def test_programme_enquiry_does_not_pollute_appendix_a(client, store):
    _, conv, headers = _start_session(client)

    client.post(
        "/v1/chat",
        headers=headers,
        json={"conversation_id": conv["id"], "message": "I want healthy ageing and longevity in Spain."},
    )

    conv_obj = store.get_conversation(headers["X-Session-ID"], conv["id"])
    # Case facts must not contain Appendix A procedure or clinical payload
    assert conv_obj.case_facts.get("procedure_or_service") is None
    assert conv_obj.cp5_confirmed_at is None

    enq = store.get_programme_enquiry_for_conversation(conv["id"])
    assert enq is not None
    assert enq.primary_programme == "hayat_100"
    assert enq.destination_preference == "Spain"


# =============================================================================
# 12. Category Switching (Medical Travel <-> Signature Programmes)
# =============================================================================

def test_category_switching_medical_to_signature_and_back(client):
    _, conv, headers = _start_session(client)

    # 1. Start with medical
    r1 = client.post(
        "/v1/chat",
        headers=headers,
        json={"conversation_id": conv["id"], "message": "I am interested in medical treatment for cardiology in India."},
    ).json()
    assert r1["service_category"] == "international_medical_travel"

    # 2. Switch to signature programmes
    r2 = client.post(
        "/v1/chat",
        headers=headers,
        json={"conversation_id": conv["id"], "message": "Actually, switch to signature wellness retreats."},
    ).json()
    assert r2["service_category"] == "signature_programmes"
    assert "We have three signature wellness experiences" in r2["reply"]

    # 3. Switch back to medical travel
    r3 = client.post(
        "/v1/chat",
        headers=headers,
        json={"conversation_id": conv["id"], "message": "Can I switch back to medical travel for cardiology?"},
    ).json()
    assert r3["service_category"] == "international_medical_travel"
    assert "cardiology" in r3["reply"].lower()


# =============================================================================
# 13. UTF-8 Character Integrity (No Mojibake)
# =============================================================================

def test_utf8_rendering_integrity(client):
    _, conv, headers = _start_session(client)

    res = client.post(
        "/v1/chat",
        headers=headers,
        json={"conversation_id": conv["id"], "message": "What are your signature wellness programmes?"},
    ).json()

    reply = res["reply"]
    # Check for absence of double-encoded mojibake
    assert "â€”" not in reply
    assert "â€" not in reply
    assert "Ø" not in reply


# =============================================================================
# 14. FastAPI Programme Endpoints
# =============================================================================

def test_fastapi_programme_endpoints(client):
    session, conv, headers = _start_session(client)

    # 1. List programmes
    res_list = client.get("/v1/programmes")
    assert res_list.status_code == 200
    programmes = res_list.json()
    assert len(programmes) == 3

    # 2. Detail programme
    res_detail = client.get("/v1/programmes/hayat_100")
    assert res_detail.status_code == 200
    detail = res_detail.json()
    assert detail["name"] == "HAYAT-100"

    # 3. Create enquiry via endpoint
    res_create = client.post(
        "/v1/programmes/enquiries",
        headers=headers,
        json={
            "conversation_id": conv["id"],
            "session_id": session["session_id"],
            "interested_programmes": ["hayat_100", "aafiya"],
            "primary_programme": "hayat_100",
            "destination_preference": "Spain",
            "preferred_month": "October",
            "activity_interests": ["Yoga", "Nutrition"],
        },
    )
    assert res_create.status_code == 200
    enq_data = res_create.json()
    enquiry_id = enq_data["enquiry_id"]

    # 4. Get conversation programme enquiry
    res_get = client.get(
        f"/v1/conversations/{conv['id']}/programme-enquiry",
        headers=headers,
    )
    assert res_get.status_code == 200
    assert res_get.json()["enquiry_id"] == enquiry_id

    # 5. Register interest via endpoint
    res_reg = client.post(
        f"/v1/programmes/enquiries/{enquiry_id}/register-interest",
        headers=headers,
        json={
            "full_name": "Elena Rostova",
            "phone_number": "+34612345678",
            "email": "elena@example.es",
            "contact_consent": True,
            "preferred_contact_method": "phone",
        },
    )
    assert res_reg.status_code == 200
    reg_body = res_reg.json()
    assert reg_body["enquiry"]["lead_name"] == "Elena Rostova"
    assert reg_body["enquiry"]["registration_status"] == "interest_registered"


# =============================================================================
# 15. Reference ID Persistence, Coordinator Retrieval & Handoff Messaging Gate
# =============================================================================

def test_programme_enquiry_reference_id_persistence_and_coordinator_retrieval(client):
    """Verify reference ID persistence, retrieval by coordinators, and non-implying contact copy."""
    _, conv, headers = _start_session(client)

    # 1. Register interest via conversational flow without contact info
    client.post("/v1/chat", headers=headers, json={"conversation_id": conv["id"], "message": "I am interested in HAYAT-100 longevity retreat."})
    client.post("/v1/chat", headers=headers, json={"conversation_id": conv["id"], "message": "I prefer Spain."})
    r_reg = client.post("/v1/chat", headers=headers, json={"conversation_id": conv["id"], "message": "Please register my interest."}).json()

    enquiry = r_reg["programme_enquiry"]
    ref_code = enquiry["reference_code"]
    enquiry_id = enquiry["enquiry_id"]

    assert ref_code is not None and ref_code.startswith("ENQ-")
    assert enquiry["registration_status"] == "interest_registered"

    # Verify handoff copy does not promise or imply confirmed human follow-up when no contact method exists
    reply_lower = r_reg["reply"].lower()
    assert "will not initiate unsolicited outreach" in reply_lower or "not initiate unrequested outreach" in reply_lower
    assert "call you" not in reply_lower
    assert "phone" not in reply_lower

    # 2. Coordinator retrieves by reference code
    res_coord_by_code = client.get(
        f"/v1/coordinator/programme-enquiries/{ref_code}",
        headers={"X-Coordinator-ID": "coord_longevity_1", "X-Coordinator-Role": "wellness_curator"},
    )
    assert res_coord_by_code.status_code == 200
    assert res_coord_by_code.json()["reference_code"] == ref_code
    assert res_coord_by_code.json()["destination_preference"] == "Spain"

    # 3. Coordinator retrieves by UUID enquiry_id
    res_coord_by_id = client.get(
        f"/v1/coordinator/programme-enquiries/{enquiry_id}",
        headers={"X-Coordinator-ID": "coord_longevity_1", "X-Coordinator-Role": "wellness_curator"},
    )
    assert res_coord_by_id.status_code == 200
    assert res_coord_by_id.json()["reference_code"] == ref_code

    # 4. Unknown reference code returns 404
    res_unknown = client.get(
        "/v1/coordinator/programme-enquiries/ENQ-NONEXISTENT",
        headers={"X-Coordinator-ID": "coord_longevity_1", "X-Coordinator-Role": "wellness_curator"},
    )
    assert res_unknown.status_code == 404
