"""The flow and state addendum (section 11 scenarios): slot memory, lanes, the flow state guard
and the turn guard. The analyzer and model are stubs, so these run offline."""

import asyncio
import json
import uuid

from hayat_backend.chat_service import ChatService, greeting
from hayat_backend.memory_store import MemoryStore
from hayat_backend.question_planner import QuestionPlanner
from hayat_backend.slots import SlotState
from hayat_backend.turn_analyzer import TurnAnalysis
from hayat_backend.turn_guard import check as guard_check


class Analyzer:
    slots_mode = True

    def __init__(self, script=None, default=None):
        self.script, self.default, self.states = script or {}, default, []

    async def analyze(self, *, text, last_assistant, pending_field, known, state=None):
        self.states.append(state)
        return self.script.get(text, self.default)


class Model:
    """Returns the queued replies in order, then the last one forever."""

    def __init__(self, *replies):
        self.replies, self.calls = list(replies) or ["Noted, thank you."], []

    async def complete(self, messages):
        self.calls.append(messages)
        return self.replies.pop(0) if len(self.replies) > 1 else self.replies[0]


def _chat(script=None, default=None, replies=(), name_asked=True):
    store, model = MemoryStore(), Model(*replies)
    service = ChatService(store, model)
    service.handoff = True
    service.question_planner = QuestionPlanner(extended=True, handoff=True)
    service.analyzer = Analyzer(script, default)
    session, _ = store.create_guest_session("en")
    conversation = store.create_conversation(session.id)
    store.append_message(conversation, "assistant", greeting("en", 10, handoff=True), "en")
    if name_asked:
        store.append_message(conversation, "assistant", "What would you like me to call you?", "en")
        conversation.case_facts["preferred_name"] = "Maria"
    return service, model, conversation


def say(service, conversation, text):
    return asyncio.run(service.respond(conversation, text, str(uuid.uuid4()), use_ai=True))


def slots(conversation):
    return SlotState(conversation.case_facts)


def A(**kw):
    return TurnAnalysis(**kw)


MED = {"m.service_category": {"value": "orthopaedics", "status": "CONFIRMED"},
       "m.destination_country": {"value": "India", "status": "CONFIRMED"}}


# ---- 1, 6, 7: filling several slots, independent lanes, answers to a different question -------
def test_1_treatment_and_destination_in_one_message_fill_both_slots():
    service, model, c = _chat({"knee in India": A(intent="answering", lane="MEDICAL", slots=MED)})
    result = say(service, c, "knee in India")
    state = slots(c)
    assert (state.value("m.service_category"), state.value("m.destination_country")) == ("orthopaedics", "India")
    assert result["follow_up_target"] == "preferred_timing"  # the next missing slot, not a repeat


def test_6_the_same_country_for_both_journeys_is_two_independent_slots():
    service, _, c = _chat({
        "India for treatment": A(intent="answering", lane="MEDICAL", slots={"m.destination_country": {"value": "India", "status": "CONFIRMED"}}),
        "and India for a retreat": A(intent="answering", lane="WELLNESS", slots={"w.destination": {"value": "India", "status": "CONFIRMED"}}),
    })
    say(service, c, "India for treatment")
    say(service, c, "and India for a retreat")
    state = slots(c)
    assert state.value("m.destination_country") == "India" and state.value("w.destination") == "India"
    assert c.case_facts["destination_preference"] == "India" and c.case_facts["w_destination"] == "India"


def test_7_an_answer_to_a_different_question_is_accepted_not_ignored():
    service, _, c = _chat({
        "knee in India": A(intent="answering", lane="MEDICAL", slots=MED),
        "around 5000 dollars": A(intent="answering", slots={"m.budget_band": {"value": "around 5000 dollars", "status": "CONFIRMED"}}),
    })
    say(service, c, "knee in India")
    result = say(service, c, "around 5000 dollars")  # the question was about timing
    assert slots(c).value("m.budget_band") == "around 5000 dollars"
    assert result["follow_up_target"] != "budget_range"  # accepted, never asked for


