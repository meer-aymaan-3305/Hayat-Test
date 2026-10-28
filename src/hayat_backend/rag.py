"""Approved-knowledge retrieval boundary.

The implementation uses explicitly supplied approved knowledge records.
It does not ingest arbitrary user uploads or unvetted external sources.
"""

from __future__ import annotations

from dataclasses import dataclass
import re


@dataclass(frozen=True)
class SourceReference:
    document_id: str
    title: str
    version: str


@dataclass(frozen=True)
class KnowledgeChunk:
    text: str
    source: SourceReference
    approved: bool = True


DEFAULT_APPROVED_KNOWLEDGE: list[KnowledgeChunk] = [
    KnowledgeChunk(
        text=(
            "What information to prepare: To prepare for a medical travel consultation with Hayat, "
            "it is helpful to have your recent medical records, formal diagnostic reports, imaging files "
            "(such as MRI, CT scans, or X-rays), your current list of prescribed medications, and a copy of "
            "your valid passport available if you have them. Specific medical records or imaging files are not "
            "strictly mandatory for initial coordination; a human coordinator will advise if particular records "
            "are needed after initial review. For wellness programmes, prepare your primary wellness goals, general "
            "health background, dietary preferences, and any physical mobility considerations."
        ),
        source=SourceReference(
            document_id="hayat-prep-v1",
            title="Hayat Consultation Preparation Guide",
            version="1.0",
        ),
        approved=True,
    ),
    KnowledgeChunk(
        text=(
            "ما المعلومات التي أحتاج إلى تجهيزها: للاستعداد لاستشارة السفر الطبي مع حياة، من المفيد توفير "
            "التقارير الطبية الحديثة، ونتائج الفحوصات التشخيصية وصور الأشعة، وقائمة الأدوية الحالية، ونسخة من جواز السفر إن وجدت. "
            "لا يُشترط تقديم وثائق معينة بشكل إلزامي في البداية؛ سيوضح المنسق البشري ما إذا كانت هناك حاجة لتقارير إضافية. "
            "وبالنسبة لبرامج العافية، يرجى تجهيز أهدافك الصحية وتاريخك الصحي العام وأي تفضيلات غذائية."
        ),
        source=SourceReference(
            document_id="hayat-prep-ar-v1",
            title="دليل التحضير للاستشارة - حياة",
            version="1.0",
        ),
        approved=True,
    ),
    KnowledgeChunk(
        text=(
            "Comparing medical travel destinations: India is recognized for internationally accredited "
            "(JCI) multi-specialty hospitals with advanced cardiology, orthopedics, and oncology departments, "
            "offering high-quality tertiary procedures with significant cost advantages. Hayat coordinates with "
            "accredited partner hospital departments rather than individual private physician practices. "
            "Oman provides high-quality regional specialized care, serene recovery settings, and dedicated wellness retreats. "
            "The UAE (Dubai and Abu Dhabi) features cutting-edge medical infrastructure, premium private hospitals, and leading "
            "cosmetic and preventive centers. Thailand is a premier international hub for medical tourism, dental procedures, and "
            "holistic integrative wellness retreats. Germany and the UK provide access to world-renowned university medical centers "
            "for rare or highly complex diagnostic cases."
        ),
        source=SourceReference(
            document_id="hayat-destinations-v1",
            title="Hayat Destination Comparison & Overview",
            version="1.0",
        ),
        approved=True,
    ),
    KnowledgeChunk(
        text=(
            "مقارنة وجهات السفر الطبي: تتميز الهند بمستشفيات معتمدة دولياً في أقسام جراحة القلب والعظام "
            "والأورام مع تكلفة اقتصادية مناسبة. وتتعاون حياة مع أقسام المستشفيات المعتمدة شريكة النجاح وليس مع أطباء أفراد بشكل مباشر. "
            "وتقدم سلطنة عمان رعاية إقليمية متخصصة وأجواء هادئة للاستشفاء والعافية. بينما توفر الإمارات مرافق طبية متطورة "
            "ومراكز متقدمة في الفحوصات والتجميل. وتشتهر تايلاند بالسياحة العلاجية والمنتجعات الصحية المتكاملة."
        ),
        source=SourceReference(
            document_id="hayat-destinations-ar-v1",
            title="مقارنة الوجهات العلاجية - حياة",
            version="1.0",
        ),
        approved=True,
    ),
    KnowledgeChunk(
        text=(
            "Hayat wellness programmes: Hayat offers structured, non-clinical wellness programmes tailored to "
            "individual goals including mental health and stress management, healthy ageing and longevity, sleep enhancement, "
            "preventive health screening, and holistic physical detox. These programmes combine lifestyle medicine, mindfulness, "
            "nutrition guidance, and therapeutic spa modalities. They are preventive wellness journeys and do not replace "
            "acute clinical or psychiatric care."
        ),
        source=SourceReference(
            document_id="hayat-wellness-v1",
            title="Hayat Wellness & Longevity Programmes",
            version="1.0",
        ),
        approved=True,
    ),
    KnowledgeChunk(
        text=(
            "برامج العافية في حياة: تقدم حياة برامج عافية متكاملة تشمل إدارة التوتر والصحة النفسية، وتحسين جودة النوم، "
            "وطول العمر والشيخوخة الصحية، والفحوصات الوقائية، والتعافي الشامل. تجمع هذه البرامج بين تغيير نمط الحياة والتغذية "
            "السليمة وجلسات الاسترخاء، وهي برامج وقائية لتحسين جودة الحياة ولا تحل محل الرعاية الطبية السريرية الطارئة."
        ),
        source=SourceReference(
            document_id="hayat-wellness-ar-v1",
            title="برامج العافية وجودة الحياة - حياة",
            version="1.0",
        ),
        approved=True,
    ),
    KnowledgeChunk(
        text=(
            "Hayat coordination and consultation workflow: Hayat assists patients and wellness seekers with coordination, "
            "collecting preliminary intake details, and submitting consultation requests. A human coordinator reviews every "
            "consultation request to verify partner hospital availability, schedules, customized price estimates, and travel logistics. "
            "Hayat does not recommend specific individual doctors, check live provider availability autonomously, send document upload links, "
            "or confirm live hospital appointments without human coordinator verification."
        ),
        source=SourceReference(
            document_id="hayat-coordination-v1",
            title="Hayat Medical Coordination & Booking Policies",
            version="1.0",
        ),
        approved=True,
    ),
]


