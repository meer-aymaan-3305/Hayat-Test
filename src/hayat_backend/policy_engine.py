"""Authoritative Deterministic Policy Enforcement Engine for HAYAT.

Governing specification: HAYAT_Guardrail_Document_v1.docx — Version 1.0.
This module executes independently of LLM output.
Rules enforced:
- CP-1 through CP-9
- HB-1 through HB-10
- DP-1 through DP-8
- UC-1 through UC-6
- UH-1 through UH-6
- EF-1 through EF-11
- AL-1 through AL-9
- Appendix A (Exhaustive permitted intake allowlist & prohibited PHI)
- Appendix B (Strict persona signal mapping & ambiguity handling)
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
import re
from typing import Any, Literal
from uuid import UUID, uuid4

from .audit_logging import ComplianceAuditStore, global_audit_store
from .schemas.appendix_a import (
    AppendixAIntakePayload,
    PERMITTED_FIELD_NAMES,
    PROHIBITED_CLINICAL_CATEGORIES,
)


# ==============================================================================
# CP-1: MANDATORY SELF-IDENTIFICATION (FIXED OPENING)
# ==============================================================================
CP1_OPENING_EN = (
    "Welcome! I'm HAYAT, Trawellcare's AI assistant. I can help you describe what you need "
    "so we can match you with the right care or travel options — I'm not a medical "
    "professional and I don't provide diagnoses or medical advice."
)

CP1_OPENING_AR = (
    "مرحباً! أنا حياة، المساعد الذكي لترافيل كير. يمكنني مساعدتك في وصف احتياجاتك لنتمكن "
    "من مطابقتك مع خيارات الرعاية أو السفر المناسبة — أنا لست متخصصاً طبياً ولا أقدم "
    "تشخيصات أو استشارات طبية."
)


# ==============================================================================
# SECTION 6: EXACT VERBATIM FALLBACK SCRIPTS (EF-1 THROUGH EF-11)
# ==============================================================================
EF_SCRIPTS_EN = {
    "EF-1": (
        "I'm not able to interpret symptoms or give a diagnosis — that needs a clinician. "
        "I can note down what kind of care you're looking for, and a doctor or case manager "
        "will review the details with you after you sign up. What would you like help with?"
    ),
    "EF-2": (
        "Thank you for sharing that — for anything clinical like this, a specialist will need "
        "to review it directly, so I won't record the details here. Let's keep going with {step}."
    ),
    "EF-3": (
        "I don't choose or recommend specific hospitals, doctors, or treatments myself — "
        "once you sign up, our matching process and a case manager or wellness curator will "
        "put together tailored options for you. I can get your preferences ready for that now."
    ),
    "EF-4": (
        "That's outside what I can help with here — I'm focused on planning your Trawellcare "
        "journey. Shall we continue with {step}?"
    ),
    "EF-5": (
        "I can help you with planning your care or travel with Trawellcare — what would you "
        "like to share first?"
    ),
    "EF-6": (
        "I won't need that, and please don't share passwords, card numbers, or ID numbers "
        "here — this chat isn't a secure place for that. Let's continue with {step}; "
        "sign-in and payment happen in a secured step later."
    ),
    "EF-7": (
        "I don't have confirmed information on that yet, and I don't want to guess. "
        "I can flag this for your case manager once you sign up, or you can reach our "
        "support team directly."
    ),
    "EF-8": (
        "I'm having trouble saving your details right now. Nothing's lost on your end — "
        "please try again in a moment, or I can have a case manager follow up with you directly."
    ),
    "EF-9": (
        "This sounds like it may need urgent attention right now, which I'm not able to help "
        "with directly. Please contact local emergency services immediately — 999 in Oman, "
        "998 in the UAE, or your local emergency number — or go to the nearest emergency room. "
        "Once you're safe, we're here to help with planning."
    ),
    "EF-10": (
        "I'm really sorry you're going through this. I'm not the right support for this moment, "
        "and I want to make sure you're safe — please reach out to a crisis line or emergency "
        "services in your country right now, or to someone you trust nearby."
    ),
    "EF-11": (
        "I want to keep this conversation helpful — I'll continue once we're back to planning "
        "your trip."
    ),
}

EF_SCRIPTS_AR = {
    "EF-1": (
        "لست مخولاً بتفسير الأعراض أو تقديم تشخيص طبي — فهذا يتطلب طبيباً مختصاً. "
        "يمكنني تسجيل نوع الرعاية التي تبحث عنها، وسيقوم طبيب أو مدير حالة بمراجعة التفاصيل "
        "معك بعد التسجيل. بمَ ترغب أن أساعدك؟"
    ),
    "EF-2": (
        "شكراً لمشاركتك ذلك — بالنسبة لأي تفاصيل سريرية مثل هذه، سيحتاج أخصائي إلى مراجعتها "
        "مباشرة، لذلك لن أسجل هذه التفاصيل هنا. دعنا نواصل بخصوص {step}."
    ),
    "EF-3": (
        "أنا لا أختار ولا أوصي بمستشفيات أو أطباء أو علاجات محددة بنفسي — بمجرد تسجيلك، "
        "ستقوم عملية المطابقة لدينا ومدير الحالة أو منسق العافية بإعداد خيارات مخصصة لك. "
        "يمكنني تجهيز تفضيلاتك لذلك الآن."
    ),
    "EF-4": (
        "هذا خارج نطاق ما يمكنني المساعدة به هنا — تركيزي ينصب على التخطيط لرحلتك مع "
        "ترافيل كير. هل نواصل بخصوص {step}؟"
    ),
    "EF-5": (
        "يمكنني مساعدتك في التخطيط لرعايتك أو سفرك مع ترافيل كير — ما الذي تود مشاركته أولاً؟"
    ),
    "EF-6": (
        "لن أحتاج إلى ذلك، ويرجى عدم مشاركة كلمات المرور أو أرقام البطاقات أو أرقام الهوية "
        "هنا — هذه المحادثة ليست مكاناً آمناً لذلك. دعنا نواصل بخصوص {step}؛ "
        "يتم تسجيل الدخول والدفع في خطوة آمنة لاحقاً."
    ),
    "EF-7": (
        "ليس لدي معلومات مؤكدة حول ذلك بعد، ولا أود التخمين. يمكنني إحالة هذا إلى مدير "
        "حالتك بمجرد تسجيلك، أو يمكنك التواصل مع فريق الدعم لدينا مباشرة."
    ),
    "EF-8": (
        "أواجه صعوبة في حفظ تفاصيلك الآن. لم يُفقد أي شيء من جانبك — يرجى المحاولة مرة "
        "أخرى بعد لحظات، أو يمكنني جعل مدير الحالة يتواصل معك مباشرة."
    ),
    "EF-9": (
        "يبدو أن هذا قد يتطلب عناية عاجلة وفورية، وهو ما لا يمكنني المساعدة به مباشرة. "
        "يرجى الاتصال بخدمات الطوارئ المحلية فوراً — 999 في سلطنة عمان، 998 في الإمارات، "
        "أو رقم الطوارئ المحلي لديك — أو التوجه إلى أقرب قسم طوارئ. بمجرد أن تكون في أمان، "
        "نحن هنا لمساعدتك في التخطيط."
    ),
    "EF-10": (
        "أنا آسف جداً لأنك تمر بهذا. لست الدعم المناسب لهذه اللحظة، وأريد التأكد من سلامتك — "
        "يرجى التواصل مع خط المساعدة في الأزمات أو خدمات الطوارئ في بلدك الآن، "
        "أو مع شخص تثق به بالقرب منك."
    ),
    "EF-11": (
        "أود أن أحافظ على فائدة هذه المحادثة — سأواصل بمجرد أن نعود إلى التخطيط لرحلتك."
    ),
}


# ==============================================================================
# DETERMINISTIC REGEX PATTERNS FOR HARD BOUNDARIES
# ==============================================================================

# HB-10 & EF-9: Medical emergencies (acute pain, breathing, bleeding, unconsciousness, stroke)
_EMERGENCY_RE = re.compile(
    r"\b(chest pain|heart attack|cardiac arrest|can't breathe|cannot breathe|"
    r"difficulty breathing|trouble breathing|not breathing|stop breathing|"
    r"shortness of breath|severe bleeding|bleeding heavily|bleeding badly|hemorrhag\w*|"
    r"unconscious|unresponsive|collapsed|passed out|feel faint|fainted|"
    r"stroke|seizure|choking|head trauma|acute pain|severe acute pain|"
    r"loss of consciousness|overdose|too many (?:pills|tablets|painkillers|medicine|medication)|"
    r"anaphylaxis|anaphylactic|severe allergic reaction)\b|"
    r"\b(?:he|she|they|someone|my (?:father|mother|dad|mum|mom|baby|child|son|daughter|wife|husband|friend|brother|sister)|"
    r"the (?:man|woman|person|patient)) (?:has |is |was |keeps )?(?:collapsed|unresponsive|not responding|passed out|unconscious)\b|"
    r"(ألم شديد في الصدر|أزمة قلبية|توقف القلب|لا أستطيع التنفس|لا أستطيع التنفس|صعوبة في التنفس|ضيق التنفس|"
    r"لا يتنفس|لا أتنفس|تنفس بصعوبة|نزيف شديد|أنزف بشدة|نزيف غزير|فاقد الوعي|فقدان الوعي|إغماء|أغمي|أشعر بالإغماء|"
    r"سكتة دماغية|جلطة|جلطة دماغية|تشنجات|اختناق|إصابة في الرأس|ألم حاد|"
    r"جرعة زائدة|تناولت جرعة زائدة|تسمم|رد فعل تحسسي شديد|حساسية شديدة|"
    r"سقط|سقطت|انهار|انهارت|لا يستجيب|لا تستجيب|لا يستجيبون|يفقد الوعي)",
    re.IGNORECASE,
)

# HB-10 & EF-10: Self-harm or crisis language
_CRISIS_RE = re.compile(
    r"\b(suicide|suicidal|kill myself|end my life|want to die|self-harm|harm myself|"
    r"cut myself|overdose|take my own life|"
    r"do(?:es)? not want to live|don't want to live|no point in living|no point in (?:this )?life|"
    r"better off without me|better off dead|thinking of hurting myself|thinking about hurting myself|"
    r"thinking of killing myself|thinking about killing myself|end it all|"
    r"wish i (?:was|were) dead|don't want to be here|do not want to be here|"
    r"can't go on living|cannot go on living|no reason to live|nothing to live for)\b|"
    r"(انتحار|أفكار انتحارية|أريد أن أموت|إنهاء حياتي|إيذاء نفسي|قتل نفسي|"
    r"لا أريد أن أعيش|لا أريد العيش|لا فائدة من الحياة|لا فائدة من الوجود|"
    r"أنهي حياتي|انهاء حياتي|أفكر في إيذاء نفسي|أفكر في قتل نفسي|"
    r"لا أريد أن أكون هنا|أتمنى لو مت|لا طاقة للعيش|مستحيل أعيش|لا سبب للعيش)",
    re.IGNORECASE,
)

# HB-9, UC-2 & EF-5: Prompt injection, role override, system prompt probing
_INJECTION_RE = re.compile(
    r"(ignore (?:all\s+)?(?:previous|prior|the)?\s*instructions|"
    r"forget (?:your\s+|all\s+)?(?:safety\s+|previous\s+)?rules|"
    r"reveal (?:the\s+|your\s+)?(?:system prompt|internal (?:rules|instructions|configuration))|"
    r"show (?:me\s+)?(?:your\s+)?(?:secret\s+|hidden\s+)?(?:system prompt|guardrails?|policy(?: document)?|rules|developer instructions)|"
    r"print (?:all\s+|your\s+)?(?:internal\s+)?(?:system prompt|instructions|guidelines)|"
    r"what is your system prompt|guardrail[s]? policy document|"
    r"developer (?:message|mode|instruction)|system instructions|"
    r"you are now (?:unrestricted|DAN)|jailbreak|override (?:system|guardrails|policy)|system (?:prompt\s+)?override|"
    r"pretend you are (?:unrestricted|DAN|a doctor who diagnoses)|"
    r"bypass (?:safety|guardrails)|new system prompt|disregard (?:rules|instructions|boundaries))",
    re.IGNORECASE,
)

# HB-6, DP-4 & EF-6: Credentials and payment data pasted in chat
_CREDENTIAL_PAYMENT_RE = re.compile(
    r"\b(?:4[0-9]{3}(?:[ -]?[0-9]{4}){3}|5[1-5][0-9]{2}(?:[ -]?[0-9]{4}){3}|3[47][0-9]{2}(?:[ -]?[0-9]{4}){2}[ -]?[0-9]{3}|"
    r"4[0-9]{12}(?:[0-9]{3})?|5[1-5][0-9]{14}|3[47][0-9]{13}|3(?:0[0-5]|[68][0-9])[0-9]{11}|"
    r"6(?:011|5[0-9]{2})[0-9]{12}|(?:2131|1800|35\d{3})\d{11})\b|"  # Credit cards
    r"\b(?:cvv|cvc|security code)[\s:]+[0-9]{3,4}\b|"  # CVV/CVC
    r"\b(?:password|passwd|pwd)[\s:]+\S+\b|"  # Passwords
    r"\b(?:otp|one[- ]time[- ]password|verification code)[\s:]+[0-9]{4,8}\b|"  # OTP
    r"\b[A-Z]{1,2}[0-9]{7,9}\b|"  # Common passport / national ID number formats
    r"\b(?:national id|civil id|emirates id|passport number)[\s:]+[A-Z0-9-]+\b",
    re.IGNORECASE,
)

# HB-1, UC-4 & EF-1: Clinical diagnosis or interpretation requests (including hypotheticals)
_DIAGNOSIS_RE = re.compile(
    r"\b(diagnose|diagnosis|what disease do i have|what is wrong with (?:me|my \w+)|what condition do i have|"
    r"prescribe|prescription|dosage|dose|should i take (?:aspirin|ibuprofen|antibiotic|medication|medicine)|"
    r"interpret my (?:scan|report|mri|x-ray|blood test|lab result|biopsy)|"
    r"is (?:this|my [a-z ]+) (?:serious|dangerous)|could this (?:rash |symptom )?be (?:cancer|serious|[a-z]+)|should i be worried|what does my symptom mean|"
    r"pretend you(?:'re| are) (?:a |an |licensed )*(?:doctor|physician|cardiologist|clinician)|"
    r"hypothetically,?\s+if (?:i|someone|a person) (?:had|has)|"
    r"as (?:a medical expert|chief medical officer),?\s+)\b|"
    r"(تشخيص|شخّص|شخص (?:حالتي|مرضي)|شخصني|ما هو مرضي|وصفة طبية|جرعة الدواء|فسر تحليلي|فسر الأشعة|هل هذا خطير|هل هذا سرطان)",
    re.IGNORECASE,
)

# HB-3 & EF-3: Provider or treatment recommendation requests
_PROVIDER_RECOMMEND_RE = re.compile(
    r"\b(which (?:hospital|clinic|doctor|surgeon|specialist)s?\b[^.?!]{0,40}\b(?:better|best|top|good)|"
    r"(?:which|what) (?:country|countries|destination|city)\b[^.?!]{0,40}\b(?:better|best|top)|"
    r"(?:best|top|better|good) (?:[a-z]+ ){0,2}(?:hospitals?|clinics?|doctors?|surgeons?|cardiologists?|specialists?)|"
    r"recommend (?:a |the (?:best|top) )?(?:[a-z]+ )?(?:hospital|doctor|surgeon|cardiologist|specialist|clinic)|"
    r"who is the (?:best|top) (?:doctor|cardiologist|surgeon|specialist)|"
    r"rank (?:the )?(?:hospitals|clinics|doctors)|(?:hospital|clinic) (?:x|y|a|b) is better|"
    r"what treatment is better for me|choose a (?:hospital|doctor) for me)\b|"
    r"(أي مستشفى أفضل|رشح لي أفضل طبيب|أفضل دكتور|مقارنة بين مستشفى ومستشفى|اختر لي دكتور|"
    r"أفضل (?:مستشفى|المستشفيات|طبيب|الأطباء|عيادة|العيادات|جراح))",
    re.IGNORECASE,
)

# HB-3: Hayat's own words. The patterns above describe questions, so a reply
# naming or ranking providers needs its own check.
_PROVIDER_CLAIM_RE = re.compile(
    r"\b(apollo|fortis|medanta|manipal|narayana|aiims|aster|burjeel|mediclinic|bumrungrad|acibadem|"
    r"cleveland clinic|mayo clinic|max (?:healthcare|hospital|super)|"
    r"(?:best|top|leading|finest|renowned|excellent|world-class) (?:[a-z-]+ ){0,3}"
    r"(?:hospitals?|clinics?|doctors?|surgeons?|cardiologists?|specialists?)|"
    r"i (?:would |'d )?(?:recommend|suggest|advise)|hospital recommendations?|strong reputation|"
    r"(?:is|are) (?:a |an |the )?(?:suitable|good|great|ideal|best|excellent|top) "
    r"(?:[a-z-]+ ){0,2}(?:option|choice|destination)s?)\b|"
    r"(أبولو|فورتيس|ميدانتا|أفضل (?:مستشفى|المستشفيات|طبيب|الأطباء|عيادة|العيادات|جراح)|أنصحك|أوصي)",
    re.IGNORECASE,
)
# A provider's proper name, such as "Sunrise Heart Hospital". Case matters here.
_PROVIDER_NAME_RE = re.compile(
    r"\b[A-Z][\w'&-]+(?: [A-Z][\w'&-]+){0,3} (?:Hospitals?|Clinics?|Medical (?:Center|Centre)|Healthcare)\b"
)

# HB-2, DP-5 & EF-2: Unsolicited clinical details volunteered (symptoms, labs, medications, vitals)
_UNSOLICITED_PHI_RE = re.compile(
    r"\b(i have severe pain in|my symptoms include|i was diagnosed with|(?:my\s+)?blood pressure(?:\s+is)?\s+[0-9]+/[0-9]+|"
    r"my hemoglobin is|my (?:mri|scan|x-ray|ultrasound|ct)(?:\s+scan)?\s+(?:showed|shows|revealed)|"
    r"(?:currently\s+)?(?:take|taking|prescribed|dose\s+of)\s+[0-9]+\s*(?:mg|ml|mcg|tablets?|pills?)?\s*(?:of\s+)?(?:[A-Za-z0-9_-]+)?|"
    r"my blood sugar is|ecg showed|family history of heart attacks|genetic (?:[A-Za-z0-9_-]+\s+)?(?:mutation|mutations|history)|"
    r"(?:past\s+)?(?:medical\s+|treatment\s+)?history(?:\s+of)?|had a (?:triple\s+|coronary\s+)?[a-z ]*(?:surgery|bypass|operation)|"
    r"(?:clinical\s+|doctor's\s+)?notes?\s+(?:state|states|show|shows|say|says)|"
    r"(?:suffering from\s+)?(?:major\s+)?(?:depressive|depression|panic attacks|bipolar|schizophrenia|ptsd)|"
    r"(?:chest\s+)?palpitations|"
    r"(?:i have|i've got|i suffer from|i am suffering from|i'm suffering from|my [a-z]+ has)\s+"
    r"(?:[a-z0-9-]+\s+){0,3}(?:diabetes|hypertension|cancer|tumou?r|asthma|hiv|hepatitis|epilepsy|arthritis|"
    r"stroke|thyroid|kidney (?:disease|failure)|heart (?:disease|failure)|high blood pressure)|"
    r"(?:i am|i'm|currently)\s+(?:on|taking)\s+(?:insulin|metformin|warfarin|statins?|aspirin|chemotherapy|[a-z]+\s+medication))\b|"
    r"(أعاني من ألم شديد في|أعراضي هي|تم تشخيصي بـ|ضغط دمي|نتيجة التحليل كانت|أتناول دواء|جرعة|"
    r"(?:لدي|عندي|أعاني من) (?:مرض )?(?:السكري|السكر|سرطان|ضغط الدم|الربو))",
    re.IGNORECASE,
)

# DP-4/DP-6: Contact identifiers and government ID numbers volunteered in chat.
# These are stripped from the stored copy and the model input; structured lead
# capture happens only through the approved secure flow.
_CONTACT_IDENTIFIER_RE = re.compile(
    r"[\w.+-]+@[\w-]+\.[\w.-]+|"  # email addresses
    r"(?=(?:\D*\d){8})\+?\d[\d\s().-]{6,}\d",  # phone / ID-like digit strings (>=8 digits)
    re.IGNORECASE,
)

# DP-5/DP-6: Named conditions, medications and symptom phrases volunteered in
# chat. The stored copy and model input must not retain them even when the
# surrounding sentence did not match the unsolicited-PHI patterns above.
_VOLUNTEERED_CLINICAL_TERM_RE = re.compile(
    r"\b(?:type\s+[12]\s+)?(?:diabetes|diabetic|hypertension|high blood pressure|hypotension|"
    r"warfarin|insulin|metformin|sciatica|methotrexate|hiv|aids|cancer|carcinoma|"
    r"tumou?r|asthma|arthritis|rheumatoid|osteoarthritis|stroke|epilepsy|hepatitis|"
    r"osteoporosis|fibromyalgia|chemotherapy|radiotherapy|immunotherapy|statins?|"
    r"aspirin|ibuprofen|paracetamol|morphine|oxycodone|prednisone|"
    r"heart failure|heart disease|kidney failure|liver failure|multiple sclerosis|copd|"
    r"heart is weak|weak heart|heart weakness|chest tightness|tightness in (?:my |the )?chest|"
    r"shortness of breath|difficulty breathing|can't breathe|cannot breathe|"
    r"severe pain|chronic pain|constant pain|paralysis|paralysed|paralyzed)\b|"
    r"(السكري|داء السكري|السكر|سرطان|السرطان|ضغط الدم|ارتفاع ضغط الدم|الربو|"
    r"التهاب المفاصل|صرع|فيروس|ميتفورمين|أنسولين|وارفارين|ألم شديد|"
    r"قلبي ضعيف|ضعف القلب|ضيق التنفس|جلطة|جلطة دماغية|شلل)",
    re.IGNORECASE,
)

# HB-4 & EF-4: Unrelated off-topic questions
_UNRELATED_RE = re.compile(
    r"\b(recipe|bake|cake|cookies|chocolate cake|football|world cup|premier league|champions league|"
    r"crypto|bitcoin|ethereum|solana|python(?: code| script)?|write (?:python )?code|debug code|programming in|"
    r"weather|stock (?:price|market)|apple stock|car repair|astrology|horoscope|capital of france)\b|"
    r"(كعكة|كيك|وصفة طعام|كرة قدم|كريبتو|بيتكوين|برمجة|الطقس في|سوق الأسهم)",
    re.IGNORECASE,
)

# EF-11: Abusive or harmful user input
_ABUSIVE_RE = re.compile(
    r"\b(fuck you|idiot bot|stupid bot|shut up|piece of shit|kill you|go to hell)\b|"
    r"(اللعنة عليك|غبي|عديم الفائدة|اخرس)",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class PolicyDecision:
    """Deterministic policy decision outcome."""
    blocked: bool = False
    escalation_required: bool = False
    rule_id: str | None = None
    reply: str | None = None
    action_type: str = "allow"  # "allow", "refusal", "redaction", "emergency", "crisis", "security"
    redaction_category: str | None = None
    session_locked: bool = False

    @property
    def is_valid(self) -> bool:
        return not self.blocked


class PolicyEnforcementEngine:
    """Centralized, deterministic policy enforcement engine.

    Executes independently of LLM-generated responses.
    """

    def __init__(self, audit_store: ComplianceAuditStore | None = None) -> None:
        self.audit_store = audit_store or global_audit_store

    def get_fallback_script(
        self, rule_id: str, language: str = "en", step: str = "planning your care or travel"
    ) -> str:
        """Get the exact fixed fallback script for a rule ID."""
        scripts = EF_SCRIPTS_AR if language == "ar" else EF_SCRIPTS_EN
        raw = scripts.get(rule_id, scripts.get("EF-4", ""))
        return raw.format(step=step)

    def evaluate_inbound(
        self,
        text: str,
        *,
        session_id: UUID | None = None,
        conversation_id: UUID | None = None,
        current_step: str = "planning your care or travel",
        language: str = "en",
        is_locked_emergency: bool = False,
        is_locked_crisis: bool = False,
        allow_clinical_context: bool = False,
    ) -> PolicyDecision:
        """Validate every inbound user message deterministically.

        allow_clinical_context is set only while the visitor is answering the
        explicit "existing diagnosis" question (owner-approved, COLLECT_DIAGNOSIS).
        It relaxes the unsolicited-clinical-detail rule (DP-5) for that one turn;
        emergency, self-harm, injection and credential rules still apply."""
        session_id = session_id or uuid4()
        conversation_id = conversation_id or uuid4()
        scripts = EF_SCRIPTS_AR if language == "ar" else EF_SCRIPTS_EN

        # 1. HB-10: Check if session is already locked in emergency or crisis state
        if is_locked_emergency:
            reply = scripts["EF-9"]
            self.audit_store.log_priority_incident(
                session_id=session_id,
                conversation_id=conversation_id,
                rule_id="EF-9",
                incident_type="medical_emergency",
            )
            return PolicyDecision(
                blocked=True,
                escalation_required=True,
                rule_id="EF-9",
                reply=reply,
                action_type="emergency",
                session_locked=True,
            )

        if is_locked_crisis:
            reply = scripts["EF-10"]
            self.audit_store.log_priority_incident(
                session_id=session_id,
                conversation_id=conversation_id,
                rule_id="EF-10",
                incident_type="crisis_self_harm",
            )
            return PolicyDecision(
                blocked=True,
                escalation_required=True,
                rule_id="EF-10",
                reply=reply,
                action_type="crisis",
                session_locked=True,
            )

        # 2. HB-10 & EF-9: Detect described medical emergencies
        if _EMERGENCY_RE.search(text):
            reply = scripts["EF-9"]
            self.audit_store.log_priority_incident(
                session_id=session_id,
                conversation_id=conversation_id,
                rule_id="EF-9",
                incident_type="medical_emergency",
            )
            self.audit_store.log_fallback(
                session_id=session_id,
                conversation_id=conversation_id,
                rule_id="EF-9",
                trigger_type="medical_emergency",
            )
            return PolicyDecision(
                blocked=True,
                escalation_required=True,
                rule_id="EF-9",
                reply=reply,
                action_type="emergency",
                session_locked=True,
            )

        # 3. HB-10 & EF-10: Detect self-harm or crisis language
        if _CRISIS_RE.search(text):
            reply = scripts["EF-10"]
            self.audit_store.log_priority_incident(
                session_id=session_id,
                conversation_id=conversation_id,
                rule_id="EF-10",
                incident_type="crisis_self_harm",
            )
            self.audit_store.log_fallback(
                session_id=session_id,
                conversation_id=conversation_id,
                rule_id="EF-10",
                trigger_type="crisis_self_harm",
            )
            return PolicyDecision(
                blocked=True,
                escalation_required=True,
                rule_id="EF-10",
                reply=reply,
                action_type="crisis",
                session_locked=True,
            )

        # 4. HB-9, UC-2 & EF-5: Detect prompt injection / role override
        if _INJECTION_RE.search(text):
            reply = scripts["EF-5"]
            self.audit_store.log_security_event(
                session_id=session_id,
                conversation_id=conversation_id,
                event_type="prompt_injection_role_override",
                rule_id="UC-2",
                severity="high",
            )
            self.audit_store.log_fallback(
                session_id=session_id,
                conversation_id=conversation_id,
                rule_id="EF-5",
                trigger_type="prompt_injection",
            )
            return PolicyDecision(
                blocked=True,
                escalation_required=False,
                rule_id="EF-5",
                reply=reply,
                action_type="security",
            )

        # 5. HB-6, DP-4 & EF-6: Detect credentials or payment details pasted in chat
        if _CREDENTIAL_PAYMENT_RE.search(text):
            step_text = current_step if current_step else "planning your trip"
            reply = scripts["EF-6"].format(step=step_text)
            self.audit_store.log_redaction(
                session_id=session_id,
                conversation_id=conversation_id,
                category_tag="credential/payment detail",
                rule_id="DP-4",
            )
            self.audit_store.log_fallback(
                session_id=session_id,
                conversation_id=conversation_id,
                rule_id="EF-6",
                trigger_type="credential_payment_pasted",
            )
            return PolicyDecision(
                blocked=True,
                escalation_required=False,
                rule_id="EF-6",
                reply=reply,
                action_type="redaction",
                redaction_category="credential/payment detail",
            )

        # 6. HB-1, UC-4 & EF-1: Detect clinical diagnosis or interpretation requests
        if _DIAGNOSIS_RE.search(text):
            reply = scripts["EF-1"]
            self.audit_store.log_fallback(
                session_id=session_id,
                conversation_id=conversation_id,
                rule_id="EF-1",
                trigger_type="clinical_diagnosis_request",
            )
            return PolicyDecision(
                blocked=True,
                escalation_required=True,
                rule_id="EF-1",
                reply=reply,
                action_type="refusal",
            )

        # 7. HB-3 & EF-3: Detect provider or treatment recommendation requests
        if _PROVIDER_RECOMMEND_RE.search(text):
            reply = scripts["EF-3"]
            self.audit_store.log_fallback(
                session_id=session_id,
                conversation_id=conversation_id,
                rule_id="EF-3",
                trigger_type="provider_recommendation_request",
            )
            return PolicyDecision(
                blocked=True,
                escalation_required=False,
                rule_id="EF-3",
                reply=reply,
                action_type="refusal",
            )

        # 8. EF-11: Detect abusive or harmful user input
        if _ABUSIVE_RE.search(text):
            reply = scripts["EF-11"]
            self.audit_store.log_fallback(
                session_id=session_id,
                conversation_id=conversation_id,
                rule_id="EF-11",
                trigger_type="abusive_user_input",
            )
            return PolicyDecision(
                blocked=True,
                escalation_required=False,
                rule_id="EF-11",
                reply=reply,
                action_type="refusal",
            )

        # 9. HB-2, DP-5 & EF-2: Detect unsolicited clinical details volunteered
        if _UNSOLICITED_PHI_RE.search(text) and not allow_clinical_context:
            step_text = current_step if current_step else "your trip preferences"
            reply = scripts["EF-2"].format(step=step_text)
            self.audit_store.log_redaction(
                session_id=session_id,
                conversation_id=conversation_id,
                category_tag="unsolicited clinical detail",
                rule_id="DP-5",
            )
            self.audit_store.log_fallback(
                session_id=session_id,
                conversation_id=conversation_id,
                rule_id="EF-2",
                trigger_type="unsolicited_phi_volunteered",
            )
            return PolicyDecision(
                blocked=True,
                escalation_required=False,
                rule_id="EF-2",
                reply=reply,
                action_type="redaction",
                redaction_category="unsolicited clinical detail",
            )

        # 10. HB-4 & EF-4: Detect unrelated off-topic questions (only if no in-scope topic or specialty present)
        has_in_scope = bool(
            re.search(
                r"\b(cardio|cardiology|orthopedic|orthopedics|dermatology|dental|oncology|neurology|"
                r"surgery|treatment|wellness|longevity|programme|program|india|oman|uae|dubai|thailand|"
                r"compare|documents|passport|appointment|consultation)\b",
                text,
                re.IGNORECASE,
            )
        )
        if _UNRELATED_RE.search(text) and not has_in_scope:
            step_text = current_step if current_step else "planning your care or travel"
            reply = scripts["EF-4"].format(step=step_text)
            self.audit_store.log_fallback(
                session_id=session_id,
                conversation_id=conversation_id,
                rule_id="EF-4",
                trigger_type="off_topic_unrelated_question",
            )
            return PolicyDecision(
                blocked=True,
                escalation_required=False,
                rule_id="EF-4",
                reply=reply,
                action_type="refusal",
            )

        # If no hard boundary is tripped, allow conversational handling
        return PolicyDecision(blocked=False, rule_id=None, reply=None, action_type="allow")

    def redact_unsolicited_content(
        self,
        text: str,
        *,
        session_id: UUID | None = None,
        conversation_id: UUID | None = None,
    ) -> tuple[str, list[str]]:
        """DP-6 Redaction Protocol: Redact sensitive credentials and prohibited clinical details.

        Returns (cleaned_text, list_of_redacted_categories).
        """
        categories: list[str] = []
        cleaned = text

        # Redact credentials/payment details
        if _CREDENTIAL_PAYMENT_RE.search(cleaned):
            cleaned = _CREDENTIAL_PAYMENT_RE.sub("[REDACTED_CREDENTIAL]", cleaned)
            categories.append("credential/payment detail")
            if session_id and conversation_id:
                self.audit_store.log_redaction(
                    session_id=session_id,
                    conversation_id=conversation_id,
                    category_tag="credential/payment detail",
                    rule_id="DP-4",
                )

        # Redact unsolicited clinical details
        if _UNSOLICITED_PHI_RE.search(cleaned):
            cleaned = _UNSOLICITED_PHI_RE.sub("[REDACTED_CLINICAL_DETAIL]", cleaned)
            categories.append("unsolicited clinical detail")
            if session_id and conversation_id:
                self.audit_store.log_redaction(
                    session_id=session_id,
                    conversation_id=conversation_id,
                    category_tag="unsolicited clinical detail",
                    rule_id="DP-5",
                )

        # Redact named conditions, medications and symptom phrases that survived
        # the pattern-level redaction above (DP-5/DP-6).
        if _VOLUNTEERED_CLINICAL_TERM_RE.search(cleaned):
            cleaned = _VOLUNTEERED_CLINICAL_TERM_RE.sub("[REDACTED_CLINICAL_DETAIL]", cleaned)
            if "unsolicited clinical detail" not in categories:
                categories.append("unsolicited clinical detail")
            if session_id and conversation_id:
                self.audit_store.log_redaction(
                    session_id=session_id,
                    conversation_id=conversation_id,
                    category_tag="unsolicited clinical detail",
                    rule_id="DP-5",
                )

        # Redact contact identifiers and ID-like numbers (DP-4).
        if _CONTACT_IDENTIFIER_RE.search(cleaned):
            cleaned = _CONTACT_IDENTIFIER_RE.sub("[REDACTED_CONTACT_DETAIL]", cleaned)
            categories.append("contact identifier")
            if session_id and conversation_id:
                self.audit_store.log_redaction(
                    session_id=session_id,
                    conversation_id=conversation_id,
                    category_tag="contact identifier",
                    rule_id="DP-4",
                )

        return cleaned, categories

    def validate_outbound(
        self, text: str, language: str = "en", allow_diagnosis_question: bool = False
    ) -> str:
        """Validate outgoing assistant response against hard restrictions."""
        cleaned = text.strip()

        # If the model hallucinates an entire transcript like "[User] ... \n[Assistant] ...",
        # extract the assistant's portion only.
        if re.search(r"\[Assistant\]:?", cleaned, re.IGNORECASE):
            cleaned = re.split(r"\[Assistant\]:?", cleaned, flags=re.IGNORECASE)[-1].strip()
        elif re.search(r"\bAssistant:\s*", cleaned, re.IGNORECASE):
            cleaned = re.split(r"\bAssistant:\s*", cleaned, flags=re.IGNORECASE)[-1].strip()

        # Sanitize role labels or leaked transcript continuation
        cleaned = re.sub(r"^\s*\[?(?:Assistant|Hayat|Bot|User|Human)\]?:?\s*", "", cleaned, flags=re.I)
        split_markers = ["\n\n[User]", "\n[User]", "\n\nUser:", "\nUser:"]
        for marker in split_markers:
            if marker in cleaned:
                cleaned = cleaned.split(marker)[0].strip()

        # Strip raw JSON markdown code blocks
        if cleaned.startswith("```json"):
            cleaned = re.sub(r"^```json\s*", "", cleaned)
            cleaned = re.sub(r"\s*```$", "", cleaned)

        # CP-4: Prohibit leading clinical questions
        if re.search(r"\b(?:do you have|are you experiencing|how severe is your)\s+(?:severe\s+)?(?:pain|fever|symptom|swelling|bleeding|cough)", cleaned, re.I):
            scripts = EF_SCRIPTS_AR if language == "ar" else EF_SCRIPTS_EN
            return scripts["EF-1"]

        # HB-5 & HB-7: Prohibit outcome guarantees or certification of legal/visa outcomes
        if re.search(r"\b(?:100% (?:cure|certain|guaranteed?)|guarantee(?:d)? (?:that\s+)?(?:your\s+)?(?:cure|healing|visa approval|medical visa|approval|outcome))\b", cleaned, re.I):
            cleaned = re.sub(r"\b(?:100% (?:cure|certain|guaranteed?)|guarantee(?:d)? (?:that\s+)?(?:your\s+)?(?:cure|healing|visa approval|medical visa|approval|outcome))\b", "support options", cleaned, flags=re.I)

        # CP-2, CP-3 & HB-5: Prohibit unsupported clinical quality guarantees and reassurance ("you are in good hands")
        if re.search(r"\b(?:you are in good hands|in the best hands|guaranteed to be safe|we promise you will be fine|don't worry about the outcome)\b", cleaned, re.I):
            cleaned = re.sub(
                r"\b(?:you are in good hands|in the best hands|guaranteed to be safe|we promise you will be fine|don't worry about the outcome)[,.]?\s*",
                "",
                cleaned,
                flags=re.I
            ).strip()

        # Ensure model never generated clinical diagnoses or prescriptions
        # Only while asking the owner-approved "existing diagnosis" question: the reply
        # may use the word itself, but never prescribing, dosing or interpretation.
        is_diagnosis_question = bool(
            allow_diagnosis_question
            and re.search(r"\b(?:existing|any) diagnosis\b|diagnosis or (?:health )?condition", cleaned, re.I)
            and not re.search(r"prescri|dosage|\bdose\b|interpret|should i take|what disease", cleaned, re.I)
        )
        diagnosis_check = "" if is_diagnosis_question else cleaned
        if _DIAGNOSIS_RE.search(diagnosis_check):
            scripts = EF_SCRIPTS_AR if language == "ar" else EF_SCRIPTS_EN
            return scripts["EF-1"]

        # Ensure model never recommended or ranked specific providers
        if (
            _PROVIDER_RECOMMEND_RE.search(cleaned)
            or _PROVIDER_CLAIM_RE.search(cleaned)
            or _PROVIDER_NAME_RE.search(cleaned)
        ):
            scripts = EF_SCRIPTS_AR if language == "ar" else EF_SCRIPTS_EN
            return scripts["EF-3"]

        return cleaned

    # ==========================================================================
    # APPENDIX B: PERSONA SIGNAL MAPPING ENGINE
    # ==========================================================================
    def evaluate_persona(
        self,
        intake: AppendixAIntakePayload | dict[str, Any],
    ) -> tuple[str | None, str, str | None]:
        """Map permitted Appendix A signals to Appendix B personas.

        Returns (persona_name, status, ambiguity_note):
        status is 'CONFIRMED' or 'REQUIRES_CONFIRMATION' (if mixed/ambiguous).
        """
        data = intake.model_dump() if isinstance(intake, AppendixAIntakePayload) else intake

        service = (data.get("service_procedure_category") or "").strip().lower()
        trip_type = (data.get("trip_type") or "").strip().lower()
        urgency = (data.get("urgency_waiting_time_context") or "").strip().lower()
        insurance = (data.get("insurance_coverage_status") or "").strip().lower()
        value_priority = (data.get("value_priority") or "").strip().lower()
        budget = (data.get("total_budget_range") or "").strip().lower()
        concierge = (data.get("concierge_requirements") or "").strip().lower()
        destination = (data.get("preferred_destination") or "").strip().lower()

        matches: list[str] = []

        # 1. Cost-conscious elective-treatment seeker:
        # High urgency/waiting-time + no insurance + cost-effectiveness
        is_cost_conscious = (
            ("waiting list" in urgency or "urgent" in urgency or "soon" in urgency or "high" in urgency)
            and insurance == "not_covered"
            and value_priority == "cost-effectiveness"
        )
        if is_cost_conscious:
            matches.append("Cost-conscious elective-treatment seeker")

        # 2. HNI / family member seeking reliable care abroad:
        # Comfort or best-available-service + higher budget + concierge/guide interest
        is_hni = (
            value_priority in ("comfort", "best-available service")
            and any(term in budget for term in ("high", "premium", "luxury", "vip", "above", "unlimited"))
            and bool(concierge)
        )
        if is_hni:
            matches.append("HNI / family member seeking reliable care abroad")

        # 3. Wellness or longevity traveller:
        # Trip type = wellness + destination-flexible + no stated procedure category
        is_wellness = (
            trip_type == "wellness"
            and not service
        )
        if is_wellness:
            matches.append("Wellness or longevity traveller")

        # 4. Dental and aesthetics seeker:
        # Service/procedure category explicitly names a dental or aesthetic treatment
        dental_aesthetic_terms = (
            "dental", "dentistry", "teeth", "implant", "veneer", "crown", "whitening",
            "aesthetic", "cosmetic", "plastic surgery", "rhinoplasty", "botox", "filler",
            "hair transplant", "liposuction"
        )
        is_dental_aesthetic = any(term in service for term in dental_aesthetic_terms)
        if is_dental_aesthetic:
            matches.append("Dental and aesthetics seeker")

        # 5. Business or family traveller (non-medical):
        # Trip type = business or family + no service/procedure category stated
        is_non_medical = (
            trip_type in ("business", "family")
            and not service
        )
        if is_non_medical:
            matches.append("Business or family traveller (non-medical)")

        if len(matches) == 1:
            return matches[0], "CONFIRMED", None
        elif len(matches) > 1:
            # Ambiguous / mixed signals per Appendix B:
            # "A session may show mixed or ambiguous signals. In that case HAYAT states the ambiguity back
            # to the user for confirmation (CP-5) rather than picking a persona silently — an unconfirmed
            # persona must not be sent to CRM/the matching engine as if it were confirmed."
            ambiguity_note = (
                f"Your preferences match both {matches[0]} and {matches[1]}. "
                "Could you please confirm which best describes your primary trip focus?"
            )
            return None, "REQUIRES_CONFIRMATION", ambiguity_note
        elif service:
            # Single service specified without conflicting signals: default to clinical elective intake
            return "Cost-conscious elective-treatment seeker" if value_priority == "cost-effectiveness" else "HNI / family member seeking reliable care abroad", "CONFIRMED", None

        return None, "UNRESOLVED", None

    # ==========================================================================
    # CP-5 & DP-2: CONFIRMATION & TRANSMISSION PROTOCOL
    # ==========================================================================
    def format_cp5_summary(
        self,
        intake_payload: AppendixAIntakePayload | dict[str, Any],
        language: str = "en",
    ) -> str:
        """CP-5 & DP-2 Protocol:

        1. Explain that information will be shared with Trawellcare's CRM and matching engine
           to prepare consultation options.
        2. Present a readable summary of permitted Appendix A information captured.
        3. Ask for explicit confirmation.
        """
        data = (
            intake_payload.model_dump(exclude_none=True)
            if isinstance(intake_payload, AppendixAIntakePayload)
            else {k: v for k, v in intake_payload.items() if v not in (None, "") and k in PERMITTED_FIELD_NAMES}
        )

        lines: list[str] = []
        for key, val in data.items():
            readable_key = key.replace("_", " ").title()
            lines.append(f"• **{readable_key}:** {val}")

        summary_bullets = "\n".join(lines) if lines else "• None"

        if language == "ar":
            return (
                "قبل إرسال بياناتك إلى نظام إدارة علاقات العملاء (CRM) ومحرك المطابقة في ترافيل كير "
                "لإعداد خيارات الاستشارة المناسبة لك، يرجى مراجعة وتأكيد التفاصيل التالية التي تم تسجيلها:\n\n"
                f"{summary_bullets}\n\n"
                "هل تؤكد رغبتك في إرسال هذه التفاصيل لمتابعة ترتيبات استشارتك مع منسق العناية؟"
            )
        return (
            "Before your details are passed to Trawellcare's CRM and matching engine to prepare "
            "consultation options, please review and confirm the information we have noted:\n\n"
            f"{summary_bullets}\n\n"
            "Do you explicitly confirm that we may share these details with our CRM and matching engine "
            "to prepare your consultation options?"
        )

    def evaluate_cp5_consent(
        self,
        text: str,
        language: str = "en",
    ) -> tuple[Literal["AFFIRMATIVE", "NEGATIVE", "CONDITIONAL", "CONTRADICTORY", "DEFERRED", "NONE"], str | None]:
        """CP-5 Ambiguity & Consent Evaluation Protocol:

        Evaluates user response when confirming transfer of structured data to CRM / matching engine.
        Distinguishes between affirmative, negative, conditional, contradictory, and deferred responses.
        No transmission of structured data may take place before the user explicitly confirms (unconditionally).
        """
        lowered = text.strip().lower()

        # 1. Contradictory patterns: Contains both affirmative and refusal / cancellation signals
        has_contradictory_phrase = bool(re.search(
            r"\b(yes and no|yes but no|agree but don't|i consent but do not|yes,? but (?:actually )?(?:no|don't|do not|wait|cancel))\b"
            r"|نعم ولا|موافق ولكن لا|أوافق ولا توافق|نعم لكن لا",
            lowered
        ))
        affirmative_signals = bool(re.search(
            r"\b(yes|i confirm|i agree|i consent|proceed|confirm|submit|please submit|go ahead|approve|yes please)\b"
            r"|نعم|أوافق|موافق|أكد|أرسل|تابع",
            lowered
        ))
        negative_signals = bool(re.search(
            r"\b(no|do not (?:share|send|submit)|don't (?:share|send|submit)|i (?:do not|don't) (?:consent|agree)|decline|refuse|reject|stop|cancel|do not proceed|not share)\b"
            r"|لا أوافق|لا ترسل|لا تشارك|أرفض|كلا|لا تشاركو",
            lowered
        ))

        if has_contradictory_phrase or (affirmative_signals and negative_signals):
            note = (
                "Your response seems to contain mixed confirmation signals. Could you please clarify if you "
                "would like us to share your details with Trawellcare's CRM and matching engine or not?"
                if language == "en" else
                "يبدو أن ردك يحتوي على إشارات تأكيد متضاربة. هل يمكنك توضيح ما إذا كنت ترغب في مشاركة تفاصيلك مع نظام CRM ومحرك المطابقة أم لا؟"
            )
            return "CONTRADICTORY", note

        # 2. Conditional patterns: User consents only subject to a condition
        conditional_signals = bool(re.search(
            r"\b(only if|if and only if|as long as|provided that|subject to|unless|conditional(?:ly)?|depending on)\b"
            r"|فقط إذا|بشرط|إذا كان",
            lowered
        ))
        if conditional_signals:
            note = (
                "I have noted your condition. Before your details can be passed to our CRM and matching engine, "
                "we require unconditional confirmation. Would you like to confirm without conditions, or would you "
                "prefer to speak to a case manager first?"
                if language == "en" else
                "لقد سجلت شرطك. قبل أن نتمكن من إرسال بياناتك إلى نظام CRM ومحرك المطابقة، نحتاج إلى تأكيد صريح وغير مشروط. "
                "هل تود التأكيد دون شروط، أو التحدث مع مدير الحالة أولاً؟"
            )
            return "CONDITIONAL", note

        # 3. Deferred patterns: User asks to delay or wait
        deferred_signals = bool(re.search(
            r"\b(not now|not yet|later|maybe later|think about it|wait a (?:moment|minute)|give me time|hold on|need to think)\b"
            r"|ليس الآن|لاحقاً|انتظر|دعني أفكر|أحتاج إلى وقت",
            lowered
        ))
        if deferred_signals:
            note = (
                "No problem at all. We will hold your details securely in this session and will not transmit them "
                "until you're ready to proceed."
                if language == "en" else
                "لا مشكلة على الإطلاق. سنحتفظ بتفاصيلك بأمان في هذه الجلسة ولن نقوم بنقلها حتى تكون مستعداً للمتابعة."
            )
            return "DEFERRED", note

        # 4. Pure negative / refusal
        if negative_signals:
            note = (
                "Understood. We will not share your details with our CRM or matching engine. We can continue planning "
                "here or update your preferences whenever you're ready."
                if language == "en" else
                "مفهوم تماماً. لن نقوم بمشاركة بياناتك مع نظام CRM أو محرك المطابقة. يمكننا مواصلة التخطيط هنا أو تحديث تفضيلاتك متى ما كنت مستعداً."
            )
            return "NEGATIVE", note

        # 5. Unambiguous affirmative
        if affirmative_signals:
            return "AFFIRMATIVE", None

        return "NONE", None


# Global policy engine singleton
global_policy_engine = PolicyEnforcementEngine()