# ---- 3, 4, 5: two journeys at once -----------------------------------------------------------------
def test_3_a_second_journey_keeps_the_first_untouched():
    service, _, c = _chat({
        "knee in India": A(intent="answering", lane="MEDICAL", slots=MED),
        "I'd also like a retreat in Spain": A(
            intent="new_request", lane="WELLNESS",
            slots={"w.experience_type": {"value": "retreat", "status": "CONFIRMED"},
                   "w.destination": {"value": "Spain", "status": "CONFIRMED"}}),
    })
    say(service, c, "knee in India")
    say(service, c, "I'd also like a retreat in Spain")
    state = slots(c)
    assert state.value("m.destination_country") == "India"      # medical unchanged
    assert state.value("w.destination") == "Spain"             # Spain only in the wellness lane
    assert c.case_facts["lanes_active"] == "MEDICAL,WELLNESS"


def test_4_a_value_that_fits_both_journeys_is_asked_about_and_not_written():
    service, model, c = _chat({
        "knee in India": A(intent="answering", lane="MEDICAL", slots=MED),
        "a retreat in Spain": A(intent="answering", lane="WELLNESS", slots={"w.experience_type": {"value": "retreat", "status": "CONFIRMED"}}),
        "around June": A(intent="answering", lane_ambiguous=True, slots={"m.timeline_window": {"value": "June", "status": "CONFIRMED"}}),
    })
    for text in ["knee in India", "a retreat in Spain"]:
        say(service, c, text)
    result = say(service, c, "around June")
    assert result["next_action"] == "clarify_lane"
    assert slots(c).value("m.timeline_window") is None and slots(c).value("w.dates_window") is None


def test_the_analyzer_is_given_the_state_every_turn():
    service, _, c = _chat({"knee in India": A(intent="answering", lane="MEDICAL", slots=MED)})
    say(service, c, "knee in India")
    say(service, c, "hello again")
    state = service.analyzer.states[-1]
    assert state["slots"]["m.destination_country"]["value"] == "India"
    assert state["focus_lane"] == "MEDICAL"


# ---- 12, 13, 14: corrections, unsure, declined ----------------------------------------------------
def test_12_a_correction_updates_the_slot_keeps_history_and_the_model_is_told():
    service, model, c = _chat({
        "knee in India": A(intent="answering", lane="MEDICAL", slots=MED),
        "sorry, Turkey not India": A(
            intent="answering", correction=True,
            slots={"m.destination_country": {"value": "Turkey", "status": "CONFIRMED"}}),
    })
    say(service, c, "knee in India")
    say(service, c, "sorry, Turkey not India")
    state = slots(c)
    assert state.value("m.destination_country") == "Turkey"
    assert state.history("m.destination_country") == ["India"]
    snapshot = json.loads(model.calls[-1][0]["content"].split("STATE: ")[1].split("\n")[0])
    assert snapshot["slots"]["m.destination_country"] == {"status": "CONFIRMED", "value": "Turkey", "was": "India"}
    assert "\"was\" value the visitor corrected it" in model.calls[-1][0]["content"]


def test_13_i_dont_know_makes_the_slot_unsure_and_it_is_not_asked_again():
    service, _, c = _chat({
        "knee in India": A(intent="answering", lane="MEDICAL", slots=MED),
        "no idea when": A(intent="answering", slots={"m.timeline_window": {"value": "", "status": "UNSURE"}}),
    })
    say(service, c, "knee in India")
    after = say(service, c, "no idea when")
    assert slots(c).status("m.timeline_window") == "UNSURE"
    assert after["follow_up_target"] != "preferred_timing"
    for i in range(4):
        assert say(service, c, f"chatting {i}")["follow_up_target"] != "preferred_timing"


def test_14_a_declined_budget_is_never_asked_again_this_session():
    service, _, c = _chat({
        "knee in India": A(intent="answering", lane="MEDICAL", slots=MED),
        "no thanks": A(intent="declines"),
    })
    say(service, c, "knee in India")
    c.case_facts["pending_slot"] = "m.budget_band"
    service.store.append_message(c, "assistant", "Do you have a rough budget band in mind?", "en")
    say(service, c, "no thanks")
    assert slots(c).status("m.budget_band") == "DECLINED"
    asked = [say(service, c, f"more {i}")["follow_up_target"] for i in range(4)]
    assert "budget_range" not in asked


