"""Deterministic next-best-step selection for the short consultation funnel."""

from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Any


@dataclass(frozen=True)
class PlannedStep:
    decision_type: str
    reason: str
    question_goal: str | None = None
    question_text: str | None = None
    target_field: str | None = None
    resume_goal: str | None = None


_CONSULTATION_INTENT = re.compile(
    r"\b(consultation|consult|speak with someone|talk to someone|coordinator|"
    r"arrange|request|book|submit|proceed)\b|استشارة|التحدث مع شخص|منسق|طلب|حجز",
    re.IGNORECASE,
)
_QUESTION_INTENT = re.compile(
    r"\?|^(how|what|when|where|which|can|could|do|does|is|are|why)\b|"
    r"كيف|ما|متى|أين|هل",
    re.IGNORECASE,
)


class QuestionPlanner:
    """Choose at most one concise question while backend code remains authoritative."""

    def __init__(self) -> None:
        self.contact_fields = (
            ("name", "name"),
            ("phone_number", "phone number"),
        )

    def plan(
        self,
        *,
        text: str,
        conversation: Any,
        decision: Any,
        progress: Any,
        visitor: str | None = None,
    ) -> PlannedStep:
        if decision.escalation_required:
            return PlannedStep("escalate", "Safety or policy escalation takes priority.")

        category = self._category(conversation)
        consultation_requested = bool(_CONSULTATION_INTENT.search(text))
        question_requested = bool(_QUESTION_INTENT.search(text))

        # Check if all clinical/wellness details are present
        missing_funnel = self._first_missing(conversation, category, include_contact=False)
        has_contact = (
            self._known(conversation, "phone_number")
            and (self._known(conversation, "name") or self._known(conversation, "contact"))
        )

        # If user asks for a consultation, provided contact details, or is in submission path
        if (
            consultation_requested
            or has_contact
            or conversation.state in {
                "awaiting_verification", "awaiting_consent", "ready_for_submission", "offering_consultation"
            }
        ):
            missing_contact = self._first_missing_contact(conversation)
            if missing_funnel:
                field, label = missing_funnel
                return PlannedStep(
                    "collect_detail",
                    "A required consultation detail is missing.",
                    question_goal=label,
                    question_text=self._question_for(field, category),
                    target_field=field,
                )
            # The website knows who a visitor is, so it never collects contact
            # details in chat: customers have an account, guests are sent to one.
            if visitor == "customer":
                return PlannedStep("account_request_saved", "The signed-in customer's account covers contact.")
            if visitor == "guest":
                return PlannedStep("sign_in_required", "A guest needs an account to take this further.")
            if missing_contact:
                field, label = missing_contact
                return PlannedStep(
                    "collect_detail",
                    "Contact details are required for the consultation request.",
                    question_goal=label,
                    question_text=self._question_for(field, category),
                    target_field=field,
                )
            if not progress.phone_verified:
                return PlannedStep(
                    "verify_phone",
                    "Required details are present but the phone number is not server-verified.",
                    question_goal="phone verification",
                    question_text=(
                        "Your details are ready. Please verify your phone number so I "
                        "can prepare the consultation request."
                    ),
                    target_field="phone_number",
                )
            if not progress.consent_granted:
                return PlannedStep(
                    "request_consent",
                    "Consultation-processing consent is required.",
                    question_goal="consultation-processing consent",
                    question_text=(
                        "May I record your details and send this consultation request "
                        "to our human coordinator?"
                    ),
                    target_field="consultation_processing_consent",
                )
            return PlannedStep(
                "submit_consultation",
                "All backend gates are satisfied; explicit submission is next.",
                question_goal="consultation submission",
                question_text="Would you like me to submit this consultation request?",
                target_field="submit_consultation",
            )

        # In standard journey discovery
        if category == "medical_treatment":
            if missing_funnel:
                field, label = missing_funnel
                return PlannedStep(
                    "collect_detail",
                    "Medical treatment journey has a missing detail.",
                    question_goal=label,
                    question_text=self._question_for(field, category),
                    target_field=field,
                )
        elif category == "wellness":
            if missing_funnel:
                field, label = missing_funnel
                return PlannedStep(
                    "collect_detail",
                    "Wellness journey has a missing detail.",
                    question_goal=label,
                    question_text=self._question_for(field, category),
                    target_field=field,
                )
        elif self._has_ambiguous_category(text):
            return PlannedStep(
                "clarify_category",
                "The customer has not selected a journey.",
                question_goal="customer category",
                question_text=(
                    "Would you like help with a medical treatment or a wellness programme?"
                ),
                target_field="customer_category",
            )
        elif question_requested:
            return PlannedStep(
                "answer",
                "Answer the direct question before asking the customer to choose a journey.",
            )

        if category:
            # Funnel details are complete, invite consultation
            return PlannedStep(
                "offer_consultation",
                "The journey details are collected and consultation support is available.",
                question_goal="consultation support",
                question_text=(
                    "Would you like to request a consultation with a coordinator using these details?"
                ),
                target_field="request_consultation",
            )

        return PlannedStep("answer", "No journey or consultation commitment was identified.")

    def _first_missing(
        self, conversation: Any, category: str | None, *, include_contact: bool
    ) -> tuple[str, str] | None:
        fields: list[tuple[str, str]] = []
        if category == "medical_treatment":
            fields.extend([
                ("procedure_or_service", "treatment or specialty"),
                ("destination_preference", "destination preference"),
                ("preferred_timing", "preferred timeframe"),
            ])
        elif category == "wellness":
            fields.extend([
                ("wellness_programme_or_goal", "wellness programme or goal"),
                ("destination_preference", "destination preference"),
                ("preferred_timing", "preferred timeframe"),
            ])
        if include_contact:
            fields.extend(self.contact_fields)
        for field, label in fields:
            if not self._known(conversation, field):
                return field, label
        return None

    def _first_missing_contact(self, conversation: Any) -> tuple[str, str] | None:
        for field, label in self.contact_fields:
            if not self._known(conversation, field):
                return field, label
        return None

    @staticmethod
    def _category(conversation: Any) -> str | None:
        value = conversation.case_facts.get("customer_category")
        if value in {"medical_treatment", "wellness"}:
            return value
        care_category = conversation.case_facts.get("care_category")
        if care_category == "wellness":
            return "wellness"
        if care_category in {"medical", "cardiology", "orthopedic", "dental", "dermatology", "oncology"}:
            return "medical_treatment"
        return None

    @staticmethod
    def _known(conversation: Any, field: str) -> bool:
        facts = getattr(conversation, "case_facts", {})
        value = facts.get(field)
        if value not in (None, ""):
            return True
        # Check alias fields: preferred_dates_times satisfies preferred_timing and vice versa
        if field == "preferred_timing" and facts.get("preferred_dates_times") not in (None, ""):
            return True
        if field == "preferred_dates_times" and facts.get("preferred_timing") not in (None, ""):
            return True
        # Check nested sections
        for section in facts.values():
            if isinstance(section, dict):
                if section.get(field) not in (None, ""):
                    return True
                if field == "preferred_timing" and section.get("preferred_dates_times") not in (None, ""):
                    return True
                if field == "preferred_dates_times" and section.get("preferred_timing") not in (None, ""):
                    return True
        return False

    @staticmethod
    def _has_ambiguous_category(text: str) -> bool:
        return bool(re.search(r"\b(medical|wellness|both|either|not sure|undecided)\b", text, re.I))

    def current_pending_field(self, conversation: Any) -> str | None:
        category = self._category(conversation)
        if not category:
            return "customer_category"
        missing = self._first_missing(conversation, category, include_contact=False)
        return missing[0] if missing else None

    @staticmethod
    def _question_for(field: str, category: str | None) -> str:
        questions = {
            "name": "What name should the coordinator use for your request?",
            "phone_number": "What phone number should the coordinator use to contact you?",
            "procedure_or_service": "What treatment or specialty would you like to explore?",
            "wellness_programme_or_goal": "Which wellness programme or goal interests you?",
            "destination_preference": "Which destination would you prefer, or would you like help exploring available destinations?",
            "preferred_timing": "What timeframe would suit you best?",
        }
        return questions.get(field, "How may I help with your consultation details?")


