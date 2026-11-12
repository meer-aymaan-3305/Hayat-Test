"""Signup handoff mode: the rules of the enhanced training document.

Chat never takes contact details, diagnosis, reports or consent. It collects only the
allowed enquiry fields, then offers the free consultation through signup or login.
"""

import asyncio
import uuid

from hayat_backend.chat_service import ChatService, greeting
from hayat_backend.memory_store import MemoryStore
from hayat_backend.question_planner import QuestionPlanner
from hayat_backend.turn_analyzer import TurnAnalysis


class StubModel:
    def __init__(self) -> None:
        self.calls: list[list[dict[str, str]]] = []

    async def complete(self, messages):
        self.calls.append(messages)
        return "Of course."


class StubAnalyzer:
    """The real analyzer sees the redacted text, so unscripted texts get the default."""

    def __init__(self, script, default=None) -> None:
        self.script = script
        self.default = default

    async def analyze(self, *, text, last_assistant, pending_field, known):
        return self.script.get(text, self.default)


def _service(script, default=None, name_asked=True):
    store = MemoryStore()
    model = StubModel()
    service = ChatService(store, model)
    service.handoff = True
    service.question_planner = QuestionPlanner(extended=True, handoff=True)
    service.analyzer = StubAnalyzer(script, default)
    session, _ = store.create_guest_session("en")
    conversation = store.create_conversation(session.id)
    store.append_message(conversation, "assistant", greeting("en", 19, handoff=True), "en")
    if name_asked:  # most tests are about later steps, so the name was already asked
        store.append_message(
            conversation, "assistant", "What would you like me to call you?", "en"
        )
        conversation.case_facts["preferred_name"] = "Maria"
    return service, model, conversation


def _say(service, conversation, text):
    return asyncio.run(service.respond(conversation, text, str(uuid.uuid4()), use_ai=True))


MEDICAL = TurnAnalysis(
    intent="answering", category="medical_treatment",
    facts={"procedure_or_service": "orthopaedics"},
)


def test_first_message_is_the_ai_introduction_in_the_visitors_time_of_day():
    text = greeting("en", 19, handoff=True)
    assert text.startswith("Good evening! 😊 I'm Hayat, trawellcare's AI concierge")
    assert "How is your evening going?" in text
    assert "your name" not in text.lower()  # the name is asked later, and is optional
    assert greeting("en", 9, handoff=True).startswith("Good morning")
    assert " - " not in text and "—" not in text


def test_a_preferred_first_name_is_asked_once_and_is_optional():
    service, model, conversation = _service(
        {"I'm good, thanks": TurnAnalysis(intent="smalltalk")}, name_asked=False
    )
    first = _say(service, conversation, "I'm good, thanks")
    assert first["follow_up_target"] == "preferred_name"
    assert "what would you like me to call you" in model.calls[-1][0]["content"].lower()
    # Declining carries on without it and never asks again.
    # The assistant asked it (the model's reply carries the question); they decline.
    service.store.append_message(conversation, "assistant", "What would you like me to call you?", "en")
    service.analyzer.script["I'd rather not say"] = TurnAnalysis(intent="declines")
    second = _say(service, conversation, "I'd rather not say")
    assert conversation.case_facts.get("preferred_name") == "declined"
    assert second["follow_up_target"] != "preferred_name"


def test_only_allowed_fields_are_collected_and_never_diagnosis_or_contact():
    service, _, conversation = _service({
        "knee surgery please": MEDICAL,
        "Germany": TurnAnalysis(intent="answering", facts={"destination_preference": "Germany"}),
    })
    asked = []
    for text in ["knee surgery please", "Germany"]:
        result = _say(service, conversation, text)
        asked.append(result["follow_up_target"])
    forbidden = {
        "condition_context_for_advisor", "medical_reports_available", "phone_number",
        "email", "callback_time", "name",
    }
    assert not forbidden & set(asked)
    assert not forbidden & set(conversation.case_facts)


