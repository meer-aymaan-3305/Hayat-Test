import asyncio
import re
from fastapi.testclient import TestClient

from hayat_backend.chat_service import ChatService
from hayat_backend.main import create_app
from hayat_backend.memory_store import MemoryStore


class MockConsultationModel:
    """Deterministic mock model for conversation flow tests."""

    def __init__(self) -> None:
        self.calls: list[list[dict[str, str]]] = []

    async def complete(self, messages: list[dict[str, str]]) -> str:
        self.calls.append(messages)
        system_content = messages[0]["content"] if messages else ""
        user_content = messages[-1]["content"] if messages else ""

        if "Cardiology" in system_content or "cardiology" in user_content.lower():
            return "Understood — you're interested in cardiology treatment."
        elif "Orthopedics" in system_content or "orthopedics" in user_content.lower():
            return "Understood — you're interested in orthopedic treatment."
        elif "Dermatology" in system_content or "dermatology" in user_content.lower():
            return "Understood — you're interested in dermatology treatment."
        elif "Nephrology" in system_content or "nephrology" in user_content.lower():
            return "Understood — you're interested in nephrology treatment."
        elif "wellness" in user_content.lower():
            return "I can help you explore our wellness programmes."
        return "I can coordinate your treatment with qualified care providers."


def _setup_api_client():
    store = MemoryStore()
    model = MockConsultationModel()
    chat_service = ChatService(store, model)
    client = TestClient(create_app(store=store, chat_service=chat_service))
    session = client.post("/v1/sessions/guest", json={"locale": "en"}).json()
    auth = {
        "X-Session-ID": session["session_id"],
        "X-Session-Token": session["session_token"],
    }
    conversation = client.post(
        "/v1/conversations",
        headers={"X-Session-Token": session["session_token"]},
        json={"guest_session_id": session["session_id"]},
    ).json()
    return client, auth, conversation, store, model


def test_exact_five_message_reproduction_conversation():
    """Reproduce and verify the exact five-message conversation from the bug report:
    1. Bot: Welcome greeting
    2. User: I am interested in medical treatment.
    3. Bot: Asks which medical field and offers Cardiology, Orthopedics, and Dermatology.
    4. User: I want Cardiology.
    5. Bot: Accepts Cardiology, does not say out of scope, does not repeat Hello!
    """
    client, auth, conversation, store, model = _setup_api_client()
    conv_id = conversation["id"]

    # 1. Bot greeting at conversation start
    history = client.get(f"/v1/conversations/{conv_id}/messages", headers=auth).json()
    assert len(history["messages"]) == 1
    bot_greeting = history["messages"][0]["content"]
    assert "I'm Hayat" in bot_greeting

    # 2. User selects: "I am interested in medical treatment."
    turn2 = client.post(
        "/v1/chat",
        headers=auth,
        json={"conversation_id": conv_id, "message": "I am interested in medical treatment."},
    ).json()

    # 3. Bot asks for specialty and offers Cardiology, Orthopedics, Dermatology
    assert turn2["follow_up_target"] == "procedure_or_service"
    assert "treatment or specialty" in turn2["reply"].lower()
    suggestion_labels = [s["label"] for s in turn2["suggested_actions"]]
    assert "Cardiology" in suggestion_labels
    assert "Orthopedics" in suggestion_labels
    assert "Dermatology" in suggestion_labels

    # 4. User: "I want Cardiology."
    turn4 = client.post(
        "/v1/chat",
        headers=auth,
        json={"conversation_id": conv_id, "message": "I want Cardiology."},
    ).json()

    # 5. Bot accepts Cardiology and advances to destination
    reply = turn4["reply"]
    # Must NOT be out of scope fallback
    assert "only about Hayat services" not in reply
    # Must NOT repeat "Hello!" on every turn
    assert not reply.startswith("Hello!")
    # Must acknowledge Cardiology
    assert "cardiology" in reply.lower()
    # Must advance to destination preference
    assert turn4["follow_up_target"] == "destination_preference"
    assert turn4["conversation_state"] == "collecting_details"
    # Cardiology must be stored as structured fact
    facts = {f["field_name"]: f["value"] for f in turn4["persona_profile"]["facts"]}
    assert facts.get("customer_category") == "medical_treatment"
    assert facts.get("procedure_or_service") == "Cardiology"


def test_selecting_medical_treatment_sets_correct_category():
    client, auth, conversation, _, _ = _setup_api_client()
    res = client.post(
        "/v1/chat",
        headers=auth,
        json={"conversation_id": conversation["id"], "message": "I am interested in medical treatment."},
    ).json()
    facts = {f["field_name"]: f["value"] for f in res["persona_profile"]["facts"]}
    assert facts.get("customer_category") == "medical_treatment"
    assert res["conversation_state"] == "collecting_details"


