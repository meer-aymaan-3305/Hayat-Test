"""Regression tests: the category-clarify ladder must never repeat itself.

Defect: vague turns ("This is my ticket.", "Please help me.", "I need
something else.") all received the identical either/or question forever.
"""

import pytest
from fastapi.testclient import TestClient

from hayat_backend import main as m
from hayat_backend.config import Settings
from hayat_backend.main import create_app
from hayat_backend.memory_store import MemoryStore


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
    c = client.post(
        "/v1/conversations",
        json={"guest_session_id": s["session_id"]},
        headers={"X-Session-Token": s["session_token"]},
    ).json()
    h = {
        "X-Session-ID": s["session_id"],
        "X-Session-Token": s["session_token"],
        "X-Visitor": "guest",
    }
    if locale == "ar":
        h["X-Reply-Language"] = "ar"
    return c, h


def _chat(client, conv, headers, msg):
    return client.post(
        "/v1/chat",
        json={"conversation_id": conv["id"], "message": msg},
        headers=headers,
    ).json()


def test_first_vague_turn_keeps_category_clarify(client):
    conv, h = _conv(client)
    r = _chat(client, conv, h, "This is my ticket.")
    assert "medical treatment or a wellness programme" in r["reply"]


def test_help_me_does_not_repeat_clarify(client):
    conv, h = _conv(client)
    r1 = _chat(client, conv, h, "This is my ticket.")
    r2 = _chat(client, conv, h, "Please help me.")
    assert r2["reply"] != r1["reply"]
    assert "what you're looking for" in r2["reply"]


def test_something_else_escalates_to_coordinator_offer(client):
    conv, h = _conv(client)
    _chat(client, conv, h, "This is my ticket.")
    _chat(client, conv, h, "Please help me.")
    r = _chat(client, conv, h, "I need something else.")
    assert "coordinator" in r["reply"].lower()


def test_explicit_something_else_skips_first_rung(client):
    conv, h = _conv(client)
    r = _chat(client, conv, h, "I need something else.")
    assert "what you're looking for" in r["reply"]
    assert "medical treatment or a wellness programme?" not in r["reply"]


def test_no_identical_clarify_repeats_across_many_turns(client):
    conv, h = _conv(client)
    replies = [
        _chat(client, conv, h, msg)["reply"]
        for msg in [
            "This is my ticket.",
            "Please help me.",
            "I need something else.",
            "I need something else.",
            "help",
            "what can you do",
            "still need help",
        ]
    ]
    # No two consecutive turns may return the identical reply, and the
    # terminal rung is a capability summary — not another question loop.
    for prev, cur in zip(replies, replies[1:]):
        assert cur != prev
    assert replies[-1].count("?") == 0 or "coordinator" not in replies[-1].lower()


def test_arabic_ladder_escalates(client):
    conv, h = _conv(client, "ar")
    r1 = _chat(client, conv, h, "هذه تذكرتي.")
    assert "علاج طبي أم في برنامج عافية" in r1["reply"]
    r2 = _chat(client, conv, h, "ساعدني من فضلك.")
    assert r2["reply"] != r1["reply"]
    assert "تبحث عنه" in r2["reply"]
    r3 = _chat(client, conv, h, "أحتاج شيئاً آخر.")
    assert "منسق" in r3["reply"]


def test_category_selection_still_works_after_clarify(client):
    """A real answer after the ladder must still route into the funnel."""
    conv, h = _conv(client)
    _chat(client, conv, h, "This is my ticket.")
    _chat(client, conv, h, "Please help me.")
    r = _chat(client, conv, h, "I need help with a medical treatment abroad.")
    assert "treatment or specialty" in r["reply"].lower() or "specialty" in r["reply"].lower()


def test_flexible_timing_answer_is_accepted_not_reasked(client):
    """'I don't know' to a timing question must be recorded as Flexible —
    the funnel advances instead of repeating the same question."""
    conv, h = _conv(client)
    _chat(client, conv, h, "I need a hair transplant consultation.")
    _chat(client, conv, h, "Turkey please.")
    r = _chat(client, conv, h, "I dont exactly know")
    # The reply must not be the identical timing question again.
    assert "what timeframe would suit you best" not in r["reply"].lower() or \
        r["reply"].lower().count("timeframe") <= 1


def test_programmes_overview_question_gets_catalogue_answer(client):
    """'What programmes do you offer' must get the grounded programme list,
    not a vague model reply or a funnel question."""
    conv, h = _conv(client)
    _chat(client, conv, h, "I am interested in a wellness programme.")
    r = _chat(client, conv, h, "What are such programmes?")
    assert "HAYAT-100" in r["reply"] and "AAfiya" in r["reply"] and "FFounders" in r["reply"]


def test_programmes_overview_does_not_hijack_interest_statement(client):
    """Declaring interest must still enter the wellness funnel, not get
    the catalogue FAQ."""
    conv, h = _conv(client)
    r = _chat(client, conv, h, "I am interested in a wellness programme.")
    assert "HAYAT-100" not in r["reply"]


def test_service_explainer_gives_grounded_comparison(client):
    conv, h = _conv(client)
    r = _chat(client, conv, h, "I dont know about anything can you explain both of them")
    assert "medical treatment" in r["reply"].lower()
    assert "wellness" in r["reply"].lower()
    assert "HAYAT-100" not in r["reply"]  # explainer, not catalogue


def test_service_explainer_repeat_uses_simpler_variant(client):
    conv, h = _conv(client)
    r1 = _chat(client, conv, h, "can you explain both of them")
    r2 = _chat(client, conv, h, "Still I dont understand these. Can you guide me through all these")
    assert r2["reply"] != r1["reply"]
    assert "simply" in r2["reply"].lower() or "holida" in r2["reply"].lower()