def test_contact_details_typed_in_chat_are_not_stored():
    service, _, conversation = _service({}, default=TurnAnalysis(intent="contact_request"))
    result = _say(service, conversation, "call me on +968 9123 4567 or maria@example.com")
    stored = " ".join(str(v) for v in conversation.case_facts.values())
    assert "9123" not in stored and "maria@example.com" not in stored
    assert "phone_number" not in conversation.case_facts and "email" not in conversation.case_facts
    # The reply model is told to explain that contact happens at signup.
    assert "cannot take contact information" in service.model.calls[-1][0]["content"]
    assert result["escalation_required"] is False


def test_the_free_consultation_is_offered_once_enough_is_shared():
    script = {
        "knee surgery": MEDICAL,
        "Germany": TurnAnalysis(intent="answering", facts={"destination_preference": "Germany"}),
        "next month": TurnAnalysis(intent="answering", facts={"preferred_timing": "next month"}),
    }
    service, model, conversation = _service(script)
    results = [_say(service, conversation, t) for t in ["knee surgery", "Germany", "next month"]]
    assert results[-1]["next_action"] == "signup_handoff"
    system = model.calls[-1][0]["content"]
    assert "free consultation with one of our medical advisors" in system
    assert "signup and login page now" in system
    assert conversation.case_facts["handoff_offered"] == "yes"


def test_wellness_visitors_are_offered_a_free_call_with_the_curator():
    script = {
        "a longevity retreat": TurnAnalysis(
            intent="answering", category="wellness",
            facts={"wellness_programme_or_goal": "longevity retreat", "preferred_programme": "HAYAT 100",
                   "destination_preference": "Spain"},
        ),
    }
    service, model, conversation = _service(script)
    result = _say(service, conversation, "a longevity retreat")
    assert result["next_action"] == "signup_handoff"
    assert "free call with our wellness curator" in model.calls[-1][0]["content"]


def _offered(extra=None):
    script = {
        "knee surgery": MEDICAL,
        "Germany": TurnAnalysis(intent="answering", facts={"destination_preference": "Germany"}),
        "next month": TurnAnalysis(intent="answering", facts={"preferred_timing": "next month"}),
        **(extra or {}),
    }
    service, model, conversation = _service(script)
    for text in ["knee surgery", "Germany", "next month"]:
        _say(service, conversation, text)
    return service, model, conversation


def test_accepting_the_offer_gives_the_signup_step_without_taking_contact_details():
    service, model, conversation = _offered({"yes please": TurnAnalysis(intent="accepts")})
    result = _say(service, conversation, "yes please")
    assert result["next_action"] == "handoff_link"
    assert "Do not take any contact details here" in model.calls[-1][0]["content"]


def test_declining_the_offer_is_respected_without_pushing():
    service, model, conversation = _offered({"not now": TurnAnalysis(intent="declines")})
    result = _say(service, conversation, "not now")
    assert result["next_action"] == "handoff_declined"
    assert "no pressure at all" in model.calls[-1][0]["content"]
    assert conversation.case_facts["handoff_declined"] == "yes"


def test_under_18_stops_the_intake_for_good():
    service, model, conversation = _service({
        "I'm 16": TurnAnalysis(intent="under_18"),
        "ok": TurnAnalysis(intent="answering"),
    })
    first = _say(service, conversation, "I'm 16")
    assert first["next_action"] == "stop_intake"
    assert "services are for adults" in model.calls[-1][0]["content"]
    later = _say(service, conversation, "ok")
    assert later["next_action"] == "stop_intake"  # it stays stopped


def test_wanting_a_human_points_to_the_free_consultation_not_to_contact_capture():
    service, model, conversation = _service({"can I talk to a person?": TurnAnalysis(intent="wants_human")})
    result = _say(service, conversation, "can I talk to a person?")
    assert result["next_action"] == "human_request"
    system = model.calls[-1][0]["content"]
    assert "quickest route is to book the free consultation" in system
    assert "Do not take contact details in chat" in system


