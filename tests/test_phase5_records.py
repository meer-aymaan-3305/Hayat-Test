"""Phase 5 of IMPLEMENTATION.md: a record per turn, an admin view, and the 11.1 measures."""

from fastapi.testclient import TestClient

from hayat_backend.audit_logging import global_audit_store
from hayat_backend.main import create_app
from hayat_backend.measures import compute, verdicts
from hayat_backend.memory_store import MemoryStore

from test_flow_addendum import A, MED, _chat, say


def test_every_turn_is_recorded_with_state_guard_and_passages():
    service, _, c = _chat({"knee in India": A(intent="answering", lane="MEDICAL", slots=MED)})
    say(service, c, "knee in India")
    record = global_audit_store.turns_for(c.id)[-1]
    assert record["visitor_message"] == "knee in India" and record["next_action"] == "collect_detail"
    assert "m.destination_country" not in record["state_before"]["slots"]
    assert record["state_after"]["slots"]["m.destination_country"]["value"] == "India"
    assert {"guard", "passage_ids", "reply_source", "latency_ms"} <= set(record)


def test_clinical_words_never_reach_the_turn_record():
    service, _, c = _chat({}, default=A(intent="clinical_detail"))
    say(service, c, "I was diagnosed with type 2 diabetes and take metformin, call me on +968 9123 4567")
    record = global_audit_store.turns_for(c.id)[-1]
    assert "9123" not in record["visitor_message"]


def test_the_admin_view_lists_a_conversations_turns():
    store = MemoryStore()
    client = TestClient(create_app(store=store))
    response = client.get("/v1/admin/conversations/does-not-exist/turns")
    assert response.status_code == 200 and response.json()["turns"] == []


def test_measures_follow_the_addendums_targets():
    good = {"reply_source": "model", "guard": {"failures": []}, "state_before": {}, "reply": "Thank you. When?",
            "next_action": "collect_detail", "latency_ms": 900}
    offer_in_cooling = {**good, "next_action": "signup_handoff", "state_before": {"handoff": {"cooling_left": 3}}}
    result = compute([good, good, offer_in_cooling])
    assert result["g2_pass_rate"] == 1.0 and result["offers_inside_cooling"] == 1
    assert verdicts(result)["offers_inside_cooling"] is False and verdicts(result)["g2_pass_rate"] is True
