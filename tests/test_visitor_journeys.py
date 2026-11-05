"""The website tells Hayat whether a visitor is a guest or a signed-in customer."""

import pytest
from fastapi.testclient import TestClient

from hayat_backend.main import create_app
from hayat_backend.memory_store import MemoryStore

ASKS_FOR_CONTACT = ("phone number", "what name", "otp", "reference:", "verify your phone")


@pytest.fixture
def client():
    return TestClient(create_app(store=MemoryStore()))


def _start(client, visitor):
    session = client.post("/v1/sessions/guest", json={"locale": "en"}).json()
    conversation = client.post(
        "/v1/conversations",
        json={"guest_session_id": session["session_id"]},
        headers={"X-Session-Token": session["session_token"]},
    ).json()
    headers = {"X-Session-ID": session["session_id"], "X-Session-Token": session["session_token"], "X-Visitor": visitor}

    def say(message, as_visitor=None):
        sent = {**headers, "X-Visitor": as_visitor or visitor}
        return client.post("/v1/chat", headers=sent, json={"conversation_id": conversation["id"], "message": message}).json()

    return say


PROGRAMME_JOURNEY = ["Tell me about AAfiya", "Yoga please", "I prefer Japan.", "I am flexible on travel timing."]


def test_guest_is_asked_to_sign_in_before_registering(client):
    say = _start(client, "guest")
    for message in PROGRAMME_JOURNEY:
        say(message)
    reply = say("Yes, please register my interest.")
    assert "sign in or create a free account" in reply["reply"]
    assert [action["type"] for action in reply["suggested_actions"]] == ["sign_in"]
    assert reply["programme_enquiry"]["registration_status"] == "unregistered"
    assert reply["programme_enquiry"]["reference_code"] is None


def test_customer_registers_with_no_details_and_no_reference_in_the_reply(client):
    say = _start(client, "customer")
    for message in PROGRAMME_JOURNEY:
        say(message)
    reply = say("Yes, please register my interest.")
    assert "My Programmes" in reply["reply"]
    assert not any(term in reply["reply"].lower() for term in ASKS_FOR_CONTACT)
    assert reply["programme_enquiry"]["registration_status"] == "interest_registered"


def test_a_guest_who_signs_in_carries_on_from_the_same_chat(client):
    say = _start(client, "guest")
    for message in PROGRAMME_JOURNEY:
        say(message)
    say("Yes, please register my interest.")
    reply = say("Yes, please register my interest.", as_visitor="customer")
    assert reply["programme_enquiry"]["destination_preference"] == "Japan"
    assert reply["programme_enquiry"]["registration_status"] == "interest_registered"


MEDICAL_JOURNEY = [
    "Cardiology: I would like to travel for treatment",
    "I prefer India.",
    "I am flexible on timing.",
    "I would like to book a consultation with a coordinator",
]


def test_customer_is_never_asked_for_contact_details_in_the_medical_journey(client):
    say = _start(client, "customer")
    for message in MEDICAL_JOURNEY:
        reply = say(message)
        assert not any(term in reply["reply"].lower() for term in ASKS_FOR_CONTACT), reply["reply"]


def test_guest_is_never_asked_for_contact_details_in_the_medical_journey(client):
    say = _start(client, "guest")
    for message in MEDICAL_JOURNEY:
        reply = say(message)
        assert not any(term in reply["reply"].lower() for term in ASKS_FOR_CONTACT), reply["reply"]


def test_an_unknown_visitor_type_is_rejected(client):
    say = _start(client, "guest")
    assert "detail" in say("Hello", as_visitor="admin")


def _register(client, consent, approved, monkeypatch):
    from hayat_backend import main
    from hayat_backend.config import Settings

    monkeypatch.setattr(main, "get_settings", lambda: Settings(app_env="test", policy_addendum_1_1_approved=approved))
    test_client = TestClient(create_app(store=MemoryStore()))
    session = test_client.post("/v1/sessions/guest", json={"locale": "en"}).json()
    conversation = test_client.post(
        "/v1/conversations",
        json={"guest_session_id": session["session_id"]},
        headers={"X-Session-Token": session["session_token"]},
    ).json()
    headers = {
        "X-Session-ID": session["session_id"],
        "X-Session-Token": session["session_token"],
        "X-Visitor": "customer",
        "X-Contact-Consent": "true" if consent else "false",
    }
    reply = {}
    for message in [*PROGRAMME_JOURNEY, "Yes, please register my interest."]:
        reply = test_client.post("/v1/chat", headers=headers, json={"conversation_id": conversation["id"], "message": message}).json()
    return reply["reply"]