def test_stop_messaging_is_recorded_and_acknowledged():
    service, model, conversation = _service({"stop messaging me": TurnAnalysis(intent="wants_stop")})
    result = _say(service, conversation, "stop messaging me")
    assert result["next_action"] == "opt_out"
    assert conversation.case_facts["opt_out_requested"] == "yes"
    assert "privacy request page" in model.calls[-1][0]["content"]


def test_clinical_detail_and_report_requests_follow_the_documents_replies():
    # The analyzer sees redacted text for clinical messages, hence the default.
    service, model, conversation = _service({
        "can you read my scan?": TurnAnalysis(intent="asks_interpretation"),
        "are you a real person?": TurnAnalysis(intent="asks_if_human"),
    }, default=TurnAnalysis(intent="clinical_detail"))
    _say(service, conversation, "I have diabetes")
    assert "keep them out of the enquiry summary" in model.calls[-1][0]["content"]
    _say(service, conversation, "can you read my scan?")
    assert "cannot interpret reports or symptoms" in model.calls[-1][0]["content"]
    _say(service, conversation, "are you a real person?")
    assert "trawellcare's AI assistant" in model.calls[-1][0]["content"]
    assert not any("diabetes" in str(v) for v in conversation.case_facts.values())


def test_the_fifth_visitor_message_triggers_the_offer_even_with_little_shared():
    chat = {f"message {i}": TurnAnalysis(intent="smalltalk") for i in range(1, 6)}
    service, model, conversation = _service(chat)
    last = None
    for i in range(1, 6):
        last = _say(service, conversation, f"message {i}")
    assert last["next_action"] == "signup_handoff"
    assert conversation.case_facts["handoff_offered"] == "yes"
    assert "free consultation with the right person" in model.calls[-1][0]["content"]


def test_no_suggestion_buttons_are_sent():
    service, _, conversation = _service({"hello": TurnAnalysis(intent="smalltalk")})
    result = _say(service, conversation, "hello")
    assert result["suggestions"] == []
    assert result["suggested_actions"] == []


def test_a_medical_statement_is_never_stored_as_the_answer_to_a_question():
    # Seen live: the analyzer called a diabetes message an "answer", so it landed in a field.
    service, _, conversation = _service(
        {"a longevity retreat": TurnAnalysis(
            intent="answering", category="wellness",
            facts={"wellness_programme_or_goal": "longevity retreat"})},
        default=TurnAnalysis(intent="answering"),
    )
    _say(service, conversation, "a longevity retreat")
    _say(service, conversation, "I have type 2 diabetes and take metformin")
    stored = " ".join(str(v) for v in conversation.case_facts.values()).lower()
    assert "diabetes" not in stored and "metformin" not in stored


def test_hayat_never_invents_a_signup_link():
    service, model, conversation = _offered({"yes please": TurnAnalysis(intent="accepts")})
    _say(service, conversation, "yes please")
    system = model.calls[-1][0]["content"]
    assert "do not write any link" in system
    assert "Never write a web address" in system

    service.signup_url = "https://example.org/join"
    service.question_planner.handoff = True
    conversation.case_facts["handoff_offer_turn"] = str(
        sum(1 for m in conversation.messages if m.role == "assistant")
    )
    service.analyzer.script["sure"] = TurnAnalysis(intent="accepts")
    _say(service, conversation, "sure")
    assert "https://example.org/join" in model.calls[-1][0]["content"]


def test_a_fixed_step_still_deals_with_a_clinical_message_first():
    service, model, conversation = _offered({})
    service.analyzer.script["I also have asthma"] = TurnAnalysis(intent="clinical_detail")
    service.analyzer.default = TurnAnalysis(intent="clinical_detail")
    _say(service, conversation, "I also have asthma")
    system = model.calls[-1][0]["content"]
    assert "keep them out of the enquiry summary" in system
