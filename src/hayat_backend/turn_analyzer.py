"""Model-based reading of a single visitor turn.

Keyword rules cannot tell "Germany" (an answer) from "do you work with hospitals in
Germany?" (a question), or notice that someone wants a human. This module asks a small
fast model to classify the turn and pull out any details the visitor actually stated.
It never writes the reply and it fails open: if the call fails, the caller falls back to
the rule-based extraction.

Only the redacted message text is sent, the same copy the reply model already sees.
"""

from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass, field
from typing import Any

from .config import Settings
from .llm_compat import CompatError, OpenAICompatClient

logger = logging.getLogger("hayat.turn_analyzer")

INTENTS = {
    "answering", "question", "mixed", "wants_human", "emotional", "smalltalk",
    "declines", "off_topic", "new_request",
    "accepts", "contact_request", "wants_stop", "under_18", "asks_if_human",
    "clinical_detail", "asks_interpretation", "how_it_works", "contact_channel",
    "what_is_trawellcare",
}
CATEGORIES = {"medical_treatment", "wellness"}
ALLOWED_FACTS = (
    "procedure_or_service",
    "wellness_programme_or_goal",
    "destination_preference",
    "preferred_timing",
    "budget_range",
    "travellers_count",
    "accommodation_preference",
    "current_country",
    "medical_reports_available",
    "name",
    "callback_time",
    "preferred_name",
    "preferred_programme",
    "trip_duration",
    "wellness_goal",
    "preferred_provider",
)

_SYSTEM = (
    "You read ONE visitor message from a medical travel and wellness enquiry chat and "
    "reply with JSON only, no prose.\n"
    'Schema: {"intent": str, "category": str|null, "facts": object, "note": str|null}\n'
    "intent is exactly one of:\n"
    "answering = gives details or answers the assistant's last question, asks nothing real;\n"
    "question = asks something (about the company, process, cost, safety, services, "
    "programmes, booking, what happens next) and gives no new details;\n"
    "mixed = gives details AND asks something;\n"
    "wants_human = asks to speak to a person or coordinator;\n"
    "emotional = mainly shares a worry or feeling;\n"
    "smalltalk = greeting, thanks or chit chat;\n"
    "declines = refuses or skips the assistant's last question;\n"
    "off_topic = about anything NOT about Trawellcare and its medical travel and wellness "
    "services: general knowledge, maths, poems, jokes, news, politics, weather, tourism or "
    "restaurant tips, other companies, coding, personal advice;\n"
    "new_request = asks for an additional or different Trawellcare service than the one "
    "being discussed (for example for another person, or a second treatment or retreat);\n"
    "if the visitor changes a detail they gave earlier (a new destination, date, budget), "
    "that is answering or mixed and the new value goes in facts.\n"
    "accepts = says yes or agrees to what the assistant just offered or suggested;\n"
    "contact_request = offers or gives a phone number or email, or asks to be contacted "
    "on WhatsApp, phone or email;\n"
    "wants_stop = asks to stop being messaged, or asks to be forgotten or deleted;\n"
    "under_18 = says they are under 18 or a child;\n"
    "asks_if_human = asks whether the assistant is a person or a bot;\n"
    "clinical_detail = volunteers a diagnosis, symptoms, medication, test results or medical "
    "history (do not copy any of it into facts);\n"
    "asks_interpretation = asks the assistant to read a report or explain what a symptom means;\n"
    "what_is_trawellcare = asks what trawellcare is, what it does, who it is, or what services "
    "it offers overall;\n"
    "how_it_works = asks how the process works, how to book, or what happens after registering "
    "(not a narrow question about one detail);\n"
    "contact_channel = asks to be contacted on WhatsApp or by phone.\n"
    "HAYAT-100, Zoé (formerly called AAfiya) and FFounders are trawellcare's "
    "signature wellness programmes: a message naming or asking about one of "
    "them is a question about the company, never off_topic.\n"
    "preferred_name: only when the visitor says what to call them, a first name only. "
    "preferred_programme: the signature programme (HAYAT 100, Zoé, FFounders; Zoé was formerly called AAfiya) they name "
    "or lean toward. trip_duration: approximate length of the trip. wellness_goal: a short "
    "category such as relaxation, fitness, longevity, executive performance or social. "
    "preferred_provider: a hospital or doctor they say they already have. budget_range is a "
    "band, not an exact figure. travellers_count is a number only.\n"
    "note: only for new_request, a short plain summary of the extra request, otherwise null.\n"
    "category is medical_treatment or wellness only when the visitor clearly wants that "
    "kind of help (knee surgery, a hospital, dental work = medical_treatment; a retreat, "
    "fitness, longevity, stress relief programme = wellness), otherwise null.\n"
    "facts: ONLY details the visitor explicitly stated in this message, using these keys: "
    + ", ".join(ALLOWED_FACTS)
    + ". Values are short plain strings. If the message is a short answer, decide which key it "
    "belongs to from what the assistant's last message actually asked; pending_field is only "
    "a hint. A place mentioned "
    "inside a question is NOT a destination preference. Never guess, never infer. Never "
    "include symptoms, diagnoses or medications."
)