def test_cardiology_accepted_and_stored_in_procedure_or_service():
    client, auth, conversation, store, _ = _setup_api_client()
    conv_id = conversation["id"]
    client.post(
        "/v1/chat",
        headers=auth,
        json={"conversation_id": conv_id, "message": "I am interested in medical treatment."},
    )
    res = client.post(
        "/v1/chat",
        headers=auth,
        json={"conversation_id": conv_id, "message": "I want Cardiology."},
    ).json()
    assert res["escalation_required"] is False
    assert "only about Hayat services" not in res["reply"]
    facts = {f["field_name"]: f["value"] for f in res["persona_profile"]["facts"]}
    assert facts["procedure_or_service"] == "Cardiology"
    assert res["follow_up_target"] == "destination_preference"


def test_medical_treatment_category_persists_across_multiple_turns():
    client, auth, conversation, _, _ = _setup_api_client()
    conv_id = conversation["id"]
    # Turn 1: select category
    client.post(
        "/v1/chat",
        headers=auth,
        json={"conversation_id": conv_id, "message": "I am interested in medical treatment."},
    )
    # Turn 2: specialty
    client.post(
        "/v1/chat",
        headers=auth,
        json={"conversation_id": conv_id, "message": "Cardiology"},
    )
    # Turn 3: destination
    res3 = client.post(
        "/v1/chat",
        headers=auth,
        json={"conversation_id": conv_id, "message": "India"},
    ).json()
    facts = {f["field_name"]: f["value"] for f in res3["persona_profile"]["facts"]}
    assert facts.get("customer_category") == "medical_treatment"
    assert facts.get("procedure_or_service") == "Cardiology"
    assert facts.get("destination_preference") == "India"
    assert res3["follow_up_target"] == "preferred_timing"


def test_various_specialties_and_natural_phrasing_accepted():
    client, auth, conversation, _, _ = _setup_api_client()
    conv_id = conversation["id"]

    for phrase, expected in [
        ("Orthopedics", "Orthopedics"),
        ("Dermatology", "Dermatology"),
        ("Nephrology", "Nephrology"),
        ("Heart treatment", "Heart treatment"),
        ("I need treatment for my heart", "Treatment for my heart"),
    ]:
        # Reset conversation category
        conv_obj = _setup_api_client()
        c_client, c_auth, c_conv, _, _ = conv_obj
        c_client.post(
            "/v1/chat",
            headers=c_auth,
            json={"conversation_id": c_conv["id"], "message": "I am interested in medical treatment."},
        )
        res = c_client.post(
            "/v1/chat",
            headers=c_auth,
            json={"conversation_id": c_conv["id"], "message": phrase},
        ).json()
        assert "only about Hayat services" not in res["reply"], f"Failed on {phrase}"
        facts = {f["field_name"]: f["value"] for f in res["persona_profile"]["facts"]}
        assert "procedure_or_service" in facts, f"Missing procedure_or_service on {phrase}"
        assert facts["customer_category"] == "medical_treatment"


def test_question_about_specialty_does_not_trigger_fallback():
    client, auth, conversation, _, _ = _setup_api_client()
    conv_id = conversation["id"]
    client.post(
        "/v1/chat",
        headers=auth,
        json={"conversation_id": conv_id, "message": "I am interested in medical treatment."},
    )
    res = client.post(
        "/v1/chat",
        headers=auth,
        json={
            "conversation_id": conv_id,
            "message": "Can you explain what cardiology treatment involves?",
        },
    ).json()
    assert "only about Hayat services" not in res["reply"]
    assert res["escalation_required"] is False


def test_genuine_unrelated_request_still_triggers_fallback():
    client, auth, conversation, _, _ = _setup_api_client()
    conv_id = conversation["id"]
    res = client.post(
        "/v1/chat",
        headers=auth,
        json={"conversation_id": conv_id, "message": "How do I bake a cake?"},
    ).json()
    assert "only about Hayat services" in res["reply"]
    assert res["escalation_required"] is False


def test_category_switch_from_medical_to_wellness_handled_cleanly():
    client, auth, conversation, _, _ = _setup_api_client()
    conv_id = conversation["id"]
    # Start with medical treatment
    client.post(
        "/v1/chat",
        headers=auth,
        json={"conversation_id": conv_id, "message": "I am interested in medical treatment."},
    )
    client.post(
        "/v1/chat",
        headers=auth,
        json={"conversation_id": conv_id, "message": "Cardiology"},
    )
    # User intentionally switches to wellness
    res = client.post(
        "/v1/chat",
        headers=auth,
        json={"conversation_id": conv_id, "message": "Actually I am interested in a wellness programme."},
    ).json()
    facts = {f["field_name"]: f["value"] for f in res["persona_profile"]["facts"]}
    assert facts.get("customer_category") == "wellness"
    # Should not mix procedure_or_service into wellness
    assert "procedure_or_service" not in facts
    assert res["follow_up_target"] == "wellness_programme_or_goal"


