"""The turn guard (addendum 5.1): every candidate reply is checked before it is shown.

Most failures are fixed in code with no extra model call. Only G2 (the reply ignores the
visitor's latest message) and G3 (a value leaks across journeys) justify one regeneration,
with the failed check named. If the regenerated reply still fails, a short natural reply is
used instead. Every failure is logged with the check id, turn number and flow state.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from typing import Any

from .slots import BY_ID, MEDICAL, NEVER_ASK_AGAIN, SLOTS, WELLNESS, SlotState

logger = logging.getLogger("hayat.guard")

REGENERATE = {"G2", "G3"}

# How each slot is usually asked about (used to catch questions about settled slots).
_ASKS = {
    "s.preferred_name": r"call you|your name|what to call",
    "s.residence_country": r"based|where do you live|country.{0,25}(?:live|reside|now|moment)",
    "m.service_category": r"which treatment|what treatment|treatment or specialty|kind of treatment|what.{0,20}specialty",
    "m.destination_country": r"destination|which country|where.{0,20}(?:travel|treatment)",
    "m.timeline_window": r"when|timeframe|time ?frame|how soon|window|timeline",
    "m.budget_band": r"budget",
    "m.travellers_count": r"travell?ing|joining|how many|on your own|just you",
    "w.experience_type": r"kind of (?:wellness|experience)|what.{0,20}(?:retreat|experience)",
    "w.goal_category": r"feeling|goal|come home with|hoping to",
    "w.destination": r"destination|where.{0,25}retreat|which country",
    "w.dates_window": r"when|timeframe|time ?frame|how soon|window|month",
    "w.duration_nights": r"how long|duration|nights|days|weeks|away for",
    "w.participants_count": r"how many|joining|participants|just you|on your own",
    "w.budget_band": r"budget",
}
_RESTRICTED_ASK = re.compile(
    r"diagnos|symptom|medication|medicine|prescri|test result|scan|report|medical history|"
    r"phone|whatsapp|e-?mail|contact (?:number|details)|your (?:full )?name\b.{0,20}(?:surname|last)|"
    r"how old|\bage\b|names? of (?:those|the people|your (?:companions?|children|kids))|children",
    re.IGNORECASE,
)
_PRICE = re.compile(
    r"(?:USD|AED|OMR|EUR|GBP|SAR|\$|€|£)\s?\d|\d[\d,\.]*\s?(?:USD|AED|OMR|SAR|dollars|dirhams|euros|rials?)\b|\b\d+\s?%\s?(?:success|cure|recovery)",
    re.IGNORECASE,
)
_PROMISE = re.compile(
    r"\b(?:is|are|has been|have been|will be)\s+(?:confirmed|booked|approved|guaranteed)\b|"
    r"\bI(?:'ve| have)\s+(?:booked|confirmed|reserved)\b|\bwe(?:'ll| will)\s+(?:book|reserve)\b|\bguarantee",
    re.IGNORECASE,
)
_HUMAN_CLAIM = re.compile(
    r"\bI(?:'m| am)\s+(?:a\s+)?(?:human|real person|person|doctor|nurse)\b|\bmy\s+(?:instructions|system prompt|rules)\b",
    re.IGNORECASE,
)
_GREETING = re.compile(r"^\s*(?:hello|hi|hey|good (?:morning|afternoon|evening)|welcome)\b", re.IGNORECASE)
_INTRO = re.compile(r"\bI(?:'m| am) Hayat\b", re.IGNORECASE)
_OFFER = re.compile(
    r"sign ?up (?:and|or) log ?in|sign up and log in|create (?:a )?free (?:trawellcare )?account|"
    r"(?:if you(?:'d| would) like|if you like|shall i|would you like me to|we can start|ready to).{0,70}"
    r"(?:consultation|sign ?up|log ?in|account)|"
    r"would you like (?:to|me to) (?:schedule|arrange|book|set up|explore that|take the next step|explore setting)|"
    r"\bsetting (?:that|it|this|one) up\b|"
    r"let me know if you(?:'d| would) like (?:to )?(?:start|set|begin|arrange|book|schedule)|"
    r"(?:schedule|arrange|book) (?:that|the|your|a) (?:free )?(?:consultation|call|next step)",
    re.IGNORECASE,
)
_CURRENCY_AFTER_FIGURE = re.compile(r"(?<=\d)\s?(?:€|\$|£|USD|EUR|GBP|AED|OMR|SAR)\b|(?<=\d)\s?[€$£]", re.IGNORECASE)
_MEDICAL_WORDS = re.compile(r"treatment|surgery|hospital|doctor|procedure|clinic|specialty", re.IGNORECASE)
_WELLNESS_WORDS = re.compile(r"retreat|wellness|programme|program|longevity|fitness|spa", re.IGNORECASE)
_ECHO = re.compile(
    r"^\s*(?:i understand|i see|i hear)?[ ,]*(?:that )?you(?:'re| are| have| just)? ?(?:asking|asked|wondering|curious|considering|looking to ask|want to know|would like to know)\b",
    re.IGNORECASE,
)
_TAIL = re.compile(
    r"perfectly fine|totally fine|is all i need|no worries|no pressure|feel free|if you(?:'d| would) rather|"
    r"if you prefer|you can skip|a range|a number|a first name",
    re.IGNORECASE,
)
_SAFE = (
    "Thank you, that's helpful. Tell me a little more whenever you like. 😊",
    "That helps me picture it better. Go on whenever you're ready, I'm listening.",
    "Thanks for sharing that. Whatever feels right to say next, I'm here.",
)
# A bare "ok", "yes", "no" or "thanks" gets a short, varied nudge, never the same line twice.
_ACK_ONLY = re.compile(r"^\s*(ok(?:ay)?|yes|yeah|yep|no|nope|fine|sure|thanks|thank you|cool|great|alright)[\s.!😊]*$", re.I)
_ACK_REPLIES = (
    "Sounds good. 😊 Is there anything else you'd like to know in the meantime?",
    "Of course. I'm here if any other questions come up.",
    "Great. Whenever you're ready, the free consultation is the best next step, and I'm happy to help until then.",
    "No problem at all. Feel free to ask me anything about your plans.",
)


@dataclass
class GuardResult:
    reply: str
    failures: list[str] = field(default_factory=list)

    @property
    def needs_regeneration(self) -> list[str]:
        return [f for f in self.failures if f in REGENERATE]


def _sentences(text: str) -> list[str]:
    return [s for s in re.split(r"(?<=[.!?؟])\s+", text.strip()) if s]


def _is_question(sentence: str) -> bool:
    return "?" in sentence or "؟" in sentence


def check(
    reply: str, *, user_text: str, plan: Any, state: SlotState, focus: str | None,
    active: list[str], assistant_history: list[str], knowledge: str, turn: int,
    handoff_expected: bool = False, scripted: bool = False,
) -> GuardResult:
    """Run G1 to G12 on a candidate reply. Fixes what it can; reports every failure."""
    if scripted:  # approved safety scripts and the definition are never altered
        return GuardResult(reply)
    failures: list[str] = []
    # G7: a list becomes flowing sentences before anything else is checked.
    if _LIST_LINE.search(reply):
        failures.append("G7")
        reply = _flatten_list(reply)
    sentences = _sentences(reply)
    previous = assistant_history[-1] if assistant_history else ""
    sources_text = _sources(knowledge, user_text, state, assistant_history)
    dropped_claim = False

    # G12: never claim to be human, never reveal instructions.
    if _HUMAN_CLAIM.search(reply):
        failures.append("G12")
        sentences = ["I'm Hayat, trawellcare's AI assistant, and the team behind me are real people."] + [
            s for s in sentences if not _HUMAN_CLAIM.search(s)
        ]

    kept: list[str] = []
    prev_questions = [s for s in _sentences(previous) if _is_question(s)]
    dropped_question = False
    for sentence in sentences:
        # A removed question takes its little tail ("A range is perfectly fine") with it.
        if dropped_question and not _is_question(sentence) and _TAIL.search(sentence) and len(sentence.split()) <= 10:
            dropped_question = False
            continue
        dropped_question = False
        # G8: no request for diagnosis, symptoms, medication, reports, contact details, ages.
        if _is_question(sentence) and _RESTRICTED_ASK.search(sentence):
            failures.append("G8")
            dropped_question = True
            continue
        # G1 and G10: nothing already settled, and not the same question twice in a row.
        if _is_question(sentence):
            if getattr(plan, "decision_type", "") != "confirm_change" and _asks_settled_slot(sentence, state, focus, active):
                failures.append("G1")
                dropped_question = True
                continue
            if any(_same_question(sentence, q) for q in prev_questions):
                failures.append("G10")
                dropped_question = True
                continue
        # Style: never repeat the visitor's question back at them ("You're asking about...").
        if _ECHO.search(sentence) and len(sentences) > 1:
            failures.append("G13")
            continue
        # G6 (light): no price or outcome the knowledge base does not contain.
        # The visitor's own figure may be echoed, but never with a currency they did not name.
        if not re.search(r"[€$£]|USD|EUR|AED|OMR|SAR|GBP", user_text):
            plain = _CURRENCY_AFTER_FIGURE.sub("", sentence)
            if plan_digits(plain, sentence, user_text):
                sentence = plain
        # G6 claim check (addendum 6.3): a statement may only carry a name, number or claim word
        # that the sources contain (knowledge passages, programme list, the visitor's own words).
        if not _is_question(sentence):
            unsupported = _unsupported_claim(sentence, sources_text)
            if unsupported:
                failures.append("G6")
                logger.info("turn_guard G6 dropped a claim with no source: %r", unsupported)
                dropped_claim = True
                continue
        priced = _PRICE.search(sentence)
        if priced and (
            re.sub(r"\D", "", priced.group(0)) and re.sub(r"\D", "", priced.group(0)) in re.sub(r"\D", "", user_text)
        ):
            priced = None  # echoing the visitor's own figure back is not inventing a price
        if priced and priced.group(0).lower() not in knowledge.lower():
            failures.append("G6")
            kept.append("I don't have prices to hand, and the team can go through them with you on your free call.")
            continue
        # G9: nothing is promised or confirmed.
        if _PROMISE.search(sentence):
            failures.append("G9")
            kept.append("The team confirms that after your consultation.")
            continue
        # G5: no repeated greeting or introduction, no repeated handoff offer.
        if assistant_history and (_GREETING.search(sentence) and len(sentence.split()) <= 6 or _INTRO.search(sentence)):
            failures.append("G5")
            continue
        if _OFFER.search(sentence) and not handoff_expected:
            failures.append("G5")
            continue
        kept.append(sentence)

    # G4: at most one question.
    questions = [s for s in kept if _is_question(s)]
    if len(questions) > 1:
        failures.append("G4")
        first = questions[0]
        kept = [s for s in kept if not _is_question(s) or s == first]

    if dropped_claim and not any(not _is_question(s) for s in kept[1:] if s):
        # Everything factual was unsupported: say so plainly instead (addendum 6.2).
        kept.insert(min(1, len(kept)), NO_SOURCE_LINE)

    # Part 3: never open with the same words as an earlier reply in this conversation.
    if kept and assistant_history:
        kept[0] = _vary_opening(kept[0], assistant_history)

    fixed = " ".join(dict.fromkeys(kept)).strip()

    # G2: the reply must respond to what the visitor just said, not only ask the next thing.
    statements = [s for s in _sentences(fixed) if not _is_question(s)]
    only_question = bool(fixed) and not statements
    word_count = len(user_text.split())
    if (only_question and word_count >= 2 and plan is not None and plan.decision_type == "collect_detail") or (
        previous and fixed and _same_opening(fixed, previous)
    ):
        failures.append("G2")

    # G3: a value from the other journey must not appear as if it belonged to this one.
    if focus and len(active) > 1 and _cross_lane_leak(fixed, state, focus):
        failures.append("G3")

    if failures:
        logger.info(
            "turn_guard turn=%s state=%s failed=%s", turn, getattr(plan, "decision_type", "-"), sorted(set(failures)),
        )
    return GuardResult(fixed or reply, sorted(set(failures), key=failures.index))


NO_SOURCE_LINE = "I don't have those details to hand, and the team can go through them with you on your free call."
_LIST_LINE = re.compile(r"(?m)^\s*(?:[-•*]|\d+[.)])\s+\S")
# Words that make a sentence a factual claim about trawellcare's offering (Guardrail HB-5).
_CLAIM_WORDS = re.compile(
    r"\b(accredit\w*|jci|certified|award\w*|partner(?:s|ed|ship)?|guarantee\w*|success rate|discount\w*|"
    r"included|includes|inclusive|free of charge|refund\w*|insurance)\b|"
    # Ranking words only count when they rank a provider or a place (Addendum 6.2).
    r"\b(?:best|top|leading|world.class|top.rated|highest.rated|renowned)\b(?:\W+\w+){0,3}?\W+"
    r"(?:hospitals?|doctors?|clinics?|surgeons?|destinations?|centres?|centers?)\b",
    re.IGNORECASE,
)
_ALLOWED_CLAIMS = re.compile(
    r"\b(free (?:consultation|call|account)|case manager|wellness curator|signup|sign up|log ?in|team)\b",
    re.IGNORECASE,
)
_SPELLED = {
    str(i): w for i, w in enumerate(
        "zero one two three four five six seven eight nine ten eleven twelve thirteen fourteen fifteen "
        "sixteen seventeen eighteen nineteen twenty".split()
    )
}
_COMMON_CAPS = {
    "i", "i'm", "i'll", "i've", "i'd", "hayat", "trawellcare", "monday", "tuesday", "wednesday", "thursday",
    "friday", "saturday", "sunday", "january", "february", "march", "april", "may", "june", "july", "august",
    "september", "october", "november", "december", "ok", "okay", "english", "arabic",
}


def _sources(knowledge: str, user_text: str, state: SlotState, history: list[str]) -> str:
    from .programmes_registry import knowledge_block

    slot_values = " ".join(str(v.get("value", "")) for v in state.snapshot().values())
    return " ".join([knowledge, knowledge_block(), user_text, slot_values]).lower().replace("é", "e")


def _unsupported_claim(sentence: str, sources: str) -> str | None:
    """The first name, number or claim word in a statement that no source contains, or None."""
    words = re.findall(r"[A-Za-zÀ-ÿ][\w'’-]*|\d[\d,.]*", sentence)
    for index, word in enumerate(words):
        low = word.lower().replace("é", "e").strip(".,")
        if word[0].isdigit():
            number = low.strip(",.")
            spelled = _SPELLED.get(number, "")
            if number not in sources and not (spelled and re.search(rf"\b{spelled}\b", sources)):
                return word
        elif index > 0 and word[0].isupper() and low not in _COMMON_CAPS and len(low) > 2:
            # "European" is supported by "Europe": compare the first five letters too.
            if low not in sources and not (len(low) >= 5 and re.search(rf"\b{re.escape(low[:5])}", sources)):
                return word
    claim = _CLAIM_WORDS.search(sentence)
    if claim and claim.group(0).lower() not in sources and not _ALLOWED_CLAIMS.search(sentence):
        return claim.group(0)
    return None


def _flatten_list(reply: str) -> str:
    """G7: bullets and numbered lines become one flowing sentence."""
    lines = [ln.strip() for ln in reply.splitlines() if ln.strip()]
    lead = [ln for ln in lines if not _LIST_LINE.match(ln)]
    items = [re.sub(r"^\s*(?:[-•*]|\d+[.)])\s+", "", ln).rstrip(".;,") for ln in lines if _LIST_LINE.match(ln)]
    items = [i[0].lower() + i[1:] if i[:1].isupper() and not i[:2].isupper() else i for i in items][:4]
    joined = ", ".join(items[:-1]) + (" and " + items[-1] if len(items) > 1 else items[0] if items else "")
    head = " ".join(lead[:1])
    tail = " ".join(lead[1:])
    sentence = (head.rstrip(":") + " " + joined).strip() if head else joined[:1].upper() + joined[1:]
    return " ".join(p for p in (sentence.rstrip(".") + ".", tail) if p).strip()


_STOCK_OPENERS = re.compile(
    r"^(?:got it|thank you|thanks|great|lovely|wonderful|of course|understood|absolutely|sure|perfect|"
    r"no problem|that sounds (?:lovely|wonderful|great))[,!.]?\s+",
    re.IGNORECASE,
)


def _vary_opening(first: str, history: list[str]) -> str:
    """Drop a stock opener already used to start an earlier reply, keeping the rest."""
    match = _STOCK_OPENERS.match(first)
    if not match:
        return first
    opener = match.group(0).strip(" ,!.").lower()
    used = any(h.strip().lower().startswith(opener) for h in history)
    rest = first[match.end():].strip()
    if not used or len(rest.split()) < 3:
        return first
    return rest[0].upper() + rest[1:]


_TOPICS: tuple[tuple[re.Pattern[str], str], ...] = tuple(
    (re.compile(pattern, re.IGNORECASE), topic)
    for pattern, topic in (
        (r"\b(price|prices|pricing|cost|costs|how much|fee|budget)\b", "the cost"),
        (r"\b(hospital|hospitals|doctor|doctors|clinic|surgeon)\b", "hospitals and doctors"),
        (r"\b(include|included|includes|inclusion|spa|meals?|accommodation|flights?)\b", "what's included"),
        (r"\b(where|destination|destinations|location|country|countries)\b", "where it would be"),
        (r"\b(when|dates?|month|timing|how long|duration|nights?)\b", "the timing"),
        (r"\b(visa|visas|insurance|transfer|transport)\b", "the travel side"),
        (r"\b(consultation|case manager|curator|team|person|call)\b", "the free consultation"),
        (r"\b(register|sign ?up|log ?in|account|book|booking)\b", "signing up"),
    )
)
_QUESTION_START = re.compile(
    r"^\s*(what|how|why|when|where|which|who|can|could|do|does|did|is|are|will|would|should|"
    r"tell me|explain|show me)\b", re.IGNORECASE,
)


def topic_of(user_text: str) -> str | None:
    """A short phrase naming what the visitor's message is about, for a fallback that still
    refers to it (guard G2). Programme names and specialty labels come first."""
    from .pre_extract import _named_programme, specialty_label

    named = _named_programme(user_text)
    if named:
        return named
    label = specialty_label(user_text)
    if label:
        return f"the {label} side"
    for pattern, topic in _TOPICS:
        if pattern.search(user_text):
            return topic
    return None


def _journey_phrase(changes: list[tuple[str, str]]) -> str:
    """Several details in plain words, one journey at a time: "orthopaedics in India around
    spring for the treatment, and a retreat in Europe for the wellness side"."""
    by_label = {label: value for label, value in changes}

    def lane(kind: str, place: str, when: str, who: str, suffix: str) -> str:
        bits = []
        if kind in by_label:
            first = by_label[kind]
            bits.append(f"a {first}" if first in {"retreat", "spa break"} else first)
        if place in by_label:
            bits.append(f"in {by_label[place]}")
        if when in by_label:
            window = by_label[when]
            bits.append(window if re.match(r"(?i)(later|next|this|within|in|early|end|by|around|before|after)\b", window)
                        else f"around {window}")
        if who in by_label:
            bits.append(f"for {by_label[who]}")
        return (" ".join(bits) + suffix) if bits else ""

    medical = lane("treatment type", "treatment destination", "treatment timeframe", "travellers for the treatment",
                   " for the treatment")
    wellness = lane("kind of wellness experience", "retreat destination", "retreat dates window",
                    "participants for the retreat", " for the wellness side")
    parts = [p for p in (medical, wellness) if p]
    used = {"treatment type", "treatment destination", "treatment timeframe", "travellers for the treatment",
            "kind of wellness experience", "retreat destination", "retreat dates window", "participants for the retreat",
            "what to call them", "language"}
    rest = [f"{label} as {value}" for label, value in changes if label not in used]
    parts += rest[:2]
    if not parts:
        return ", ".join(value for _label, value in changes[:3])
    return ", and ".join(parts) if len(parts) <= 2 else ", ".join(parts[:-1]) + ", and " + parts[-1]


