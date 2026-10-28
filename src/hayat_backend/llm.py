"""Provider adapter with a deterministic offline implementation for tests."""

from __future__ import annotations

from dataclasses import dataclass
import re
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
        system_content = next(
            (message["content"] for message in messages if message["role"] == "system"),
            "",
        )

        user_lower = user_text.lower()

        # Handle destination comparison questions
        if "compare" in user_lower or "destination" in user_lower or "مقارن" in user_text or "وجه" in user_text:
            if is_arabic:
                return (
                    "تتميز الهند بمستشفيات معتمدة دولياً وتكلفة اقتصادية في جراحة القلب والعظام. "
                    "وتقدم سلطنة عمان والإمارات مرافق متطورة في برامج العافية والفحوصات، بينما تشتهر تايلاند بالسياحة العلاجية المتكاملة."
                )
            return (
                "India offers world-class tertiary care with significant cost advantages for cardiology and orthopedics. "
                "Oman and the UAE provide advanced facilities for specialized wellness and preventive care, while Thailand is renowned for holistic wellness retreats."
            )

        # Handle document preparation questions
        if "prepare" in user_lower or "document" in user_lower or "information" in user_lower or "تجهيز" in user_text or "مستند" in user_text:
            if is_arabic:
                return (
                    "للاستعداد للاستشارة، يرجى تجهيز التقارير الطبية الحديثة، ونتائج الفحوصات وصور الأشعة، "
                    "وقائمة الأدوية الحالية، ونسخة من جواز السفر. وبالنسبة لبرامج العافية، يرجى تجهيز أهدافك الصحية وتاريخك الصحي العام."
                )
            return (
                "To prepare for your consultation, please gather your recent medical records, formal diagnostic reports, "
                "imaging files (MRI/CT scans), current medication list, and passport copy. For wellness programmes, prepare your primary wellness goals and health history."
            )

        # Handle wellness goals (mental health, stress, sleep, etc.)
        if any(term in user_lower for term in ["stress", "mental health", "sleep", "longevity", "wellness", "توتر", "نفسية", "عافية"]):
            goal = "mental health and stress management" if "stress" in user_lower or "mental" in user_lower else "wellness"
            if is_arabic:
                return f"ممتاز — سأساعدك في استكشاف برامج العافية المتخصصة في {goal}."
            return f"Understood — you are looking to explore programmes for {goal}."

        # Handle short contextual affirmative/negative/neutral answers
        if user_lower in {"yes", "yeah", "yep", "sure", "ok", "okay", "either is fine", "any city is fine", "no preference", "نعم", "موافق", "تمام", "أجل"}:
            if is_arabic:
                return "شكراً لتأكيدك ومشاركتك التفاصيل."
            return "Thank you for confirming your preferences."

        # Acknowledge selected specialty if known in case facts or prompt
        match = re.search(r"'(?:procedure_or_service|care_category)':\s*'([^']+)'", system_content)
        if match and match.group(1).lower() not in {"medical", "wellness", "none"}:
            specialty = match.group(1).lower()
            if is_arabic:
                return f"مفهوم — أنت مهتم بخدمات {specialty}."
            return f"Understood — you're interested in {specialty} treatment."

        # Direct specialty in user text
        for spec in ["cardiology", "orthopedics", "dermatology", "oncology", "neurology", "dentistry"]:
            if spec in user_lower:
                if is_arabic:
                    return f"مفهوم — أنت مهتم بخدمات {spec}."
                return f"Understood — you're interested in {spec} treatment."

        # Check if structured context indicates details are already known
        if "procedure_or_service" in system_content or "cardiology" in system_content.lower():
            if is_arabic:
                return "مفهوم — لقد تم تسجيل تفاصيل طلبك لدى منسق حياة."
            return "Understood — your intake details have been recorded for the Hayat coordinator."

        return (
            "I can help you explore approved travel and wellness coordination services. "
            "Please share your preferred service, destination, and timing; a coordinator "
            "can confirm the details."
            if not is_arabic
            else (
                "يمكنني مساعدتك في استكشاف خدمات السفر الطبي والعافية المعتمدة. "
                "يرجى مشاركة الخدمة والوجهة والوقت المفضل، وسيؤكد المنسق التفاصيل."
            )
        )


class GroqChatModel:
    """Thin async Groq adapter; imported only when a key is configured."""

    def __init__(self, settings: Settings) -> None:
        from groq import AsyncGroq

        if not settings.groq_api_key:
            raise LLMError("Groq API key is not configured.")
        self._client = AsyncGroq(api_key=settings.groq_api_key.get_secret_value())
        self._model = settings.groq_model

    async def complete(self, messages: list[dict[str, str]]) -> str:
        from groq import APIError

        try:
            response = await self._client.chat.completions.create(
                model=self._model,
                messages=messages,
                temperature=0.2,
                max_tokens=400,
                timeout=20,
            )
        except (APIError, TimeoutError) as exc:
            raise LLMError("Configured language model request failed.") from exc
        content = response.choices[0].message.content
        if not content:
            raise LLMError("Groq returned an empty response.")
        return content


def create_chat_model(settings: Settings) -> ChatModel:
    return GroqChatModel(settings) if "GROQ_API_KEY" not in settings.missing_integrations else OfflineChatModel()
