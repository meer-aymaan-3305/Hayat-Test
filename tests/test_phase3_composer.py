"""Phase 3 of IMPLEMENTATION.md: the reply comes back as four labelled parts."""

import json

from hayat_backend.chat_service import read_model_output

from test_flow_addendum import A, MED, _chat, say


class JsonModel:
    supports_json = True

    def __init__(self, *replies):
        self.replies, self.calls, self.modes = list(replies), [], []

    async def complete(self, messages, json_mode=False):
        self.calls.append(messages)
        self.modes.append(json_mode)
        return self.replies.pop(0) if len(self.replies) > 1 else self.replies[0]


def composed(**parts):
    return json.dumps(parts)


def test_the_four_parts_are_assembled_in_the_addendums_order():
    reply, chips, parts = read_model_output(composed(
        acknowledge="Orthopaedic treatment in India is clear", answer="", bridge="",
        ask="Do you have a rough timeframe in mind", chips=["Within 3 months", "Later this year"],
    ))
    assert reply == "Orthopaedic treatment in India is clear. Do you have a rough timeframe in mind?"
    assert chips == ["Within 3 months", "Later this year"] and parts["ask"]


def test_plain_text_and_a_cut_off_json_reply_are_both_read():
    assert read_model_output("Lovely. [[chips: Yes | No]]")[:2] == ("Lovely.", ["Yes", "No"])
    cut = '{"acknowledge": "Two of you in June sounds lovely.", "answer": "What is included depends on'
    reply, _chips, parts = read_model_output(cut)
    assert reply == "Two of you in June sounds lovely." and parts is not None


def test_a_json_capable_model_is_asked_for_the_parts_and_its_chips_are_used():
    service, _, c = _chat({"knee in India": A(intent="answering", lane="MEDICAL", slots=MED)})
    service.model = model = JsonModel(composed(
        acknowledge="Thank you, orthopaedic treatment in India is clear", answer="", bridge="",
        ask="Do you have a rough timeframe in mind, like within the next few months",
        chips=["Within 3 months", "Later this year", "I'm flexible"],
    ))
    result = say(service, c, "knee in India")
    assert model.modes == [True]
    assert "OUTPUT: JSON only" in model.calls[-1][0]["content"]
    assert result["reply"] == ("Thank you, orthopaedic treatment in India is clear. Do you have a rough "
                               "timeframe in mind, like within the next few months?")
    assert [a.label for a in result["suggestions"]] == ["Within 3 months", "Later this year", "I'm flexible"]


def test_length_matches_the_visitor_and_used_openings_are_listed():
    service, model, c = _chat({}, default=A(intent="smalltalk"))
    for text in ["hi", "just looking", "ok", "fine thanks"]:
        say(service, c, text)
    system = model.calls[-1][0]["content"]
    assert "LENGTH: the visitor wrote 2 words; reply in one or two short sentences." in system
    assert "Openings already used in this chat" in system


def test_a_bridge_ending_in_a_comma_runs_into_the_question():
    reply, _c, _p = read_model_output(composed(
        acknowledge="Got it, Sam", answer="", bridge="To help with that,", ask="Roughly when are you hoping to go"))
    assert reply == "Got it, Sam. To help with that, roughly when are you hoping to go?"
    reply, _c, _p = read_model_output(composed(acknowledge="Noted", answer="", bridge="For the treatment,",
                                               ask="India or Turkey"))
    assert reply.endswith("For the treatment, India or Turkey?")


def test_when_the_extraction_model_is_down_code_still_reads_a_booking_request():
    from hayat_backend.pre_extract import fallback_analysis
    from hayat_backend.turn_analyzer import TurnAnalysis

    assert fallback_analysis("can I book a consultation?", TurnAnalysis).intent == "wants_booking"
    assert fallback_analysis("can I speak to a real person", TurnAnalysis).intent == "wants_human"
    knee = fallback_analysis("I need help with my knee surgery", TurnAnalysis)
    assert knee.slots["m.service_category"]["value"] == "orthopaedics"

    service, _, c = _chat({}, default=None)
    assert say(service, c, "can I book a consultation?")["next_action"] == "signup_handoff"


def test_an_emoji_alone_is_not_a_part_and_punctuation_goes_before_trailing_emojis():
    reply, _c, _p = read_model_output(composed(acknowledge="🌟", answer="", bridge="",
                                               ask="What would you like me to call you"))
    assert reply == "What would you like me to call you?"
    reply, _c, _p = read_model_output(composed(acknowledge="Knee surgery in India, lovely 🏥", answer="", bridge="",
                                               ask="Roughly when are you hoping to travel 😊"))
    assert reply == "Knee surgery in India, lovely. 🏥 Roughly when are you hoping to travel? 😊"
