"""Phase 2 of IMPLEMENTATION.md: allowed slot values, the flow transition table and G11."""

import json

from hayat_backend.flow import next_flow_state, state_problems
from hayat_backend.slot_values import check

from test_flow_addendum import A, MED, _chat, say, slots


# ---- allowed values (Addendum 2.3) -------------------------------------------------------------
def test_places_are_normalised_and_vague_places_are_only_heard():
    assert check("m.destination_country", "india", "CONFIRMED") == ("India", "CONFIRMED")
    assert check("w.destination", "UAE", "CONFIRMED") == ("United Arab Emirates", "CONFIRMED")
    assert check("w.destination", "Spain and Portugal", "CONFIRMED") == ("Spain and Portugal", "CONFIRMED")
    assert check("w.destination", "somewhere in Europe", "CONFIRMED") == ("Europe", "CONFIRMED")
    assert check("w.destination", "somewhere warm", "CONFIRMED") == ("somewhere warm", "HEARD")
    assert check("s.residence_country", "Oman", "CONFIRMED") == ("Oman", "CONFIRMED")


def test_counts_windows_durations_and_bands():
    assert check("m.travellers_count", "just me", "CONFIRMED") == ("1", "CONFIRMED")
    assert check("w.participants_count", "me and my sister", "CONFIRMED") == ("2", "CONFIRMED")
    assert check("w.participants_count", "a few of us", "CONFIRMED").status == "HEARD"
    assert check("m.timeline_window", "next spring", "CONFIRMED") == ("next spring", "CONFIRMED")
    assert check("w.dates_window", "around June", "CONFIRMED") == ("around June", "CONFIRMED")
    assert check("w.dates_window", "next one", "CONFIRMED").status == "HEARD"
    assert check("w.duration_nights", "7", "CONFIRMED") == ("7 nights", "CONFIRMED")
    assert check("w.budget_band", "about 8000", "CONFIRMED") == ("about 8000", "CONFIRMED")
    assert check("w.budget_band", "whatever works", "CONFIRMED").status == "HEARD"


def test_labels_and_programmes_come_only_from_the_allowed_lists():
    assert check("m.service_category", "cardiac", "CONFIRMED") == ("cardiology", "CONFIRMED")
    assert check("m.service_category", "knee replacement", "CONFIRMED") == ("orthopaedics", "CONFIRMED")
    assert check("w.goal_category", "more energy", "CONFIRMED") == ("fitness", "CONFIRMED")
    assert check("w.goal_category", "calm", "CONFIRMED") == ("relaxation", "CONFIRMED")
    assert check("w.programme_interest", "aafiya", "CONFIRMED") == ("Zoé", "CONFIRMED")
    assert check("w.programme_interest", "the Bali detox camp", "CONFIRMED").value is None  # not in the KB


def test_a_vague_destination_is_echoed_not_settled_in_a_live_turn():
    service, _, c = _chat({"somewhere warm for the retreat": A(intent="answering", lane="WELLNESS", slots={
        "w.destination": {"value": "somewhere warm", "status": "CONFIRMED"}})})
    say(service, c, "somewhere warm for the retreat")
    assert slots(c).status("w.destination") == "HEARD"


# ---- flow state guard (Addendum part 5) --------------------------------------------------------
def test_the_transition_table_refuses_moves_it_does_not_allow():
    assert next_flow_state({"flow_state": "MEDICAL_INTAKE"}, "HANDOFF_DECLINED") == [("flow_state", "MEDICAL_INTAKE")]
    assert next_flow_state({"flow_state": "HANDOFF_OFFERED"}, "HANDOFF_DECLINED") == [("flow_state", "HANDOFF_DECLINED")]


def test_general_qa_remembers_where_it_came_from_and_returns_there():
    into = next_flow_state({"flow_state": "MEDICAL_INTAKE"}, "GENERAL_QA")
    assert into == [("flow_state", "GENERAL_QA"), ("previous_flow_state", "MEDICAL_INTAKE")]
    back = next_flow_state({"flow_state": "GENERAL_QA", "previous_flow_state": "MEDICAL_INTAKE"}, "DISCOVERY")
    assert back[0] == ("flow_state", "MEDICAL_INTAKE")


def test_safety_hold_is_sticky_except_after_a_pasted_secret():
    hold = next_flow_state({"flow_state": "MEDICAL_INTAKE"}, "SAFETY_HOLD")
    assert dict(hold) == {"flow_state": "SAFETY_HOLD", "previous_flow_state": ""}
    assert next_flow_state(dict(hold), "MEDICAL_INTAKE") == [("flow_state", "SAFETY_HOLD")]
    secret = dict(next_flow_state({"flow_state": "WELLNESS_INTAKE"}, "SAFETY_HOLD", returnable=True))
    assert next_flow_state(secret, "GENERAL_QA")[0] == ("flow_state", "WELLNESS_INTAKE")


# ---- G11: state present, valid and current -----------------------------------------------------
def test_g11_names_what_is_wrong_with_the_state():
    assert state_problems({}) == []
    assert state_problems({"slot_meta": "{not json"}) == ["slot_meta is not valid JSON"]
    assert state_problems({"slot_meta": json.dumps({"m.nonsense": {"status": "CONFIRMED"}})}) == ["unknown slot m.nonsense"]
    assert state_problems({"flow_state": "PARTY", "focus_lane": "SPA"}) == ["unknown flow state", "unknown focus lane"]


def test_a_corrupt_state_is_cleared_and_rebuilt_not_trusted():
    service, model, c = _chat({"knee in India": A(intent="answering", lane="MEDICAL", slots=MED)},
                              default=A(intent="smalltalk"))
    say(service, c, "knee in India")
    c.case_facts["slot_meta"] = "{broken"
    c.case_facts["flow_state"] = "PARTY"
    say(service, c, "so what happens next?")
    assert state_problems(c.case_facts) == []
    assert c.case_facts["flow_state"] in {"DISCOVERY", "GENERAL_QA", "MEDICAL_INTAKE"}
