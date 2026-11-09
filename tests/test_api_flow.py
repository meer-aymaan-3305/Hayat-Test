from fastapi.testclient import TestClient

from hayat_backend.main import create_app
from hayat_backend.memory_store import MemoryStore
from hayat_backend.otp import SyntheticOTPProvider


app = create_app(store=MemoryStore())


def test_guest_chat_and_authorized_history():
    client = TestClient(app)
    session = client.post("/v1/sessions/guest").json()
    headers = {"X-Session-Token": session["session_token"]}
    conversation = client.post(
        "/v1/conversations",
        headers=headers,
        json={"guest_session_id": session["session_id"]},
    )
    assert conversation.status_code == 200
    conversation_id = conversation.json()["id"]
    chat_headers = {**headers, "X-Session-ID": session["session_id"]}

    response = client.post(
        "/v1/chat",
        headers=chat_headers,
        json={"conversation_id": conversation_id, "message": "What wellness services are available?"},
    )
    assert response.status_code == 200
    assert response.json()["reply"]

    history = client.get(
        f"/v1/conversations/{conversation_id}/messages", headers=chat_headers
    )
    assert [item["role"] for item in history.json()["messages"]] == [
        "assistant", "user", "assistant"
    ]


def test_chat_accepts_streamlit_payload_and_duplicate_id_is_safe():
    client = TestClient(create_app(store=MemoryStore()))
    session = client.post("/v1/sessions/guest", json={"locale": "en"}).json()
    conversation = client.post(
        "/v1/conversations",
        headers={"X-Session-Token": session["session_token"]},
        json={"guest_session_id": session["session_id"]},
    ).json()
    headers = {
        "X-Session-ID": session["session_id"],
        "X-Session-Token": session["session_token"],
    }
    payload = {
        "conversation_id": conversation["id"],
        "message": "What wellness services are available?",
        "client_message_id": "streamlit-rerun-1",
    }
    first = client.post("/v1/chat", headers=headers, json=payload)
    second = client.post("/v1/chat", headers=headers, json=payload)

    assert first.status_code == 200
    assert second.status_code == 200
    assert second.json()["message_id"] == first.json()["message_id"]


def test_chat_validation_error_identifies_invalid_payload_fields():
    client = TestClient(create_app(store=MemoryStore()))
    response = client.post(
        "/v1/chat",
        headers={"X-Session-ID": "not-a-uuid", "X-Session-Token": "redacted-token"},
        json={"conversation_id": "not-a-uuid", "message": 123},
    )

    assert response.status_code == 422
    locations = {tuple(item["loc"]) for item in response.json()["detail"]}
    assert ("header", "X-Session-ID") in locations
    assert ("body", "conversation_id") in locations
    assert ("body", "message") in locations


def test_conversation_creation_returns_greeting_and_initial_actions_once():
    client = TestClient(create_app(store=MemoryStore()))
    session = client.post("/v1/sessions/guest").json()
    response = client.post(
        "/v1/conversations",
        headers={"X-Session-Token": session["session_token"]},
        json={"guest_session_id": session["session_id"]},
    )

    body = response.json()
    assert response.status_code == 200
    assert body["greeting"]["role"] == "assistant"
    assert len(body["suggested_actions"]) == 2
    assert body["state"] == "requested"
    assert [action["action_id"] for action in body["suggested_actions"]] == [
        "medical_treatment", "wellness_programme"
    ]
    assert body["greeting"]["content"] == (
        "Welcome! I'm Hayat, your Trawellcare assistant. I can help you arrange a "
        "medical treatment consultation or explore our wellness programmes. Which are "
        "you interested in?"
    )


