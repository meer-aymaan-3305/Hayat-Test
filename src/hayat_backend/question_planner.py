"""Deterministic next-best-step selection for the short consultation funnel."""

from __future__ import annotations

from dataclasses import dataclass, replace
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
    clarify_attempts: int = 0
    answer_first: bool = False


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

# First-turn journey hints: distinguish medical travel from general wellness
# (and signature programmes, which are intercepted earlier) so the first
# follow-up question is relevant instead of a generic either/or clarify.
_MEDICAL_HINT_RE = re.compile(
    r"\b(medical|medicine|treatment|procedure|surgery|hospital|doctor|specialist|"
    r"clinic|dental|cardiology|cardiologist|orthop\w+|dermatolog\w+|oncolog\w+|"
    r"medical travel|travell?ing for|travel for)\b|"
    r"سفر\s+طبي|عملية\s+طبية|سفر|علاج|جراحة|مستشفى|طبيب|أسنان|قسطرة|باطنية|تجميل",
    re.IGNORECASE,
)
_WELLNESS_HINT_RE = re.compile(
    r"\b(wellness|wellbeing|well-being|fitness|retreat|programme|program|spa|"
    r"longevity|stress|sleep|meditation|yoga|pilates|detox|healthy ageing|"
    r"healthy aging|wellness programme|wellness experience)\b|"
    r"عافية|لياقة|منتجع|سبا|يوغا|بيلاتس|تأمل|إجهاد|نوم|رياضي",
    re.IGNORECASE,
)
_FOLLOWUP_CONTEXT_RE = re.compile(
    r"\b(second|third|another|also|what about|and then|instead|other option|"
    r"the other)\b|ثان|أيضاً|ماذا عن|بدلاً من|الخيار الآخر",
    re.IGNORECASE,
)
_AMBIGUOUS_HINT_RE = re.compile(
    r"\b(both|either|not sure|unsure|undecided|don't know|do not know|"
    r"help me decide|not certain)\b|"
    r"غير\s+متأكد|لست\s+متأكد|كلاهما|أي\s+منهما|لا\s+أعرف|لا\s+ادري|ساعدني\s+أقرر|"
    r"(طبية|علاج|جراحة).{0,40}(عافية|لياقة)|(عافية|لياقة).{0,40}(طبية|علاج|جراحة)",
    re.IGNORECASE,
)
# Category-clarification ladder. The same either/or question must never be
# repeated: the first vague turn gets the category choice, the next gets an
# open-ended prompt, and repeated failure offers a human coordinator.
CLARIFY_CATEGORY_Q = (
    "Would you like help with a medical treatment or a wellness programme?"
)
CLARIFY_OPEN_Q = (
    "Could you tell me a little more about what you're looking for? "
    "It doesn't have to be medical treatment or wellness — just describe "
    "it in your own words."
)
CLARIFY_COORDINATOR_Q = (
    "I want to make sure you get the right help — would you like me to "
    "connect you with a TrawellCare coordinator? They can help with "
    "bookings, existing enquiries, travel arrangements, or anything else."
)
# Substrings that identify each ladder rung inside stored assistant replies
# (English canonical text and the Arabic translations appended by ChatService).
_CLARIFY_MARKERS = (
    "medical treatment or a wellness programme",
    "what you're looking for",
    "connect you with a TrawellCare coordinator",
    "علاج طبي أم في برنامج عافية",
    "تبحث عنه",
    "منسق من ترافيل كير",
)
# Explicit out-of-category phrasing skips straight to the open question.
_OPEN_CATEGORY_RE = re.compile(
    r"\b(something else|anything else|something different|something unrelated|"
    r"not related to|other (?:things?|stuff|matters)|help me with something)\b|"
    r"شيء آخر|غير ذلك|شيء مختلف|مساعدة في شيء",
    re.IGNORECASE,
)

_INTENT_DECLARATION_RE = re.compile(
    r"\b(interested|interest|looking for|want|need|exploring|seeking|would like|"
    r"i'?m interested|i am interested)\b|"
    r"أهتم|مهتم|أبحث|أريد|أستكشف|أسعى|أرغب|أحتاج|"
    r"عايز|أبغى|ابغى|بدّي|محتاج|محتاجة|ودي|وديّة",
    re.IGNORECASE,
)


def wants_open_category(text: str) -> bool:
    """True when the visitor explicitly asks for something outside the
    medical-treatment/wellness categories."""
    return bool(_OPEN_CATEGORY_RE.search(text))


