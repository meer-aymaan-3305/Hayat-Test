"""Deterministic safety checks used before and after model calls.

Authoritative specification: HAYAT_Guardrail_Document_v1.docx — Version 1.0.
"""

from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Any
from uuid import UUID, uuid4

from .policy_engine import (
    CP1_OPENING_AR,
    CP1_OPENING_EN,
    EF_SCRIPTS_AR,
    EF_SCRIPTS_EN,
    PolicyDecision,
    global_policy_engine,
)

POLICY_VERSION = "HAYAT_Guardrails_v1.0"


@dataclass(frozen=True)
class GuardrailDecision:
    blocked: bool = False
    escalation_required: bool = False
    reason: str | None = None
    reply: str | None = None


_EMERGENCY = re.compile(
    r"\b(chest pain|can't breathe|cannot breathe|severe bleeding|unconscious|"
    r"stroke|heart attack|difficulty breathing|suicidal|overdose|acute pain)\b|"
    r"(ألم شديد في الصدر|لا أستطيع التنفس|نزيف شديد|فاقد الوعي|سكتة دماغية|أفكار انتحارية)",
    re.IGNORECASE,
)
_DIAGNOSIS = re.compile(
    r"\b(diagnose|diagnosis|what disease do i have|prescribe|prescription|dosage|"
    r"should i take (?:aspirin|ibuprofen|antibiotic|medication|medicine)|"
    r"interpret my (?:scan|report|mri|x-ray|blood test)|is this serious|could this be cancer)\b|"
    r"(شخّص|تشخيص حالتي|ما هو مرضي|وصفة طبية|جرعة الدواء|فسر تحليلي|فسر الأشعة|هل هذا خطير|هل هذا سرطان)",
    re.IGNORECASE,
)
_COMMERCIAL_GUARANTEES = re.compile(
    r"\b(guaranteed outcome|exact price|promise a cure|guarantee a cure|"
    r"guaranteed visa|visa approval guaranteed|guarantee (?:visa|price|cure))\b|"
    r"(سعر مضمون|ضمان النتيجة|ضمان الشفاء|تأشيرة مضمونة|علاج مضمون)",
    re.IGNORECASE,
)
_INJECTION = re.compile(
    r"(ignore (?:all\s+previous|all|previous|the) instructions|reveal (?:the\s+|your\s+)?system prompt|"
    r"show your hidden prompt|developer message|pretend you are|system instructions|"
    r"jailbreak|override system|disregard instructions)",
    re.IGNORECASE,
)
_UNRELATED = re.compile(
    r"\b(recipe|bake|cake|cookies|chocolate cake|football|premier league|champions league|"
    r"crypto|bitcoin|ethereum|solana|python code|programming|weather|stock market|car repair)\b|"
    r"(كعكة|كيك|وصفة طعام|كرة قدم|كريبتو|بيتكوين|برمجة)",
    re.IGNORECASE,
)
_IN_SCOPE = re.compile(
    r"\b(hayat|trawellcare|medical|treatments?|abroad|dental|aesthetic|wellness|longevity|preventive|"
    r"recovery|travel|india|oman|uae|dubai|turkey|thailand|germany|uk|london|singapore|"
    r"destination|destinations|compare|comparison|clinic|hospital|consultation|coordinator|"
    r"service|services|visa|visas|budget|companion|booking|appointment|care|doctor|physician|"
    r"patient|prepare|preparation|documents|records|passport|information|pricing|cost|"
    r"timing|timeframe|schedule|step|process|help|guidance|mental health|stress|sleep)\b|"
    r"(حياة|ترافيل كير|طبي|علاج|أسنان|تجميل|عافية|رفاهية|وقاية|تعافي|سفر|الهند|عمان|الإمارات|دبي|"
    r"تركيا|تايلاند|ألمانيا|بريطانيا|وجهة|وجهات|مقارنة|عيادة|مستشفى|استشارة|منسق|خدمة|"
    r"خدمات|تأشيرة|ميزانية|موعد|حجز|طبيب|مريض|تجهيز|مستندات|تقارير|أوراق|معلومات|تكلفة|"
    r"وقت|خطوات|مساعدة|توتر|نوم|صحة)",
    re.IGNORECASE,
)
_MEDICAL_SPECIALTIES = re.compile(
    r"\b[a-z]{3,}(?:ology|iatry|ics|surgery|therapy|scopy|plasty)\b|"
    r"\b(cardio|cardiology|cardiac|heart|orthopedic|orthopedics|orthopaedics|bone|joint|spine|knee|hip|"
    r"dermatology|dermatologist|skin|oncology|oncologist|cancer|tumor|chemotherapy|"
    r"neurology|neurologist|brain|neurosurgery|ophthalmology|eye|eyes|lasik|cataract|cornea|"
    r"dental|dentistry|teeth|implant|implants|endodontic|periodontic|orthodontic|"
    r"gastroenterology|digestive|stomach|liver|endoscopy|colonoscopy|"
    r"ent|otolaryngology|ear|ears|hearing|sinus|pulmonology|respiratory|lung|lungs|asthma|"
    r"nephrology|kidney|kidneys|dialysis|urology|prostate|bladder|"
    r"endocrinology|diabetes|thyroid|hormone|rheumatology|arthritis|"
    r"hematology|blood|anemia|gynecology|obstetrics|maternity|fertility|ivf|"
    r"pediatrics|pediatric|geriatrics|allergy|immunology|"
    r"bariatric|gastric|weight loss|cosmetic|plastic surgery|hair transplant|"
    r"transplant|rehabilitation|physiotherapy|checkup|screening)\b|"
    r"(قلب|عظام|جلدية|جلد|أورام|سرطان|أعصاب|مخ|عيون|باطنة|مسالك|أذن|أنف|حنجرة|"
    r"رئة|تنفس|صدر|كلى|غسيل كلى|مسالك بولية|بروستاتا|نساء|ولادة|عقم|أطفال|سكري|"
    r"غدد|روماتيزم|مفاصل|عمود فقري|ركبة|زراعة|سمنة|شعر|تأهيل)",
    re.IGNORECASE,
)
_WELLNESS_GOALS = re.compile(
    r"\b(mental health|stress|stress management|better sleep|sleep improvement|healthy ageing|"
    r"healthy aging|longevity|detox|detoxification|burnout|mindfulness|rejuvenation|vitality|"
    r"weight management|holistic health|preventive checkup|recovery)\b|"
    r"(صحة نفسية|إدارة التوتر|علاج التوتر|تحسين النوم|الشيخوخة الصحية|طول العمر|ديتوكس|استرخاء|عافية)",
    re.IGNORECASE,
)
_DESTINATIONS = re.compile(
    r"\b(india|oman|uae|united arab emirates|dubai|turkey|thailand|germany|uk|london|singapore|malaysia|spain|switzerland)\b|"
    r"(الهند|عمان|الإمارات|دبي|تركيا|تايلاند|ألمانيا|بريطانيا|لندن|سنغافورة|ماليزيا)",
    re.IGNORECASE,
)
_TIMINGS = re.compile(
    r"\b(january|february|march|april|may|june|july|august|september|october|november|december|"
    r"month|months|week|weeks|year|soon|immediate|asap|urgent|next|spring|summer|autumn|fall|winter|"
    r"afternoon|morning|weekday|weekend)\b|"
    r"(يناير|فبراير|مارس|أبريل|مايو|يونيو|يوليو|أغسطس|سبتمبر|أكتوبر|نوفمبر|ديسمبر|شهر|أسبوع|قريبا|عاجل|المقبل|صباح|مساء)",
    re.IGNORECASE,
)
_GREETING = re.compile(
    r"^\s*(hi|hello|hey|good morning|good afternoon|good evening|مرحبا|مرحباً|أهلاً|السلام عليكم|صباح الخير|مساء الخير)\b",
    re.IGNORECASE,
)
_PROCEDURAL_QUESTIONS = re.compile(
    r"\b(what information|what should i prepare|what documents|how does this work|how does the process work|"
    r"compare destinations|help me compare|recommend a destination|which destination|what are the options|"
    r"how do i request|how do i book|what are the next steps|can you explain)\b|"
    r"(ما المعلومات|ماذا أحتاج|ما الوثائق|كيف تعمل|مقارنة الوجهات|ما الخيارات|ما هي الخطوات)",
    re.IGNORECASE,
)
_SHORT_CONTEXTUAL_ANSWERS = re.compile(
    r"^\s*(yes|yeah|yep|sure|ok|okay|certainly|no|nope|neither|either(?: is fine)?|"
    r"any(?: city| option)?(?: is fine)?|both(?: are fine)?|no preference|"
    r"i don't have a preference|please suggest(?: one)?|suggest(?: one)?|recommend one|"
    r"the first(?: one)?|the second(?: one)?|flexible|none|n/a)\b|"
    r"^\s*(نعم|أجل|بالتأكيد|تمام|موافق|حسناً|حسنا|لا|كلا|أي منهما|لا مانع|لا تفضيل|الخيار الأول|اقترح لي)\b",
    re.IGNORECASE,
)


