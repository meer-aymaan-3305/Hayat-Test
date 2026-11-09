"""Signature Wellness Programmes Conversation Service & State Machine.

Governed by docs/knowledge/signature_programmes.md.
Provides conversational guidance, preference collection, and registration of interest
for HAYAT-100, AAfiya, and FFounders as a distinct service category from the
Appendix A medical-travel workflow.

Enforces Policy Addendum 1.1:
- In-chat contact data collection is disabled.
- Registration of interest is free and non-binding.
- Human coordinator handoff handles final proposals and appointment coordination.
"""

from __future__ import annotations

import re
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from .memory_store import Conversation, MemoryStore
from .programmes_catalog import (
    ALL_THREE_INTEREST_AR,
    ALL_THREE_INTEREST_EN,
    DATES_EXPLANATION_AR,
    DATES_EXPLANATION_EN,
    AAFIYA_DESTINATIONS_EXPLANATION_AR,
    AAFIYA_DESTINATIONS_EXPLANATION_EN,
    DESTINATIONS_EXPLANATION_AR,
    DESTINATIONS_EXPLANATION_EN,
    PRICING_EXPLANATION_AR,
    PRICING_EXPLANATION_EN,
    PROGRAMMES_CATALOG,
    REGISTRATION_DECLINED_AR,
    REGISTRATION_DECLINED_EN,
    SIGNATURE_PROGRAMMES_INTRO_AR,
    SIGNATURE_PROGRAMMES_INTRO_EN,
    get_programme,
)
from .schemas.chat import ChatAction
from .schemas.programme import (
    ContactConsentStatus,
    EnquiryStatus,
    ProgrammeId,
    ProgrammeStage,
    RegistrationStatus,
    SignatureProgrammeEnquiry,
)


_PROGRAMME_DETECTION_RE = re.compile(
    r"\b(signature (?:wellness )?programme?s?|signature retreats?|signature wellness|"
    r"hayat[- ]?100|aafiya|aafiyah|ffounders|f[- ]founders|"
    r"all three(?: programmes?)?|all of them|"
    r"healthy ageing|healthy aging|longevity|"
    r"women'?s (?:fitness|wellness|retreat)|executive (?:fitness|wellness|retreat)|"
    r"wellness retreats?|retreats?)\b|"
    r"برامج العافية المتميزة|برامج متميزة|حياة[- ]?100|فاوندرز|طول العمر|الشيخوخة الصحية|منتجع طول العمر|منتجع السيدات|منتجع القادة|منتجعات العافية",
    re.IGNORECASE,
)

_SWITCH_TO_MEDICAL_RE = re.compile(
    r"\b(?:switch|change|back to|return to|prefer|want)\b.*\b(?:medical|cardiology|orthopedic|surgery|treatment|doctor|hospital|medical travel)\b|"
    r"سفر طبي|علاج طبي|جراحة|مستشفى|طبيب",
    re.IGNORECASE,
)

_SWITCH_TO_SIGNATURE_RE = re.compile(
    r"\b(?:switch to|change to|prefer|explore|tell me about)\s+(?:signature|wellness retreat|hayat-100|aafiya|ffounders|programmes?)\b|"
    r"برامج العافية المتميزة|استكشاف برامج العافية",
    re.IGNORECASE,
)

_PROGRAMME_INFO_RE = re.compile(
    r"\b(tell me about|what do you offer|what'?s on offer|what'?s included|what is included|"
    r"what else|what'?s in (?:this|the|it)|what does (?:it|this|that|the plan|the programme) "
    r"(?:include|offer|have|get you)|in this plan|in the programme|plan (?:includes?|offers?|has)|"
    r"benefits?|explain|describe|more (?:details|information|info)|programme details|programme information|"
    r"what does\b.*\b(?:offer|include|involve)|guide me|i (?:was |am )?asking about|i meant)\b|"
    r"ماذا تقدم|ما الذي تقدمه|اشرح|اشرح لي|فوائد|تفاصيل|معلومات|أخبرني عن|كنت أسأل عن",
    re.IGNORECASE,
)

_PROGRAMME_AR_DETAIL: dict[str, dict[str, str]] = {
    "hayat_100": {
        "focus": "يركز HAYAT-100 على طول العمر والشيخوخة الصحية من خلال التغذية السليمة، والنشاط البدني واللياقة، والنوم والاستشفاء، والتعلم بإشراف مختصين.",
        "philosophy": "الأمر لا يتعلق فقط بالعيش حتى سن المئة، بل بجعل كل عام ذا قيمة.",
        "themes": "التغذية السليمة والعادات الحياتية، والنشاط البدني والقوة والمرونة، والراحة والنوم والتعافي، واليقظة الذهنية وإدارة التوتر",
    },
    "aafiya": {
        "focus": "AAfiya هي تجربة للياقة والعافية مخصصة للسيدات، تجمع بين الحركة والتغذية السليمة والعناية الذاتية والتواصل الإيجابي في بيئة مرحبة لجميع المستويات.",
        "philosophy": "رحلتك. عافيتك. بطريقتك.",
        "themes": "البيلاتس واليوغا وتمارين اللياقة، وورش العمل الصحية والعناية الذاتية، والتغذية المتوازنة والأكل الواعي، والاسترخاء والتأمل وبناء الصداقات",
    },
    "ffounders": {
        "focus": "FFounders هو منتجع متميز للياقة والعافية التنفيذية مصمم لمؤسسي الشركات ورواد الأعمال والقادة لإعادة شحن طاقتهم وبناء المرونة الجسدية والنفسية.",
        "philosophy": "بناء شركة ناجحة يجب ألا يكون على حساب بناء حياة أكثر صحة.",
        "themes": "اللياقة والقوة البدنية والتحمل، وإدارة التوتر والمرونة وعلوم النوم والأداء، والتغذية والطاقة المستدامة، واللقاءات النوعية مع قادة الأعمال",
    },
}

_SKIP_KEYWORDS_RE = re.compile(
    r"\b(skip|flexible|not sure|undecided|don't know|no preference|any|either|next question|skip next|later|open to exploring)\b|"
    r"تخطي|مرن|غير متأكد|لا أعلم|لا تفضيل|أي منها|السؤال التالي|لاحقاً|منفتح على الخيارات",
    re.IGNORECASE,
)


