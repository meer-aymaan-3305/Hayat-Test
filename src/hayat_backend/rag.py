"""Approved-knowledge retrieval boundary.

The implementation uses explicitly supplied approved knowledge records.
It does not ingest arbitrary user uploads or unvetted external sources.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
import math
import re

_MIN_RELEVANCE = 1.0


def _tokenize(text: str) -> list[str]:
    return [w.lower() for w in re.findall(r"[\w'-]+", text) if len(w) > 1]


def _stem(word: str) -> str:
    """Very light English suffix stripping so 'programmes' matches 'programme'."""
    if not word.isascii() or len(word) < 5:
        return word
    for suffix in ("ing", "ed", "es", "s"):
        if word.endswith(suffix) and len(word) - len(suffix) >= 4:
            return word[: -len(suffix)]
    return word


def _term_counts(text: str) -> Counter[str]:
    return Counter(_stem(t) for t in _tokenize(text))


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
    KnowledgeChunk(
        text=(
            "Trawellcare Signature Wellness Programmes Overview: Trawellcare is developing three distinctive "
            "premium wellness retreat programmes: HAYAT-100 (longevity & healthy ageing), AAfiya (women's fitness "
            "& wellness), and FFounders (executive fitness & wellness for founders and leaders). "
            "Each signature programme is designed as a seven-day experience comprising five retreat days and two travel days. "
            "All three programmes are individually curated with no fixed or standard package price. "
            "Potential retreat destinations being explored include the United States, Spain, Japan, Singapore, "
            "India, and the United Arab Emirates. Specific facilities, dates and retreat partners are currently under curation. "
            "Visitors can register their interest without any payment or booking commitment."
        ),
        source=SourceReference(
            document_id="hayat-signature-overview-v1",
            title="Trawellcare Signature Wellness Programmes Overview",
            version="1.0",
        ),
        approved=True,
    ),
    KnowledgeChunk(
        text=(
            "HAYAT-100 Longevity & Healthy Ageing Retreat: A signature longevity and healthy-ageing retreat concept "
            "designed for adults across different stages of life who want to invest in their future health. "
            "Philosophy: It is not just about living to 100; it is about making every year count. "
            "Core proposed components include personal health and lifestyle awareness, longevity education, guided fitness "
            "and mobility, healthy dining and nutrition workshops, and restorative mindfulness and sleep/rest recovery education. "
            "These are proposed experiences under curation with destination partners rather than guaranteed clinical treatments. "
            "HAYAT-100 is a non-clinical wellness retreat and does not offer anti-ageing medical treatments, cure diseases, "
            "or guarantee a specific lifespan or health outcome."
        ),
        source=SourceReference(
            document_id="hayat-100-longevity-v1",
            title="HAYAT-100 Longevity Retreat Guide",
            version="1.0",
        ),
        approved=True,
    ),
    KnowledgeChunk(
        text=(
            "AAfiya Women's Fitness & Wellness Retreat: A women-focused retreat designed to step away from daily routines "
            "and reconnect through movement, nutrition, self-care, and relaxation. Philosophy: Your journey. Your wellbeing. Your way. "
            "AAfiya is exclusively for women and welcomes all fitness levels from beginners to active individuals without any fitness prerequisites. "
            "Proposed activities include pilates, yoga, guided strength and conditioning, women's health workshops, mindful eating, "
            "restorative spa experiences, and curated group connection."
        ),
        source=SourceReference(
            document_id="hayat-aafiya-women-v1",
            title="AAfiya Women's Retreat Guide",
            version="1.0",
        ),
        approved=True,
    ),
    KnowledgeChunk(
        text=(
            "FFounders Executive Fitness & Wellness Retreat: A premium retreat created for startup founders, entrepreneurs, "
            "investors, and C-suite business leaders to recharge, reset, and build resilience. "
            "Philosophy: Building a successful business should never come at the expense of building a healthier life. "
            "Focus areas include physical conditioning, energy and vitality, sleep and recovery science, stress management, "
            "and curated peer discussions with fellow leaders. FFounders is primarily a fitness and wellness retreat, not a business conference."
        ),
        source=SourceReference(
            document_id="hayat-ffounders-executive-v1",
            title="FFounders Executive Retreat Guide",
            version="1.0",
        ),
        approved=True,
    ),
    KnowledgeChunk(
        text=(
            "Signature Programmes Pricing & Customisation: All three signature programmes (HAYAT-100, AAfiya, FFounders) "
            "are individually curated, and there is no fixed package price or generic package rate. "
            "Pricing depends on the selected destination country, retreat facility, accommodation tier, activities, services, "
            "and customisation requirements. A tailored proposal is prepared after understanding the visitor's preferences and expectations."
        ),
        source=SourceReference(
            document_id="hayat-signature-pricing-v1",
            title="Signature Programmes Pricing and Customisation Policy",
            version="1.0",
        ),
        approved=True,
    ),
    KnowledgeChunk(
        text=(
            "Signature Programmes Potential Destinations & Schedule: Trawellcare is exploring candidate destinations across the "
            "Americas, Europe and Asia, including the United States, Spain, Japan, Singapore, India, and the UAE. "
            "These are markets under exploration rather than confirmed facilities. Dates and itineraries are actively being curated. "
            "Each retreat is planned as a seven-day experience with five retreat days and two travel days."
        ),
        source=SourceReference(
            document_id="hayat-signature-destinations-v1",
            title="Signature Programmes Destination Exploration Guide",
            version="1.0",
        ),
        approved=True,
    ),
    KnowledgeChunk(
        text=(
            "برامج العافية المتميزة - نظرة عامة: تطور ترافيل كير ثلاثة برامج عافية متميزة: "
            "HAYAT-100 (طول العمر والشيخوخة الصحية)، وAAfiya (لياقة وعافية السيدات)، وFFounders (لياقة وعافية القادة ورواد الأعمال). "
            "مدة كل برنامج سبعة أيام (خمسة أيام منتجع ويومان للسفر). يتم تصميم البرامج بشكل مخصص وفردي دون سعر ثابت للباقة. "
            "الوجهات قيد الاستكشاف تشمل أمريكا وإسبانيا واليابان وسنغافورة والهند والإمارات. التسجيل مجاني ولا يترتب عليه أي التزام مالي."
        ),
        source=SourceReference(
            document_id="hayat-signature-overview-ar-v1",
            title="نظرة عامة على برامج العافية المتميزة - حياة",
            version="1.0",
        ),
        approved=True,
    ),
]


class InMemoryRetriever:
    """Retrieve approved knowledge passages grounded in validated source materials."""

    def __init__(self, chunks: list[KnowledgeChunk] | None = None) -> None:
        self._chunks = list(chunks) if chunks is not None else list(DEFAULT_APPROVED_KNOWLEDGE)

    def replace_uploaded(self, chunks: list[KnowledgeChunk]) -> None:
        """Swap in re-indexed approved-knowledge chunks (built-in defaults stay)."""
        self._chunks = [
            c for c in self._chunks
            if not c.source.document_id.startswith("doc-")
        ] + list(chunks)

    def add_chunks(self, chunks: list[KnowledgeChunk]) -> None:
        """Add newly indexed approved-knowledge chunks."""
        self._chunks.extend(chunks)

    async def retrieve_scored(self, query: str, limit: int = 3) -> list[tuple[float, KnowledgeChunk]]:
        """Like retrieve() but keeps relevance scores for attribution gating."""
        return await self._retrieve(query, limit)

    async def retrieve(self, query: str, limit: int = 3) -> list[KnowledgeChunk]:
        scored = await self._retrieve(query, limit)
        return [chunk for _, chunk in scored]

    async def _retrieve(self, query: str, limit: int = 3) -> list[tuple[float, KnowledgeChunk]]:
        stopwords = {
            "a", "an", "the", "and", "or", "in", "on", "at", "to", "for", "of", "with",
            "is", "are", "was", "were", "be", "been", "i", "me", "my", "you", "your",
            "we", "our", "he", "she", "it", "they", "what", "which", "how", "when",
            "where", "who", "can", "could", "would", "should", "do", "does", "did",
            "please", "help", "tell", "about", "want", "like", "need", "interested",
            "من", "في", "على", "إلى", "عن", "مع", "هل", "ما", "ماذا", "كيف", "أين",
            "متى", "أنا", "أريد", "ممكن", "يرجى", "لو", "سمحت",
        }
        tokens = _tokenize(query)
        meaningful_terms = {_stem(t) for t in tokens if t not in stopwords} or {
            _stem(t) for t in tokens
        }

        active = [c for c in self._chunks if c.approved]
        chunk_terms = [_term_counts(c.text) for c in active]
        n_docs = max(len(active), 1)
        avg_len = (sum(sum(tc.values()) for tc in chunk_terms) / n_docs) or 1.0

        scored: list[tuple[float, KnowledgeChunk]] = []
        lower_query = query.lower()

        for chunk, counts in zip(active, chunk_terms):
            chunk_lower = chunk.text.lower()
            score = 0.0

            # BM25 over whole (lightly stemmed) words. Replaces raw substring
            # matching, which let short fragments match almost any chunk.
            doc_len = sum(counts.values()) or 1
            for term in meaningful_terms:
                tf = counts.get(term, 0)
                if not tf:
                    continue
                df = sum(1 for tc in chunk_terms if term in tc)
                idf = math.log(1 + (n_docs - df + 0.5) / (df + 0.5))
                score += 2.2 * idf * (tf * 2.2) / (tf + 1.2 * (0.25 + 0.75 * doc_len / avg_len))

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

            # Signature Wellness Programmes signals
            if "hayat-100" in lower_query or "hayat 100" in lower_query or "longevity" in lower_query or "ageing" in lower_query or "aging" in lower_query:
                if "hayat-100" in chunk_lower or "longevity" in chunk_lower:
                    score += 5.0
            if "aafiya" in lower_query or "عافية" in lower_query or "women" in lower_query or "pilates" in lower_query:
                if "aafiya" in chunk_lower or "عافية" in chunk_lower or "women" in chunk_lower:
                    score += 5.0
            if "ffounders" in lower_query or "founder" in lower_query or "executive" in lower_query or "فاوندرز" in lower_query:
                if "ffounders" in chunk_lower or "executive" in chunk_lower:
                    score += 5.0
            if "signature" in lower_query or "retreat" in lower_query or "retreats" in lower_query:
                if "signature wellness programmes" in chunk_lower or "برامج العافية المتميزة" in chunk_lower:
                    score += 4.0
            if any(term in lower_query for term in ["price", "cost", "how much", "rate", "سعر", "تكلفة"]):
                if "pricing & customisation" in chunk_lower or "individually curated" in chunk_lower:
                    score += 5.0

            if score >= _MIN_RELEVANCE:
                scored.append((score, chunk))

        scored.sort(key=lambda item: item[0], reverse=True)
        return scored[:limit]
