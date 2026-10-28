import asyncio

from hayat_backend.chat_service import ChatService
from hayat_backend.memory_store import MemoryStore


class RecordingModel:
    def __init__(self) -> None:
        self.calls: list[list[dict[str, str]]] = []

    async def complete(self, messages: list[dict[str, str]]) -> str:
        self.calls.append(messages)
        return "I used the conversation context."


def _conversation(store: MemoryStore):
    session, _ = store.create_guest_session()
    return store.create_conversation(session.id)


def test_context_uses_prior_turns_once_and_includes_structured_facts():
    store = MemoryStore()
    model = RecordingModel()
    conversation = _conversation(store)
    conversation.case_facts["destination_preference"] = "India"
    store.append_message(conversation, "assistant", "India is one possible destination.", "en")

    result = asyncio.run(ChatService(store, model).respond(
        conversation, "What about the second destination option for my medical travel?", "message-1"
    ))

    request = model.calls[0]
    assert [message["content"] for message in request].count(
        "What about the second destination option for my medical travel?"
    ) == 1
    assert any("India" in message["content"] for message in request)
    assert result["suggestions"] == []


def test_separate_conversations_do_not_share_context():
    store = MemoryStore()
    model = RecordingModel()
    first = _conversation(store)
    second = _conversation(store)
    store.append_message(first, "user", "My name is Amina Example.", "en")

    asyncio.run(ChatService(store, model).respond(
        second, "What do you know about my consultation options?", "message-2"
    ))

    assert all("Amina Example" not in message["content"] for message in model.calls[0])


def test_repeated_client_message_id_is_idempotent():
    store = MemoryStore()
    model = RecordingModel()
    conversation = _conversation(store)
    service = ChatService(store, model)

    first = asyncio.run(service.respond(conversation, "What services do you offer?", "same-id"))
    second = asyncio.run(service.respond(conversation, "What services do you offer?", "same-id"))

    assert second["assistant_message"].id == first["assistant_message"].id
    assert len([message for message in conversation.messages if message.role == "user"]) == 1


def test_multiple_consultation_facts_are_extracted_and_progress_is_returned():
    store = MemoryStore()
    model = RecordingModel()
    conversation = _conversation(store)

    result = asyncio.run(ChatService(store, model).respond(
        conversation,
        "My name is Amina Example. I am interested in dental implants in India in December. "
        "My budget is 2000 USD and my goal is to replace missing teeth.",
        "facts-1",
    ))

    fields = {fact.field_name for fact in result["fact_updates"]}
    assert {"name", "procedure_or_service", "destination_preference", "preferred_timing",
            "budget_range", "treatment_objective", "care_category"} <= fields
    assert "phone_number" in result["consultation_progress"].missing_fields


def test_treatment_discovery_asks_one_contextual_question_without_contact_collection():
    store = MemoryStore()
    model = RecordingModel()
    conversation = _conversation(store)

    result = asyncio.run(ChatService(store, model).respond(
        conversation,
        "I'm interested in dental implants in India.",
        "discovery-1",
    ))

    reply = result["assistant_message"].content
    assert result["next_action"] == "collect_detail"
    assert result["conversation_state"] == "collecting_details"
    assert "What timeframe would suit you best" in reply
    assert "phone" not in reply.lower()
    assert "answer the user's immediate question first" in model.calls[0][0]["content"]


def test_question_is_answered_then_planner_preserves_a_single_followup_goal():
    store = MemoryStore()
    model = RecordingModel()
    conversation = _conversation(store)

    result = asyncio.run(ChatService(store, model).respond(
        conversation,
        "How does the treatment process work?",
        "question-1",
    ))

    assert result["next_action"] == "answer"
    assert result["assistant_message"].content == "Hello! I used the conversation context."


def test_conversation_facts_automatically_create_a_lead_after_consultation_intent():
    store = MemoryStore()
    model = RecordingModel()
    conversation = _conversation(store)

    asyncio.run(ChatService(store, model).respond(
        conversation,
        "I want a consultation. My name is Amina Example and my phone is +971501234567. "
        "I need dental implants.",
        "lead-1",
    ))

    lead = store.lead_for(conversation.id)
    assert lead is not None
    assert lead.details.name == "Amina Example"
    assert lead.details.phone_number == "+971501234567"
