"""Provider adapter with a deterministic offline implementation for tests."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from .config import Settings


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
        self._client = AsyncGroq(api_key=self.settings.groq_api_key.get_secret_value())
        self._model = self.settings.groq_model
        self._temperature = self.settings.groq_temperature
        self._max_tokens = self.settings.groq_max_tokens
        self._timeout = self.settings.groq_timeout_seconds

    async def complete(self, messages: list[dict[str, str]]) -> str:
        from groq import APIError

        try:
            kwargs: dict = {}
            if self._model.startswith("openai/gpt-oss"):
                # Reasoning models burn completion tokens on hidden reasoning;
                # keep it low so the reply fits in the token budget.
                kwargs["reasoning_effort"] = "low"
            response = await self._client.chat.completions.create(
                model=self._model,
                messages=messages,
                temperature=self._temperature,
                max_tokens=self._max_tokens,
                timeout=self._timeout,
                **kwargs,
            )
        except (APIError, TimeoutError) as exc:
            raise LLMError("Configured language model request failed.") from exc
        content = response.choices[0].message.content
        if not content:
            raise LLMError("Groq returned an empty response.")
        return content


def create_chat_model(settings: Settings) -> ChatModel:
    return GroqChatModel(settings) if "GROQ_API_KEY" not in settings.missing_integrations else OfflineChatModel()