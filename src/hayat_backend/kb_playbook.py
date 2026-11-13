"""The knowledge base's own answers and questions, followed as written.

The Signature Programmes document gives Hayat approved FAQ answers (sections 2 to 5) and the
suggested responses and questions for the situations in section 6. When a visitor's message is one
of those situations, Hayat answers with the document's text and asks the document's question,
instead of improvising. Names and wording rules still apply afterwards (current programme names,
trawellcare in lower case), and a question about something already settled is left out.

Section 6.6 (collecting contact details in chat) is deliberately not followed: the newer training
documents send contact details to signup and login.
"""

from __future__ import annotations

import os
import re
import zipfile
from dataclasses import dataclass, field
from functools import lru_cache
from html import unescape
from pathlib import Path
from typing import Any

from .programmes_registry import alias_pattern, programmes

DOC_NAME = "trawellcare SIGNATURE PROGRAMMES.docx"

# Section 6 of the document, as written.
S61_OVERVIEW = (
    "We have three signature wellness experiences, each designed around a different aspect of wellbeing. "
    "HAYAT-100 focuses on longevity and healthy ageing. AAfiya is a women's fitness and wellness experience. "
    "FFounders is an executive fitness and wellness retreat for founders, entrepreneurs and business leaders. "
    "Each programme is designed as a seven-day experience, including five days of retreat activities and two travel days."
)
Q61 = "May I ask which of these interests you most?"
Q62 = "What interests you most about this experience?"
S63_PRICE = (
    "Each of our retreats is individually curated, so there is no fixed package price. Pricing depends on your "
    "preferred destination, accommodation, experiences and the level of customisation."
)
Q63 = "May I ask which destination you are considering?"
S63_NO_DESTINATION = (
    "That's absolutely fine. Are there any countries or regions you would particularly like to explore? "
    "I can note your preference for our team."
)
S63_QUOTE = (
    "Our team can explore a suitable experience and prepare a customised proposal once we understand your "
    "preferences and requirements."
)
S64_DATES = (
    "The retreat dates are still being curated. Do you have a preferred month or travel period? "
    "I can make a note of it for our team."
)
S65_DESTINATIONS = (
    "We are exploring destinations across the Americas, Europe, the Middle East and Asia. "
    "Do you have a particular country or destination in mind?"
)
S67_ALL_THREE = (
    "That's lovely. Each programme offers a different experience. I can note your interest in all three, and our "
    "team can share more information as the programmes develop. Is there one you'd currently prioritise?"
)

_QUOTE_RE = re.compile(r"\b(quote|quotation|proposal|estimate)\b", re.I)
_PRICE_RE = re.compile(r"\b(price|prices|pricing|cost|costs|how much|fee|fees|rates?|expensive|afford)\b", re.I)
_DATES_RE = re.compile(r"\b(dates?|when (?:is|are|does|will|can)|next retreat|when.*(?:start|begin|take place|happen))\b", re.I)
_WHERE_RE = re.compile(
    r"\b(where (?:is|are|will|does|do|would)|which (?:country|countries|destination|destinations|place)|"
    r"destinations?|location|locations|held|take place|taking place|located)\b", re.I,
)
_ALL_THREE_RE = re.compile(r"\b(all three|all 3|all of them|every one|each of them|all the programmes)\b", re.I)
_OVERVIEW_RE = re.compile(
    r"\b(what|which) (?:programmes?|retreats?|programs?)\b|\b(three|3) (?:signature )?(?:programmes?|retreats?|programs?)\b|"
    r"\b(?:tell me about|show me|explain|what are) (?:the |your |all )?(?:signature )?(?:programmes?|retreats?|programs?)\b|"
    r"\bwhat (?:wellness )?(?:experiences|retreats|programmes) do you (?:have|offer)\b", re.I,
)
_WELLNESS_RE = re.compile(r"\b(retreat|retreats|programme|programmes|wellness|longevity|fitness|healthy ageing)\b", re.I)
_SKIP_FAQ = re.compile(
    r"register|contact details|contact me|how will trawellcare contact|\bmean\b|express interest without|"
    r"interest for a family member", re.I,
)
_STOP = frozenset(
    "a an the is are was were be been am do does did can could would should will may might i me my we our you your "
    "it its this that these those of to in on at for with and or but if so as by from about into over than then there "
    "what which who whom how why when where any some more most much many very also just only not no yes please tell "
    "me us".split()
)
_WOMEN_RE = re.compile(r"\bwomen'?s? (?:one|programme|program|retreat)\b|\bthe women'?s\b", re.I)
_EXEC_RE = re.compile(r"\b(?:executive|founders?') (?:one|programme|program|retreat)\b|\bthe executive\b", re.I)


@dataclass
class KbReply:
    text: str
    chips: list[str] = field(default_factory=list)
    slot: str | None = None  # the slot the question asks about, so the visitor's answer fills it
    topic: str = ""


