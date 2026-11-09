"""Shadow mode: the AI runs beside the scripted reply and is only logged."""

import asyncio
import logging

import pytest

from hayat_backend import chat_service as chat_service_module
from hayat_backend.chat_service import ChatService
from hayat_backend.llm import LLMError
from hayat_backend.memory_store import MemoryStore

# Reaches the model step for a website visitor: the scripted fallback answers it.
# (Must not match any deterministic FAQ — those bypass the model entirely.)
OPENING_MESSAGE = "Hello, tell me something interesting about Trawellcare"


class RecordingModel:
    def __init__(self, reply="Apollo Hospitals is the best choice for you.", error=None):
        self.reply = reply
        self.error = error
        self.calls = []

    async def complete(self, messages):
        self.calls.append(messages)
        if self.error:
            raise self.error
        return self.reply


def _turn(model, *, use_ai, shadow_ai, message=OPENING_MESSAGE, service=None):
    store = MemoryStore()
    session, _ = store.create_guest_session("en")
    conversation = store.create_conversation(session.id)
    service = service or ChatService(store, model)

    async def run():
        result = await service.respond(conversation, message, visitor="guest", use_ai=use_ai, shadow_ai=shadow_ai)
        await service.wait_for_shadow()
        return result

    return asyncio.run(run()), service


def test_the_visitor_still_gets_the_scripted_reply(caplog):
    model = RecordingModel()
    with caplog.at_level(logging.INFO, logger="hayat.shadow"):
        result, _ = _turn(model, use_ai=False, shadow_ai=True)
    reply = result["assistant_message"].content
    assert "Apollo" not in reply
    assert len(model.calls) == 1


def test_it_logs_what_the_ai_would_have_said_and_whether_it_was_blocked(caplog):
    with caplog.at_level(logging.INFO, logger="hayat.shadow"):
        _turn(RecordingModel(), use_ai=False, shadow_ai=True)
    line = next(record.getMessage() for record in caplog.records if record.name == "hayat.shadow")
    assert "outcome=blocked_or_edited" in line
    assert "language=en" in line


def test_an_acceptable_reply_is_logged_as_passed(caplog):
    with caplog.at_level(logging.INFO, logger="hayat.shadow"):
        _turn(RecordingModel(reply="Understood. Which destination would you prefer?"), use_ai=False, shadow_ai=True)
    assert any("outcome=passed" in record.getMessage() for record in caplog.records)


def test_the_visitors_words_are_not_written_to_the_log(caplog):
    with caplog.at_level(logging.INFO, logger="hayat.shadow"):
        _turn(RecordingModel(), use_ai=False, shadow_ai=True, message="Hello, I want to know about wellness programmes for Sarah")
    assert "Sarah" not in caplog.text


def test_a_failing_model_is_logged_and_never_reaches_the_visitor(caplog):
    with caplog.at_level(logging.INFO, logger="hayat.shadow"):
        result, _ = _turn(RecordingModel(error=LLMError("down")), use_ai=False, shadow_ai=True)
    assert result["assistant_message"].content
    assert any("outcome=model_error" in record.getMessage() for record in caplog.records)


def test_it_does_nothing_unless_it_is_switched_on():
    model = RecordingModel()
    _turn(model, use_ai=False, shadow_ai=False)
    assert model.calls == []


def test_it_does_not_run_twice_when_the_ai_is_already_answering():
    model = RecordingModel(reply="Understood. Which destination would you prefer?")
    _turn(model, use_ai=True, shadow_ai=True)
    assert len(model.calls) == 1


def test_it_stops_at_the_per_minute_cap(monkeypatch):
    monkeypatch.setattr(chat_service_module, "SHADOW_CALLS_PER_MINUTE", 2)
    model = RecordingModel()
    store = MemoryStore()
    service = ChatService(store, model)
    for _ in range(4):
        _turn(model, use_ai=False, shadow_ai=True, service=service)
    assert len(model.calls) == 2