def test_repeated_answer_does_not_duplicate_facts_or_corrupt_history():
    client, auth, conversation, store, _ = _setup_api_client()
    conv_id = conversation["id"]
    client.post(
        "/v1/chat",
        headers=auth,
        json={"conversation_id": conv_id, "message": "I am interested in medical treatment."},
    )
    client.post(
        "/v1/chat",
        headers=auth,
        json={"conversation_id": conv_id, "message": "I want Cardiology."},
    )
    # Repeated answer
    res_repeat = client.post(
        "/v1/chat",
        headers=auth,
        json={"conversation_id": conv_id, "message": "I want Cardiology."},
    ).json()
    cardiology_facts = [
        f for f in res_repeat["persona_profile"]["facts"]
        if f["field_name"] == "procedure_or_service"
    ]
    assert len(cardiology_facts) == 1
    assert cardiology_facts[0]["value"] == "Cardiology"
    assert res_repeat["profile_updates"] == []


def test_opening_greeting_is_not_repeated_on_every_turn():
    client, auth, conversation, _, _ = _setup_api_client()
    conv_id = conversation["id"]

    res1 = client.post(
        "/v1/chat",
        headers=auth,
        json={"conversation_id": conv_id, "message": "I am interested in medical treatment."},
    ).json()
    # First user message response starts with greeting
    # The greeting was given once at conversation start, never re-added to a reply.
    assert not res1["reply"].startswith("Hello")

    res2 = client.post(
        "/v1/chat",
        headers=auth,
        json={"conversation_id": conv_id, "message": "I want Cardiology."},
    ).json()
    # Second turn MUST NOT start with "Hello!"
    assert not res2["reply"].startswith("Hello!")

    res3 = client.post(
        "/v1/chat",
        headers=auth,
        json={"conversation_id": conv_id, "message": "India"},
    ).json()
    # Third turn MUST NOT start with "Hello!"
    assert not res3["reply"].startswith("Hello!")


def test_conversation_history_is_supplied_to_llm():
    client, auth, conversation, store, model = _setup_api_client()
    conv_id = conversation["id"]
    client.post(
        "/v1/chat",
        headers=auth,
        json={"conversation_id": conv_id, "message": "I am interested in medical treatment."},
    )
    client.post(
        "/v1/chat",
        headers=auth,
        json={"conversation_id": conv_id, "message": "I want Cardiology."},
    )
    last_call = model.calls[-1]
    # Check that prior messages are passed
    all_contents = [msg["content"] for msg in last_call]
    assert any("I am interested in medical treatment." in c for c in all_contents)
    assert any("I want Cardiology." in c for c in all_contents)
    assert any("procedure_or_service" in c for c in all_contents)


def test_mixed_in_scope_answer_and_unrelated_question():
    client, auth, conversation, _, _ = _setup_api_client()
    conv_id = conversation["id"]
    client.post(
        "/v1/chat",
        headers=auth,
        json={"conversation_id": conv_id, "message": "I am interested in medical treatment."},
    )
    # User message contains both a valid specialty answer and an unrelated question
    res = client.post(
        "/v1/chat",
        headers=auth,
        json={
            "conversation_id": conv_id,
            "message": "I want Cardiology, and also what is the recipe for chocolate cake?",
        },
    ).json()
    # Must NOT trigger the out_of_scope guardrail
    assert "only about Hayat services" not in res["reply"]
    assert res["escalation_required"] is False
    # Must extract the valid consultation specialty
    facts = {f["field_name"]: f["value"] for f in res["persona_profile"]["facts"]}
    assert facts.get("procedure_or_service") == "Cardiology"
    assert res["follow_up_target"] == "destination_preference"


def test_fertility_button_keeps_the_conversation_going():
    client = TestClient(create_app(store=MemoryStore()))
    session = client.post("/v1/sessions/guest", json={"locale": "en"}).json()
    headers = {"X-Session-ID": session["session_id"], "X-Session-Token": session["session_token"]}
    conversation = client.post(
        "/v1/conversations",
        json={"guest_session_id": session["session_id"]},
        headers={"X-Session-Token": session["session_token"]},
    ).json()
    body = client.post(
        "/v1/chat",
        json={"conversation_id": conversation["id"], "message": "Fertility: I want to explore options abroad"},
        headers=headers,
    ).json()
    assert body["next_action"] == "collect_detail"
    assert body["follow_up_target"] == "destination_preference"
