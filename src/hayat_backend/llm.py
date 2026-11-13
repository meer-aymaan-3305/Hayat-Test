"""Provider adapter with a deterministic offline implementation for tests."""

from __future__ import annotations

import logging
import asyncio
import time
from dataclasses import dataclass
from typing import Protocol

from .config import Settings
from .llm_compat import CompatError, OpenAICompatClient


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
        # No SDK retries or waiting: a failure moves straight on to the next model.
        self._client = AsyncGroq(api_key=self.settings.groq_api_key.get_secret_value(), max_retries=0)
        self._fallbacks = [
            m for m in self.settings.groq_fallback_models if m != self.settings.groq_model
        ]
        # A model that just said "rate limited" is skipped for a short while.
        self._cooldown_until: dict[str, float] = {}
        self._backup = backup_client(self.settings)
        self._model = self.settings.groq_model
        self._temperature = self.settings.groq_temperature
        self._max_tokens = self.settings.groq_max_tokens
        self._timeout = self.settings.groq_timeout_seconds

    # The composer may ask for the reply as structured JSON (IMPLEMENTATION.md, phase 3).
    supports_json = True

    async def complete(self, messages: list[dict[str, str]], json_mode: bool = False) -> str:
        """Ask the primary model; if it is rate limited or down, try the other Groq models
        and then the backup provider, so one account's limit never silences the chat."""
        from groq import APIError, AuthenticationError, RateLimitError

        from .ratelimit import MAX_WAIT, note_limited, retry_wait, wait_for_window

        last_error: Exception | None = None
        models = [self._model, *self._fallbacks]
        soonest = min(self._cooldown_until.get(m, 0) for m in models) - time.monotonic()
        if 0 < soonest <= MAX_WAIT:  # every model is cooling down: wait for the first to reopen
            await asyncio.sleep(soonest + 0.2)
        for model in models:
            if self._cooldown_until.get(model, 0) > time.monotonic():
                continue
            for attempt in range(2):
                await wait_for_window()  # the per-minute token window is shared by every Groq model
                try:
                    if json_mode:
                        return await self._complete_with(model, messages, json_mode)
                    return await self._complete_with(model, messages)
                except RateLimitError as exc:
                    wait = retry_wait(exc)
                    last_error = exc
                    if wait <= MAX_WAIT and attempt == 0:
                        note_limited(wait)
                        logger.warning("model %s hit the minute limit; waiting %.1fs", model, wait)
                        continue
                    self._cooldown_until[model] = time.monotonic() + min(wait, 3600)
                    logger.warning("model %s is rate limited; skipping it for %.0fs", model, min(wait, 3600))
                except AuthenticationError as exc:
                    self._cooldown_until[model] = time.monotonic() + 300
                    last_error = exc
                    logger.warning("model %s rejected the API key; skipping it for 5 minutes", model)
                except (APIError, TimeoutError, LLMError) as exc:
                    last_error = exc
                    logger.warning("model %s failed (%s); trying the next one", model, type(exc).__name__)
                break
        if self._backup is not None:
            try:
                if json_mode:
                    return await self._complete_backup(messages, json_mode)
                return await self._complete_backup(messages)
            except CompatError as exc:
                last_error = exc
                logger.warning("backup model failed: %s", exc)
        raise LLMError("Configured language model request failed.") from last_error

    async def _complete_backup(self, messages: list[dict[str, str]], json_mode: bool = False) -> str:
        budget = max(self._max_tokens, 1500)  # some providers think before answering
        text = ""
        for _attempt in range(2):
            text, finish = await self._backup.chat(
                messages, max_tokens=budget, temperature=self._reply_temperature(json_mode), json_mode=json_mode,
            )
            if finish != "length":
                return text
            budget *= 2
        return _trim_to_last_sentence(text)

    def _reply_temperature(self, json_mode: bool) -> float:
        # Addendum 7.2: low temperature for extraction, a moderate one for the reply.
        return max(self._temperature, 0.5) if json_mode else self._temperature

    async def _complete_with(self, model: str, messages: list[dict[str, str]], json_mode: bool = False) -> str:
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
            if json_mode:
                kwargs["response_format"] = {"type": "json_object"}
            response = await self._client.chat.completions.create(
                model=model,
                messages=messages,
                temperature=self._reply_temperature(json_mode),
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
            return text if json_mode else _trim_to_last_sentence(text)
        raise LLMError("Groq returned an empty response.")


def backup_client(settings: Settings) -> OpenAICompatClient | None:
    """The backup provider, when LLM_FALLBACK_* is configured."""
    if settings.llm_fallback_base_url and settings.llm_fallback_api_key and settings.llm_fallback_model:
        return OpenAICompatClient(
            settings.llm_fallback_base_url,
            settings.llm_fallback_api_key.get_secret_value(),
            settings.llm_fallback_model,
            timeout=settings.groq_timeout_seconds,
            # Gemini 2.5 thinks before answering (3s); without it a reply takes about 1s.
            # Gemini thinks before answering (seconds); a chat reply does not need it.
            extra={"reasoning_effort": "none"} if "gemini" in settings.llm_fallback_model else None,
        )
    return None


def _trim_to_last_sentence(text: str) -> str:
    """Drop a trailing half sentence from a reply that was cut off at the token limit."""
    for index in range(len(text) - 1, -1, -1):
        if text[index] in ".!?؟":
            return text[: index + 1]
    return text


def create_chat_model(settings: Settings) -> ChatModel:
    return GroqChatModel(settings) if "GROQ_API_KEY" not in settings.missing_integrations else OfflineChatModel()