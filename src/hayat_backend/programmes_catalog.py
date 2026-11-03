"""Signature Wellness Programmes Catalog and Approved Knowledge Repository.

Sourced directly from docs/knowledge/signature_programmes.md.
"""

from __future__ import annotations

from typing import Any
from .schemas.programme import (
    ProgrammeDetail,
    ProgrammeFAQ,
    ProgrammeId,
)

SIGNATURE_PROGRAMMES_INTRO_EN: str = (
    "We have three signature wellness experiences, each designed around a different aspect of wellbeing.\n\n"
    "HAYAT-100 focuses on longevity and healthy ageing.\n\n"
    "AAfiya is a women's fitness and wellness experience.\n\n"
    "FFounders is an executive fitness and wellness retreat for founders, entrepreneurs and business leaders.\n\n"
    "Each programme is designed as a seven-day experience, including five days of retreat activities and two travel days.\n\n"
    "May I ask which of these interests you most?"
)

SIGNATURE_PROGRAMMES_INTRO_AR: str = (
    "لدينا ثلاث تجارب عافية متميزة، كل منها مصمم حول جانب مختلف من جوانب العافية وجودة الحياة.\n\n"
    "يركز برنامج حياة-100 على طول العمر والشيخوخة الصحية.\n\n"
    "وعافية هي تجربة للياقة والعافية مخصصة للسيدات.\n\n"
    "أما فاوندرز فهو منتجع للياقة والعافية التنفيذية مخصص لمؤسسي الشركات ورواد الأعمال والقادة.\n\n"
    "تم تصميم كل برنامج كتجربة مدتها سبعة أيام، تشمل خمسة أيام من أنشطة المنتجع ويومين للسفر.\n\n"
    "هل لي أن أسأل أي من هذه البرامج يثير اهتمامك أكثر؟"
)

PRICING_EXPLANATION_EN: str = (
    "Each of our retreats is individually curated, so there is no fixed package price. "
    "Pricing depends on your preferred destination, accommodation, experiences and the level of customisation. "
    "Our team can explore a suitable experience and prepare a tailored proposal once we understand your preferences."
)

PRICING_EXPLANATION_AR: str = (
    "يتم تصميم كل منتجع من منتجعاتنا بشكل فردي ومخصص، لذا لا يوجد سعر ثابت للباقة. "
    "تعتمد التكلفة على الوجهة المفضلة، ونوع الإقامة، والأنشطة ومستوى التخصيص. "
    "يمكن لفريقنا دراسة خيارات مناسبة وإعداد مقترح مخصص بمجرد فهم تفضيلاتك."
)

DESTINATIONS_EXPLANATION_EN: str = (
    "We are exploring premium retreat destinations across the Americas, Europe, the Middle East and Asia, "
    "including the United States, Spain, Japan, Singapore, India, and the United Arab Emirates. "
    "These destinations are currently being explored, and specific retreat facilities and dates are yet to be confirmed."
)

DESTINATIONS_EXPLANATION_AR: str = (
    "نستكشف وجهات متميزة للمنتجعات في الأمريكتين وأوروبا والشرق الأوسط وآسيا، "
    "بما في ذلك الولايات المتحدة وإسبانيا واليابان وسنغافورة والهند والإمارات العربية المتحدة. "
    "هذه الوجهات قيد الاستكشاف حالياً، وسيتم تأكيد المواقع والمواعيد لاحقاً."
)

DATES_EXPLANATION_EN: str = (
    "The retreat dates are still being curated. Do you have a preferred month or travel period? "
    "I can make a note of it for our team."
)

DATES_EXPLANATION_AR: str = (
    "مواعيد الرحلات والمنتجعات قيد الإعداد حالياً. هل لديك شهر مفضل أو فترة محددة للسفر؟ "
    "يمكنني تسجيل ذلك لفريق التنسيق."
)

ALL_THREE_INTEREST_EN: str = (
    "That's lovely. Each programme offers a different experience. "
    "I can note your interest in all three, and our team can share more information as the programmes develop. "
    "Is there one you'd currently prioritise?"
)

ALL_THREE_INTEREST_AR: str = (
    "رائع جداً. يقدم كل برنامج تجربة متميزة ومختلفة. "
    "يمكنني تسجيل اهتمامك بالبرامج الثلاثة، وسيقوم فريقنا بمشاركتك المزيد من المعلومات مع اكتمال تفاصيلها. "
    "هل هناك برنامج تود إعطاءه الأولوية حالياً؟"
)