@dataclass
class TurnAnalysis:
    intent: str = "answering"
    category: str | None = None
    facts: dict[str, str] = field(default_factory=dict)
    note: str | None = None


class TurnAnalyzer:
    def __init__(self, settings: Settings) -> None:
        from groq import AsyncGroq

        if not settings.groq_api_key:
            raise ValueError("Groq API key is not configured.")
        # No SDK retries or waiting: a limited model is skipped and the next one is tried.
        self._client = AsyncGroq(api_key=settings.groq_api_key.get_secret_value(), max_retries=0)
        self._model = settings.groq_analysis_model
        self._models = [
            self._model, *[m for m in settings.groq_fallback_models if m != self._model]
        ]
        self._timeout = settings.groq_analysis_timeout_seconds
        self._cooldown_until: dict[str, float] = {}
        from .llm import backup_client

        self._backup: OpenAICompatClient | None = backup_client(settings)

    async def analyze(
        self,
        *,
        text: str,
        last_assistant: str,
        pending_field: str | None,
        known: dict[str, Any],
    ) -> TurnAnalysis | None:
        from groq import AuthenticationError, RateLimitError

        payload = {
            "assistant_last_message": last_assistant[:400],
            "pending_field": pending_field,
            "already_known": {k: str(v)[:60] for k, v in known.items()},
            "visitor_message": text[:600],
        }
        messages = [
            {"role": "system", "content": _SYSTEM},
            {"role": "user", "content": json.dumps(payload, ensure_ascii=False)},
        ]
        for model in self._models:
            if self._cooldown_until.get(model, 0) > time.monotonic():
                continue
            extra: dict[str, Any] = {}
            max_tokens = 400
            if model.startswith("openai/gpt-oss"):
                extra["reasoning_effort"] = "low"  # keep hidden reasoning small and fast
                max_tokens = 800
            elif model.startswith("qwen/"):
                extra["reasoning_effort"] = "none"  # no thinking: about 0.2s
            try:
                response = await self._client.chat.completions.create(
                    model=model, messages=messages, temperature=0, max_tokens=max_tokens,
                    response_format={"type": "json_object"}, timeout=self._timeout, **extra,
                )
                return parse_analysis(json.loads(response.choices[0].message.content or "{}"))
            except RateLimitError:
                self._cooldown_until[model] = time.monotonic() + 60
                logger.warning("turn analysis: %s is rate limited, trying the next model", model)
            except AuthenticationError:
                self._cooldown_until[model] = time.monotonic() + 300
                logger.warning("turn analysis: %s rejected the API key, skipping it", model)
            except Exception as exc:  # try the next model; the rule-based path is the last resort
                logger.warning("turn analysis failed on %s: %s", model, type(exc).__name__)
        return await self._analyze_with_backup(payload)

    async def _analyze_with_backup(self, payload: dict[str, Any]) -> TurnAnalysis | None:
        if self._backup is None:
            return None
        try:
            text, _ = await self._backup.chat(
                [
                    {"role": "system", "content": _SYSTEM},
                    {"role": "user", "content": json.dumps(payload, ensure_ascii=False)},
                ],
                max_tokens=700, temperature=0, json_mode=True,
            )
            start, end = text.find("{"), text.rfind("}")
            return parse_analysis(json.loads(text[start : end + 1]))
        except (CompatError, ValueError):
            logger.warning("backup turn analysis unavailable")
            return None


def parse_analysis(data: Any) -> TurnAnalysis | None:
    if not isinstance(data, dict):
        return None
    intent = data.get("intent")
    category = data.get("category")
    note = data.get("note")
    facts_raw = data.get("facts") if isinstance(data.get("facts"), dict) else {}
    facts: dict[str, str] = {}
    for key in ALLOWED_FACTS:
        value = facts_raw.get(key)
        if isinstance(value, (str, int, float)) and not isinstance(value, bool):
            value = str(value).strip()
            if value and value.lower() not in {"null", "none", "unknown", "n/a"}:
                facts[key] = value[:120]
    return TurnAnalysis(
        intent=intent if intent in INTENTS else "answering",
        category=category if category in CATEGORIES else None,
        facts=facts,
        note=(note[:160] if isinstance(note, str) and note.strip() else None),
    )
