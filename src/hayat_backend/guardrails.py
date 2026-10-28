"""Deterministic safety checks used before and after model calls."""

from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Any


POLICY_VERSION = "guardrails_v1"


@dataclass(frozen=True)
class GuardrailDecision:
    blocked: bool = False
    escalation_required: bool = False
    reason: str | None = None
    reply: str | None = None


_EMERGENCY = re.compile(
    r"\b(chest pain|can't breathe|cannot breathe|severe bleeding|unconscious|"
    r"stroke|heart attack|difficulty breathing|suicidal|overdose)\b|"
    r"(ألم شديد في الصدر|لا أستطيع التنفس|نزيف شديد|فاقد الوعي|سكتة دماغية|أفكار انتحارية)",
    re.IGNORECASE,
)
_DIAGNOSIS = re.compile(
    r"\b(diagnose|diagnosis|what disease do i have|prescribe|prescription|dosage|"
    r"should i take (?:aspirin|ibuprofen|antibiotic|medication|medicine)|"
    r"interpret my (?:scan|report|mri|x-ray|blood test))\b|"
    r"(شخّص|تشخيص حالتي|ما هو مرضي|وصفة طبية|جرعة الدواء|فسر تحليلي|فسر الأشعة)",
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
    r"jailbreak|override system)",
    re.IGNORECASE,
)
_UNRELATED = re.compile(
    r"\b(recipe|bake|cake|cookies|chocolate cake|football|premier league|champions league|"
    r"crypto|bitcoin|ethereum|python code|write code|weather in)\b",
    re.IGNORECASE,
)
_IN_SCOPE = re.compile(
    r"\b(hayat|medical|treatment|dental|aesthetic|wellness|longevity|preventive|"
    r"recovery|travel|india|oman|uae|dubai|turkey|thailand|germany|uk|london|singapore|"
    r"destination|destinations|compare|comparison|clinic|hospital|consultation|coordinator|"
    r"service|services|visa|visas|budget|companion|booking|appointment|care|doctor|physician|"
    r"patient|prepare|preparation|documents|records|passport|information|pricing|cost|"
    r"timing|timeframe|schedule|step|process|help|guidance|mental health|stress|sleep)\b|"
    r"(حياة|طبي|علاج|أسنان|تجميل|عافية|رفاهية|وقاية|تعافي|سفر|الهند|عمان|الإمارات|دبي|"
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
_UNRELATED = re.compile(
    r"\b(bake|cake|recipe|football|premier league|crypto|bitcoin|ethereum|solana|python code|programming|weather in|stock market|car repair)\b|"
    r"(كعكة|كيك|وصفة طعام|كرة قدم|كريبتو|بيتكوين|برمجة)",
    re.IGNORECASE,
)


def inspect_input(
    text: str,
    conversation: Any = None,
    pending_field: str | None = None,
    extracted_facts: list[Any] | None = None,
) -> GuardrailDecision:
    """Return a deterministic policy decision for user text."""
    if _EMERGENCY.search(text):
        return GuardrailDecision(
            escalation_required=True,
            reason="possible_emergency",
            reply=(
                "If this may be an emergency, contact your local emergency services "
                "or seek urgent in-person medical care now. Hayat cannot assess emergencies."
            ),
        )
    if _DIAGNOSIS.search(text):
        return GuardrailDecision(
            escalation_required=True,
            reason="medical_advice",
            reply=(
                "I can't diagnose conditions, prescribe treatment, or interpret medical "
                "reports. Please consult a qualified clinician; I can help coordinate a "
                "non-clinical consultation."
            ),
        )
    if _COMMERCIAL_GUARANTEES.search(text):
        return GuardrailDecision(
            escalation_required=True,
            reason="unsupported_guarantee",
            reply=(
                "I can't guarantee prices, availability, visa approval, bookings, or "
                "outcomes. A coordinator can confirm current details after review."
            ),
        )
    if _INJECTION.search(text):
        return GuardrailDecision(
            blocked=True,
            reason="prompt_injection",
            reply="I can help with Hayat services and coordination, but I can't reveal internal instructions.",
        )
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
        return GuardrailDecision(
            blocked=True,
            reason="out_of_scope",
            reply=None,
        )

    # Short contextual answers in ongoing conversations are always in-scope
    if _SHORT_CONTEXTUAL_ANSWERS.search(text):
        return GuardrailDecision()

    # If the user provided valid consultation facts (specialty, destination, name, timing, etc.)
    if extracted_facts:
        return GuardrailDecision()

    # Procedural questions about Hayat services, preparation, destinations, or steps
    if _PROCEDURAL_QUESTIONS.search(text):
        return GuardrailDecision()

    # Broad in-scope checks
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
            # Reject obvious unrelated requests even in an active conversation
            if _UNRELATED.search(text) and not has_valid_in_scope:
                return GuardrailDecision(blocked=True, reason="out_of_scope")
            # In an active journey, answers to pending questions or conversational queries are in-scope
            if pending_field:
                return GuardrailDecision()
            # General query with a question mark or conversational prompt
            if "?" in text or "؟" in text or len(text.split()) < 15:
                return GuardrailDecision()

    return GuardrailDecision(
        blocked=True,
        reason="out_of_scope",
        reply=None,
    )


def validate_output(text: str) -> str:
    """Sanitize model output: strip internal prompts, role labels, and trailing auto-regressions."""
    if not isinstance(text, str) or not text.strip():
        raise ValueError("Model output must be non-empty text.")
    if _INJECTION.search(text):
        return "I can help with Hayat services and coordination. How may I assist you?"

    cleaned = text.strip()

    # If the model hallucinates an entire transcript like "[User] ... \n[Assistant] ...",
    # extract the assistant's portion only.
    if re.search(r"\[Assistant\]:?", cleaned, re.IGNORECASE):
        cleaned = re.split(r"\[Assistant\]:?", cleaned, flags=re.IGNORECASE)[-1].strip()
    elif re.search(r"\bAssistant:\s*", cleaned, re.IGNORECASE):
        cleaned = re.split(r"\bAssistant:\s*", cleaned, flags=re.IGNORECASE)[-1].strip()

    # Strip auto-regressive continuation if the model simulated a subsequent [User] turn
    split_markers = [
        "\n\n[User]", "\n[User]", "\n\nUser:", "\nUser:",
        "\n\n[Human]", "\n[Human]", "\n\nHuman:", "\nHuman:",
    ]
    for marker in split_markers:
        if marker in cleaned:
            cleaned = cleaned.split(marker)[0].strip()

    # Strip leading role markers like [Assistant]: or Assistant: or [User]:
    cleaned = re.sub(
        r"^\s*\[?(?:Assistant|Hayat|Bot|User|Human)\]?:?\s*",
        "",
        cleaned,
        flags=re.IGNORECASE,
    ).strip()

    # Strip raw JSON fences if model outputted raw JSON block
    if cleaned.startswith("```json"):
        cleaned = re.sub(r"^```json\s*", "", cleaned)
        cleaned = re.sub(r"\s*```$", "", cleaned)

    return cleaned