class InMemoryRetriever:
    """Retrieve approved knowledge passages grounded in validated source materials."""

    def __init__(self, chunks: list[KnowledgeChunk] | None = None) -> None:
        self._chunks = list(chunks) if chunks is not None else list(DEFAULT_APPROVED_KNOWLEDGE)

    async def retrieve(self, query: str, limit: int = 3) -> list[KnowledgeChunk]:
        stopwords = {
            "a", "an", "the", "and", "or", "in", "on", "at", "to", "for", "of", "with",
            "is", "are", "was", "were", "be", "been", "i", "me", "my", "you", "your",
            "we", "our", "he", "she", "it", "they", "what", "which", "how", "when",
            "where", "who", "can", "could", "would", "should", "do", "does", "did",
            "please", "help", "tell", "about", "want", "like", "need", "interested",
            "من", "في", "على", "إلى", "عن", "مع", "هل", "ما", "ماذا", "كيف", "أين",
            "متى", "أنا", "أريد", "ممكن", "يرجى", "لو", "سمحت",
        }
        tokens = [w.lower() for w in re.findall(r"[\w'-]+", query) if len(w) > 1]
        meaningful_terms = [t for t in tokens if t not in stopwords] or tokens

        scored: list[tuple[float, KnowledgeChunk]] = []
        lower_query = query.lower()

        for chunk in self._chunks:
            if not chunk.approved:
                continue
            chunk_lower = chunk.text.lower()
            score = 0.0

            # Direct phrase overlap bonuses
            for term in meaningful_terms:
                if term in chunk_lower:
                    score += 1.5

            # Keyword combination signals
            if "destination" in lower_query or "وجه" in lower_query or "compare" in lower_query or "مقارن" in lower_query:
                if "comparing medical travel destinations" in chunk_lower or "مقارنة وجهات" in chunk_lower:
                    score += 4.0
            if "prepare" in lower_query or "تجهيز" in lower_query or "مستند" in lower_query or "information" in lower_query:
                if "what information to prepare" in chunk_lower or "ما المعلومات التي أحتاج" in chunk_lower:
                    score += 4.0
            if "wellness" in lower_query or "stress" in lower_query or "mental" in lower_query or "sleep" in lower_query or "عافي" in lower_query:
                if "hayat wellness programmes" in chunk_lower or "برامج العافية" in chunk_lower:
                    score += 3.0

            if score > 0.0:
                scored.append((score, chunk))

        scored.sort(key=lambda item: item[0], reverse=True)
        return [chunk for _, chunk in scored[:limit]]
