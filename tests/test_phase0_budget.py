"""Phase 0 of IMPLEMENTATION.md: a token budget, fewer model calls, fallbacks that still
refer to what the visitor said, and the specialty label read in code."""

import re

from hayat_backend.chat_service import _CORE_RULES
from hayat_backend.pre_extract import fast_analysis, reinforce, specialty_label
from hayat_backend.turn_analyzer import TurnAnalysis
from hayat_backend.turn_guard import safe_reply, topic_of

from test_flow_addendum import A, _chat, say


def test_the_core_rules_stay_near_the_addendums_length():
    words = len(_CORE_RULES.split())
    assert words <= 320, words  # Annex B suggests about 250


def test_the_reply_prompt_outside_the_knowledge_block_stays_small():
    service, model, c = _chat({"knee in India": A(intent="answering", lane="MEDICAL", slots={
        "m.service_category": {"value": "orthopaedics", "status": "CONFIRMED"}})})
    say(service, c, "knee in India")
    system = model.calls[-1][0]["content"]
    without_knowledge = re.sub(r"KNOWLEDGE.*?(?=\n\n[A-Z])", "", system, flags=re.S)
    assert len(without_knowledge) < 4200, len(without_knowledge)  # roughly 1,000 tokens


def test_greetings_thanks_and_playbook_questions_need_no_extraction_model():
    for text in ["hi", "Good evening!", "thanks", "thank you 😊"]:
        result = fast_analysis(text, handoff_just_offered=False, kb_would_answer=False, turn_analysis_cls=TurnAnalysis)
        assert result is not None and result.intent == "smalltalk", text
    playbook = fast_analysis("Tell me about FFounders", handoff_just_offered=False, kb_would_answer=True,
                             turn_analysis_cls=TurnAnalysis)
    assert playbook.slots == {"w.programme_interest": {"value": "FFounders", "status": "CONFIRMED"}}
    # A reply to the signup offer, or a message with details, always goes to the model.
    assert fast_analysis("yes", handoff_just_offered=True, kb_would_answer=False, turn_analysis_cls=TurnAnalysis) is None
    assert fast_analysis("how much for 2 people in June?", handoff_just_offered=False, kb_would_answer=True,
                         turn_analysis_cls=TurnAnalysis) is None


def test_a_playbook_turn_makes_no_model_call_at_all():
    service, model, c = _chat(default=A(intent="question"))
    calls = []
    original = service.analyzer.analyze

    async def counting(**kwargs):
        calls.append(kwargs)
        return await original(**kwargs)

    service.analyzer.analyze = counting
    say(service, c, "Tell me about FFounders")
    assert not calls and not model.calls


def test_the_specialty_is_read_in_code_when_redaction_hid_it_from_the_model():
    assert specialty_label("my mum needs a heart valve surgery") == "cardiology"
    assert specialty_label("I'll keep an eye on it") == "ophthalmology"  # the label alone is not enough...
    blind = TurnAnalysis(intent="answering")
    assert reinforce(blind, "I'll keep an eye on it").slots == {}  # ...a request for help is needed
    seen = reinforce(blind, "what about my knee problem, can you help with that too?")
    assert seen.slots["m.service_category"] == {"value": "orthopaedics", "status": "HEARD"}
    assert seen.lane == "MEDICAL" and blind.slots == {}  # a copy; the model's object is untouched


def test_fallbacks_refer_to_what_the_visitor_asked():
    assert "about hospitals and doctors" in safe_reply(2, "", None, user_text="which hospitals do you work with?")
    assert "about the orthopaedics side" in safe_reply(2, "", None, user_text="can you help with my knee?")
    assert topic_of("how much does it cost?") == "the cost"
    assert safe_reply(2, "", [("treatment destination", "Turkey")], user_text="Turkey") == \
        "Got it, I've noted treatment destination as Turkey. 😊"


def test_a_playbook_question_with_trip_details_still_goes_to_the_extraction_model():
    from hayat_backend.pre_extract import has_details

    for text in ["Can I bring my sister to Zoé in March?", "how much is it for me and my husband?",
                 "is FFounders held in Spain?"]:
        assert has_details(text), text
        assert fast_analysis(text, handoff_just_offered=False, kb_would_answer=True,
                             turn_analysis_cls=TurnAnalysis) is None, text
    assert not has_details("Tell me about FFounders")


def test_ordinary_words_are_not_treated_as_claims():
    from hayat_backend.slots import SlotState
    from hayat_backend.turn_guard import check

    out = check("We've covered that already. On top of that, the team can help on your free call.",
                user_text="ok", plan=None, state=SlotState({}), focus=None, active=[],
                assistant_history=["Hello."], knowledge="", turn=3)
    assert "G6" not in out.failures
    ranked = check("Thanks. India has the best hospitals for knees.", user_text="india?", plan=None,
                   state=SlotState({}), focus=None, active=[], assistant_history=["Hello."], knowledge="india", turn=3)
    assert "best hospitals" not in ranked.reply and "G6" in ranked.failures