# ---- 16, 17: the handoff and the cooling period ---------------------------------------------------
def _offered_chat(extra=None):
    script = {
        "knee in India": A(intent="answering", lane="MEDICAL", slots={
            **MED, "m.timeline_window": {"value": "spring", "status": "CONFIRMED"}}),
        **(extra or {}),
    }
    service, model, c = _chat(script, default=A(intent="smalltalk"))
    for filler in ("hi there", "just looking around"):  # the offer comes at a natural pause, not turn one
        say(service, c, filler)
    result = say(service, c, "knee in India")
    assert result["next_action"] == "signup_handoff"
    return service, model, c


def test_16_after_a_decline_there_is_no_new_offer_for_six_visitor_messages():
    service, _, c = _offered_chat({"not now": A(intent="declines")})
    assert say(service, c, "not now")["next_action"] == "handoff_declined"
    assert c.case_facts["flow_state"] == "HANDOFF_DECLINED"
    for i in range(5):
        assert say(service, c, f"just chatting {i}")["next_action"] != "signup_handoff"


def test_17_asking_to_book_or_for_a_quote_gets_the_offer_straight_away():
    service, _, c = _chat(
        {"how much and can I book?": A(intent="wants_booking")}, default=A(intent="smalltalk"),
    )
    result = say(service, c, "how much and can I book?")
    assert result["next_action"] == "signup_handoff"  # whatever is filled in


def test_booking_is_offered_even_inside_the_cooling_period():
    service, _, c = _offered_chat({"not now": A(intent="declines"), "ok book me in": A(intent="wants_booking")})
    say(service, c, "not now")
    assert say(service, c, "ok book me in")["next_action"] == "signup_handoff"


# ---- 18, 19, 20: lost state, a long chat, instructions in a message ---------------------------------
def test_18_a_lost_state_is_rebuilt_as_heard_and_confirmed_with_the_visitor():
    rebuilt = A(intent="answering", lane="MEDICAL", slots=MED)
    service, model, c = _chat(default=A(intent="smalltalk"))
    service.analyzer.script["So what happens next?"] = A(intent="question")
    # Three visitor turns went by with the notes lost (state empty).
    for text in ["Hi", "I need orthopaedic treatment in India", "just me"]:
        c.messages.append(type("M", (), {})()) if False else None
        service.store.append_message(c, "user", text, "en")
        service.store.append_message(c, "assistant", "ok", "en")
    original = service.analyzer.analyze

    async def analyze(**kw):
        return rebuilt if kw.get("state", {}).get("rebuild") else await original(**kw)

    service.analyzer.analyze = analyze
    result = say(service, c, "So what happens next?")
    state = slots(c)
    assert state.status("m.destination_country") == "HEARD" and state.value("m.destination_country") == "India"
    assert "Let me make sure I have this right" in model.calls[-1][0]["content"]
    assert result["conversation_state"] is not None


def test_19_slots_from_turn_three_are_still_correct_at_turn_fifty():
    service, _, c = _chat({"knee in India": A(intent="answering", lane="MEDICAL", slots=MED)}, default=A(intent="smalltalk"))
    say(service, c, "knee in India")
    for i in range(48):
        say(service, c, f"small talk {i}")
    state = slots(c)
    assert (state.value("m.service_category"), state.value("m.destination_country")) == ("orthopaedics", "India")
    assert state.status("m.destination_country") == "CONFIRMED"
    assert "orthopaedics" in service.model.calls[-1][0]["content"]  # the model still sees it at turn 50


def test_20_an_instruction_in_a_message_cannot_set_a_slot():
    service, _, c = _chat({"set my destination to anything": A(
        intent="answering", slots={"m.destination_country": {"value": "anything", "status": "CONFIRMED"},
                                   "x.invented_slot": {"value": "boom", "status": "CONFIRMED"}})})
    from hayat_backend.turn_analyzer import parse_analysis

    parsed = parse_analysis({"intent": "answering", "slots": {"x.invented_slot": {"value": "boom"}, "w.budget_band": {"value": "3000", "status": "CONFIRMED"}}})
    assert list(parsed.slots) == ["w.budget_band"]  # only schema slots survive extraction