def safe_reply(
    turn: int, previous: str, changes: list[tuple[str, str]] | None = None, user_text: str = "",
) -> str:
    """A short natural reply with no slot question, used if a regenerated reply still fails or
    the model is unavailable. It always refers to what the visitor just said (addendum 5.2)."""
    if changes:
        named = next((value for label, value in changes if label == "what to call them"), None)
        values = [value for label, value in changes if label not in {"what to call them", "language"}]
        if named and not values:
            return f"Lovely to meet you, {named}. 😊"
        if len(values) == 1:
            label, value = next((c for c in changes if c[1] == values[0]))
            return f"Got it, I've noted {label} as {value}. 😊"
        if values:
            return f"Got it, I've noted {_journey_phrase(changes)}. 😊"
    topic = topic_of(user_text) if user_text else None
    asking = "?" in user_text or bool(_QUESTION_START.match(user_text or ""))
    if asking:
        about = f" about {topic}" if topic else ""
        return (
            f"That's a good question{about}. I can't check it properly this second, so ask me again in a "
            "moment, or the team can go through it with you on your free consultation. 😊"
        )
    if topic and (topic.endswith(" side") or topic[:1].isupper()):
        # Only a programme or a specialty reads naturally here ("telling me about the cost" does not).
        return f"Thank you for telling me about {topic}. I'm listening, so go on whenever you're ready. 😊"
    pool = _ACK_REPLIES if _ACK_ONLY.match(user_text or "") else _SAFE
    options = [s for s in pool if s != previous] or list(pool)
    return options[turn % len(options)]


