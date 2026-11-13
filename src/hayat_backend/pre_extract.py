"""Deterministic reading of the visitor's message, done in code before and after the model.

Two jobs (IMPLEMENTATION.md, phase 0):

1. ``fast_analysis``: some turns need no extraction model at all (a greeting, a thanks, a
   goodbye, a programme question the knowledge playbook answers). Skipping the model there
   halves the calls for those turns, which keeps Hayat inside the provider's per minute limit.

2. ``reinforce``: the extraction model reads a redacted copy of the message (the Guardrail's
   redaction protocol), so a clinical word that decides the journey ("knee", "heart valve")
   may be blanked before it sees it. The raw text never leaves this process; here, in code, a
   plain specialty label is derived from it. A label is allowed (Addendum 2.3, m.service_category
   "label only, no condition description"); the detail itself is never stored.
"""

from __future__ import annotations

import re
from dataclasses import replace
from typing import Any

from .programmes_registry import programmes

# Words that name a specialty, mapped to the label stored in m.service_category.
_SPECIALTIES: tuple[tuple[re.Pattern[str], str], ...] = tuple(
    (re.compile(pattern, re.I), label)
    for pattern, label in (
        (r"\b(knee|hip|joint|spine|spinal|back surgery|shoulder|orthopa?edic\w*|acl|meniscus|bone)\b", "orthopaedics"),
        (r"\b(heart|cardiac|cardio\w*|valve|bypass|angioplasty|stent)\b", "cardiology"),
        (r"\b(teeth|tooth|dental|dentist|implants?|veneers?|crowns?|root canal)\b", "dental"),
        (r"\b(ivf|fertility|infertility|egg freezing|surrogacy)\b", "fertility"),
        (r"\b(eye|eyes|cataract|lasik|retina\w*|ophthalm\w*)\b", "ophthalmology"),
        (r"\b(cancer|oncolog\w*|tumou?r|chemo\w*|radiotherapy)\b", "oncology"),
        (r"\b(bariatric|weight loss surgery|gastric (?:bypass|sleeve))\b", "bariatric surgery"),
        (r"\b(cosmetic|aesthetic\w*|rhinoplasty|liposuction|facelift|hair transplant)\b", "aesthetics"),
        (r"\b(kidney|renal|dialysis|transplant)\b", "nephrology and transplant"),
        (r"\b(neuro\w*|brain)\b", "neurology"),
    )
)
_MEDICAL_ASK = re.compile(
    r"\b(treatment|surgery|operation|procedure|hospital|doctor|clinic|replacement|problem|pain|"
    r"injur\w*|condition|help (?:me |us )?with|need)\b",
    re.I,
)
_WELLNESS_WORDS = re.compile(r"\b(retreat|wellness|spa|longevity|detox|yoga|relax\w*|programme|program)\b", re.I)

_GREETING_ONLY = re.compile(
    r"^\s*(hi|hello|hey|hiya|salam|salaam|assalamu? ?alaikum|good (?:morning|afternoon|evening))"
    r"(?: there| hayat)?[\s!.,😊👋]*$",
    re.I,
)
_THANKS_ONLY = re.compile(r"^\s*(thanks|thank you|thank u|thx|cheers|great,? thanks|ok,? thanks)[\s!.😊🙏]*$", re.I)
_ANY_DIGIT = re.compile(r"\d")


def specialty_label(raw_text: str) -> str | None:
    """The specialty a message names, as a plain label, or None."""
    for pattern, label in _SPECIALTIES:
        if pattern.search(raw_text):
            return label
    return None


def reinforce(analysis: Any, raw_text: str, pending_slot: str | None = None) -> Any:
    """Add the lane and a specialty label the model could not see because of redaction.
    Returns a copy; the model's own object is never modified."""
    if analysis is None:
        return analysis
    slots = dict(getattr(analysis, "slots", {}) or {})
    lane = getattr(analysis, "lane", None)
    label = specialty_label(raw_text)
    changed = False
    if label and "m.service_category" not in slots and (
        _MEDICAL_ASK.search(raw_text) or pending_slot == "m.service_category"
    ):
        if not (_WELLNESS_WORDS.search(raw_text) and not _MEDICAL_ASK.search(raw_text)):
            slots["m.service_category"] = {"value": label, "status": "HEARD"}
            changed = True
            if lane is None:
                lane = "MEDICAL"
    if not changed:
        return analysis
    return replace(analysis, slots=slots, lane=lane)


