"""Phase 6 of IMPLEMENTATION.md: rolling summary, language, and not extending intake."""

from hayat_backend.language import unsupported_language

from test_flow_addendum import A, MED, _chat, say


def test_turns_no_longer_shown_are_summarised_with_slot_values_only():
    service, model, c = _chat({"knee in India": A(intent="answering", lane="MEDICAL", slots=MED)},
                              default=A(intent="smalltalk"))
    say(service, c, "knee in India")
    for i in range(4):
        say(service, c, f"ok {i}")
    system = model.calls[-1][0]["content"]
    assert "EARLIER IN THIS CHAT (slot values only): " in system
    assert "treatment destination: India" in system


def test_a_language_hayat_is_not_approved_for_gets_english_and_an_offer():
    assert unsupported_language("Bonjour, je voudrais une retraite")
    assert unsupported_language("Здравствуйте, мне нужна операция")
    assert not unsupported_language("Hello, I need knee surgery")
    assert not unsupported_language("مرحبا أحتاج إلى علاج")
    service, model, c = _chat({}, default=A(intent="smalltalk"))
    say(service, c, "Bonjour, merci")
    assert "LANGUAGE: the visitor wrote in a language you are not approved to use" in model.calls[-1][0]["content"]


def test_after_the_offer_hayat_stops_asking_once_enough_is_known():
    service, _, c = _chat({
        "knee in India": A(intent="answering", lane="MEDICAL", slots={
            **MED, "m.timeline_window": {"value": "spring", "status": "CONFIRMED"}}),
        "not now": A(intent="declines"),
    }, default=A(intent="smalltalk"))
    for text in ["hi there", "just looking around", "knee in India", "not now"]:
        say(service, c, text)
    later = [say(service, c, text) for text in ["ok", "thanks", "sounds good"]]
    assert all(r["next_action"] == "answer" for r in later)
    assert all(r["follow_up_question"] is None for r in later)
