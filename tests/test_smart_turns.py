"""Mid-flow questions: Hayat answers them, and only then returns to the flow.

The analyzer and the reply model are stubbed so these run offline.
"""

import asyncio
import uuid

from hayat_backend.chat_service import (
    ChatService,
    _declarative_part,
    _merge_analysis,
    _slot_value,
)
from hayat_backend.memory_store import MemoryStore
from hayat_backend.question_planner import QuestionPlanner
from hayat_backend.schemas.intake import FactStatus, FactValue
from hayat_backend.turn_analyzer import TurnAnalysis, parse_analysis


class StubModel:
    def __init__(self) -> None:
        self.calls: list[list[dict[str, str]]] = []

    async def complete(self, messages):
        self.calls.append(messages)
        return "Happy to explain that."


class StubAnalyzer:
    """Returns a scripted analysis per message text."""

    def __init__(self, script: dict[str, TurnAnalysis]) -> None:
        self.script = script

    async def analyze(self, *, text, last_assistant, pending_field, known):
        return self.script.get(text)


def _service(script):
    store = MemoryStore()
    model = StubModel()
    service = ChatService(store, model)
    service.question_planner = QuestionPlanner(extended=True, collect_diagnosis=True)
    service.collect_diagnosis = True
    service.analyzer = StubAnalyzer(script)
    session, _ = store.create_guest_session("en")
    conversation = store.create_conversation(session.id)
    return service, store, model, conversation


def _say(service, conversation, text):
    return asyncio.run(service.respond(conversation, text, str(uuid.uuid4()), use_ai=True))


def test_declarative_part_keeps_the_answer_and_drops_the_question():
    assert _declarative_part("I have a torn ACL, is that something you can fix?") == "I have a torn ACL"
    assert _declarative_part("around 8000 dollars, is that enough?") == "around 8000 dollars"
    assert _declarative_part("how does it work?") == ""


def test_slot_value_uses_the_statement_part_of_a_mixed_message():
    assert _slot_value("budget_range", "around 8000 dollars, is that enough?") == "around 8000 dollars"
    assert _slot_value("budget_range", "what do you charge?") is None


def test_parse_analysis_rejects_junk_and_unknown_keys():
    parsed = parse_analysis(
        {"intent": "nonsense", "category": "hospital", "facts": {"budget_range": "5k", "x": "y"}}
    )
    assert parsed.intent == "answering" and parsed.category is None
    assert parsed.facts == {"budget_range": "5k"}
    assert parse_analysis(["not", "a", "dict"]) is None


def test_a_place_named_inside_a_question_is_not_a_destination():
    store = MemoryStore()
    session, _ = store.create_guest_session("en")
    conversation = store.create_conversation(session.id)
    rule_based = [
        FactValue(field_name="destination_preference", value="Germany", status=FactStatus.CONFIRMED),
        FactValue(field_name="phone_number", value="+96891234567", status=FactStatus.CONFIRMED),
    ]
    merged = _merge_analysis(rule_based, TurnAnalysis(intent="question"), uuid.uuid4(), conversation)
    names = {fact.field_name for fact in merged}
    assert "destination_preference" not in names
    assert "phone_number" in names


def test_question_turn_is_answer_first_and_keeps_the_pending_step():
    script = {
        "I want knee surgery": TurnAnalysis(
            intent="answering", category="medical_treatment",
            facts={"procedure_or_service": "knee surgery"},
        ),
        "how does this work?": TurnAnalysis(intent="question"),
    }
    service, _, model, conversation = _service(script)
    _say(service, conversation, "I want knee surgery")
    result = _say(service, conversation, "how does this work?")
    # The destination step is still pending, but the model decides whether to return.
    assert result["follow_up_target"] == "destination_preference"
    system = model.calls[-1][0]["content"]
    assert "Respond to THAT first" in system
    assert "Happy to explain that." in result["reply"]
    # The planned question is not bolted on when the model did not ask it.
    assert "Which destination" not in result["reply"]


def test_plain_answers_still_follow_the_flow():
    script = {
        "I want knee surgery": TurnAnalysis(
            intent="answering", category="medical_treatment",
            facts={"procedure_or_service": "knee surgery"},
        ),
    }
    service, _, _, conversation = _service(script)
    result = _say(service, conversation, "I want knee surgery")
    assert result["follow_up_target"] == "destination_preference"
    assert "destination" in result["reply"].lower()


def test_wants_human_goes_straight_to_contact_details():
    script = {
        "I want knee surgery": TurnAnalysis(
            intent="answering", category="medical_treatment",
            facts={"procedure_or_service": "knee surgery"},
        ),
        "can I talk to a person now?": TurnAnalysis(intent="wants_human"),
    }
    service, _, _, conversation = _service(script)
    _say(service, conversation, "I want knee surgery")
    result = _say(service, conversation, "can I talk to a person now?")
    assert result["follow_up_target"] in {"name", "phone_number"}


def test_a_diagnosis_given_with_a_question_is_still_recorded():
    script = {
        "I want knee surgery": TurnAnalysis(
            intent="answering", category="medical_treatment",
            facts={"procedure_or_service": "knee surgery"},
        ),
        "Germany": TurnAnalysis(intent="answering", facts={"destination_preference": "Germany"}),
        "next month": TurnAnalysis(intent="answering", facts={"preferred_timing": "next month"}),
        "I have a torn ACL, can your doctors fix it?": TurnAnalysis(intent="question"),
    }
    service, _, _, conversation = _service(script)
    for text in ["I want knee surgery", "Germany", "next month"]:
        _say(service, conversation, text)
    result = _say(service, conversation, "I have a torn ACL, can your doctors fix it?")
    assert conversation.case_facts.get("condition_context_for_advisor") == "I have a torn ACL"
    assert result["follow_up_target"] == "budget_range"