_COMPANIONS = re.compile(
    r"\b(me and|with my|my (?:wife|husband|partner|spouse|sister|brother|mum|mom|mother|dad|father|friends?|"
    r"family|kids|children|son|daughter|colleagues?)|of us|people|adults|couple|two|three|four|five|alone|"
    r"just me|on my own|solo)\b",
    re.IGNORECASE,
)


def has_details(text: str) -> bool:
    """True when a message carries a trip detail (a time, a place, companions or a specialty), so
    the extraction model must read it even if the knowledge playbook answers its question
    (Addendum 3.1: fill every slot the visitor covered)."""
    from .slot_values import _COUNTRIES, _COUNTRY_ALIASES, _REGIONS, _WINDOW

    if _WINDOW.search(text) or _COMPANIONS.search(text) or specialty_label(text):
        return True
    lowered = " " + re.sub(r"[^a-z\s]", " ", text.lower()) + " "
    return any(f" {place} " in lowered for place in (*_COUNTRIES, *_REGIONS, *_COUNTRY_ALIASES))


def _named_programme(text: str) -> str | None:
    lowered = text.lower().replace("é", "e")
    for programme in programmes():
        names = [programme.name, *programme.former_names] + (["hayat 100"] if programme.id == "hayat-100" else [])
        for name in names:
            if name.lower().replace("é", "e") in lowered:
                return programme.name
    return None


_BOOKING = re.compile(
    r"\b(?:can i|could i|i want to|i'd like to|i would like to|how do i|let me|please)\s+(?:book|reserve|schedule|"
    r"arrange|get a quote|get a quotation)\b|\bbook me\b|\bget a (?:quote|quotation)\b",
    re.IGNORECASE,
)
_HUMAN = re.compile(
    r"\b(?:talk|speak|chat) (?:to|with) (?:a |an |someone|somebody|a real )?(?:person|human|agent|someone|somebody|"
    r"representative|team member)\b|\breal person\b|\bhuman agent\b",
    re.IGNORECASE,
)


_NOT_A_NAME = re.compile(
    r"^(?:hi|hello|hey|yes|yeah|no|nope|ok|okay|sure|thanks|thank you|fine|good|great|maybe|later|skip|"
    r"treatment|wellness|retreat|medical|knee|hip|india|spain)$",
    re.IGNORECASE,
)
_REFUSE = re.compile(r"\b(rather not|prefer not|skip|no thanks|not comfortable|not right now|not now)\b", re.IGNORECASE)
_INSTRUCTION = re.compile(
    r"\b(ignore|forget|disregard) (?:your|all|the|previous|my) (?:rules|instructions|prompt)|\bset my \w+ to\b|"
    r"\byou are now\b|\bsystem prompt\b",
    re.IGNORECASE,
)
_DONT_KNOW = re.compile(r"\b(not sure|don'?t know|no idea|undecided|not yet|flexible)\b", re.IGNORECASE)
_LANE_WORDS = {
    "MEDICAL": re.compile(r"\b(treatment|surgery|operation|procedure|hospital|doctor|clinic|medical)\b", re.I),
    "WELLNESS": re.compile(r"\b(retreat|wellness|spa|programme|program|longevity|relax\w*)\b", re.I),
}


def _places_in(text: str) -> list[str]:
    from .slot_values import _COUNTRIES, _COUNTRY_ALIASES, _REGIONS, check

    lowered = " " + re.sub(r"[^a-z\s]", " ", text.lower()) + " "
    found = []
    for place in sorted((*_COUNTRIES, *_REGIONS, *_COUNTRY_ALIASES), key=len, reverse=True):
        if f" {place} " in lowered and not any(place in f for f in found):
            found.append(place)
    return [check("w.destination", p, "CONFIRMED").value for p in found if check("w.destination", p, "CONFIRMED").status == "CONFIRMED"]