def enforce_single_question(reply: str) -> str:
    """Ensure the assistant asks at most one question per turn."""
    if not reply:
        return reply

    sentences = re.split(r"(?<=[.!?؟])\s+", reply.strip())
    question_count = 0
    kept: list[str] = []

    for s in sentences:
        if "?" in s or "؟" in s:
            if question_count == 0:
                kept.append(s)
                question_count += 1
            # Discard additional questions to strictly prevent multi-question turns
        else:
            kept.append(s)

    return " ".join(kept)


def append_planned_question(reply: str, plan: PlannedStep) -> str:
    if not plan.question_text or plan.decision_type in {"escalate", "answer"}:
        return enforce_single_question(reply)
    # If the reply already poses a question, avoid asking two questions in a turn
    if "?" in reply or "؟" in reply:
        return enforce_single_question(reply)
    reply_lower = reply.lower()
    semantic_markers = [
        "please let me know", "please confirm", "could you provide", "would you prefer",
        "tell me if", "tell me which", "do you prefer", "are you interested in",
        "يرجى تأكيد", "هل يمكنك", "أخبرني",
    ]
    if any(marker in reply_lower for marker in semantic_markers):
        return enforce_single_question(reply)
    if plan.decision_type == "verify_phone" and ("verify" in reply_lower and "phone" in reply_lower):
        return enforce_single_question(reply)
    if plan.decision_type == "request_consent" and ("consent" in reply_lower or "permission" in reply_lower or "أوافق" in reply or "موافقة" in reply):
        return enforce_single_question(reply)
    if plan.question_text.lower().rstrip("?. ") in reply_lower:
        return enforce_single_question(reply)
    combined = f"{reply.rstrip()} {plan.question_text}"
    return enforce_single_question(combined)