def test_medical_category_action_stores_category_and_uses_medical_funnel():
    client = TestClient(create_app(store=MemoryStore()))
    session = client.post("/v1/sessions/guest").json()
    conversation = client.post(
        "/v1/conversations",
        headers={"X-Session-Token": session["session_token"]},
        json={"guest_session_id": session["session_id"]},
    ).json()
    headers = {
        "X-Session-ID": session["session_id"],
        "X-Session-Token": session["session_token"],
    }

    response = client.post(
        "/v1/chat",
        headers=headers,
        json={
            "conversation_id": conversation["id"],
            "message": "I am interested in medical treatment.",
            "client_message_id": "medical-category",
        },
    )

    body = response.json()
    assert response.status_code == 200
    assert any(
        fact["field_name"] == "customer_category"
        and fact["value"] == "medical_treatment"
        for fact in body["persona_profile"]["facts"]
    )
    assert body["follow_up_target"] == "procedure_or_service"
    assert any(action["action_id"] == "request_consultation" for action in body["suggested_actions"])


def test_wellness_category_action_asks_wellness_goal_not_treatment():
    client = TestClient(create_app(store=MemoryStore()))
    session = client.post("/v1/sessions/guest").json()
    conversation = client.post(
        "/v1/conversations",
        headers={"X-Session-Token": session["session_token"]},
        json={"guest_session_id": session["session_id"]},
    ).json()
    headers = {
        "X-Session-ID": session["session_id"],
        "X-Session-Token": session["session_token"],
    }

    response = client.post(
        "/v1/chat",
        headers=headers,
        json={
            "conversation_id": conversation["id"],
            "message": "I am interested in a wellness programme.",
            "client_message_id": "wellness-category",
        },
    )

    body = response.json()
    assert response.status_code == 200
    assert body["follow_up_target"] == "wellness_programme_or_goal"
    assert "wellness programme or goal" in body["follow_up_question"]
    assert "treatment or specialty" not in body["follow_up_question"]


def test_conversational_submission_is_pending_after_otp_and_consent():
    client = TestClient(create_app(otp_provider=SyntheticOTPProvider(), store=MemoryStore()))
    session = client.post("/v1/sessions/guest").json()
    conversation = client.post(
        "/v1/conversations",
        headers={"X-Session-Token": session["session_token"]},
        json={"guest_session_id": session["session_id"]},
    ).json()
    headers = {
        "X-Session-ID": session["session_id"],
        "X-Session-Token": session["session_token"],
    }
    chat = client.post(
        "/v1/chat",
        headers=headers,
        json={
            "conversation_id": conversation["id"],
            "message": (
                "I want a consultation for medical treatment. My name is Amina Example, "
                "my phone is +96890000000, I need dental implants in India in December, "
                "and my timezone is Asia/Muscat."
            ),
            "client_message_id": "conversational-details",
        },
    )
    assert chat.status_code == 200

    challenge = client.post(
        "/v1/consultations/otp/start",
        headers=headers,
        json={
            "conversation_id": conversation["id"],
            "phone_number": "+96890000000",
        },
    ).json()
    verified = client.post(
        "/v1/consultations/otp/verify",
        headers=headers,
        json={
            "conversation_id": conversation["id"],
            "challenge_id": challenge["challenge_id"],
            "code": "123456",
        },
    )
    assert verified.json()["verified"] is True

    consent = client.post(
        "/v1/consent",
        headers={"X-Session-Token": session["session_token"]},
        json={
            "guest_session_id": session["session_id"],
            "consent_type": "consultation_processing",
            "granted": True,
            "policy_version": "consultation_v1",
        },
    )
    assert consent.status_code == 200

    submitted = client.post(
        "/v1/chat",
        headers=headers,
        json={
            "conversation_id": conversation["id"],
            "message": "Please submit the request.",
            "client_message_id": "conversational-submit",
        },
    )
    body = submitted.json()
    assert submitted.status_code == 200
    assert body["submission_status"] == "pending"
    assert body["conversation_state"] == "pending_coordinator_confirmation"
    assert "coordinator will contact you shortly" in body["reply"]
    assert body["consultation"]["id"]


def test_guest_cannot_read_another_session_conversation():
    client = TestClient(app)
    first = client.post("/v1/sessions/guest").json()
    second = client.post("/v1/sessions/guest").json()
    conversation = client.post(
        "/v1/conversations",
        headers={"X-Session-Token": first["session_token"]},
        json={"guest_session_id": first["session_id"]},
    ).json()

    response = client.get(
        f"/v1/conversations/{conversation['id']}/messages",
        headers={"X-Session-ID": second["session_id"], "X-Session-Token": second["session_token"]},
    )
    assert response.status_code == 403