@pytest.mark.parametrize("consent, approved, promised", [(True, True, True), (True, False, False), (False, True, False)])
def test_contact_is_only_promised_with_consent_and_compliance_approval(client, monkeypatch, consent, approved, promised):
    assert ("contact you" in _register(client, consent, approved, monkeypatch)) is promised


def test_pressing_a_button_on_the_arabic_site_stays_in_arabic(client):
    session = client.post("/v1/sessions/guest", json={"locale": "ar"}).json()
    conversation = client.post(
        "/v1/conversations",
        json={"guest_session_id": session["session_id"]},
        headers={"X-Session-Token": session["session_token"]},
    ).json()
    headers = {"X-Session-ID": session["session_id"], "X-Session-Token": session["session_token"], "X-Visitor": "guest"}
    first = client.post("/v1/chat", headers=headers, json={"conversation_id": conversation["id"], "message": "أخبرني عن برنامج AAfiya"}).json()
    labels = [action["label"] for action in first["suggested_actions"]]
    assert "البيلاتس واليوغا" in labels
    pressed = first["suggested_actions"][0]["payload"]
    second = client.post("/v1/chat", headers={**headers, "X-Reply-Language": "ar"}, json={"conversation_id": conversation["id"], "message": pressed}).json()
    assert second["language"] == "ar"
    assert "الإمارات" in [action["label"] for action in second["suggested_actions"]]


class _ForbiddenModel:
    """Fails the test if the AI is asked to write a reply."""

    async def complete(self, messages):
        raise AssertionError("The AI must not be used for website visitors.")


def test_website_visitors_get_scripted_replies_while_the_ai_is_off():
    from hayat_backend.chat_service import ChatService

    store = MemoryStore()
    client = TestClient(create_app(store=store, chat_service=ChatService(store, _ForbiddenModel())))
    say = _start(client, "guest")
    for message in ["Medical treatments abroad", "Cardiology: I need a heart valve treatment", "I prefer India."]:
        reply = say(message)
        assert reply["reply"]
        assert "outside what I can help" not in reply["reply"]


@pytest.mark.parametrize(
    "opening, visitor",
    [("أخبرني عن برنامج AAfiya", "customer"), ("أخبرني عن برنامج HAYAT-100", "customer"), ("أخبرني عن برنامج FFounders", "customer"), ("علاج طبي", "guest")],
)
def test_arabic_journeys_have_no_english_replies_or_buttons(client, opening, visitor):
    import re

    def english(text):
        return re.findall(r"[A-Za-z]{3,}", re.sub(r"HAYAT-100|AAfiya|FFounders", "", text))

    session = client.post("/v1/sessions/guest", json={"locale": "ar"}).json()
    conversation = client.post(
        "/v1/conversations",
        json={"guest_session_id": session["session_id"]},
        headers={"X-Session-Token": session["session_token"]},
    ).json()
    headers = {"X-Session-ID": session["session_id"], "X-Session-Token": session["session_token"], "X-Visitor": visitor}
    message, sent = opening, headers
    for _ in range(11):
        body = client.post("/v1/chat", headers=sent, json={"conversation_id": conversation["id"], "message": message}).json()
        assert not english(body["reply"]), body["reply"]
        actions = [action for action in body["suggested_actions"] if action["type"] == "message"]
        assert not [action["label"] for action in actions if english(action["label"])]
        if (body.get("programme_enquiry") or {}).get("registration_status") == "interest_registered" or not actions:
            break
        pick = next((action for action in actions if "register" in action["payload"].lower()), actions[0])
        message, sent = pick["payload"], {**headers, "X-Reply-Language": "ar"}