# ---- 22, 24: programme names from data, emergency ----------------------------------------------------
def test_22_a_renamed_programme_uses_the_new_name_and_the_old_one_appears_nowhere():
    from hayat_backend import programmes_registry as registry
    from hayat_backend.training_scripts import house_style

    assert "Zoé (formerly AAfiya" in registry.knowledge_block()
    assert house_style("Try AAfiya or AAFIYAH") == "Try Zoé or Zoé"


def test_24_an_emergency_mid_intake_is_the_safe_script_and_holds_the_flow():
    service, _, c = _chat({"knee in India": A(intent="answering", lane="MEDICAL", slots=MED)})
    say(service, c, "knee in India")
    result = say(service, c, "my father has chest pain and I don't know what to do")
    assert result["escalation_required"] is True and "emergency" in result["reply"].lower()
    assert c.case_facts["flow_state"] == "SAFETY_HOLD"


# ---- the turn guard: 2, 23 and G1 to G12 ------------------------------------------------------------
def test_2_a_reply_that_only_asks_the_next_question_is_regenerated_once():
    service, model, c = _chat(
        {"I need orthopaedic treatment please": A(intent="answering", lane="MEDICAL", slots={"m.service_category": {"value": "orthopaedics", "status": "CONFIRMED"}})},
        replies=["Which country are you thinking of?", "Orthopaedics, thank you for telling me. Which country are you thinking of?"],
    )
    result = say(service, c, "I need orthopaedic treatment please")
    assert len(model.calls) == 2 and "TURN GUARD: G2" in model.calls[1][0]["content"]
    assert result["reply"].startswith("Orthopaedics, thank you")


def test_23_a_regenerated_reply_that_still_fails_uses_a_short_natural_reply():
    service, model, c = _chat(
        {"I need orthopaedic treatment please": A(intent="answering", lane="MEDICAL", slots={"m.service_category": {"value": "orthopaedics", "status": "CONFIRMED"}})},
        replies=["Which country are you thinking of?"],
    )
    result = say(service, c, "I need orthopaedic treatment please")
    assert len(model.calls) == 2
    assert "?" not in result["reply"] and "country" not in result["reply"]  # no slot question


def _slots_with(**statuses):
    store = MemoryStore()
    session, _ = store.create_guest_session("en")
    c = store.create_conversation(session.id)
    state = SlotState(c.case_facts)
    for slot_id, (value, status) in statuses.items():
        state.apply(slot_id.replace("__", "."), value, status, 1)
    c.case_facts.update(state.overlay)
    c.case_facts["slot_meta"] = json.dumps(state.meta)
    return c, SlotState(c.case_facts)


def _guard(reply, state, focus="MEDICAL", active=("MEDICAL",), history=(), knowledge="", plan=None, user="hello there"):
    return guard_check(reply, user_text=user, plan=plan, state=state, focus=focus, active=list(active),
                       assistant_history=list(history), knowledge=knowledge, turn=4)


def test_g1_a_question_about_a_settled_slot_is_removed():
    _, state = _slots_with(m__budget_band=("", "DECLINED"), m__timeline_window=("", "UNSURE"))
    out = _guard("Thanks for that. Do you have a budget in mind? And what timeframe suits you?", state)
    assert "G1" in out.failures and "?" not in out.reply and out.reply.startswith("Thanks for that")


def test_g3_a_value_from_the_other_journey_is_flagged():
    _, state = _slots_with(m__destination_country=("India", "CONFIRMED"), w__experience_type=("retreat", "CONFIRMED"))
    out = _guard("Lovely. Will the retreat be in India?", state, focus="WELLNESS", active=("MEDICAL", "WELLNESS"))
    assert "G3" in out.failures and out.needs_regeneration == ["G3"]


def test_g5_no_repeated_greeting_introduction_or_offer():
    _, state = _slots_with()
    out = _guard("Hello! I'm Hayat. That sounds good. You can sign up and log in whenever you like.", state, history=["Hi, I'm Hayat."])
    assert "G5" in out.failures and out.reply == "That sounds good."


def test_g6_a_price_the_knowledge_base_does_not_contain_is_replaced():
    _, state = _slots_with()
    out = _guard("It costs USD 4,800 for the week.", state, knowledge="Zoé is a seven day retreat.")
    assert "G6" in out.failures and "4,800" not in out.reply and "team can go through them" in out.reply
    assert "G6" not in _guard("It costs USD 4,800.", state, knowledge="Price: USD 4,800.").failures