def repair_leaks(reply: str, state: SlotState, focus: str) -> str:
    """G3 repair: drop the sentences that carry the other journey's trip details."""
    other = WELLNESS if focus == MEDICAL else MEDICAL
    other_words = _WELLNESS_WORDS if other == WELLNESS else _MEDICAL_WORDS
    values = [
        v.lower() for sid, v in state.lane_values(other).items()
        if BY_ID[sid].key not in {"procedure_or_service", "wellness_programme_or_goal"} and len(v) >= 3
    ]
    kept = [
        s for s in _sentences(reply)
        if not any(v in s.lower() for v in values) or other_words.search(s)
    ]
    return " ".join(kept).strip()


def _asks_settled_slot(sentence: str, state: SlotState, focus: str | None, active: list[str]) -> bool:
    lane_text = "M" if _MEDICAL_WORDS.search(sentence) and not _WELLNESS_WORDS.search(sentence) else (
        "W" if _WELLNESS_WORDS.search(sentence) and not _MEDICAL_WORDS.search(sentence) else None
    )
    for slot in SLOTS:
        pattern = _ASKS.get(slot.id)
        if not pattern or state.status(slot.id) not in NEVER_ASK_AGAIN:
            continue
        if slot.lane in (MEDICAL, WELLNESS):
            lane_of_sentence = {"M": MEDICAL, "W": WELLNESS}.get(lane_text or "", focus)
            if lane_of_sentence != slot.lane:
                continue
        if re.search(pattern, sentence, re.IGNORECASE):
            return True
    return False