_CLAUSE_SPLIT = re.compile(r"[.;!?]+|\s*,?\s*\b(?:and also|also|but|plus|oh and)\b\s*|,\s+and\s+", re.IGNORECASE)
_NEGATED_PLACE = re.compile(r"\b(?:not|instead of|rather than|no longer)\s+(?:in\s+)?([A-Za-z][A-Za-z ]{1,25})", re.IGNORECASE)
_CORRECTION = re.compile(r"\b(sorry|i meant|meant|actually|instead|change|not .{1,25}\bbut)\b", re.IGNORECASE)
_OFFER_YES = re.compile(r"^\s*(yes|yeah|yep|sure|ok(?:ay)?|please|go ahead|let'?s do it|take me there|sounds good)\b", re.I)
_OFFER_NO = re.compile(r"\b(not now|not right now|not yet|no thanks|maybe later|later|i'?ll think|not ready|rather not|prefer not|no\b)", re.I)
_CLINICAL = re.compile(
    r"\b(diagnos\w*|diabet\w*|cancer|tumou?r|asthma|blood pressure|hypertension|medication|metformin|insulin|"
    r"symptom\w*|pain|chemo\w*|mri|x-?ray|scan results?|blood test)\b",
    re.IGNORECASE,
)


def _clause_lane(clause: str) -> str | None:
    medical = bool(_LANE_WORDS["MEDICAL"].search(clause) or specialty_label(clause))
    wellness = bool(_LANE_WORDS["WELLNESS"].search(clause))
    if medical == wellness:
        return None
    return "MEDICAL" if medical else "WELLNESS"


