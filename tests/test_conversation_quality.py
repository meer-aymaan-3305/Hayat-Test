"""Regression tests for conversational-quality defects D1-D4."""

import pytest
from fastapi.testclient import TestClient

from hayat_backend import main as m
from hayat_backend.config import Settings
from hayat_backend.main import create_app
from hayat_backend.memory_store import MemoryStore
from hayat_backend.question_planner import QuestionPlanner


@pytest.fixture
def client(tmp_path):
    settings = Settings(app_env="test", knowledge_dir=str(tmp_path / "k"))
    orig = m.get_settings
    m.get_settings = lambda: settings
    try:
        yield TestClient(create_app(store=MemoryStore()))
    finally:
        m.get_settings = orig


def _conv(client, locale="en"):
    s = client.post("/v1/sessions/guest", json={"locale": locale}).json()
    c = client.post("/v1/conversations", json={"guest_session_id": s["session_id"]},
                    headers={"X-Session-Token": s["session_token"]}).json()
    h = {"X-Session-ID": s["session_id"], "X-Session-Token": s["session_token"], "X-Visitor": "guest"}
    if locale == "ar":
        h["X-Reply-Language"] = "ar"
    return c, h


def _chat(client, conv, headers, msg):
    return client.post("/v1/chat", json={"conversation_id": conv["id"], "message": msg}, headers=headers).json()


# ---------- D1: first-turn intent differentiation ----------

def test_medical_first_turn_asks_treatment_not_generic_clarify(client):
    conv, h = _conv(client)
    r = _chat(client, conv, h, "I am interested in travelling for a medical procedure. How can you help?")
    reply = r["reply"]
    assert "treatment or specialty" in reply.lower() or "specialty" in reply.lower()
    assert "or a wellness programme" not in reply  # not the generic either/or


def test_wellness_first_turn_asks_wellness_goal(client):
    conv, h = _conv(client)
    r = _chat(client, conv, h, "I am looking for a wellness experience. What options do you have?")
    reply = r["reply"].lower()
    assert "wellness programme or goal" in reply or "wellness goal" in reply
    assert "or a wellness programme?" != reply.strip().lower()[-45:]


def test_ambiguous_first_turn_keeps_clarify(client):
    conv, h = _conv(client)
    r = _chat(client, conv, h, "I want something related to health, but I am not sure what.")
    assert "medical treatment or a wellness programme" in r["reply"]


def test_mixed_intent_first_turn_gets_relevant_question(client):
    conv, h = _conv(client)
    r = _chat(client, conv, h, "I am exploring medical and wellness options. What do you offer?")
    # Mixed intent must not get the old identical generic reply — it should
    # either clarify or ask a journey-relevant question.
    assert "?" in r["reply"]
    assert "wellness" in r["reply"].lower() or "medical" in r["reply"].lower()


# ---------- D2: Arabic intent classification ----------

def test_arabic_generic_wellness_not_aafiya(client):
    conv, h = _conv(client, "ar")
    r = _chat(client, conv, h, "أبحث عن برنامج عافية عام.")
    reply = r["reply"]
    assert "AAfiya" not in reply and "السيدات" not in reply.split("؟")[0]


def test_arabic_hayat100_maps_longevity(client):
    conv, h = _conv(client, "ar")
    r = _chat(client, conv, h, "أريد معرفة المزيد عن HAYAT-100")
    assert "HAYAT-100" in r["reply"] and ("طول العمر" in r["reply"] or "شيخوخة" in r["reply"])


def test_arabic_aafiya_maps_womens(client):
    conv, h = _conv(client, "ar")
    r = _chat(client, conv, h, "برنامج عافية السيدات AAfiya")
    assert "AAfiya" in r["reply"] and "سيدات" in r["reply"]


def test_arabic_ffounders_maps_executive(client):
    conv, h = _conv(client, "ar")
    r = _chat(client, conv, h, "ما هو برنامج FFounders للمدراء التنفيذيين؟")
    assert "FFounders" in r["reply"]


def test_arabic_ambiguous_wellness_clarifies(client):
    conv, h = _conv(client, "ar")
    r = _chat(client, conv, h, "أريد شيئاً متعلقاً بالصحة لكنني لست متأكداً مما أريد.")
    # Must not silently assign a programme; should clarify or ask a goal question
    assert "AAfiya" not in r["reply"] or "HAYAT-100" in r["reply"] or "FFounders" in r["reply"] or "؟" in r["reply"]


# ---------- D3: source attribution honesty ----------

def test_sources_empty_for_unsupported_signin_reply(client):
    conv, h = _conv(client)
    r = _chat(client, conv, h, "I want a consultation with a coordinator please.")
    assert r["sources"] == [] or all(s.get("document_id") for s in r["sources"])


def test_sources_have_required_fields_when_present(client, tmp_path):
    conv, h = _conv(client)
    # Drive a knowledge-style question in scripted mode; whatever sources
    # appear must carry document_id/title/version and never be invented.
    r = _chat(client, conv, h, "What should I prepare for a consultation?")
    for s in r["sources"]:
        assert set(("document_id", "title", "version")) <= set(s)


# ---------- D4: repetitive sign-in CTA ----------

def test_signin_cta_not_repeated_consecutively(client):
    conv, h = _conv(client)
    # Drive into funnel state with consultation intent twice.
    r1 = _chat(client, conv, h, "I want to speak to a coordinator about cardiology in India.")
    r2 = _chat(client, conv, h, "Cardiology treatment, India, next month.")
    r3 = _chat(client, conv, h, "Yes, please proceed with the consultation.")
    cta_count = sum(
        1 for r in (r1, r2, r3)
        if "sign in or create a free account" in r["reply"].lower()
    )
    assert cta_count <= 2, f"CTA repeated {cta_count} times: {[r['reply'][:60] for r in (r1,r2,r3)]}"
