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
from dataclasses import dataclass, field
from typing import Any

from .config import Settings

logger = logging.getLogger("hayat.turn_analyzer")

INTENTS = {
    "answering", "question", "mixed", "wants_human", "emotional", "smalltalk",
    "declines", "off_topic", "new_request",
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
        # One quick retry only: a rate limit must fail open fast, never stall the chat turn.
        self._client = AsyncGroq(api_key=settings.groq_api_key.get_secret_value(), max_retries=1)
        self._model = settings.groq_analysis_model
        self._timeout = settings.groq_analysis_timeout_seconds

    async def analyze(
        self,
        *,
        text: str,
        last_assistant: str,
        pending_field: str | None,
        known: dict[str, Any],
    ) -> TurnAnalysis | None:
        payload = {
            "assistant_last_message": last_assistant[:400],
            "pending_field": pending_field,
            "already_known": {k: str(v)[:60] for k, v in known.items()},
            "visitor_message": text[:600],
        }
        extra: dict[str, Any] = {}
        if self._model.startswith("openai/gpt-oss"):
            extra["reasoning_effort"] = "low"  # keep hidden reasoning small and fast
        try:
            response = await self._client.chat.completions.create(
                model=self._model,
                messages=[
                    {"role": "system", "content": _SYSTEM},
                    {"role": "user", "content": json.dumps(payload, ensure_ascii=False)},
                ],
                temperature=0,
                max_tokens=500,
                response_format={"type": "json_object"},
                timeout=self._timeout,
                **extra,
            )
            data = json.loads(response.choices[0].message.content or "{}")
        except Exception as exc:  # fail open: the rule-based path still works
            logger.warning("turn analysis unavailable: %s", type(exc).__name__)
            return None
        return parse_analysis(data)


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