@dataclass(frozen=True)
class Faq:
    programme: str  # programme id, or "general"
    number: str
    question: str
    answer: str


def _doc_path() -> Path | None:
    for base in (os.environ.get("KB_SEED_DIR"), Path(__file__).resolve().parents[2] / "knowledge_seed"):
        if base and (Path(base) / DOC_NAME).exists():
            return Path(base) / DOC_NAME
    return None


def _docx_lines(path: Path) -> list[str]:
    xml = zipfile.ZipFile(path).read("word/document.xml").decode("utf-8")
    xml = re.sub(r"</w:p>", "\n", xml)
    return [unescape(re.sub(r"<[^>]+>", "", line)).strip() for line in xml.split("\n")]


@lru_cache
def faqs() -> tuple[Faq, ...]:
    """Every Q and A of sections 2 to 5, with the programme each belongs to."""
    path = _doc_path()
    if path is None:
        return ()
    try:
        lines = _docx_lines(path)
    except (OSError, KeyError, zipfile.BadZipFile):
        return ()
    names = {p.name.lower(): p.id for p in programmes()}
    section = "general"
    out: list[Faq] = []
    current: tuple[str, str] | None = None
    answer: list[str] = []

    def flush() -> None:
        nonlocal current, answer
        if current and answer:
            out.append(Faq(section, current[0], current[1], " ".join(answer).strip()))
        current, answer = None, []

    for line in lines:
        if not line:
            continue
        heading = re.match(r"^\d+\.\s+(.+)$", line)
        if heading and not re.match(r"^\d+\.\d", line):
            flush()
            title = heading.group(1).lower()
            if "hayat-100" in title:
                section = names.get("hayat-100", "hayat-100")
            elif "aafiya" in title or "zoé" in title or "zoe" in title:
                section = "zoe"
            elif "ffounders" in title:
                section = "ffounders"
            elif "general faq" in title:
                section = "general"
            else:
                section = "other"
            continue
        question = re.match(r"^Q(\d+)\.\s+(.+\?)\s*$", line)
        if question and section != "other":
            flush()
            current = (question.group(1), question.group(2))
            continue
        if current is not None:
            if re.match(r"^\d+\.\d", line) or line.isupper():
                flush()
            else:
                answer.append(line)
    flush()
    return tuple(out)


def _programme_in(text: str) -> str | None:
    """The programme id a text names, by current or former name."""
    lowered = text.lower()
    for programme in programmes():
        names = [programme.name, *programme.former_names]
        if programme.id == "hayat-100":
            names.append("hayat 100")
        if programme.id == "zoe":
            names.append("zoe")
        if any(re.search(rf"\b{re.escape(n.lower())}\b", lowered.replace("é", "e")) or n.lower() in lowered for n in names):
            return programme.id
    if _WOMEN_RE.search(text):
        return "zoe"
    if _EXEC_RE.search(text):
        return "ffounders"
    return None


def _tokens(text: str) -> set[str]:
    drop = {n.lower().replace("é", "e") for p in programmes() for n in (p.name, *p.former_names)} | {"hayat"}
    words = re.findall(r"[a-z]{3,}", re.sub(r"[^a-z\s]", " ", text.lower().replace("é", "e")))
    return {w.rstrip("s") for w in words if w not in _STOP and w not in drop}


def _best_faq(text: str, programme: str | None) -> Faq | None:
    wanted = _tokens(text)
    if len(wanted) < 1:
        return None
    best: tuple[float, Faq] | None = None
    pool = [f for f in faqs() if f.programme in {"general", programme} and not _SKIP_FAQ.search(f.question)]
    frequency: dict[str, int] = {}
    for faq in pool:
        for word in _tokens(faq.question):
            frequency[word] = frequency.get(word, 0) + 1
    for faq in pool:
        q = _tokens(faq.question)
        shared = wanted & q
        rare_single = len(shared) == 1 and len(wanted) <= 4 and frequency.get(next(iter(shared)), 9) <= 3
        if len(shared) < 2 and not rare_single and not (q and len(q) <= 2 and shared == q):
            continue
        score = len(shared) / max(1, len(q))
        if faq.programme == programme and programme:
            score += 0.1  # the programme's own answer beats the general one
        if score >= (0.3 if rare_single else 0.5) and (best is None or score > best[0]):
            best = (score, faq)
    return best[1] if best else None


def _intro(programme: str) -> str | None:
    for faq in faqs():
        if faq.programme == programme and faq.number == "1":
            return faq.answer
    return None


def _faq_for(programme: str, pattern: str) -> str | None:
    for faq in faqs():
        if faq.programme == programme and re.search(pattern, faq.question, re.I):
            return faq.answer
    return None


def _name(programme: str | None) -> str:
    for p in programmes():
        if p.id == programme:
            return p.name
    return "this programme"