# Pending review by an Arabic speaker. See docs/HAYAT_POLICY_REGISTER.md.
ARABIC_LABELS = {
    "Spain": "إسبانيا",
    "Japan": "اليابان",
    "United States": "الولايات المتحدة",
    "UAE": "الإمارات",
    "Singapore": "سنغافورة",
    "India": "الهند",
    "Undecided / Open": "لم أقرر بعد",
    "HAYAT-100 (Longevity)": "HAYAT-100 (طول العمر)",
    "AAfiya (Women's Wellness)": "AAfiya (عافية السيدات)",
    "FFounders (Executive Wellness)": "FFounders (عافية التنفيذيين)",
    "Change destination": "تغيير الوجهة",
    "Change timing": "تغيير الموعد",
    "Curated peer connections": "التواصل مع الأقران",
    "Explore medical travel": "استكشاف السفر العلاجي",
    "Explore proposals first": "الاطلاع على المقترحات أولًا",
    "Fitness & mobility": "اللياقة والحركة",
    "Flexible on dates": "مرن في التواريخ",
    "Flexible on timing": "مرن في التوقيت",
    "Focus on wellbeing": "التركيز على العافية",
    "How is pricing determined?": "كيف يُحدد السعر؟",
    "I'm interested in all three": "أنا مهتم بالبرامج الثلاثة",
    "Individual / Solo": "بمفردي",
    "Lifestyle & nutrition": "نمط الحياة والتغذية",
    "Next 3 months": "خلال 3 أشهر",
    "Next 6 months": "خلال 6 أشهر",
    "Pilates & yoga": "البيلاتس واليوغا",
    "Register my interest": "تسجيل اهتمامي",
    "Restorative break": "استراحة للاستجمام",
    "Review my summary": "مراجعة الملخص",
    "Self-care workshops": "ورش العناية الذاتية",
    "Sleep & recovery": "النوم والتعافي",
    "Strength & conditioning": "القوة واللياقة",
    "Stress & recovery": "التوتر والتعافي",
    "With colleagues": "مع الزملاء",
    "With spouse / friend": "مع الزوج أو صديق",
    "United Arab Emirates": "الإمارات العربية المتحدة",
    "Other / Undecided": "لم أقرر بعد",
    "Pilates & core strength": "البيلاتس وقوة الجذع",
    "Yoga & stretching": "اليوغا والتمدد",
    "Longevity & healthy ageing awareness": "التوعية بطول العمر والشيخوخة الصحية",
    "Nutrition & healthy dining habits": "التغذية وعادات الأكل الصحية",
    "Guided fitness & mobility": "اللياقة والحركة بإشراف مختص",
    "Mindfulness & lifestyle awareness": "اليقظة الذهنية والتوعية بأسلوب الحياة",
    "Curated peer discussions": "نقاشات مختارة مع الأقران",
    "Next 3 Months": "خلال 3 أشهر",
    "Next 6 Months": "خلال 6 أشهر",
    "Flexible": "مرن",
    "Flexible / Still exploring timing": "مرن / ما زلت أستكشف التوقيت",
    "Solo / Individual": "بمفردي",
    "To be evaluated with tailored proposal": "يُحدد مع المقترح المخصص",
    "To be evaluated with proposal": "يُحدد مع المقترح",
    "Open / Undecided (candidate market under exploration)": "لم تحدد بعد (قيد الاستكشاف)",
    "Help me compare destinations": "ساعدني في مقارنة الوجهات",
    "Next three months": "خلال ثلاثة أشهر",
    "I am still exploring timing": "ما زلت أستكشف التوقيت",
    "Accommodation assistance": "المساعدة في الإقامة",
    "Airport transfers": "النقل من المطار وإليه",
    "Translation support": "دعم الترجمة",
}

_DESTINATION_ACTIONS = {
    "Spain": ("dest_spain", "Spain", "I prefer Spain."),
    "Japan": ("dest_japan", "Japan", "I prefer Japan."),
    "United States": ("dest_us", "United States", "I prefer the United States."),
    "United Arab Emirates": ("dest_uae", "UAE", "I prefer the UAE."),
    "Singapore": ("dest_singapore", "Singapore", "I prefer Singapore."),
    "India": ("dest_india", "India", "I prefer India."),
    "Other / Undecided": ("dest_flexible", "Undecided / Open", "I am open to exploring any suitable destination."),
}


def _destination_actions(enquiry: SignatureProgrammeEnquiry) -> list[ChatAction]:
    """Offer only the destinations approved for the visitor's programme."""
    return [
        ChatAction(action_id=action_id, type="message", label=label, payload=payload, relevance="destination")
        for action_id, label, payload in (
            _DESTINATION_ACTIONS[name]
            for name in get_programme(ProgrammeId(enquiry.primary_programme)).candidate_destinations
        )
    ]


SIGN_IN_REPLY_EN = (
    "To take this further, please sign in or create a free account. "
    "This chat will move to your account, so you won't need to repeat anything."
)
SIGN_IN_REPLY_AR = (
    "للمتابعة، يُرجى تسجيل الدخول أو إنشاء حساب مجاني. "
    "ستنتقل هذه المحادثة إلى حسابك، فلن تحتاج إلى تكرار أي شيء."
)


def sign_in_action(language: str) -> ChatAction:
    """A button the website turns into a link to its sign-in page."""
    label = "تسجيل الدخول أو إنشاء حساب" if language == "ar" else "Sign in or create an account"
    return ChatAction(action_id="sign_in", type="sign_in", label=label, payload="sign_in", relevance="account")


def assign_reference_code(enquiry: SignatureProgrammeEnquiry) -> None:
    """Give a registered enquiry its reference number, once."""
    if not enquiry.reference_code:
        enquiry.reference_code = f"ENQ-{str(enquiry.enquiry_id)[:8].upper()}"


def _programme_name(enquiry: SignatureProgrammeEnquiry) -> str:
    try:
        return get_programme(ProgrammeId(enquiry.primary_programme)).name
    except ValueError:
        return "Signature Wellness Programmes"