def test_g8_no_request_for_diagnosis_symptoms_or_contact_details():
    _, state = _slots_with()
    for ask in ["What is your diagnosis?", "Could I have your phone number?", "How old are you?"]:
        out = _guard(f"Thanks. {ask}", state)
        assert "G8" in out.failures and "?" not in out.reply


def test_g9_nothing_is_promised_or_confirmed():
    _, state = _slots_with()
    out = _guard("Great news, your booking is confirmed.", state)
    assert "G9" in out.failures and out.reply == "The team confirms that after your consultation."


def test_g10_the_same_question_is_not_asked_twice_in_a_row():
    _, state = _slots_with()
    out = _guard("Noted. What timeframe suits you best?", state, history=["When would you like to travel, what timeframe suits you best?"])
    assert "G10" in out.failures and "?" not in out.reply


def test_g12_hayat_never_claims_to_be_human():
    _, state = _slots_with()
    out = _guard("I'm a real person here to help you.", state)
    assert "G12" in out.failures and "AI assistant" in out.reply


def test_g4_at_most_one_question():
    _, state = _slots_with()
    out = _guard("Lovely. Where would you like to go? When would you like to go?", state)
    assert out.reply.count("?") == 1


# ---- changes of mind, checked lightly (addendum 4.1) and a graceful close ------------------------------
def _confirmed_chat(extra):
    script = {"knee in India": A(intent="answering", lane="MEDICAL", slots=MED), **extra}
    service, model, c = _chat(script, default=A(intent="smalltalk"))
    say(service, c, "knee in India")
    return service, model, c


TURKEY = {"m.destination_country": {"value": "Turkey", "status": "CONFIRMED"}}


def test_a_conflicting_value_is_held_and_checked_once_not_overwritten():
    service, model, c = _confirmed_chat({"what about Turkey": A(intent="answering", lane="MEDICAL", slots=TURKEY)})
    result = say(service, c, "what about Turkey")
    assert slots(c).value("m.destination_country") == "India"  # not silently replaced
    assert result["next_action"] == "confirm_change"
    assert "second option" in model.calls[-1][0]["content"]


def test_the_check_is_resolved_by_the_visitors_answer():
    for answer, expected in [
        ("yes change it", "Turkey"), ("both, a second option", "India and Turkey"), ("no keep India", "India"),
    ]:
        service, _, c = _confirmed_chat({
            "what about Turkey": A(intent="answering", lane="MEDICAL", slots=TURKEY),
            answer: A(intent="answering"),
        })
        say(service, c, "what about Turkey")
        say(service, c, answer)
        assert slots(c).value("m.destination_country") == expected, answer
        assert not c.case_facts.get("pending_change")


def test_an_explicit_correction_is_applied_without_a_check():
    service, _, c = _confirmed_chat({"sorry, Turkey not India": A(
        intent="answering", lane="MEDICAL", slots=TURKEY, correction=True)})
    say(service, c, "sorry, Turkey not India")
    assert slots(c).value("m.destination_country") == "Turkey"
    assert slots(c).snapshot()["m.destination_country"]["was"] == "India"


def test_a_visitor_who_is_done_is_closed_warmly_with_no_new_question():
    service, model, c = _confirmed_chat({"thanks, that's all": A(intent="smalltalk")})
    say(service, c, "hi")
    result = say(service, c, "thanks, that's all")
    assert result["next_action"] == "close"
    assert c.case_facts["flow_state"] == "CLOSED"
    assert "wrapping up" in model.calls[-1][0]["content"]
    assert "?" not in result["reply"]


def test_guard_strips_a_currency_the_visitor_never_named_and_a_repeated_soft_offer():
    state = SlotState({})
    kw = dict(plan=None, state=state, focus=None, active=[], assistant_history=["Earlier."], knowledge="", turn=4)
    out = guard_check("Lovely, a budget of about 8000 € is noted.", user_text="budget about 8000", **kw)
    assert "€" not in out.reply and "8000" in out.reply
    out = guard_check("Got it. Would you like me to guide you to the signup or login page?",
                      user_text="make it hip", **kw)
    assert "signup" not in out.reply and "G5" in out.failures


