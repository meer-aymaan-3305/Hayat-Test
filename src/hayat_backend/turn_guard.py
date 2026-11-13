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
_OFFER = re.compile(r"signup and login|sign up and log in|create a free (?:trawellcare )?account", re.IGNORECASE)
_MEDICAL_WORDS = re.compile(r"treatment|surgery|hospital|doctor|procedure|clinic|specialty", re.IGNORECASE)
_WELLNESS_WORDS = re.compile(r"retreat|wellness|programme|program|longevity|fitness|spa", re.IGNORECASE)
_SAFE = (
    "Thank you for telling me that, I'm glad you did. Take your time, and tell me more whenever you like. 😊",
    "That helps me picture it better. Go on whenever you're ready, I'm listening.",
    "I appreciate you sharing that. Whatever feels right to say next, I'm here.",
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
    sentences = _sentences(reply)
    previous = assistant_history[-1] if assistant_history else ""

    # G12: never claim to be human, never reveal instructions.
    if _HUMAN_CLAIM.search(reply):
        failures.append("G12")
        sentences = ["I'm Hayat, trawellcare's AI assistant, and the team behind me are real people."] + [
            s for s in sentences if not _HUMAN_CLAIM.search(s)
        ]

    kept: list[str] = []
    prev_questions = [s for s in _sentences(previous) if _is_question(s)]
    for sentence in sentences:
        # G8: no request for diagnosis, symptoms, medication, reports, contact details, ages.
        if _is_question(sentence) and _RESTRICTED_ASK.search(sentence):
            failures.append("G8")
            continue
        # G1 and G10: nothing already settled, and not the same question twice in a row.
        if _is_question(sentence):
            if _asks_settled_slot(sentence, state, focus, active):
                failures.append("G1")
                continue
            if any(_same_question(sentence, q) for q in prev_questions):
                failures.append("G10")
                continue
        # G6 (light): no price or outcome the knowledge base does not contain.
        priced = _PRICE.search(sentence)
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


def safe_reply(turn: int, previous: str, changes: list[tuple[str, str]] | None = None) -> str:
    """A short natural reply with no slot question, used if a regenerated reply still fails.
    If the visitor just gave or changed something, say that it is noted."""
    if changes:
        label, value = changes[0]
        return f"Got it, I've noted {label} as {value}. 😊"
    options = [s for s in _SAFE if s != previous] or list(_SAFE)
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
