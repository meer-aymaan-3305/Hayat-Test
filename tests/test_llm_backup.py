"""The backup provider keeps Hayat answering when Groq is rate limited."""

import asyncio

import httpx
import pytest

from hayat_backend.config import Settings
from hayat_backend.llm import GroqChatModel, LLMError
from hayat_backend.llm_compat import CompatError, OpenAICompatClient


def _client(handler):
    return OpenAICompatClient("https://backup.example/v1", "k", "m", transport=httpx.MockTransport(handler))


def _ok(text="Hello from the backup.", finish="stop"):
    return httpx.Response(200, json={"choices": [{"message": {"content": text}, "finish_reason": finish}]})


def test_backup_client_returns_text_and_finish_reason():
    text, finish = asyncio.run(_client(lambda request: _ok()).chat([{"role": "user", "content": "hi"}], max_tokens=50))
    assert (text, finish) == ("Hello from the backup.", "stop")


def test_backup_client_retries_without_json_mode_when_the_provider_rejects_it():
    seen = []

    def handler(request):
        body = request.read().decode()
        seen.append("response_format" in body)
        return httpx.Response(400) if "response_format" in body else _ok("{}")

    text, _ = asyncio.run(_client(handler).chat([], max_tokens=50, json_mode=True))
    assert text == "{}" and seen == [True, False]


def test_backup_client_reports_failures_as_compat_errors():
    with pytest.raises(CompatError):
        asyncio.run(_client(lambda request: httpx.Response(429)).chat([], max_tokens=5))
    with pytest.raises(CompatError):
        asyncio.run(_client(lambda request: _ok("")).chat([], max_tokens=5))


def _groq_model(**extra):
    settings = Settings(
        groq_api_key="test-key", groq_model="primary", groq_fallback_models=["second"],
        llm_fallback_base_url="https://backup.example/v1", llm_fallback_api_key="k",
        llm_fallback_model="backup", **extra,
    )
    model = GroqChatModel(settings)
    model._backup = _client(lambda request: _ok("Backup answer."))
    return model


def test_when_every_groq_model_is_down_the_backup_answers():
    model = _groq_model()

    async def down(name, messages):
        raise LLMError("down")

    model._complete_with = down
    assert asyncio.run(model.complete([{"role": "user", "content": "hi"}])) == "Backup answer."


def test_a_rate_limited_model_is_skipped_for_a_while():
    import groq

    model = _groq_model()
    tried: list[str] = []

    async def limited(name, messages):
        tried.append(name)
        if name == "primary":
            raise groq.RateLimitError(
                "limited",
                response=httpx.Response(429, request=httpx.Request("POST", "https://x")),
                body=None,
            )
        return "Second model answer."

    model._complete_with = limited
    assert asyncio.run(model.complete([])) == "Second model answer."
    assert asyncio.run(model.complete([])) == "Second model answer."
    assert tried == ["primary", "second", "second"]  # primary was not retried right away