def registration_reply(
    enquiry: SignatureProgrammeEnquiry,
    language: str,
    visitor: str | None = None,
    contactable: bool = False,
) -> str:
    """Confirm a registration, promising follow-up only if contact is possible."""
    prog_display = _programme_name(enquiry)
    if visitor == "customer":
        if language == "ar":
            follow_up = "سيراجع فريقنا تفضيلاتك ويتواصل معك عبر بيانات حسابك." if contactable else "سيراجع فريقنا تفضيلاتك."
            return (
                f"تم تسجيل اهتمامك في {prog_display} وحفظه في حسابك ضمن برامجي.\n\n"
                f"هذا التسجيل مجاني ولا يترتب عليه أي التزام أو حجز. {follow_up}"
            )
        follow_up = (
            "Our team will review your preferences and contact you using your account details."
            if contactable else "Our team will review your preferences."
        )
        return (
            f"Your interest in {prog_display} is registered and saved to your account under My Programmes.\n\n"
            f"This is free and non-binding, and it isn't a booking. {follow_up}"
        )
    has_authorized_contact = bool(enquiry.lead_phone or enquiry.lead_email)

    if language == "ar":
        if has_authorized_contact:
            contact_msg = "سيقوم منسق العافية المعتمد بمراجعة خيارات المقترح والتواصل معك عبر وسيلة التواصل المسجلة."
        else:
            contact_msg = (
                "نظراً لعدم جمع أي بيانات اتصال شخصية في هذه المحادثة، فلن يبدأ منسقو العافية تواصلاً مباشراً تلقائياً. "
                "يمكنك الاحتفاظ بالرقم المرجعي أعلاه واستخدامه عند التواصل معنا أو استكمال تسجيل وسيلة التواصل عبر بوابتنا الآمنة."
            )
        reply = (
            f"تم تسجيل اهتمامك بنجاح في {prog_display}! (الرقم المرجعي: {enquiry.reference_code})\n\n"
            "هذا التسجيل مجاني تماماً ولا يترتب عليه أي التزام مالي أو حجز تلقائي. "
            "سيقوم فريق تنسيق العافية بدراسة تفضيلاتك وتجهيز مقترح مخصص عند اكتمال ترتيبات الوجهة والمواعيد.\n\n"
            f"{contact_msg}"
        )
    else:
        if has_authorized_contact:
            contact_msg = "An authorized wellness coordinator will review your proposal options and follow up via your registered contact method."
        else:
            contact_msg = (
                "Because no personal contact details were requested or collected in this chat, "
                "our team will not initiate unsolicited outreach. You may reference this registration code "
                "whenever you choose to connect through our secure portal or authorized channels."
            )
        reply = (
            f"Thank you! Your interest in {prog_display} has been successfully registered! (Reference: {enquiry.reference_code})\n\n"
            "This registration of interest is completely free and non-binding. It is not an autonomous booking or charge. "
            "Our wellness coordination team will review your curated preferences and evaluate tailored retreat options as partner arrangements and dates are finalised.\n\n"
            f"{contact_msg}"
        )
    return reply