def inspect_input(
    text: str,
    conversation: Any = None,
    pending_field: str | None = None,
    extracted_facts: list[Any] | None = None,
    language: str = "en",
    allow_clinical_context: bool = False,
) -> GuardrailDecision:
    """Return a deterministic policy decision for user text grounded in the governing specification."""
    session_id = getattr(conversation, "session_id", uuid4())
    conversation_id = getattr(conversation, "id", uuid4())
    is_locked_emergency = bool(getattr(conversation, "emergency_locked", False))
    is_locked_crisis = bool(getattr(conversation, "crisis_locked", False))

    # Evaluate against the centralized deterministic policy engine
    decision: PolicyDecision = global_policy_engine.evaluate_inbound(
        text,
        session_id=session_id,
        conversation_id=conversation_id,
        current_step="planning your care or travel",
        language=language,
        is_locked_emergency=is_locked_emergency,
        is_locked_crisis=is_locked_crisis,
        allow_clinical_context=allow_clinical_context,
    )

    if decision.blocked:
        # If policy engine blocked the request (EF-1, EF-2, EF-3, EF-4, EF-5, EF-6, EF-9, EF-10, EF-11)
        reason_map = {
            "EF-9": "possible_emergency",
            "EF-10": "crisis_self_harm",
            "EF-5": "prompt_injection",
            "EF-6": "credential_payment_pasted",
            "EF-1": "medical_advice",
            "EF-3": "provider_recommendation",
            "EF-2": "unsolicited_clinical_detail",
            "EF-4": "out_of_scope",
            "EF-11": "abusive_input",
        }
        reason = reason_map.get(decision.rule_id or "", decision.rule_id or "policy_violation")
        return GuardrailDecision(
            blocked=True,
            escalation_required=decision.escalation_required,
            reason=reason,
            reply=decision.reply,
        )

    # Contextual in-scope validation for continuing conversational turns
    has_valid_in_scope = bool(
        extracted_facts
        or _MEDICAL_SPECIALTIES.search(text)
        or _WELLNESS_GOALS.search(text)
        or _DESTINATIONS.search(text)
        or _TIMINGS.search(text)
        or _IN_SCOPE.search(text)
        or _PROCEDURAL_QUESTIONS.search(text)
        or _SHORT_CONTEXTUAL_ANSWERS.search(text)
    )

    if _UNRELATED.search(text) and not has_valid_in_scope:
        scripts = EF_SCRIPTS_AR if language == "ar" else EF_SCRIPTS_EN
        return GuardrailDecision(
            blocked=True,
            reason="out_of_scope",
            reply=scripts["EF-4"].format(step="planning your care or travel"),
        )

    if _SHORT_CONTEXTUAL_ANSWERS.search(text):
        return GuardrailDecision()

    if extracted_facts:
        return GuardrailDecision()

    if _PROCEDURAL_QUESTIONS.search(text):
        return GuardrailDecision()

    if (
        _IN_SCOPE.search(text)
        or _MEDICAL_SPECIALTIES.search(text)
        or _WELLNESS_GOALS.search(text)
        or _DESTINATIONS.search(text)
        or _TIMINGS.search(text)
        or _GREETING.search(text)
    ):
        return GuardrailDecision()

    # Active journey context: If user is already in a conversation with prior messages or established category
    if conversation is not None:
        has_prior_messages = any(
            getattr(m, "role", None) == "assistant" for m in getattr(conversation, "messages", [])
        )
        facts = getattr(conversation, "case_facts", {})
        category = None
        if isinstance(facts, dict):
            category = facts.get("customer_category") or facts.get("care_category")
            if not category and isinstance(facts.get("needs"), dict):
                category = facts["needs"].get("customer_category") or facts["needs"].get("care_category")

        if category in {"medical_treatment", "wellness", "medical", "cardiology", "orthopedic"} or has_prior_messages:
            if _UNRELATED.search(text) and not has_valid_in_scope:
                scripts = EF_SCRIPTS_AR if language == "ar" else EF_SCRIPTS_EN
                return GuardrailDecision(
                    blocked=True,
                    reason="out_of_scope",
                    reply=scripts["EF-4"].format(step="planning your care or travel"),
                )
            if pending_field:
                return GuardrailDecision()
            if "?" in text or "؟" in text or len(text.split()) < 15:
                return GuardrailDecision()

    scripts = EF_SCRIPTS_AR if language == "ar" else EF_SCRIPTS_EN
    return GuardrailDecision(
        blocked=True,
        reason="out_of_scope",
        reply=scripts["EF-4"].format(step="planning your care or travel"),
    )


def redact_message(text: str) -> str:
    """The copy of a visitor's message that may be saved or sent to the AI."""
    return global_policy_engine.redact_unsolicited_content(text)[0]


def validate_output(text: str, language: str = "en", allow_diagnosis_question: bool = False) -> str:
    """Sanitize model output using the authoritative policy engine."""
    if not isinstance(text, str) or not text.strip():
        raise ValueError("Model output must be non-empty text.")
    return global_policy_engine.validate_outbound(
        text, language=language, allow_diagnosis_question=allow_diagnosis_question
    )