def test_emergency_message_escalates_without_model_claim():
    client = TestClient(app)
    session = client.post("/v1/sessions/guest").json()
    headers = {"X-Session-Token": session["session_token"]}
    conversation = client.post(
        "/v1/conversations",
        headers=headers,
        json={"guest_session_id": session["session_id"]},
    ).json()
    response = client.post(
        "/v1/chat",
        headers={**headers, "X-Session-ID": session["session_id"]},
        json={"conversation_id": conversation["id"], "message": "I have severe chest pain"},
    )
    assert response.json()["escalation_required"] is True
    assert "emergency" in response.json()["reply"].lower()


def test_english_reply_starts_with_greeting_and_suggests_questions():
    client = TestClient(app)
    session = client.post("/v1/sessions/guest").json()
    headers = {"X-Session-Token": session["session_token"]}
    conversation = client.post(
        "/v1/conversations", headers=headers,
        json={"guest_session_id": session["session_id"]},
    ).json()
    response = client.post(
        "/v1/chat",
        headers={**headers, "X-Session-ID": session["session_id"]},
        json={"conversation_id": conversation["id"], "message": "What wellness services do you offer?"},
    )
    reply = response.json()["reply"]
    assert reply.startswith("Hello!")
    assert response.json()["suggestions"]


def test_arabic_reply_is_arabic_and_suggests_questions():
    client = TestClient(app)
    session = client.post("/v1/sessions/guest").json()
    headers = {"X-Session-Token": session["session_token"]}
    conversation = client.post(
        "/v1/conversations", headers=headers,
        json={"guest_session_id": session["session_id"]},
    ).json()
    response = client.post(
        "/v1/chat",
        headers={**headers, "X-Session-ID": session["session_id"]},
        json={"conversation_id": conversation["id"], "message": "ما خدمات العافية المتاحة؟"},
    )
    reply = response.json()["reply"]
    assert reply.startswith("مرحباً!")
    assert not reply.startswith("Hello!")


def test_out_of_scope_question_gets_topic_boundary_and_suggestions():
    client = TestClient(app)
    session = client.post("/v1/sessions/guest").json()
    headers = {"X-Session-Token": session["session_token"]}
    conversation = client.post(
        "/v1/conversations", headers=headers,
        json={"guest_session_id": session["session_id"]},
    ).json()
    response = client.post(
        "/v1/chat",
        headers={**headers, "X-Session-ID": session["session_id"]},
        json={"conversation_id": conversation["id"], "message": "How do I bake a cake?"},
    )
    body = response.json()
    assert body["escalation_required"] is False
    assert "only about Hayat services" in body["reply"]
    assert body["reply"].startswith("Hello!")
    assert body["suggestions"] == []


def test_chat_returns_persona_facts_once_and_tracks_state():
    client = TestClient(create_app(store=MemoryStore()))
    session = client.post("/v1/sessions/guest").json()
    session_headers = {
        "X-Session-Token": session["session_token"],
        "X-Session-ID": session["session_id"],
    }
    conversation = client.post(
        "/v1/conversations",
        headers={"X-Session-Token": session["session_token"]},
        json={"guest_session_id": session["session_id"]},
    ).json()
    payload = {
        "conversation_id": conversation["id"],
        "message": "I am interested in a consultation. Email me at a@example.com in Asia/Muscat.",
    }
    first = client.post("/v1/chat", headers=session_headers, json=payload).json()
    second = client.post("/v1/chat", headers=session_headers, json=payload).json()

    assert first["conversation_state"] == "collecting_details"
    assert first["next_action"] == "collect_detail"
    assert {"email", "timezone"}.issubset(
        {fact["field_name"] for fact in first["persona_profile"]["facts"]}
    )
    assert second["persona_profile"]["facts"] == first["persona_profile"]["facts"]