def test_a_chip_marker_without_the_label_never_leaks_into_the_reply():
    from hayat_backend.chat_service import _split_chips

    reply, chips = _split_chips("Which country are you in? [[I'm in the US|I'm in Canada]] Thanks.")
    assert "[[" not in reply and chips == ["I'm in the US", "I'm in Canada"]


def test_a_goodbye_is_not_an_opt_out_but_a_real_stop_request_is():
    service, _, c = _confirmed_chat({"ok thanks, bye": A(intent="wants_stop")})
    say(service, c, "hi")
    assert say(service, c, "ok thanks, bye")["next_action"] == "close"
    assert not c.case_facts.get("opt_out_requested")
    service, _, c = _confirmed_chat({"please stop messaging me": A(intent="wants_stop")})
    assert say(service, c, "please stop messaging me")["next_action"] == "opt_out"


def test_unanswered_questions_are_not_recorded_as_unsure():
    service, _, c = _confirmed_chat({"what about spa?": A(
        intent="answering", slots={"m.timeline_window": {"value": "", "status": "UNSURE"}})})
    say(service, c, "what about spa?")
    assert slots(c).status("m.timeline_window") == "EMPTY"


def test_a_wellness_question_is_never_repeated_after_every_answer():
    service, _, c = _chat({"a retreat in Spain": A(intent="answering", lane="WELLNESS", slots={
        "w.destination": {"value": "Spain", "status": "CONFIRMED"}})}, default=A(intent="question"))
    say(service, c, "a retreat in Spain")
    asked = [say(service, c, f"what about my condition {i}?")["follow_up_target"] for i in range(5)]
    assert "wellness_programme_or_goal" not in asked  # a goal or destination already says what it is
    assert asked.count("w_dates_window") <= 1  # and a question just asked is not asked again while they ask things


def test_a_question_asked_twice_without_an_answer_is_dropped():
    service, _, c = _chat({"a retreat": A(intent="answering", lane="WELLNESS", slots={})},
                          default=A(intent="smalltalk"),
                          replies=("Noted. Which wellness programme or goal interests you?",))
    c.case_facts.update({"lanes_active": "WELLNESS", "focus_lane": "WELLNESS"})
    targets = [say(service, c, f"hmm {i}")["follow_up_target"] for i in range(6)]
    assert "wellness_programme_or_goal" not in targets[3:]  # asked twice, then the flow moves on


def test_where_they_live_is_residence_not_the_treatment_destination():
    service, _, c = _chat({"we're in Oman": A(intent="answering", lane="MEDICAL", slots={
        "m.destination_country": {"value": "Oman", "status": "CONFIRMED"}})})
    say(service, c, "we're in Oman")
    assert slots(c).value("s.residence_country") == "Oman"
    assert slots(c).status("m.destination_country") == "EMPTY"


def test_an_opinion_style_change_is_checked_not_dropped():
    service, model, c = _confirmed_chat({"Actually maybe Turkey is better, what do you think?": A(
        intent="question", lane="MEDICAL", slots=TURKEY)})
    result = say(service, c, "Actually maybe Turkey is better, what do you think?")
    assert result["next_action"] == "confirm_change"
    assert slots(c).value("m.destination_country") == "India"


def test_the_guard_drops_an_echo_of_the_visitors_question():
    kw = dict(plan=None, state=SlotState({}), focus=None, active=[], assistant_history=["Hello."], knowledge="", turn=4)
    out = guard_check("You're asking about the length of the retreat. It lasts seven days.", user_text="how long?", **kw)
    assert out.reply == "It lasts seven days." and "G13" in out.failures


def test_the_shared_limit_window_is_waited_for_not_hopped_over():
    from hayat_backend import ratelimit

    class Err(Exception):
        response = type("R", (), {"headers": {"retry-after": "3"}})()

    assert ratelimit.retry_wait(Err()) == 3.0
    assert ratelimit.retry_wait(type("E", (), {"response": type("R", (), {"headers": {"x-ratelimit-reset-tokens": "1m2.5s"}})()})()) == 62.5
    ratelimit.note_limited(4)
    assert 0 < ratelimit.short_wait_left() <= 4
    ratelimit.note_limited(500)  # a long limit is not waited for
    ratelimit.reset()
    assert ratelimit.short_wait_left() == 0


