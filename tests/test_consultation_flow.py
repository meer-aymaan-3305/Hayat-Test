from fastapi.testclient import TestClient

from hayat_backend.main import create_app
from hayat_backend.memory_store import MemoryStore
from hayat_backend.otp import OTPProviderError, SyntheticOTPProvider


def _setup():
    client = TestClient(create_app(SyntheticOTPProvider(), store=MemoryStore()))
    session = client.post("/v1/sessions/guest").json()
    headers = {"X-Session-Token": session["session_token"]}
    conversation = client.post(
        "/v1/conversations",
        headers=headers,
        json={"guest_session_id": session["session_id"]},
    ).json()
    auth = {**headers, "X-Session-ID": session["session_id"]}
    return client, session, conversation, auth


def _details():
    return {
        "name": "Amina Example",
        "phone_number": "+96890000000",
        "email": "amina@example.com",
        "preferred_contact_method": "phone",
        "care_category": "wellness",
        "procedure_or_service": "recovery programme",
        "destination_preference": "India",
        "preferred_timing": "next month",
        "preferred_dates_times": "Weekday afternoons",
        "timezone": "Asia/Muscat",
    }


def test_guest_greeting_and_full_pending_consultation_export():
    client, session, conversation, auth = _setup()
    greeting = client.get(
        f"/v1/conversations/{conversation['id']}/messages", headers=auth
    ).json()["messages"][0]
    assert greeting["role"] == "assistant"
    assert greeting["content"].startswith("Welcome! I'm Hayat")

    lead = client.post(
        f"/v1/leads?conversation_id={conversation['id']}",
        headers=auth,
        json=_details(),
    )
    assert lead.status_code == 200

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

    start = client.post(
        "/v1/consultations/otp/start",
        headers=auth,
        json={"conversation_id": conversation["id"], "phone_number": _details()["phone_number"]},
    )
    challenge_id = start.json()["challenge_id"]
    invalid = client.post(
        "/v1/consultations/otp/verify",
        headers=auth,
        json={"conversation_id": conversation["id"], "challenge_id": challenge_id, "code": "000000"},
    )
    assert invalid.status_code == 400

    verified = client.post(
        "/v1/consultations/otp/verify",
        headers=auth,
        json={"conversation_id": conversation["id"], "challenge_id": challenge_id, "code": "123456"},
    )
    assert verified.json()["verified"] is True

    request = client.post(
        "/v1/consultations",
        headers=auth,
        json={"conversation_id": conversation["id"], "consent_policy_version": "consultation_v1", **_details()},
    )
    assert request.status_code == 200
    assert request.json()["status"] == "pending"

    duplicate = client.post(
        "/v1/consultations",
        headers=auth,
        json={"conversation_id": conversation["id"], "consent_policy_version": "consultation_v1", **_details()},
    )
    assert duplicate.json()["id"] == request.json()["id"]

    export = client.get(
        f"/v1/conversations/{conversation['id']}/export.json", headers=auth
    )
    assert export.status_code == 200
    assert export.json()["case_facts"]["needs"]["care_category"] == "wellness"
    assert export.json()["consultation"]["status"] == "pending"
    assert "session_token" not in export.text
    assert "123456" not in export.text


def test_consultation_requires_consent_and_verified_phone():
    client, _, conversation, auth = _setup()
    client.post(
        f"/v1/leads?conversation_id={conversation['id']}",
        headers=auth,
        json=_details(),
    )
    response = client.post(
        "/v1/consultations",
        headers=auth,
        json={"conversation_id": conversation["id"], "consent_policy_version": "consultation_v1", **_details()},
    )
    assert response.status_code == 400
    assert "consent" in response.text.lower()


def test_missing_sms_provider_fails_closed():
    from hayat_backend.main import create_app

    client = TestClient(create_app(store=MemoryStore()))
    session = client.post("/v1/sessions/guest").json()
    auth = {"X-Session-Token": session["session_token"], "X-Session-ID": session["session_id"]}
    conversation = client.post(
        "/v1/conversations",
        headers=auth,
        json={"guest_session_id": session["session_id"]},
    ).json()
    client.post(
        f"/v1/leads?conversation_id={conversation['id']}",
        headers=auth,
        json=_details(),
    )
    response = client.post(
        "/v1/consultations/otp/start",
        headers=auth,
        json={"conversation_id": conversation["id"], "phone_number": _details()["phone_number"]},
    )
    assert response.status_code == 503