def _settled(state: Any, slot_id: str) -> bool:
    return state.status(slot_id) in {"CONFIRMED", "HEARD", "UNSURE", "DECLINED"}


def _chips_for(programme: str | None, topic: str) -> list[str]:
    if topic == "overview":
        return [f"Tell me about {p.name}" for p in programmes()][:3]
    if topic == "all_three":
        return [f"I'd prioritise {p.name}" for p in programmes()][:3]
    if topic in {"price", "quote"}:
        return ["Which destination?", "I'm flexible on destination", "Tell me about dates"]
    if topic == "dates":
        return ["Next few months", "Later this year", "I'm flexible"]
    if topic == "destinations":
        return ["I'm flexible", "Somewhere in Europe", "How much does it cost?"]
    return ["What's included?", "Where is it held?", "How much does it cost?"]


def respond(
    text: str, *, recent_text: str, state: Any, focus: str | None, last_assistant: str,
    answered_before: list[str],
) -> KbReply | None:
    """The document's answer and question for this message, or None when it is not covered."""
    named = _programme_in(text)
    context = named or _programme_in(recent_text) or _programme_in(
        str(state.value("w.programme_interest") or "")
    )
    wellness = bool(named or _WELLNESS_RE.search(text) or focus == "WELLNESS" or context)
    if not wellness or not faqs() and not S61_OVERVIEW:
        return None

    def done(reply: KbReply) -> KbReply | None:
        flat = re.sub(r"\W+", " ", reply.text.lower())[:80]
        if any(flat and flat in re.sub(r"\W+", " ", earlier.lower()) for earlier in answered_before):
            return None  # never say the same thing twice in a row: let the model vary it
        return reply

    asking = "?" in text or bool(re.match(r"\s*(?:when|what|which|where|how|do you|are there|is there|can i|could i)\b", text, re.I))
    destination_known = _settled(state, "w.destination")
    dates_known = _settled(state, "w.dates_window")

    if _ALL_THREE_RE.search(text) and (named is None):
        return done(KbReply(S67_ALL_THREE, _chips_for(None, "all_three"), None, "all_three"))

    if Q63.lower() in last_assistant.lower() and re.search(
        r"not sure|don'?t know|no idea|haven'?t decided|undecided|not yet|flexible|no preference|open to|anywhere|any country",
        text, re.I,
    ):
        return done(KbReply(S63_NO_DESTINATION, _chips_for(context, "destinations"), "w.destination", "price"))

    if asking and (_PRICE_RE.search(text) or _QUOTE_RE.search(text)):
        if _QUOTE_RE.search(text):
            return done(KbReply(S63_QUOTE, _chips_for(context, "quote"), None, "quote"))
        if "which destination" in last_assistant.lower() or "countries or regions" in last_assistant.lower():
            return done(KbReply(S63_NO_DESTINATION, _chips_for(context, "price"), "w.destination", "price"))
        body = S63_PRICE  # section 6.3 is the document's answer for every programme
        question = "" if destination_known else f" {Q63}"
        return done(KbReply(body + question, _chips_for(context, "price"),
                            None if destination_known else "w.destination", "price"))

    if asking and (_DATES_RE.search(text) or re.search(r"\b(when|dates?)\b", text, re.I)):
        return done(KbReply(S64_DATES if not dates_known else S64_DATES.split(" Do you")[0], _chips_for(None, "dates"),
                            None if dates_known else "w.dates_window", "dates"))

    if asking and _WHERE_RE.search(text):
        own = _faq_for(context, r"where") if context else None
        if own:
            question = "" if destination_known else " Do you have a particular country or destination in mind?"
            return done(KbReply(own + question, _chips_for(context, "destinations"),
                                None if destination_known else "w.destination", "destinations"))
        if not destination_known:
            return done(KbReply(S65_DESTINATIONS, _chips_for(None, "destinations"), "w.destination", "destinations"))
        return done(KbReply(S65_DESTINATIONS.split(" Do you")[0], _chips_for(None, "destinations"), None, "destinations"))

    if _OVERVIEW_RE.search(text) and named is None:
        return done(KbReply(S61_OVERVIEW + " " + Q61, _chips_for(None, "overview"), None, "overview"))

    faq = _best_faq(text, named or context)
    if faq is not None:
        question = ""
        if not _settled(state, "w.goal_category") and not any(Q62.lower() in a.lower() for a in answered_before[-3:]):
            question = " " + Q62
        return done(KbReply(faq.answer + question, _chips_for(named or context, "faq"),
                            "w.goal_category" if question else None, "faq"))

    if named and re.search(r"\b(tell me|about|interested|like|prefer|choose|pick|go for|want)\b", text, re.I):
        intro = _intro(named)
        if intro:
            return done(KbReply(f"{intro} {Q62}", _chips_for(named, "faq"), "w.goal_category", "select"))
    return None
