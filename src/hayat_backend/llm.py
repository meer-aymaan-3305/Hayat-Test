"""Provider adapter with a deterministic offline implementation for tests."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Protocol

from .config import Settings


logger = logging.getLogger("hayat.llm")


class LLMError(RuntimeError):
    """Raised when the configured language model cannot answer."""


class ChatModel(Protocol):
    async def complete(self, messages: list[dict[str, str]]) -> str: ...


@dataclass
class OfflineChatModel:
    """Safe local adapter used when no provider credential is configured or in tests."""

    async def complete(self, messages: list[dict[str, str]]) -> str:
        user_text = next(
            (message["content"] for message in reversed(messages) if message["role"] == "user"),
            "",
        )
        is_arabic = any("\u0600" <= char <= "\u06ff" for char in user_text)
        user_lower = user_text.lower()

        # Safe preparation advice (no mandatory clinical records, no prohibited info).
        if "prepare" in user_lower or "document" in user_lower or "information" in user_lower or "تجهيز" in user_text or "مستند" in user_text:
            if is_arabic:
                return (
                    "للاستعداد للاستشارة، من المفيد توفير التقارير الطبية الحديثة أو قائمة الأدوية إن وجدت، "
                    "وسيوضح المنسق ما إذا كانت هناك حاجة لتقارير محددة."
                )
            return (
                "To prepare for your consultation, it is helpful to have your recent medical records, reports, "
                "or current medication list available if you have them. A coordinator will advise if specific records are needed."
            )

        # Safe, policy-compliant generic fallback. No destination comparisons,
        # no medical recommendations, no requests for prohibited clinical details.
        if is_arabic:
            return (
                "يمكنني مساعدتك في التخطيط لرحلة الرعاية أو العافية مع ترافيل كير. "
                "يرجى مشاركة الخدمة والوجهة والوقت المفضل، وسيؤكد المنسق التفاصيل."
            )
        return (
            "I can help you plan your care or wellness journey with Trawellcare. "
            "Please share your preferred service, destination, and timing, and a coordinator "
            "will confirm the details."
        )


@dataclass
class GroqChatModel:
    """Thin async Groq adapter; imported only when a key is configured."""

    settings: Settings

    def __post_init__(self) -> None:
        from groq import AsyncGroq

        if not self.settings.groq_api_key:
            raise LLMError("Groq API key is not configured.")
        # One quick SDK retry; after that we fail over to the next model instead of waiting.
        self._client = AsyncGroq(api_key=self.settings.groq_api_key.get_secret_value(), max_retries=1)
        self._fallbacks = [
            m for m in self.settings.groq_fallback_models if m != self.settings.groq_model
        ]
        self._model = self.settings.groq_model
        self._temperature = self.settings.groq_temperature
        self._max_tokens = self.settings.groq_max_tokens
        self._timeout = self.settings.groq_timeout_seconds

    async def complete(self, messages: list[dict[str, str]]) -> str:
        """Ask the primary model; if it is rate limited or down, try the fallbacks, so a
        limit on one model never turns into canned replies for the visitor."""
        from groq import APIError

        last_error: Exception | None = None
        for model in [self._model, *self._fallbacks]:
            try:
                return await self._complete_with(model, messages)
            except (APIError, TimeoutError, LLMError) as exc:
                last_error = exc
                logger.warning("model %s failed (%s); trying the next one", model, type(exc).__name__)
        raise LLMError("Configured language model request failed.") from last_error

    async def _complete_with(self, model: str, messages: list[dict[str, str]]) -> str:
        gpt_oss = model.startswith("openai/gpt-oss")
        qwen = model.startswith("qwen/")
        # gpt-oss spends completion tokens on hidden thinking, so it needs a larger
        # ceiling. qwen is told not to think at all: faster, and the budget goes to the
        # reply. Reply length itself is controlled by the prompt.
        budget = max(self._max_tokens, 1500) if gpt_oss else self._max_tokens
        text = ""
        for _attempt in range(2):
            kwargs: dict = {}
            if gpt_oss:
                kwargs["reasoning_effort"] = "low"
            elif qwen:
                kwargs["reasoning_effort"] = "none"
            response = await self._client.chat.completions.create(
                model=model,
                messages=messages,
                temperature=self._temperature,
                max_tokens=budget,
                timeout=self._timeout,
                **kwargs,
            )
            choice = response.choices[0]
            text = (choice.message.content or "").strip()
            if text and choice.finish_reason != "length":
                return text
            budget *= 2  # empty or cut off at the limit: retry once with more room
        if text:
            return _trim_to_last_sentence(text)
        raise LLMError("Groq returned an empty response.")


def _trim_to_last_sentence(text: str) -> str:
    """Drop a trailing half sentence from a reply that was cut off at the token limit."""
    for index in range(len(text) - 1, -1, -1):
        if text[index] in ".!?؟":
            return text[: index + 1]
    return text


def create_chat_model(settings: Settings) -> ChatModel:
    return GroqChatModel(settings) if "GROQ_API_KEY" not in settings.missing_integrations else OfflineChatModel()