class ProgrammeConversationService:
    """Manages dialogue state, preference extraction, and enquiry lifecycle

    for Signature Wellness Programmes using an adaptive conversation state machine.
    """

    def __init__(self, store: MemoryStore) -> None:
        self.store = store

    def is_programme_intent(self, text: str, conversation: Conversation) -> bool:
        """Determine whether the message pertains to Signature Wellness Programmes."""
        if _SWITCH_TO_MEDICAL_RE.search(text):
            return False
        if _SWITCH_TO_SIGNATURE_RE.search(text):
            return True
        if _PROGRAMME_DETECTION_RE.search(text):
            return True
        if conversation.case_facts.get("service_category") == "signature_programmes":
            return True
        return False

    def handle_programme_message(
        self,
        conversation: Conversation,
        text: str,
        language: str,
        visitor: str | None = None,
        contactable: bool = False,
    ) -> dict[str, Any]:
        """Process a message within the Signature Wellness Programmes category."""
        conversation.case_facts["service_category"] = "signature_programmes"

        enquiry = self.store.get_programme_enquiry_for_conversation(conversation.id)
        if enquiry is None:
            enquiry = SignatureProgrammeEnquiry(
                conversation_id=conversation.id,
                session_id=conversation.session_id,
            )
            self.store.save_programme_enquiry(enquiry)

        lower_text = text.lower()
        reply: str
        suggestions: list[ChatAction] = []

        # 1. Decline to register or participate check
        if re.search(r"\b(not now|no thanks|prefer not to|not ready|don't want to share|maybe later)\b|لا أرغب الآن|ليس الآن|لاحقاً", lower_text):
            reply = REGISTRATION_DECLINED_AR if language == "ar" else REGISTRATION_DECLINED_EN
            return self._build_result(enquiry, reply, suggestions, language)

        # 2. Extract any multi-attribute details present in the current message
        self._extract_programme_facts(text, enquiry)
        self.store.save_programme_enquiry(enquiry)

        # 3. Check for general FAQ queries (Pricing, Dates, Destinations, Accommodations, Flights)
        faq_response = self._check_faq_queries(lower_text, language, enquiry)
        if faq_response:
            reply = faq_response
            suggestions = self._contextual_next_suggestions(enquiry, language)
            return self._build_result(enquiry, reply, suggestions, language)

        # 3b. Programme detail/info questions ("tell me about HAYAT-100",
        # "what do you offer", "what are the benefits") — answer from the
        # approved catalog instead of falling through to the stage prompt.
        detail_response = self._check_programme_detail_query(text, lower_text, language, enquiry)
        if detail_response:
            reply = detail_response
            suggestions = self._contextual_next_suggestions(enquiry, language)
            return self._build_result(enquiry, reply, suggestions, language)

        # 4. State Machine Evaluation
        # A. Registration intent triggered
        register_intent = bool(re.search(
            r"\b(register|sign up|note my interest|register interest|register my interest|confirm my interest|proceed with enquiry|submit enquiry)\b|"
            r"تسجيل|تسجيل اهتمامي|سجل اهتمامي|إبداء اهتمام|تأكيد اهتمامي",
            lower_text,
        ))

        if register_intent or enquiry.current_stage in (ProgrammeStage.REGISTRATION_CONSENT, ProgrammeStage.REGISTERED_INTEREST):
            return self._handle_registration_stage(enquiry, lower_text, language, visitor, contactable)

        # B. Check if user requested summary review
        summary_intent = bool(re.search(
            r"\b(summary|review|show my preferences|what do you have|check my details)\b|ملخص|مراجعة|عرض تفاصيلي",
            lower_text,
        ))
        if summary_intent or enquiry.current_stage == ProgrammeStage.SUMMARY_REVIEW:
            return self._handle_summary_review_stage(enquiry, language)

        # C. Initial Programme Selection / Identification
        # If user selected or mentioned healthy ageing / longevity:
        if enquiry.primary_programme != "hayat_100" and re.search(r"\b(healthy ageing|healthy aging|longevity|hayat[- ]?100)\b|الشيخوخة الصحية|طول العمر|حياة[- ]?100", lower_text):
            enquiry.primary_programme = "hayat_100"
            if "hayat_100" not in enquiry.interested_programmes:
                enquiry.interested_programmes.append("hayat_100")
            enquiry.current_stage = ProgrammeStage.PREFERENCE_COLLECTION
            self.store.save_programme_enquiry(enquiry)

            # Natural response identifying HAYAT-100 without repeating generic intro
            if language == "ar":
                reply = (
                    "يبدو أن برنامج HAYAT-100 هو البرنامج الأكثر توافقاً مع ما تبحث عنه. "
                    "تم تصميم هذا البرنامج حول طول العمر والشيخوخة الصحية، مع تجارب مقترحة تركز على التغذية السليمة، "
                    "والنشاط الحركي، والتوعية بأسلوب الحياة الصحي، والراحة والاستشفاء.\n\n"
                    "ما الذي يثير اهتمامك أكثر في رحلة الشيخوخة الصحية — التوعية بطول العمر، أم تحسين العادات الغذائية، "
                    "أم اللياقة والحركة، أم تخصيص وقت للراحة والاسترخاء؟"
                )
            else:
                reply = (
                    "That sounds like HAYAT-100 would be the programme most relevant to what you're exploring. "
                    "It's designed around longevity and healthy ageing, with experiences focused on nutrition, "
                    "movement, healthy lifestyle awareness, rest and recovery.\n\n"
                    "What interests you most about healthy ageing — learning about longevity, improving your lifestyle habits, "
                    "fitness and mobility, or simply taking time to focus on your wellbeing?"
                )
            suggestions = [
                ChatAction(action_id="h100_lifestyle", type="message", label="Lifestyle & nutrition", payload="I am interested in nutrition and healthy lifestyle habits.", relevance="focus"),
                ChatAction(action_id="h100_fitness", type="message", label="Fitness & mobility", payload="I want to focus on guided fitness, strength and mobility.", relevance="focus"),
                ChatAction(action_id="h100_sleep", type="message", label="Sleep & recovery", payload="I am interested in rest, sleep and recovery awareness.", relevance="focus"),
                ChatAction(action_id="h100_wellbeing", type="message", label="Focus on wellbeing", payload="I simply want time to step away and focus on my wellbeing.", relevance="focus"),
            ]
            return self._build_result(enquiry, reply, suggestions, language)

        # If user selected or mentioned women's wellness / AAfiya:
        if enquiry.primary_programme != "aafiya" and re.search(r"\b(women'?s (?:wellness|fitness|retreat)|aafiya|aafiyah|pilates|yoga for women)\b|عافية\s+السيدات|لياقة\s+السيدات|برنامج\s+السيدات|منتجع\s+السيدات|نسائي", lower_text):
            enquiry.primary_programme = "aafiya"
            if "aafiya" not in enquiry.interested_programmes:
                enquiry.interested_programmes.append("aafiya")
            enquiry.current_stage = ProgrammeStage.PREFERENCE_COLLECTION
            self.store.save_programme_enquiry(enquiry)

            if language == "ar":
                reply = (
                    "يبدو أن AAfiya هي التجربة الأنسب لما تبحثين عنه. AAfiya هي تجربة للياقة والعافية مخصصة للسيدات، "
                    "تجمع بين الحركة، والتغذية السليمة، والعناية الذاتية، والتواصل الإيجابي في بيئة مرحبة وداعمة لجميع المستويات.\n\n"
                    "ما نوع التجارب التي تفضلين التركيز عليها — تمارين البيلاتس واليوغا، أم ورش العمل الصحية، "
                    "أم التغذية المتوازنة، أم الاسترخاء والاستجمام؟"
                )
            else:
                reply = (
                    "That sounds like AAfiya would be the experience best suited to what you're looking for. "
                    "AAfiya is our women-focused fitness and wellness retreat centring on movement, nutrition, "
                    "self-care, and personal connection in a supportive, pressure-free setting for all fitness levels.\n\n"
                    "What kind of experience interests you most — pilates and yoga, wellness workshops, "
                    "balanced nutrition, or a quiet restorative break?"
                )
            suggestions = [
                ChatAction(action_id="aafiya_movement", type="message", label="Pilates & yoga", payload="I'm interested in pilates and yoga sessions.", relevance="focus"),
                ChatAction(action_id="aafiya_selfcare", type="message", label="Self-care workshops", payload="I want to focus on self-care and women's wellbeing workshops.", relevance="focus"),
                ChatAction(action_id="aafiya_rest", type="message", label="Restorative break", payload="I am seeking a restorative wellness break from daily routine.", relevance="focus"),
            ]
            return self._build_result(enquiry, reply, suggestions, language)

        # If user selected or mentioned executive wellness / FFounders:
        if enquiry.primary_programme != "ffounders" and re.search(r"\b(executive (?:wellness|fitness|retreat)|ffounders|f[- ]founders|founders|entrepreneurs?|c-suite|leadership)\b|فاوندرز|رواد الأعمال|القادة", lower_text):
            enquiry.primary_programme = "ffounders"
            if "ffounders" not in enquiry.interested_programmes:
                enquiry.interested_programmes.append("ffounders")
            enquiry.current_stage = ProgrammeStage.PREFERENCE_COLLECTION
            self.store.save_programme_enquiry(enquiry)

            if language == "ar":
                reply = (
                    "يبدو أن FFounders هو الخيار المثالي لك. FFounders هو منتجع متميز للياقة والعافية التنفيذية "
                    "مصمم لمؤسسي الشركات ورواد الأعمال والقادة لإعادة شحن طاقتهم، وبناء المرونة الجسدية والنفسية، "
                    "والتواصل البنّاء مع أقرانهم من قادة الأعمال.\n\n"
                    "ما الجانب الذي تود إعطاءه الأولوية — اللياقة والقوة البدنية، أم إدارة التوتر والتعافي، "
                    "أم علوم النوم والأداء، أم النقاشات المثرية مع رواد الأعمال؟"
                )
            else:
                reply = (
                    "That sounds like FFounders would be the ideal retreat. FFounders is our executive fitness and "
                    "wellness retreat created for founders, entrepreneurs, and business leaders to reset, build resilience, "
                    "and optimize recovery alongside fellow leaders.\n\n"
                    "What areas would you most like to focus on — physical strength and conditioning, stress resilience, "
                    "sleep and recovery science, or curated peer discussions?"
                )
            suggestions = [
                ChatAction(action_id="ff_strength", type="message", label="Strength & conditioning", payload="I want to focus on guided strength and physical conditioning.", relevance="focus"),
                ChatAction(action_id="ff_resilience", type="message", label="Stress & recovery", payload="I'm interested in stress management, sleep science and recovery.", relevance="focus"),
                ChatAction(action_id="ff_peers", type="message", label="Curated peer connections", payload="I value curated peer discussions alongside wellness.", relevance="focus"),
            ]
            return self._build_result(enquiry, reply, suggestions, language)

        # If user mentioned all three:
        all_three_intent = bool(
            re.search(r"\b(all three|all of them|interested in all|every programme|all programmes)\b|جميعها|كلها|الثلاثة معاً", lower_text)
            or ("hayat" in lower_text and "aafiya" in lower_text and "ffounders" in lower_text)
        )
        if all_three_intent:
            enquiry.interested_programmes = ["hayat_100", "aafiya", "ffounders"]
            enquiry.current_stage = ProgrammeStage.PROGRAMME_SELECTED
            self.store.save_programme_enquiry(enquiry)
            reply = ALL_THREE_INTEREST_AR if language == "ar" else ALL_THREE_INTEREST_EN
            suggestions = [
                ChatAction(action_id="p_h100", type="message", label="HAYAT-100", payload="I would prioritise HAYAT-100", relevance="priority programme"),
                ChatAction(action_id="p_aafiya", type="message", label="AAfiya", payload="I would prioritise AAfiya", relevance="priority programme"),
                ChatAction(action_id="p_ffounders", type="message", label="FFounders", payload="I would prioritise FFounders", relevance="priority programme"),
            ]
            return self._build_result(enquiry, reply, suggestions, language)

        # If visitor has not yet selected a primary programme:
        if not enquiry.primary_programme:
            enquiry.current_stage = ProgrammeStage.DISCOVERY
            self.store.save_programme_enquiry(enquiry)
            reply = SIGNATURE_PROGRAMMES_INTRO_AR if language == "ar" else SIGNATURE_PROGRAMMES_INTRO_EN
            suggestions = [
                ChatAction(action_id="sel_h100", type="message", label="HAYAT-100 (Longevity)", payload="I want healthy ageing and longevity.", relevance="programme selection"),
                ChatAction(action_id="sel_aafiya", type="message", label="AAfiya (Women's Wellness)", payload="Tell me about AAfiya women's retreat.", relevance="programme selection"),
                ChatAction(action_id="sel_ffounders", type="message", label="FFounders (Executive Wellness)", payload="Tell me about FFounders executive retreat.", relevance="programme selection"),
                ChatAction(action_id="sel_all", type="message", label="I'm interested in all three", payload="I am interested in all three programmes.", relevance="multi-programme"),
            ]
            return self._build_result(enquiry, reply, suggestions, language)

        # D. Progression based on missing conditional fields
        # If programme is known but destination is not yet collected:
        if enquiry.primary_programme and not enquiry.destination_preference:
            enquiry.current_stage = ProgrammeStage.DESTINATION_PREFERENCE
            self.store.save_programme_enquiry(enquiry)
            act_ack = ""
            if enquiry.activity_interests:
                act_ack = "سجلت اهتماماتك. " if language == "ar" else f"I've noted your interest in {', '.join(enquiry.activity_interests)}. "
            aafiya = enquiry.primary_programme == ProgrammeId.AAFIYA.value
            if language == "ar":
                countries = (
                    "الإمارات، والهند، واليابان، وسنغافورة" if aafiya
                    else "إسبانيا، واليابان، والولايات المتحدة، والإمارات، وسنغافورة، والهند"
                )
                reply = (
                    f"{act_ack}نستكشف حالياً وجهات متميزة للمنتجعات في {countries}، إلى جانب وجهات دولية أخرى ملائمة.\n\n"
                    "هل لديك وجهة أو دولة مفضلة، أم ترغب في استكشاف كافة الخيارات المتاحة دون تفضيل محدد؟"
                )
            else:
                countries = (
                    "the UAE, India, Japan, and Singapore" if aafiya
                    else "Spain, Japan, the United States, the UAE, Singapore, and India"
                )
                reply = (
                    f"{act_ack}We are currently exploring candidate retreat destinations across {countries}, "
                    "alongside other suitable international locations.\n\n"
                    "Do you have a preferred country in mind, or are you open to exploring available options?"
                )
            suggestions = _destination_actions(enquiry)
            return self._build_result(enquiry, reply, suggestions, language)

        # If destination is known but travel period is not yet collected:
        if enquiry.destination_preference and not enquiry.preferred_travel_period:
            enquiry.current_stage = ProgrammeStage.TRAVEL_PERIOD
            self.store.save_programme_enquiry(enquiry)
            dest_ack = "سجلت وجهتك المفضلة. " if language == "ar" else f"I have noted your destination preference for {enquiry.destination_preference}. "
            if language == "ar":
                reply = (
                    f"{dest_ack}مواعيد الرحلات والمنتجعات قيد الإعداد حالياً مع شركائنا.\n\n"
                    "هل لديك شهر مفضل أو فترة محددة للسفر (مثلاً خلال الأشهر الثلاثة أو الستة القادمة)؟"
                )
            else:
                reply = (
                    f"{dest_ack}The retreat dates and itineraries are actively being curated with destination partners.\n\n"
                    "Do you have a preferred month or travel period in mind (for example, the next 3 to 6 months)?"
                )
            suggestions = [
                ChatAction(action_id="timing_3m", type="message", label="Next 3 months", payload="I prefer the next 3 months.", relevance="timing"),
                ChatAction(action_id="timing_6m", type="message", label="Next 6 months", payload="I prefer the next 6 months.", relevance="timing"),
                ChatAction(action_id="timing_flex", type="message", label="Flexible on dates", payload="I am flexible on travel dates.", relevance="timing"),
            ]
            return self._build_result(enquiry, reply, suggestions, language)

        # If travel period is known but group preference is not yet noted:
        if enquiry.preferred_travel_period and not enquiry.group_size and not enquiry.group_participation:
            enquiry.current_stage = ProgrammeStage.GROUP_PREFERENCES
            self.store.save_programme_enquiry(enquiry)
            if language == "ar":
                reply = (
                    "هل تخطط للمشاركة بمفردك كتجربة شخصية، أم تفكر في الحضور مع زوج/زوجة، أو صديق، أو مجموعة صغيرة؟"
                )
            else:
                reply = (
                    "Would you be planning to participate individually as a solo retreat experience, "
                    "or are you considering joining with a spouse, friend, or colleagues?"
                )
            suggestions = [
                ChatAction(action_id="grp_solo", type="message", label="Individual / Solo", payload="I plan to attend individually.", relevance="group"),
                ChatAction(action_id="grp_pair", type="message", label="With spouse / friend", payload="I am interested in attending with a spouse or friend.", relevance="group"),
                ChatAction(action_id="grp_team", type="message", label="With colleagues", payload="I am considering joining with a small leadership team.", relevance="group"),
            ]
            return self._build_result(enquiry, reply, suggestions, language)

        # If group is noted but optional budget has not been asked:
        if not enquiry.budget_range and enquiry.current_stage == ProgrammeStage.GROUP_PREFERENCES:
            enquiry.current_stage = ProgrammeStage.OPTIONAL_BUDGET
            self.store.save_programme_enquiry(enquiry)
            if language == "ar":
                reply = (
                    "نظراً لأن كل تجربة منتجع يتم تصميمها بشكل مخصص وفردي، فإنه لا يوجد سعر ثابت للباقة. "
                    "إذا كان لديك نطاق ميزانية تقديري، يمكنك مشاركته لمساعدة فريقنا في إعداد خيارات ملائمة، "
                    "أو يمكننا استكشاف المقترحات أولاً بناءً على تفضيلاتك."
                )
            else:
                reply = (
                    "Because each retreat experience is individually curated, there is no fixed package price. "
                    "If you have an optional budget preference in mind, you may share it to help our team tailor proposal options, "
                    "or we can evaluate suitable options based on your preferences first."
                )
            suggestions = [
                ChatAction(action_id="bud_proposals", type="message", label="Explore proposals first", payload="I would like to explore tailored proposals first.", relevance="budget"),
                ChatAction(action_id="bud_review", type="message", label="Review my summary", payload="Please show me my preference summary.", relevance="summary"),
            ]
            return self._build_result(enquiry, reply, suggestions, language)

        # If all core preferences are gathered, present Summary Review:
        return self._handle_summary_review_stage(enquiry, language)

    def _handle_summary_review_stage(
        self,
        enquiry: SignatureProgrammeEnquiry,
        language: str,
    ) -> dict[str, Any]:
        """Present the structured enquiry summary and offer registration of interest."""
        enquiry.current_stage = ProgrammeStage.SUMMARY_REVIEW
        self.store.save_programme_enquiry(enquiry)

        prog_title = _programme_name(enquiry)
        dest_display = enquiry.destination_preference or "Open / Undecided (candidate market under exploration)"
        time_display = enquiry.preferred_travel_period or enquiry.preferred_month or "Flexible"
        activities_display = ", ".join(enquiry.activity_interests) if enquiry.activity_interests else "Wellness, healthy lifestyle & recovery"
        group_display = "Solo / Individual" if not enquiry.group_participation else f"Group ({enquiry.group_size or 'multiple participants'})"
        budget_display = enquiry.budget_range or "To be evaluated with tailored proposal"

        if language == "ar":
            dest_display, time_display, budget_display = (
                ARABIC_LABELS.get(value, value) for value in (dest_display, time_display, budget_display)
            )
            if enquiry.activity_interests:
                activities_display = "، ".join(ARABIC_LABELS.get(item, item) for item in enquiry.activity_interests)
            else:
                activities_display = "العافية وأسلوب الحياة الصحي والتعافي"
            group_display = "بمفردي" if not enquiry.group_participation else f"مجموعة ({enquiry.group_size or 'عدة مشاركين'})"
            reply = (
                f"إليك ملخص تفضيلاتك لرحلة العافية حتى الآن:\n\n"
                f"• البرنامج: {prog_title}\n"
                f"• مجالات الاهتمام: {activities_display}\n"
                f"• الوجهة المفضلة: {dest_display}\n"
                f"• فترة السفر: {time_display}\n"
                f"• نوع المشاركة: {group_display}\n"
                f"• الميزانية: {budget_display}\n"
                f"• التسعير: مخصص بالكامل (لا يوجد سعر باقة ثابت)\n\n"
                "هل تود تسجيل اهتمامك مجاناً وبدون أي التزام حتى يتمكن فريق تنسيق العافية من مراجعة تفضيلاتك وإعداد مقترح مخصص عند اكتمال الترتيبات؟"
            )
        else:
            reply = (
                f"Here is a summary of your retreat preferences so far:\n\n"
                f"• Programme: {prog_title}\n"
                f"• Areas of Interest: {activities_display}\n"
                f"• Destination Preference: {dest_display}\n"
                f"• Preferred Timing: {time_display}\n"
                f"• Participation: {group_display}\n"
                f"• Budget Preference: {budget_display}\n"
                f"• Pricing: Individually curated (tailored proposal)\n\n"
                "Would you like to register your interest for a tailored proposal? "
                "Registration of interest is completely free and non-binding."
            )

        suggestions = [
            ChatAction(action_id="confirm_reg", type="message", label="Register my interest", payload="Yes, please register my interest.", relevance="registration"),
            ChatAction(action_id="edit_dest", type="message", label="Change destination", payload="I would like to change my destination preference.", relevance="edit"),
            ChatAction(action_id="edit_time", type="message", label="Change timing", payload="I would like to change my travel timing.", relevance="edit"),
        ]
        return self._build_result(enquiry, reply, suggestions, language)

    def _handle_registration_stage(
        self,
        enquiry: SignatureProgrammeEnquiry,
        lower_text: str,
        language: str,
        visitor: str | None = None,
        contactable: bool = False,
    ) -> dict[str, Any]:
        """Record registration of interest, assign reference code, and enforce Policy Addendum 1.1."""
        if visitor == "guest":
            reply = SIGN_IN_REPLY_AR if language == "ar" else SIGN_IN_REPLY_EN
            return self._build_result(enquiry, reply, [sign_in_action(language)], language)

        enquiry.registration_status = RegistrationStatus.INTEREST_REGISTERED
        enquiry.enquiry_status = EnquiryStatus.SUBMITTED
        # No contact details are collected in chat, so contact consent stays
        # PENDING — it can only become GRANTED through the approved secure flow.
        enquiry.current_stage = ProgrammeStage.REGISTERED_INTEREST

        assign_reference_code(enquiry)
        self.store.save_programme_enquiry(enquiry)
        reply = registration_reply(enquiry, language, visitor, contactable)

        suggestions = [
            ChatAction(action_id="view_summary", type="message", label="Review my summary", payload="Please show me my preference summary.", relevance="summary"),
            ChatAction(action_id="faq_pricing", type="message", label="How is pricing determined?", payload="How is pricing determined?", relevance="faq"),
            ChatAction(action_id="switch_med", type="message", label="Explore medical travel", payload="Can I switch to medical travel for cardiology?", relevance="switch"),
        ]
        return self._build_result(enquiry, reply, suggestions, language)

    def _extract_programme_facts(self, text: str, enquiry: SignatureProgrammeEnquiry) -> None:
        """Extract preferences from the message without asking duplicate questions."""
        lower = text.lower()

        # Destination extraction
        dest_patterns = {
            "spain": "Spain",
            "japan": "Japan",
            "united states": "United States",
            "usa": "United States",
            "uae": "United Arab Emirates",
            "dubai": "United Arab Emirates",
            "abu dhabi": "United Arab Emirates",
            "singapore": "Singapore",
            "india": "India",
            "إسبانيا": "Spain",
            "اليابان": "Japan",
            "أمريكا": "United States",
            "الإمارات": "United Arab Emirates",
            "سنغافورة": "Singapore",
            "الهند": "India",
        }
        for term, canonical in dest_patterns.items():
            if term in lower:
                enquiry.destination_preference = canonical
                break
        destination_flexible = re.search(
            r"\b(no (?:such |strong |particular |real )?preference|no preference|any(thing)? is fine|"
            r"up to you|whatever you (?:recommend|suggest|think)|surprise me|don'?t mind|open to (?:any|options|suggestions)|"
            r"you choose|you decide|help me choose|not sure yet|undecided)\b|"
            r"لا تفضيل|لا يوجد (?:لدي |عندي )?تفضيل|بدون تفضيل|ما عندي تفضيل|أي وجهة|"
            r"كما تشاء|لا يهمني|مفتوح على الخيارات|غير متأكد|لا أعلم",
            lower,
        )
        if not enquiry.destination_preference and (
            destination_flexible
            or (
                _SKIP_KEYWORDS_RE.search(lower)
                and (
                    "destination" in lower
                    or "country" in lower
                    or "place" in lower
                    or enquiry.current_stage == ProgrammeStage.DESTINATION_PREFERENCE
                )
            )
        ):
            enquiry.destination_preference = "Undecided / Open to exploring options"

        # Timing extraction
        timing_patterns = [
            r"\b(next (?:3|three) months|next (?:6|six) months|october|november|december|january|february|march|april|may|june|july|august|september|spring|summer|autumn|fall|winter)\b",
            r"خلال (?:ثلاثة|ستة) أشهر|أكتوبر|نوفمبر|ديسمبر|يناير|فبراير|مارس|أبريل|مايو|يونيو|يوليو|أغسطس|سبتمبر|الربيع|الصيف|الخريف|الشتاء",
        ]
        for pat in timing_patterns:
            m = re.search(pat, lower)
            if m:
                enquiry.preferred_travel_period = m.group(0).strip().title()
                break
        if not enquiry.preferred_travel_period and _SKIP_KEYWORDS_RE.search(lower) and ("timing" in lower or "date" in lower or enquiry.current_stage == ProgrammeStage.TRAVEL_PERIOD):
            enquiry.preferred_travel_period = "Flexible / Still exploring timing"

        # Activities extraction
        activity_terms = {
            "pilates": "Pilates & core strength",
            "yoga": "Yoga & stretching",
            "longevity": "Longevity & healthy ageing awareness",
            "sleep": "Rest, sleep & recovery awareness",
            "recovery": "Rest, sleep & recovery awareness",
            "nutrition": "Nutrition & healthy dining habits",
            "dining": "Nutrition & healthy dining habits",
            "fitness": "Guided fitness & mobility",
            "mobility": "Guided fitness & mobility",
            "strength": "Strength & conditioning",
            "mindfulness": "Mindfulness & lifestyle awareness",
            "meditation": "Mindfulness & lifestyle awareness",
            "self-care": "Self-care & personal wellbeing",
            "peer": "Curated peer discussions",
            "networking": "Curated peer discussions",
        }
        for kw, canonical in activity_terms.items():
            if kw in lower and canonical not in enquiry.activity_interests:
                enquiry.activity_interests.append(canonical)

        # Group preference
        if re.search(r"\b(solo|individually|myself|alone| بمفردي|بمفردي|شخصي)\b", lower):
            enquiry.group_participation = False
            enquiry.group_size = 1
        elif re.search(r"\b(spouse|partner|friend|colleague|colleagues|team|group|زوج|زوجة|صديق|فريق|مجموعة)\b", lower):
            enquiry.group_participation = True

        # Budget extraction
        budget_m = re.search(r"\b(?:\$|usd|eur|gbp|aed)?\s?(\d{1,3}(?:,\d{3})+|\d{4,6})\b", lower)
        if budget_m and "month" not in lower and "day" not in lower:
            enquiry.budget_range = f"Estimated: {budget_m.group(0).strip()}"
        elif "evaluate proposals first" in lower or "explore proposals" in lower:
            enquiry.budget_range = "To be evaluated with proposal"

    def _check_faq_queries(self, lower_text: str, language: str, enquiry: SignatureProgrammeEnquiry) -> str | None:
        """Ground responses to user questions in approved knowledge."""
        if _SKIP_KEYWORDS_RE.search(lower_text):
            return None

        if any(term in lower_text for term in ["price", "cost", "pricing", "package price", "how much", "rate", "سعر", "تكلفة"]):
            return PRICING_EXPLANATION_AR if language == "ar" else PRICING_EXPLANATION_EN

        if any(term in lower_text for term in ["flight", "flights", "airfare", "طيران", "تذاكر"]):
            return (
                "The seven-day duration includes two travel days allocated for outbound and return travel. "
                "However, flight arrangements and inclusions are not confirmed as part of a fixed package; "
                "logistics depend on the selected destination and confirmed retreat proposal."
                if language == "en" else
                "تشمل مدة الأيام السبعة يومين مخصصين للسفر ذهاباً وإياباً، لكن ترتيبات تذاكر الطيران غير مؤكدة كباقة ثابتة، "
                "وتعتمد الترتيبات على الوجهة المحددة والمقترح النهائي."
            )

        if any(term in lower_text for term in ["date", "dates", "when", "timing", "schedule", "موعد", "مواعيد", "متى"]):
            return DATES_EXPLANATION_AR if language == "ar" else DATES_EXPLANATION_EN

        if any(term in lower_text for term in ["where will", "where are", "locations", "which country", "countries", "أين", "وجهات"]):
            if enquiry.primary_programme == ProgrammeId.AAFIYA.value:
                return AAFIYA_DESTINATIONS_EXPLANATION_AR if language == "ar" else AAFIYA_DESTINATIONS_EXPLANATION_EN
            return DESTINATIONS_EXPLANATION_AR if language == "ar" else DESTINATIONS_EXPLANATION_EN

        return None

    def _resolve_programme(self, lower_text: str, enquiry: SignatureProgrammeEnquiry) -> ProgrammeId | None:
        """Resolve which programme a detail question refers to: an explicit
        programme name in the message wins, then the enquiry's primary or sole
        interested programme."""
        if re.search(r"hayat[- ]?100|حياة[- ]?100", lower_text):
            return ProgrammeId.HAYAT_100
        if re.search(r"aafiya|aafiyah|عافية\s+السيدات|برنامج\s+السيدات", lower_text):
            return ProgrammeId.AAFIYA
        if re.search(r"ffounders|f[- ]?founders|فاوندرز", lower_text):
            return ProgrammeId.FFOUNDERS
        if enquiry.primary_programme in (p.value for p in ProgrammeId):
            return ProgrammeId(enquiry.primary_programme)
        if len(enquiry.interested_programmes) == 1:
            return ProgrammeId(enquiry.interested_programmes[0])
        return None

    def _check_programme_detail_query(
        self,
        text: str,
        lower_text: str,
        language: str,
        enquiry: SignatureProgrammeEnquiry,
    ) -> str | None:
        """Answer "tell me about / what do you offer / benefits" questions from
        the approved programme catalog instead of repeating the stage prompt."""
        if _SKIP_KEYWORDS_RE.search(lower_text) or not _PROGRAMME_INFO_RE.search(lower_text):
            return None
        # A bare first mention ("tell me about AAfiya") should go through the
        # programme-selection branch, which records the choice and offers
        # activity suggestions. Only answer directly when the visitor is
        # already inside a programme or asks a deeper question.
        deeper_intent = re.search(
            r"offer|included|benefit|detail|explain|guide|understand|more|again|really|actually|mean|"
            r"ماذا تقدم|فوائد|تفاصيل|اشرح|مزيد|فهمت|لا أفهم|الفرق",
            lower_text,
        )
        if not enquiry.primary_programme and not deeper_intent:
            return None
        pid = self._resolve_programme(lower_text, enquiry)
        if pid is None:
            return None
        detail = get_programme(pid)
        if detail is None:
            return None

        if not enquiry.primary_programme:
            enquiry.primary_programme = pid.value
            if pid.value not in enquiry.interested_programmes:
                enquiry.interested_programmes.append(pid.value)
            if enquiry.current_stage in (ProgrammeStage.DISCOVERY, ProgrammeStage.PROGRAMME_SELECTED):
                enquiry.current_stage = ProgrammeStage.PREFERENCE_COLLECTION
            self.store.save_programme_enquiry(enquiry)

        if language == "ar":
            ar = _PROGRAMME_AR_DETAIL.get(pid.value, {})
            return (
                f"{detail.name} — {ar.get('focus', '')}\n\n"
                f"فكرة البرنامج: \"{ar.get('philosophy', '')}\"\n\n"
                f"تركز التجربة على: {ar.get('themes', '')}.\n\n"
                "يمكنك أيضاً أن تسألني عن الوجهات، أو الأسعار، أو شكل اليوم النموذجي في المنتجع."
            )
        themes = ", ".join(detail.distinguishing_themes[:5])
        return (
            f"{detail.name} — {detail.tagline}.\n\n"
            f"{detail.focus}\n\n"
            f'The idea behind it: "{detail.philosophy}"\n\n'
            f"It's a {detail.duration_total_days}-day experience "
            f"({detail.retreat_days} days of retreat activities plus {detail.travel_days} travel days), "
            f"built around {themes}.\n\n"
            "You can also ask me about destinations, pricing, or what a typical day looks like."
        )

    def _contextual_next_suggestions(
        self,
        enquiry: SignatureProgrammeEnquiry,
        language: str,
    ) -> list[ChatAction]:
        """Generate suggestions that naturally guide the visitor to the next enquiry step."""
        if not enquiry.primary_programme:
            return [
                ChatAction(action_id="sel_h100", type="message", label="HAYAT-100 (Longevity)", payload="I want healthy ageing and longevity.", relevance="programme selection"),
                ChatAction(action_id="sel_aafiya", type="message", label="AAfiya (Women's Wellness)", payload="Tell me about AAfiya women's retreat.", relevance="programme selection"),
                ChatAction(action_id="sel_ffounders", type="message", label="FFounders (Executive Wellness)", payload="Tell me about FFounders executive retreat.", relevance="programme selection"),
            ]
        if not enquiry.destination_preference:
            return _destination_actions(enquiry)
        if not enquiry.preferred_travel_period:
            return [
                ChatAction(action_id="time_3m", type="message", label="Next 3 months", payload="I prefer the next 3 months.", relevance="timing"),
                ChatAction(action_id="time_flex", type="message", label="Flexible on timing", payload="I am flexible on travel timing.", relevance="timing"),
            ]
        if enquiry.registration_status != RegistrationStatus.INTEREST_REGISTERED:
            return [
                ChatAction(action_id="reg_confirm", type="message", label="Register my interest", payload="Yes, please register my interest.", relevance="registration"),
                ChatAction(action_id="show_summary", type="message", label="Review my summary", payload="Please show me my preference summary.", relevance="summary"),
            ]
        return [
            ChatAction(action_id="show_summary", type="message", label="Review my summary", payload="Please show me my preference summary.", relevance="summary"),
            ChatAction(action_id="switch_med", type="message", label="Explore medical travel", payload="Can I switch to medical travel for cardiology?", relevance="switch"),
        ]

    def _build_result(
        self,
        enquiry: SignatureProgrammeEnquiry,
        reply: str,
        suggestions: list[ChatAction],
        language: str,
    ) -> dict[str, Any]:
        if language == "ar":
            suggestions = [
                action.model_copy(update={"label": ARABIC_LABELS.get(action.label, action.label)})
                for action in suggestions
            ]
        return {
            "reply": reply,
            "answer": reply,
            "suggestions": suggestions,
            "suggested_actions": suggestions,
            "programme_enquiry": enquiry,
            "service_category": "signature_programmes",
        }