def _filled_conversation(script_extra=None):
    script = {
        "I want knee surgery": TurnAnalysis(
            intent="answering", category="medical_treatment",
            facts={"procedure_or_service": "knee surgery"},
        ),
        "Germany": TurnAnalysis(intent="answering", facts={"destination_preference": "Germany"}),
        **(script_extra or {}),
    }
    service, store, model, conversation = _service(script)
    for text in ["I want knee surgery", "Germany"]:
        _say(service, conversation, text)
    return service, store, model, conversation


def test_changing_a_detail_updates_it_and_the_flow_continues():
    service, _, _, conversation = _filled_conversation({
        "actually Turkey instead": TurnAnalysis(
            intent="answering", facts={"destination_preference": "Turkey"}
        ),
    })
    result = _say(service, conversation, "actually Turkey instead")
    assert conversation.case_facts["destination_preference"] == "Turkey"
    assert conversation.case_facts["preferred_destination"] == "Turkey"
    assert result["follow_up_target"] == "preferred_timing"


def test_switching_category_midway_is_followed():
    service, _, _, conversation = _filled_conversation({
        "I want a wellness retreat instead": TurnAnalysis(
            intent="answering", category="wellness",
            facts={"wellness_programme_or_goal": "wellness retreat"},
        ),
    })
    _say(service, conversation, "I want a wellness retreat instead")
    assert conversation.case_facts["customer_category"] == "wellness"
    assert conversation.case_facts["wellness_programme_or_goal"] == "wellness retreat"


def test_an_extra_request_is_noted_for_the_coordinator_not_lost():
    service, _, model, conversation = _filled_conversation({
        "my sister also wants a retreat": TurnAnalysis(
            intent="new_request", note="Retreat for the visitor's sister"
        ),
    })
    _say(service, conversation, "my sister also wants a retreat")
    assert "sister" in conversation.case_facts["additional_requests"]
    assert "added to their enquiry" in model.calls[-1][0]["content"]


def test_off_topic_is_declined_by_the_model_not_answered_or_scripted():
    service, _, model, conversation = _filled_conversation({
        "what is 25 times 4?": TurnAnalysis(intent="off_topic"),
    })
    result = _say(service, conversation, "what is 25 times 4?")
    system = model.calls[-1][0]["content"]
    assert "unrelated to Trawellcare. Do NOT answer it" in system
    assert "SCOPE: you only talk about Trawellcare" in system
    assert result["escalation_required"] is False
    # Nothing was recorded from an off topic message.
    assert "additional_requests" not in conversation.case_facts


def test_after_submission_there_is_no_submit_loop():
    service, store, model, conversation = _filled_conversation({
        "thanks, bye": TurnAnalysis(intent="smalltalk"),
    })
    conversation.consultation_id = uuid.uuid4()  # already submitted
    result = _say(service, conversation, "thanks, bye")
    assert result["next_action"] == "post_submission"
    assert "submit this consultation" not in result["reply"].lower()
    assert "ALREADY submitted" in model.calls[-1][0]["content"]


def test_a_question_asked_three_times_without_an_answer_is_skipped():
    service, _, _, conversation = _filled_conversation()
    for _ in range(3):
        store = service.store
        store.append_message(conversation, "assistant", "Do you have a rough budget in mind?", "en")
    facts = service._skip_if_stuck(conversation, "budget_range", [], uuid.uuid4())
    assert [f.field_name for f in facts] == ["budget_range"]
    assert service._skip_if_stuck(conversation, "current_country", [], uuid.uuid4()) == []


def test_a_rate_limited_model_fails_over_instead_of_failing_the_turn():
    from hayat_backend.config import Settings
    from hayat_backend.llm import GroqChatModel, LLMError

    settings = Settings(
        groq_api_key="test-key", groq_model="primary-model",
        groq_fallback_models=["backup-model"],
    )
    model = GroqChatModel(settings)
    tried: list[str] = []

    async def fake(name, messages):
        tried.append(name)
        if name == "primary-model":
            raise LLMError("rate limited")
        return "Backup answer."

    model._complete_with = fake
    assert asyncio.run(model.complete([{"role": "user", "content": "hi"}])) == "Backup answer."
    assert tried == ["primary-model", "backup-model"]


def test_total_model_outage_is_honest_and_keeps_the_flow_moving():
    from hayat_backend.llm import LLMError

    class DownModel:
        async def complete(self, messages):
            raise LLMError("all models down")

    script = {
        "I want knee surgery": TurnAnalysis(
            intent="answering", category="medical_treatment",
            facts={"procedure_or_service": "knee surgery"},
        ),
    }
    service, _, _, conversation = _service(script)
    service.model = DownModel()
    result = _say(service, conversation, "I want knee surgery")
    assert "having a little trouble" in result["reply"]
    assert "interested in knee surgery treatment" not in result["reply"]
    assert result["follow_up_target"] == "destination_preference"
    assert "destination" in result["reply"].lower()