def test_a_companions_name_or_age_gets_a_privacy_note_and_a_bare_yes_gets_a_gentle_check():
    service, model, c = _confirmed_chat({"Mum's name is Fatima and she's 68": A(intent="smalltalk")})
    say(service, c, "Mum's name is Fatima and she's 68")
    assert "PRIVACY" in model.calls[-1][0]["content"]
    service.store.append_message(c, "assistant", "Roughly when are you hoping to have the treatment?", "en")
    say(service, c, "yes")
    assert "CHECK: the visitor sent a bare yes" in model.calls[-1][0]["content"]


def test_a_repeated_consultation_pitch_is_removed_when_no_offer_is_due():
    kw = dict(plan=None, state=SlotState({}), focus=None, active=[], assistant_history=["Hello."], knowledge="", turn=4)
    out = guard_check("Lovely choice. Would you like to arrange the free consultation now?", user_text="India", **kw)
    assert "arrange" not in out.reply and "G5" in out.failures


def test_a_health_fit_question_gets_a_no_advice_instruction():
    service, model, c = _confirmed_chat({"can someone with high blood pressure join a retreat?": A(intent="question")})
    say(service, c, "can someone with high blood pressure join a retreat?")
    system = " ".join(call[0]["content"] for call in model.calls)
    assert "HEALTH QUESTION" in system and "Do NOT say yes, no, safe" in system


# ---- the knowledge base's own answers and questions ---------------------------------------------------
def test_programme_questions_get_the_documents_answer_and_the_documents_question():
    service, model, c = _chat(default=A(intent="question"))
    first = say(service, c, "Tell me about FFounders")
    assert first["reply"].startswith("FFounders is a premium executive fitness and wellness retreat concept")
    assert first["reply"].endswith("What interests you most about this experience?")
    assert [a.label for a in first["suggestions"]] == ["What's included?", "Where is it held?", "How much does it cost?"]
    where = say(service, c, "where is this retreat")
    assert "Potential destinations include the United States, Spain, Japan" in where["reply"]
    assert where["reply"].endswith("Do you have a particular country or destination in mind?")
    assert c.case_facts["pending_slot"] == "w.destination"
    price = say(service, c, "how much does it cost?")
    assert "no fixed package price" in price["reply"] and price["reply"].endswith("May I ask which destination you are considering?")
    assert not model.calls  # the document answered; the model was not needed


def test_the_overview_dates_and_all_three_use_section_6_as_written():
    service, _, c = _chat(default=A(intent="question"))
    overview = say(service, c, "what programmes do you have?")["reply"]
    assert overview.startswith("We have three signature wellness experiences") and "Zoé is a women's fitness" in overview
    assert overview.endswith("May I ask which of these interests you most?") and "AAfiya" not in overview
    dates = say(service, c, "when are the retreat dates?")["reply"]
    assert dates == ("The retreat dates are still being curated. Do you have a preferred month or travel period? "
                     "I can make a note of it for our team.")
    assert say(service, c, "I like all three")["reply"].endswith("Is there one you'd currently prioritise?")


def test_a_question_the_document_asks_is_left_out_once_it_is_settled():
    service, _, c = _chat(default=A(intent="question"))
    c.case_facts["slot_meta"] = '{"w.destination": {"status": "CONFIRMED", "turn": 1}}'
    c.case_facts["w_destination"] = "Spain"
    reply = say(service, c, "how much does it cost?")["reply"]
    assert "May I ask which destination" not in reply


def test_medical_questions_are_not_answered_from_the_programme_document():
    service, model, c = _chat(default=A(intent="question"))
    c.case_facts.update({"lanes_active": "MEDICAL", "focus_lane": "MEDICAL"})
    say(service, c, "how much does a knee replacement cost?")
    assert model.calls  # the model answered, not a programme FAQ


def test_a_question_about_dates_fills_no_date_slot():
    service, _, c = _chat({"when is the next one?": A(intent="question", lane="WELLNESS", slots={
        "w.dates_window": {"value": "next one", "status": "CONFIRMED"}})})
    say(service, c, "when is the next one?")
    assert slots(c).status("w.dates_window") == "EMPTY"