REGISTRATION_DECLINED_EN: str = (
    "Of course. There's no pressure to register. "
    "You're welcome to explore the programmes and return whenever you're ready."
)

REGISTRATION_DECLINED_AR: str = (
    "بالتأكيد، لا يوجد أي إلزام للتسجيل. "
    "يسعدنا استكشافك للبرامج ويمكنك العودة في أي وقت عندما تكون مستعداً."
)

PROGRAMMES_CATALOG: dict[ProgrammeId, ProgrammeDetail] = {
    ProgrammeId.HAYAT_100: ProgrammeDetail(
        programme_id=ProgrammeId.HAYAT_100,
        name="HAYAT-100",
        tagline="Longevity & Healthy Ageing Retreat",
        focus="Longevity and healthy ageing through nutrition, movement, sleep, mindfulness and expert-led learning.",
        philosophy="It is not just about living to 100. It is about making every year count.",
        duration_total_days=7,
        retreat_days=5,
        travel_days=2,
        intended_audience=[
            "Adults of all stages interested in longevity and healthy ageing",
            "Professionals wanting a proactive approach to lifelong wellbeing",
            "People interested in nutrition, fitness and lifestyle optimisation",
            "Individuals seeking a premium wellness break",
        ],
        distinguishing_themes=[
            "Understanding healthy ageing and longevity concepts",
            "Personal health and lifestyle priorities",
            "Nutrition and healthy eating habits",
            "Physical activity, strength and mobility",
            "Rest, sleep and recovery science",
            "Mindfulness and stress management",
            "Restorative wellness experiences",
            "Peer connections around healthier living",
        ],
        proposed_experiences={
            "health_awareness": [
                "Personal health and lifestyle assessments",
                "General wellness consultations",
                "Longevity education sessions",
            ],
            "fitness_movement": [
                "Guided fitness activities",
                "Strength and mobility sessions",
                "Yoga and stretching",
                "Walking and outdoor activities",
            ],
            "nutrition_dining": [
                "Healthy dining experiences",
                "Nutrition workshops and mindful eating",
            ],
            "restoration": [
                "Meditation and mindfulness",
                "Relaxation and restorative spa experiences",
            ],
        },
        faqs=[
            ProgrammeFAQ(
                question="Is HAYAT-100 a medical programme?",
                answer="No. It is primarily a wellness and healthy-ageing retreat concept. Any clinical assessments or consultations included would be delivered by appropriately qualified healthcare professionals.",
            ),
            ProgrammeFAQ(
                question="Why is it called HAYAT-100?",
                answer="The name reflects the programme's aspiration to encourage people to think about longevity, healthy ageing and making every year count. It is not a promise or guarantee of living to 100.",
            ),
            ProgrammeFAQ(
                question="Does HAYAT-100 offer anti-ageing treatments or disease cures?",
                answer="No. The programme focuses on healthy ageing, longevity awareness and wellness experiences. It does not promise anti-ageing clinical treatments, guarantee longevity, or cure disease.",
            ),
            ProgrammeFAQ(
                question="Is the programme suitable for people in their 30s or 40s?",
                answer="Yes. The programme is intended for adults at different stages of life who are interested in healthy ageing, not only older individuals.",
            ),
        ],
    ),
    ProgrammeId.AAFIYA: ProgrammeDetail(
        programme_id=ProgrammeId.AAFIYA,
        name="AAfiya",
        tagline="Women's Fitness & Wellness Retreat",
        focus="A women-focused fitness and wellness retreat centring on movement, nutrition, self-care, and personal connection.",
        philosophy="Your journey. Your wellbeing. Your way.",
        duration_total_days=7,
        retreat_days=5,
        travel_days=2,
        intended_audience=[
            "Women looking to prioritise their wellbeing and take time for themselves",
            "Women interested in fitness, pilates, yoga and physical activity",
            "Women seeking a restorative wellness break from everyday routines",
            "Women at different stages of their fitness journey (beginners welcome)",
        ],
        distinguishing_themes=[
            "Movement without pressure or competition",
            "Fitness at different levels and abilities",
            "Women's wellbeing and self-care",
            "Nutrition and healthier lifestyle choices",
            "Mental and emotional balance",
            "Confidence and personal growth",
            "Friendship and meaningful peer connections",
        ],
        proposed_experiences={
            "fitness_movement": [
                "Pilates and yoga sessions",
                "Guided fitness, strength and conditioning",
                "Mobility and stretching",
                "Outdoor movement activities",
            ],
            "womens_wellbeing": [
                "Women's health and lifestyle workshops",
                "Self-care discussions and personal growth",
            ],
            "nutrition_dining": [
                "Nutrition workshops and healthy dining experiences",
                "Mindful eating practices",
            ],
            "mindfulness_community": [
                "Meditation, mindfulness and spa relaxation",
                "Curated group wellness and social gatherings",
            ],
        },
        faqs=[
            ProgrammeFAQ(
                question="What does AAfiya mean?",
                answer="AAfiya (عافية) is an Arabic word associated with wellbeing, holistic health, and vitality.",
            ),
            ProgrammeFAQ(
                question="Is AAfiya exclusively for women?",
                answer="Yes. AAfiya is designed specifically as a women-focused retreat experience.",
            ),
            ProgrammeFAQ(
                question="Do I need to be physically fit to participate?",
                answer="No particular fitness level is required to express interest. The programme is designed to accommodate different levels of experience, from complete beginners to active individuals.",
            ),
            ProgrammeFAQ(
                question="Is AAfiya only about intense fitness?",
                answer="No. Movement is just one part. AAfiya equally focuses on nutrition, relaxation, self-care, personal reflection and connecting with like-minded women.",
            ),
        ],
    ),
    ProgrammeId.FFOUNDERS: ProgrammeDetail(
        programme_id=ProgrammeId.FFOUNDERS,
        name="FFounders",
        tagline="Executive Fitness & Wellness Retreat",
        focus="A premium retreat for founders, entrepreneurs and business leaders to reset, build physical and mental resilience, and recharge.",
        philosophy="Building a successful business should never come at the expense of building a healthier life.",
        duration_total_days=7,
        retreat_days=5,
        travel_days=2,
        intended_audience=[
            "Startup founders and entrepreneurs",
            "Business owners and investors",
            "C-suite executives and senior corporate leaders",
            "Leaders facing high-pressure demands who want to invest in sustainable health",
        ],
        distinguishing_themes=[
            "Physical fitness, strength and vitality",
            "Stress management, resilience and nervous system regulation",
            "Sleep, recovery and performance science",
            "Nutrition and sustainable energy",
            "Mental wellbeing and executive mindfulness",
            "Curated peer connections with ambitious leaders",
        ],
        proposed_experiences={
            "executive_wellness": [
                "Personal health and lifestyle assessments",
                "Executive wellbeing workshops and resilience sessions",
            ],
            "fitness_performance": [
                "Guided fitness, strength, conditioning and mobility",
                "Outdoor challenge and movement sessions",
            ],
            "recovery_sleep": [
                "Sleep and recovery awareness",
                "Stress-management and restorative practices",
            ],
            "peer_community": [
                "Curated founder gatherings and confidential peer discussions",
                "Leadership and lifestyle exploration in a relaxed setting",
            ],
        },
        faqs=[
            ProgrammeFAQ(
                question="Is FFounders a business conference or networking event?",
                answer="No. Its primary purpose is personal fitness, wellness and health. Curated peer networking is an organic, valuable secondary dimension, but it is not a conference.",
            ),
            ProgrammeFAQ(
                question="Is FFounders only for tech startup founders?",
                answer="No. It is designed for founders, entrepreneurs, investors, C-suite executives and leaders across industries.",
            ),
            ProgrammeFAQ(
                question="Do I need to be in peak physical condition?",
                answer="No. You can express interest regardless of your current fitness level; activities will be tailored to suit participants.",
            ),
            ProgrammeFAQ(
                question="Can leadership teams attend together?",
                answer="Yes. Co-founders and executive colleagues can express interest together.",
            ),
        ],
    ),
}


def get_programme(programme_id: str | ProgrammeId) -> ProgrammeDetail | None:
    try:
        pid = ProgrammeId(programme_id.lower().replace("-", "_"))
        return PROGRAMMES_CATALOG.get(pid)
    except ValueError:
        return None