def clarify_attempts(conversation: Any) -> int:
    """How many category-clarification questions this conversation already asked."""
    return sum(
        1
        for m in getattr(conversation, "messages", [])
        if m.role == "assistant"
        and any(marker in m.content for marker in _CLARIFY_MARKERS)
    )


class QuestionPlanner:
    """Choose at most one concise question while backend code remains authoritative."""

    # Extra intake questions asked, one at a time, when extended intake is on.
    EXTENDED_MEDICAL = (
        ("condition_context_for_advisor", "existing diagnosis"),
        ("budget_range", "budget"),
        ("travellers_count", "number of travellers"),
        ("medical_reports_available", "medical reports"),
        ("current_country", "country of residence"),
    )
    EXTENDED_WELLNESS = (
        ("budget_range", "budget"),
        ("travellers_count", "number of travellers"),
        ("accommodation_preference", "accommodation preference"),
    )
    # Asked after the number is verified; skippable.
    OPTIONAL_CONTACT = (
        ("email", "email"),
        ("callback_time", "callback time"),
    )

    def __init__(self, extended: bool = False, collect_diagnosis: bool = False) -> None:
        self.extended = extended
        self.collect_diagnosis = collect_diagnosis
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
        intent: str | None = None,
        submitted: bool = False,
    ) -> PlannedStep:
        """Pick the next step. When the visitor asked or shared something rather than
        simply answering, the step is flagged answer_first so the reply deals with that
        before (and only if natural) returning to the planned question."""
        if self.extended and submitted and not decision.escalation_required:
            # The enquiry is already with the team. Nothing is left to collect or submit,
            # so never loop on "shall I submit?": just help with whatever they need.
            return PlannedStep(
                "post_submission",
                "The enquiry was submitted; help with changes, questions or new requests.",
            )
        step = self._plan_core(
            text=text, conversation=conversation, decision=decision,
            progress=progress, visitor=visitor, intent=intent,
        )
        if (
            self.extended
            and intent in {"question", "mixed", "emotional", "smalltalk", "off_topic", "new_request"}
            and step.decision_type not in {"escalate"}
        ):
            return replace(step, answer_first=True)
        return step

    def _plan_core(
        self,
        *,
        text: str,
        conversation: Any,
        decision: Any,
        progress: Any,
        visitor: str | None = None,
        intent: str | None = None,
    ) -> PlannedStep:
        if decision.escalation_required:
            return PlannedStep("escalate", "Safety or policy escalation takes priority.")

        category = self._category(conversation)
        consultation_requested = bool(_CONSULTATION_INTENT.search(text))
        question_requested = bool(_QUESTION_INTENT.search(text))
        wants_human = self.extended and intent == "wants_human"
        if self.extended and intent is not None:
            # The model's reading of the turn beats keyword guessing.
            consultation_requested = wants_human
            question_requested = intent in {"question", "mixed", "off_topic"}
        _msgs = getattr(conversation, "messages", [])
        user_turns = sum(1 for m in _msgs if m.role == "user")

        # Check if all clinical/wellness details are present
        missing_funnel = self._first_missing(conversation, category, include_contact=False)
        if wants_human:
            missing_funnel = None  # they want a person now: go straight to contact
        has_contact = (
            self._known(conversation, "phone_number")
            and (self._known(conversation, "name") or self._known(conversation, "contact"))
        )

        # If user asks for a consultation, provided contact details, or is in submission path
        if (
            consultation_requested
            or (self.extended and category and not missing_funnel)
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
            if self.extended:
                for field, label in self.OPTIONAL_CONTACT:
                    if not self._known(conversation, field):
                        return PlannedStep(
                            "collect_detail",
                            "Optional contact detail for the coordinator.",
                            question_goal=label,
                            question_text=self._question_for(field, category),
                            target_field=field,
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
        elif (
            self.extended
            or self._has_ambiguous_category(text)
            or _AMBIGUOUS_HINT_RE.search(text)
            or (
                self._journey_hint(text)
                and user_turns <= 1
                and not _FOLLOWUP_CONTEXT_RE.search(text)
                and (_INTENT_DECLARATION_RE.search(text) or not question_requested)
            )
        ):
            # Journey hints apply to first-turn intent declarations only;
            # follow-up/contextual phrasing and pure informational questions
            # keep the generic clarify/answer behaviour.
            hint = (
                self._journey_hint(text)
                if user_turns <= 1 and not _FOLLOWUP_CONTEXT_RE.search(text)
                else None
            )
            if hint == "medical_treatment":
                field, label = ("procedure_or_service", "treatment or specialty")
                return PlannedStep(
                    "collect_detail",
                    "Visitor signalled medical travel; collect the treatment detail first.",
                    question_goal=label,
                    question_text=self._question_for(field, "medical_treatment"),
                    target_field=field,
                )
            if hint == "wellness":
                field, label = ("wellness_programme_or_goal", "wellness programme or goal")
                return PlannedStep(
                    "collect_detail",
                    "Visitor signalled general wellness; collect the wellness goal first.",
                    question_goal=label,
                    question_text=self._question_for(field, "wellness"),
                    target_field=field,
                )
            attempts, question = self._category_question(text, conversation)
            return PlannedStep(
                "clarify_category",
                "The customer has not selected a journey.",
                question_goal="customer category",
                question_text=question,
                target_field="customer_category",
                clarify_attempts=attempts,
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
        if self.extended and category == "medical_treatment":
            fields.extend(
                f for f in self.EXTENDED_MEDICAL
                if self.collect_diagnosis or f[0] != "condition_context_for_advisor"
            )
        elif self.extended and category == "wellness":
            fields.extend(self.EXTENDED_WELLNESS)
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

    def _category_question(self, text: str, conversation: Any) -> tuple[int, str | None]:
        attempts = clarify_attempts(conversation)
        if wants_open_category(text):
            attempts = max(attempts, 1)
        if attempts <= 0:
            return 0, CLARIFY_CATEGORY_Q
        if attempts == 1:
            return attempts, CLARIFY_OPEN_Q
        if attempts == 2:
            return attempts, CLARIFY_COORDINATOR_Q
        # Ladder exhausted: no further question — ChatService falls back to a
        # capability summary so the same prompt is never repeated.
        return attempts, None

    @staticmethod
    def _category(conversation: Any) -> str | None:
        value = conversation.case_facts.get("customer_category")
        if isinstance(value, dict):
            value = value.get("value") or value.get("canonical") or next(
                (v for v in value.values() if isinstance(v, str)), None)
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

    @staticmethod
    def _journey_hint(text: str) -> str | None:
        """Classify a first-turn message into a journey hint.

        Returns 'medical_treatment', 'wellness', or None when the intent is
        genuinely ambiguous (both signals present or neither)."""
        medical = bool(_MEDICAL_HINT_RE.search(text))
        wellness = bool(_WELLNESS_HINT_RE.search(text))
        if medical and not wellness:
            return "medical_treatment"
        if wellness and not medical:
            return "wellness"
        return None

    def current_pending_field(self, conversation: Any) -> str | None:
        category = self._category(conversation)
        if self.extended:
            last = next(
                (m.content for m in reversed(getattr(conversation, "messages", []))
                 if m.role == "assistant"),
                "",
            )
            if not self._known(conversation, "name") and re.search(
                r"(?:know your name|your name\?|what name|اسمك)", last, re.I
            ):
                return "name"
        if not category:
            return "customer_category"
        missing = self._first_missing(conversation, category, include_contact=False)
        if missing:
            return missing[0]
        if self.extended:
            nxt = self._first_missing_contact(conversation)
            if nxt:
                return nxt[0]
            for field, _ in self.OPTIONAL_CONTACT:
                if not self._known(conversation, field):
                    return field
        return None

    @staticmethod
    def _question_for(field: str, category: str | None) -> str:
        questions = {
            "name": "What name should the coordinator use for your request?",
            "phone_number": "What phone number should the coordinator use to contact you?",
            "procedure_or_service": "What treatment or specialty would you like to explore?",
            "wellness_programme_or_goal": "Which wellness programme or goal interests you?",
            "destination_preference": "Which destination would you prefer, or would you like help exploring available destinations?",
            "preferred_timing": "What timeframe would suit you best?",
            "budget_range": "Do you have a rough budget in mind? A range is perfectly fine 😊",
            "travellers_count": "Will you be travelling on your own, or is anyone joining you?",
            "accommodation_preference": "Do you have any preferences for where you would like to stay?",
            "condition_context_for_advisor": "If you are comfortable sharing, is there an existing diagnosis our Medical Advisor should know about?",
            "medical_reports_available": "Do you have any medical reports or records handy?",
            "current_country": "Which country are you based in at the moment?",
            "email": "Would you like to share an email address too? You can skip this if you prefer.",
            "callback_time": "When would be a good time for our coordinator to reach you?",
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