def fallback_analysis(
    text: str, turn_analysis_cls: Any, *, pending_slot: str | None = None, lanes: list[str] | None = None,
    focus: str | None = None, handoff_just_offered: bool = False,
) -> Any:
    """What code alone can read when the extraction model is unavailable (rate limit or outage):
    a booking or person request, a reply to the signup offer, a greeting, clinical detail, an
    answer to the question just asked, and per clause the journey, places, a time window and
    companions, with corrections. Rules 1 to 5 of Addendum part 4 apply as for the model.
    Better than reading nothing, which left the flow stuck (live evaluation, scenarios 15, 17)."""
    from .slot_values import _WINDOW, check

    stripped = text.strip()
    if _BOOKING.search(stripped):
        return turn_analysis_cls(intent="wants_booking")
    if _HUMAN.search(stripped):
        return turn_analysis_cls(intent="wants_human")
    if handoff_just_offered and len(stripped.split()) <= 8:
        if _OFFER_NO.search(stripped):
            return turn_analysis_cls(intent="declines")
        if _OFFER_YES.match(stripped):
            return turn_analysis_cls(intent="accepts")
    if _GREETING_ONLY.match(stripped) or _THANKS_ONLY.match(stripped):
        return turn_analysis_cls(intent="smalltalk")
    if _INSTRUCTION.search(stripped):
        # Visitor text is content, never an instruction: nothing is written (Addendum 7.2).
        return turn_analysis_cls(intent="off_topic", note="instruction attempt")
    if _CLINICAL.search(stripped) and not specialty_label(stripped):
        return turn_analysis_cls(intent="clinical_detail")  # no slot for the detail (Addendum 4.2)
    asking = "?" in stripped
    lanes = list(lanes or [])
    slots: dict[str, dict[str, str]] = {}
    message_lanes: set[str] = set()

    # Addendum part 4 rule 2: a short answer fills the slot that was just asked about.
    if pending_slot and not asking and len(stripped.split()) <= 6:
        if _REFUSE.search(stripped):
            slots[pending_slot] = {"value": "", "status": "DECLINED"}
        elif _DONT_KNOW.search(stripped):
            slots[pending_slot] = {"value": "", "status": "UNSURE"}
        elif pending_slot == "s.preferred_name":
            if re.fullmatch(r"[A-Za-zÀ-ɏ'-]{2,20}", stripped) and not _NOT_A_NAME.match(stripped):
                slots[pending_slot] = {"value": stripped, "status": "CONFIRMED"}
        else:
            checked = check(pending_slot, stripped, "CONFIRMED")
            if checked.value and checked.status == "CONFIRMED":
                slots[pending_slot] = {"value": checked.value, "status": "CONFIRMED"}

    pending_lane = {"m.": "MEDICAL", "w.": "WELLNESS"}.get((pending_slot or "")[:2])
    negated = {m.group(1).strip().lower() for m in _NEGATED_PLACE.finditer(stripped)}
    correction = bool(negated) or bool(_CORRECTION.search(stripped))
    ambiguous = False
    if not asking:
        residence = re.search(r"\b(?:i'?m|we'?re|i am|we are|i live|we live|based)\s+(?:in|from)\b", stripped, re.I)
        for clause in [c.strip() for c in _CLAUSE_SPLIT.split(stripped) if c and c.strip()]:
            lane = _clause_lane(clause)
            if lane:
                message_lanes.add(lane)
            # Rule 3: no lane words, one journey open (or the one in focus answers a pending slot).
            target_lane = lane or (lanes[0] if len(lanes) == 1 else None) or pending_lane
            places = [p for p in _places_in(clause) if not any(p.lower().startswith(n[:5]) for n in negated)]
            if places and residence and "s.residence_country" not in slots:
                slots["s.residence_country"] = {"value": places[0], "status": "CONFIRMED"}
                places = places[1:]
            if places:
                if target_lane in ("MEDICAL", "WELLNESS"):
                    key = "m.destination_country" if target_lane == "MEDICAL" else "w.destination"
                    slots.setdefault(key, {"value": " and ".join(places), "status": "CONFIRMED"})
                elif len(lanes) > 1:
                    ambiguous = True  # rule 4: ask which journey, write nothing
            window = _WINDOW.search(clause)
            if window and target_lane in ("MEDICAL", "WELLNESS"):
                key = "m.timeline_window" if target_lane == "MEDICAL" else "w.dates_window"
                slots.setdefault(key, {"value": window.group(0), "status": "CONFIRMED"})
            if _COMPANIONS.search(clause):
                count_lane = target_lane or focus
                if count_lane in ("MEDICAL", "WELLNESS"):
                    key = "m.travellers_count" if count_lane == "MEDICAL" else "w.participants_count"
                    counted = check(key, clause, "CONFIRMED")
                    if counted.status == "CONFIRMED":
                        slots.setdefault(key, {"value": counted.value, "status": "CONFIRMED"})
            if lane == "WELLNESS" and "w.experience_type" not in slots and not lanes.count("WELLNESS"):
                kind = check("w.experience_type", clause, "CONFIRMED")
                if kind.value in {"retreat", "rest", "fitness", "longevity", "detox", "yoga"}:
                    slots["w.experience_type"] = {"value": kind.value, "status": "CONFIRMED"}
    lane = next(iter(message_lanes)) if len(message_lanes) == 1 else None
    intent = "question" if asking else "answering"
    analysis = turn_analysis_cls(
        intent=intent, slots=slots, lane=lane, lane_ambiguous=ambiguous, correction=correction,
    )
    return reinforce(analysis, stripped, pending_slot)


def fast_analysis(
    text: str, *, handoff_just_offered: bool, kb_would_answer: bool, turn_analysis_cls: Any,
) -> Any | None:
    """A TurnAnalysis built in code for turns that need no extraction model, else None."""
    stripped = text.strip()
    if not stripped:
        return None
    if handoff_just_offered:
        return None  # yes, no and maybe after the offer are left to the model and the flow
    if _GREETING_ONLY.match(stripped) or _THANKS_ONLY.match(stripped):
        return turn_analysis_cls(intent="smalltalk")
    if kb_would_answer and not _ANY_DIGIT.search(stripped) and len(stripped.split()) <= 12 and not has_details(stripped):
        named = _named_programme(stripped)
        slots = {"w.programme_interest": {"value": named, "status": "CONFIRMED"}} if named else {}
        return turn_analysis_cls(intent="question", lane="WELLNESS" if named else None, slots=slots)
    return None