def _words(sentence: str) -> set[str]:
    return {w for w in re.findall(r"[a-z]{4,}", sentence.lower())}


def _same_question(a: str, b: str) -> bool:
    wa, wb = _words(a), _words(b)
    return bool(wa and wb) and len(wa & wb) / min(len(wa), len(wb)) >= 0.7


def _same_opening(reply: str, previous: str) -> bool:
    take = lambda t: [w for w in re.findall(r"[a-z']+", t.lower())][:3]  # noqa: E731
    return len(take(reply)) == 3 and take(reply) == take(previous)


def _cross_lane_leak(reply: str, state: SlotState, focus: str) -> bool:
    other = WELLNESS if focus == MEDICAL else MEDICAL
    own_values = {v.lower() for v in state.lane_values(focus).values()}
    other_words = _WELLNESS_WORDS if other == WELLNESS else _MEDICAL_WORDS
    for slot_id, value in state.lane_values(other).items():
        if BY_ID[slot_id].key in {"procedure_or_service", "wellness_programme_or_goal"}:
            continue  # the type of journey may be named; trip details may not leak
        text = value.lower()
        if len(text) < 3 or text in own_values:
            continue
        for sentence in _sentences(reply):
            if text in sentence.lower() and not other_words.search(sentence):
                return True
    return False


def plan_digits(stripped: str, original: str, user_text: str) -> bool:
    """True when a currency was stripped from a figure the visitor themselves gave."""
    if stripped == original:
        return False
    figures = re.findall(r"\d[\d,\.]*", original)
    return any(f.strip(",.") and f.strip(",.") in user_text.replace(",", "") .replace(" ", "") + user_text for f in figures)
