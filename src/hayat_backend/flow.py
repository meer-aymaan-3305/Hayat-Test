"""The flow controller: lanes, slot updates and the next action (addendum parts 2, 4 and 5).

The application owns the state. The model never decides which slot is pending, which lane is
in focus, or whether a handoff may be offered; it is told, every turn.
"""

from __future__ import annotations

import json
import re
from typing import Any

from .question_planner import PlannedStep
from .slots import (
    BY_ID, CONFIRMED, DECLINED, EMPTY, HEARD, MEDICAL, NEVER_ASK_AGAIN, ORDER, SHARED, SLOTS,
    UNSURE, WELLNESS, LANE_OF_KEY, SlotState, slot_for,
)

COOLING_MESSAGES = 6  # visitor messages without a new offer after a declined handoff

_CATEGORY_LANE = {"medical_treatment": MEDICAL, "wellness": WELLNESS}
_LANE_CATEGORY = {MEDICAL: "medical_treatment", WELLNESS: "wellness"}


def lanes_active(facts: dict[str, Any]) -> list[str]:
    raw = str(facts.get("lanes_active") or "")
    return [lane for lane in (MEDICAL, WELLNESS) if lane in raw.split(",")]


def focus_lane(facts: dict[str, Any]) -> str | None:
    lane = facts.get("focus_lane")
    if lane in (MEDICAL, WELLNESS):
        return lane
    active = lanes_active(facts)
    return active[0] if len(active) == 1 else None


def user_turn_count(conversation: Any) -> int:
    return sum(1 for m in getattr(conversation, "messages", []) if m.role == "user")


def pending_slot_id(facts: dict[str, Any]) -> str | None:
    slot = facts.get("pending_slot")
    return slot if slot in BY_ID else None


_RESIDENCE = re.compile(
    r"\b(?:i['’]?m|we['’]?re|i am|we are|i live|we live|living|based)\s+(?:currently\s+|based\s+)?(?:in|from)\s+"
    r"([A-Za-z][A-Za-z .'-]{1,28}?)(?:[,.!?]|\s+and\b|\s+but\b|$)",
    re.I,
)
_DONT_KNOW = re.compile(
    r"not sure|don'?t know|do not know|no idea|unsure|haven'?t (?:decided|thought)|undecided|not yet|"
    r"flexible|no preference|any(?:thing| is fine)|whatever|open to (?:anything|suggestions)|you (?:tell|suggest|decide)",
    re.I,
)
_REFUSES = re.compile(
    r"prefer not|rather not|no thanks|skip|don'?t want to (?:say|share|tell)|not comfortable|private|"
    r"not (?:going to|gonna) (?:say|share)|pass on that",
    re.I,
)
_MEDICAL_TEXT = re.compile(r"treatment|surgery|replacement|operation|hospital|doctor|procedure|clinic|dental|knee|hip|heart", re.I)
_WELLNESS_TEXT = re.compile(r"retreat|wellness|spa|longevity|detox|yoga|relax|programme|program", re.I)


def lane_unclear(analysis: Any, text: str) -> bool:
    """The analyzer's lane doubt, unless the visitor's own words name exactly one journey."""
    if not getattr(analysis, "lane_ambiguous", False):
        return False
    medical, wellness = bool(_MEDICAL_TEXT.search(text)), bool(_WELLNESS_TEXT.search(text))
    return medical == wellness


def slot_updates(conversation: Any, analysis: Any) -> dict[str, tuple[str, str]]:
    """slot id -> (value, status) from the analysis, lane aware. Legacy flat facts are mapped
    into the lane the visitor is talking about."""
    facts = conversation.case_facts
    active, focus = lanes_active(facts), focus_lane(facts)
    updates: dict[str, tuple[str, str]] = {
        sid: (e.get("value", ""), e.get("status", CONFIRMED)) for sid, e in analysis.slots.items()
    }
    hint = analysis.lane or _CATEGORY_LANE.get(analysis.category or "")
    for key, value in analysis.facts.items():
        lane = LANE_OF_KEY.get(key) or hint or focus or (active[0] if len(active) == 1 else None)
        slot = slot_for(key, lane)
        if slot and slot not in updates:
            updates[slot] = (str(value), CONFIRMED)
    pending = pending_slot_id(facts)
    if pending:
        from .chat_service import _GOAL_KEYWORDS

        # Only a slot the last reply actually asked about can be answered or refused.
        if _GOAL_KEYWORDS.get(BY_ID[pending].key) and not _asked_times(conversation, pending, window=1):
            pending = None
    last_user = next(
        (m.content for m in reversed(conversation.messages) if m.role == "user"), ""
    )
    still_asking = bool(re.search(r"[?؟]|\b(what|how|tell me|more about|like to know)\b", last_user, re.I))
    if analysis.intent == "declines" and pending and pending not in updates and not still_asking:
        updates[pending] = ("", DECLINED)
    # The analyzer over-reports "I don't know": believe UNSURE or DECLINED only for the slot
    # that was just asked about, never for slots the visitor did not mention.
    updates = {
        sid: v for sid, v in updates.items()
        if v[1] not in (UNSURE, DECLINED) or sid == pending
    }
    # "I'm in Oman" says where they live, whatever the analyzer made of it.
    place = _RESIDENCE.search(last_user)
    if place:
        country = place.group(1).strip(" .,'").lower()
        for sid in ("m.destination_country", "w.destination"):
            if sid in updates and updates[sid][0].strip().lower() == country:
                updates.pop(sid)
                updates["s.residence_country"] = (place.group(1).strip(" .,'").title(), CONFIRMED)
    # ...and only when the visitor's own words say so, not because the question went unanswered.
    updates = {
        sid: v for sid, v in updates.items()
        if not (
            (v[1] == UNSURE and not _DONT_KNOW.search(last_user))
            or (v[1] == DECLINED and not (_REFUSES.search(last_user) or analysis.intent == "declines"))
        )
    }
    if lane_unclear(analysis, last_user):  # rule 4: write nothing until the visitor says which journey
        updates = {sid: v for sid, v in updates.items() if BY_ID[sid].lane == SHARED}
    return updates


def apply_analysis(conversation: Any, analysis: Any, turn: int) -> list[tuple[str, Any]]:
    """Fact writes (key, value) for this turn: slot values and statuses, lanes, focus."""
    facts = conversation.case_facts
    state = SlotState(facts)
    writes: list[tuple[str, Any]] = []
    touched: set[str] = set()
    updates = slot_updates(conversation, analysis)
    updates, change_writes = _settle_changes(conversation, analysis, state, updates)
    writes += change_writes
    for slot_id, (value, status) in updates.items():
        writes += state.apply(slot_id, value or None, status, turn)
        if BY_ID[slot_id].lane != SHARED and status in (CONFIRMED, HEARD):
            touched.add(BY_ID[slot_id].lane)

    # Fallback: the legacy extractors sometimes catch a value the slot analyzer
    # missed. Fill still-EMPTY slots from unambiguous flat facts so the planner
    # never re-asks something already known. Lane-shared keys (destination,
    # timing, budget, travellers) are skipped — they need the analyzer's lane.
    _SKIP = {"declined", "unsure", "heard", "flexible", "not specified",
             "no preference", "none", "not provided", "undecided"}
    for slot in SLOTS:
        if state.status(slot.id) != EMPTY or slot.lane == SHARED:
            continue
        if slot.id not in LANE_OF_KEY.values():
            continue  # only keys with exactly one possible lane
        raw = facts.get(slot.key)
        if raw in (None, "") or isinstance(raw, dict):
            continue
        if str(raw).strip().lower() in _SKIP:
            continue
        writes += state.apply(slot.id, raw, CONFIRMED, turn)
        touched.add(slot.lane)
    for lane in (analysis.lane, _CATEGORY_LANE.get(analysis.category or "")):
        if lane:
            touched.add(lane)

    active = lanes_active(facts)
    for lane in (MEDICAL, WELLNESS):
        if lane in touched and lane not in active:
            active.append(lane)
    focus = focus_lane(facts)
    if len(touched) == 1:
        focus = next(iter(touched))  # they are talking about one journey: follow them
    elif len(touched) > 1:
        # Both journeys at once: work on the one the analyzer says comes first, else keep the
        # one already in focus, else start with the treatment.
        focus = analysis.lane if analysis.lane in touched else (focus if focus in touched else MEDICAL)
    elif not focus and active:
        focus = active[0]
    if active:
        writes.append(("lanes_active", ",".join(l for l in (MEDICAL, WELLNESS) if l in active)))
    if focus:
        writes += [("focus_lane", focus), ("customer_category", _LANE_CATEGORY[focus]),
                   ("trip_type", "medical" if focus == MEDICAL else "wellness")]
    if lane_unclear(analysis, next((m.content for m in reversed(conversation.messages) if m.role == "user"), "")) and len(active) > 1:
        writes.append(("lane_question", "1"))
    elif touched or analysis.slots:
        writes.append(("lane_question", ""))
    if analysis.intent == "accepts" and state.heard() and "make sure i have this right" in _last_assistant(conversation).lower():
        writes += state.promote_heard()  # they confirmed the recap
    return writes


_CHANGE_YES = re.compile(r"\b(change|switch|instead|replace|yes|yeah|yep|correct|go with|make it|that one|the new)\b", re.I)
_CHANGE_BOTH = re.compile(r"\b(both|second|also|as well|another option|alongside|in addition|too)\b", re.I)
_SPACES = re.compile(r"\s+")


def _norm(text: Any) -> str:
    return _SPACES.sub(" ", str(text or "").strip().lower())


def pending_change(facts: dict[str, Any]) -> dict[str, Any] | None:
    raw = facts.get("pending_change")
    if not raw:
        return None
    try:
        data = json.loads(raw) if isinstance(raw, str) else dict(raw)
    except (TypeError, ValueError):
        return None
    return data if data.get("slot") in BY_ID and data.get("new") else None


def change_asked_write(facts: dict[str, Any]) -> list[tuple[str, Any]]:
    """The check has been put to the visitor: from now on their next message answers it."""
    change = pending_change(facts)
    if not change or change.get("asked"):
        return []
    return [("pending_change", json.dumps({**change, "asked": True}, ensure_ascii=False))]


def _settle_changes(
    conversation: Any, analysis: Any, state: SlotState, updates: dict[str, tuple[str, str]],
) -> tuple[dict[str, tuple[str, str]], list[tuple[str, Any]]]:
    """Addendum 4.1: a new answer that contradicts a CONFIRMED value, without being called a
    correction, is held and checked once, lightly. A stated correction is applied at once."""
    facts = conversation.case_facts
    updates = dict(updates)
    writes: list[tuple[str, Any]] = []
    held = pending_change(facts)
    settled = False
    if held and held.get("asked"):
        last_user = next((m.content for m in reversed(conversation.messages) if m.role == "user"), "")
        asking = "?" in last_user and analysis.intent in {"question", "what_is_trawellcare", "how_it_works"}
        if not asking:
            sid, new, old = held["slot"], str(held["new"]), state.value(held["slot"])
            restated = updates.get(sid, ("", ""))[0]
            if _CHANGE_BOTH.search(last_user) and old:
                updates[sid] = (f"{old} and {new}", CONFIRMED)
            elif _CHANGE_YES.search(last_user) or analysis.intent == "accepts" or (
                restated and _norm(restated) == _norm(new)
            ):
                updates[sid] = (new, CONFIRMED)
            else:
                updates.pop(sid, None)  # keep the old one
            writes.append(("pending_change", ""))
            held, settled = None, True
    if held:
        updates.pop(held["slot"], None)  # still waiting for the answer to the check
    if getattr(analysis, "correction", False) or settled:
        return updates, writes
    for sid, (value, status) in list(updates.items()):
        old = state.value(sid)
        if status != CONFIRMED or not value or old is None or state.status(sid) != CONFIRMED:
            continue
        if sid == "s.preferred_name":
            continue
        a, b = _norm(old), _norm(value)
        if a == b or a in b or b in a:
            continue  # the same thing, or a more specific version of it
        updates.pop(sid)
        writes.append(("pending_change", json.dumps({"slot": sid, "new": value, "old": old}, ensure_ascii=False)))
        break  # one check at a time
    return updates, writes


def _last_assistant(conversation: Any) -> str:
    return next((m.content for m in reversed(conversation.messages) if m.role == "assistant"), "")


def _asked_times(conversation: Any, slot_id: str, window: int = 6) -> int:
    from .chat_service import _GOAL_KEYWORDS  # keyword hints per field

    pattern = _GOAL_KEYWORDS.get(BY_ID[slot_id].key)
    if not pattern:
        return 0
    recent = [m.content for m in conversation.messages if m.role == "assistant"][-window:]
    return sum(
        1 for content in recent
        if any(re.search(pattern, part, re.I) for part in re.split(r"(?<=[.!?])\s+", content) if "?" in part)
    )


def stuck_slot_writes(conversation: Any, turn: int, already: dict[str, Any]) -> list[tuple[str, Any]]:
    """A question asked three times with no answer is treated as UNSURE: never loop on a slot."""
    slot_id = pending_slot_id(conversation.case_facts)
    if not slot_id or any(k == BY_ID[slot_id].key for k, _ in already):
        return []
    state = SlotState(conversation.case_facts)
    if state.status(slot_id) != "EMPTY" or _asked_times(conversation, slot_id) < 2:
        return []
    return state.apply(slot_id, None, UNSURE, turn)


def plan_handoff(planner: Any, conversation: Any, decision: Any, intent: str | None, analysis: Any = None) -> PlannedStep:
    """Next step, in the addendum's priority order (5.3)."""
    if decision.escalation_required:
        return PlannedStep("escalate", "Safety or policy escalation takes priority.")
    facts = conversation.case_facts
    state = SlotState(facts)
    messages = conversation.messages
    assistants = sum(1 for m in messages if m.role == "assistant")
    turns = user_turn_count(conversation)
    active, focus = lanes_active(facts), focus_lane(facts)

    # 1. Safety
    if facts.get("under_18") or intent == "under_18":
        return PlannedStep("stop_intake", "The visitor is under 18: intake stops (S14).")
    last_text = next((m.content for m in reversed(messages) if m.role == "user"), "")
    if intent == "wants_stop" and _STOP_WORDS.search(last_text):
        return PlannedStep("opt_out", "The visitor asked us to stop or to forget them (S11).")
    if intent == "wants_stop":
        intent = "smalltalk"  # a goodbye is not an opt-out request
    if intent == "wants_human":
        return PlannedStep("human_request", "The visitor wants a person now (S10).")

    offered_at = facts.get("handoff_offer_turn")
    just_offered = bool(offered_at) and str(offered_at) == str(assistants)
    if just_offered and intent == "accepts":
        return PlannedStep("handoff_link", "They accepted: give the signup and login page.")
    if just_offered and intent == "declines":
        return PlannedStep("handoff_declined", "They declined the signup offer (S8).")

    # A new value that contradicts a confirmed one is checked once, lightly (addendum 4.1).
    change = pending_change(facts)
    if change and not change.get("asked") and intent not in {"what_is_trawellcare", "how_it_works"}:
        slot = BY_ID[change["slot"]]
        return PlannedStep(
            "confirm_change", "A new answer conflicts with a confirmed one: check it once.",
            question_goal=f"change {slot.label}", target_field=slot.key, slot_id=change["slot"],
            lane=slot.lane if slot.lane != SHARED else focus,
            question_text=(
                f"Ask lightly whether they want to change {slot.label} from {change.get('old')} to "
                f"{change['new']}, or whether {change['new']} is a second option alongside it."
            ),
        )

    # A visitor who is simply done is let go warmly, with nothing new to answer or ask.
    if _is_closing(conversation, intent):
        return PlannedStep("close", "The visitor is wrapping up: close warmly, no new question.")

    # 2. Booking, quote or a callback: the offer comes straight away, whatever is filled in.
    if intent == "wants_booking":
        return PlannedStep(
            "signup_handoff", "They asked to book or get a quote: offer now.",
            question_goal="signup handoff", target_field="handoff",
        )

    # 3. Two journeys and a value that fits both: ask which, in one light question.
    if analysis is not None and lane_unclear(analysis, next((m.content for m in reversed(messages) if m.role == "user"), "")) and len(active) > 1:
        return PlannedStep(
            "clarify_lane", "Rule 4: the value could belong to either journey.",
            question_goal="which journey",
            question_text="Is that for the treatment or for the retreat?",
            target_field="lane",
        )

    # The visitor's own optional first name, asked once and only when it feels natural.
    name_asked = any(
        m.role == "assistant" and re.search(r"(?:call you|what to call)", m.content, re.I)
        for m in messages
    )
    plain = intent not in {"question", "off_topic", "emotional", "clinical_detail", "what_is_trawellcare", "how_it_works"}
    if not name_asked and state.status("s.preferred_name") == "EMPTY" and turns >= 1 and plain:
        return PlannedStep(
            "collect_detail", "Ask for an optional preferred first name.",
            question_goal="preferred name", target_field="preferred_name", slot_id="s.preferred_name",
            question_text="What would you like me to call you? A first name is perfect, and no worries if you'd rather not say.",
        )

    # Deterministic question guard: whatever the analyzer called it, a visitor
    # who is still asking things gets answers before any offer (addendum 5.3).
    last_user = next(
        (m.content for m in reversed(messages) if m.role == "user"), ""
    )
    asks = bool(
        re.search(r"[?؟]|\b(what|how|can|could|do you|are you|tell me|explain|"
                  r"more about|features?|include[sd]?|offer[sd]?)\b", last_user, re.I)
    )
    # A correction or change of mind is the visitor's own thread (5.3 priority
    # 4): acknowledge the change, never answer it with the signup offer.
    correcting = bool(
        getattr(analysis, "correction", False)
        or re.search(
            r"\b(actually|instead|change|wait|no i meant|i meant|correction|"
            r"rather|scratch that|make that|update|on second thought|"
            r"changed my mind|switch|prefer .* instead|new dates?|new budget|"
            r"different destination|different dates?)\b",
            last_user, re.I,
        )
    )
    blocking = asks or correcting or intent in {
        "question", "mixed", "off_topic", "new_request", "clinical_detail", "asks_interpretation",
        "asks_if_human", "contact_request", "contact_channel", "what_is_trawellcare", "how_it_works", "emotional",
    }
    if not active:
        # B6: the fifth visitor message offers the consultation even when the
        # journey is still unclear — never while they are mid-question.
        if turns >= 5 and not facts.get("handoff_offer_turn") and not blocking:
            return PlannedStep(
                "signup_handoff", "The conversation has gone on long enough: offer the free consultation.",
                question_goal="signup handoff", target_field="handoff",
            )
        attempts = _clarify_attempts(conversation)
        return PlannedStep(
            "clarify_category", "Neither journey is clear yet.",
            question_goal="customer category", target_field="customer_category",
            clarify_attempts=attempts,
            question_text=(
                "What brings you to trawellcare today? Is it a medical treatment you are exploring, "
                "or something more like a wellness experience?"
            ) if attempts == 0 else "Tell me in your own words what you have in mind, and I'll help from there.",
        )

    focus = focus or active[0]
    declined_at = facts.get("decline_turn")
    cooling = bool(declined_at) and turns - int(declined_at) < COOLING_MESSAGES
    # The slot minimum alone is not enough: the visitor should have shared a
    # few real details (three filled slots in this journey) before the offer
    # lands, unless the conversation has simply gone on long enough (B6).
    enough = (
        state.meets_handoff_minimum(focus) and len(state.lane_values(focus)) >= 3 and turns >= 3
    ) or turns >= 5
    if enough and not offered_at and not blocking and not cooling:
        return PlannedStep(
            "signup_handoff", "Enough is known for this journey: offer the free consultation.",
            question_goal="signup handoff", target_field="handoff",
            lane=focus if len(active) < 2 else f"{focus}+other",
        )
    if offered_at and declined_at and turns - int(declined_at) >= COOLING_MESSAGES and enough and not blocking:
        return PlannedStep(
            "signup_handoff", "The cooling period is over and they are still engaged.",
            question_goal="signup handoff", target_field="handoff", lane=focus,
        )

    # 4. The next empty slot that follows naturally. HEARD, CONFIRMED, UNSURE and DECLINED are not asked.
    slot_id = _next_fresh(state, conversation, focus)
    if slot_id is None and len(active) > 1:
        other = WELLNESS if focus == MEDICAL else MEDICAL
        other_slot = _next_fresh(state, conversation, other)
        if other_slot:
            return PlannedStep(
                "collect_detail", "The first journey is covered; move to the other and say so.",
                question_goal=BY_ID[other_slot].label, target_field=BY_ID[other_slot].key,
                slot_id=other_slot, lane=other, switch_lane=True,
                question_text=_question_for(planner, BY_ID[other_slot].key, other),
            )
    if slot_id and blocking and _asked_times(conversation, slot_id, window=2) >= 1:
        # They are asking something, and this slot was just asked: answer, do not ask it again.
        return PlannedStep("answer", "The visitor asks something; the last question is still open.", answer_first=True)
    if slot_id:
        slot = BY_ID[slot_id]
        return PlannedStep(
            "collect_detail", "The next empty slot in this journey.",
            question_goal=slot.label, target_field=slot.key, slot_id=slot_id, lane=focus,
            question_text=_question_for(planner, slot.key, focus),
        )
    if not offered_at and not blocking and not cooling:
        return PlannedStep(
            "signup_handoff", "Everything useful is shared: offer the free consultation.",
            question_goal="signup handoff", target_field="handoff", lane=focus,
        )
    return PlannedStep("answer", "Nothing is missing: stay with what the visitor wants to talk about.")


_STOP_WORDS = re.compile(
    r"\bstop\b|unsubscribe|don'?t (?:contact|message|call|email|text)|do not (?:contact|message|call|email)|"
    r"forget (?:me|my)|delete (?:me|my)|remove (?:me|my)|opt[- ]?out|leave me alone|no more (?:messages|emails|calls)",
    re.I,
)
_FAREWELL = re.compile(
    r"\b(that'?s (?:all|it|everything|enough)|that will be all|nothing else|no (?:more|other) questions|"
    r"i'?m (?:done|all set|good for now)|all good|good ?bye|bye|talk (?:to you )?later|see you|"
    r"thanks?,? (?:that'?s|bye|for now)|i'?ll (?:think about it|come back|get back))\b",
    re.I,
)


def _is_closing(conversation: Any, intent: str | None) -> bool:
    last_user = next((m.content for m in reversed(conversation.messages) if m.role == "user"), "")
    if not last_user or "?" in last_user or len(last_user.split()) > 14:
        return False
    if intent in {"question", "mixed", "wants_booking", "wants_human", "emotional", "clinical_detail"}:
        return False
    return bool(_FAREWELL.search(last_user)) and user_turn_count(conversation) >= 2


_LANE_QUESTIONS = {
    "preferred_timing": "Roughly when are you hoping to have the treatment?",
    "w_destination": "Where would you love the retreat to be?",
    "w_dates_window": "Roughly when are you thinking of going?",
    "w_participants": "Will it be just you, or is anyone joining you?",
    "w_budget_band": "Do you have a rough budget band in mind for the retreat? A range is perfectly fine 😊",
}


def _next_fresh(state: SlotState, conversation: Any, lane: str) -> str | None:
    """The next empty slot that has not already been asked about twice without an answer."""
    for slot_id in ORDER.get(lane, ()):
        if state.status(slot_id) != EMPTY:
            continue
        if slot_id == "w.experience_type" and state.lane_values(lane):
            continue
        if _asked_times(conversation, slot_id) >= 2:
            continue
        return slot_id
    return None


def _question_for(planner: Any, key: str, lane: str) -> str:
    return _LANE_QUESTIONS.get(key) or planner._question_for(key, _LANE_CATEGORY.get(lane))


def _clarify_attempts(conversation: Any) -> int:
    from .question_planner import clarify_attempts

    return clarify_attempts(conversation)


def flow_state_for(step: PlannedStep, facts: dict[str, Any], intent: str | None) -> str:
    """The named flow state after this turn (addendum part 5)."""
    kind = step.decision_type
    if kind in {"escalate", "stop_intake"}:
        return "SAFETY_HOLD"
    if kind == "signup_handoff":
        return "HANDOFF_OFFERED"
    if kind == "handoff_declined":
        return "HANDOFF_DECLINED"
    if kind in {"handoff_link", "opt_out", "close"}:
        return "CLOSED"
    if intent in {"question", "what_is_trawellcare", "how_it_works", "off_topic"}:
        return "GENERAL_QA"
    focus = focus_lane(facts)
    if focus == MEDICAL:
        return "MEDICAL_INTAKE"
    if focus == WELLNESS:
        return "WELLNESS_INTAKE"
    return "DISCOVERY" if facts.get("flow_state") not in (None, "", "GREETING") else "GREETING"


def state_snapshot(conversation: Any, step: PlannedStep | None = None) -> dict[str, Any]:
    """The structured state given to the model every turn (addendum 7.1, block 2)."""
    facts = conversation.case_facts
    state = SlotState(facts)
    turns = user_turn_count(conversation)
    declined_at = facts.get("decline_turn")
    return {
        "turn": turns,
        "flow_state": facts.get("flow_state") or "GREETING",
        "focus_lane": focus_lane(facts),
        "lanes_active": lanes_active(facts),
        "pending_slot": step.slot_id if step and step.slot_id else pending_slot_id(facts),
        "handoff": {
            "offered": bool(facts.get("handoff_offered")),
            "declined": bool(facts.get("handoff_declined")),
            "cooling_left": max(0, COOLING_MESSAGES - (turns - int(declined_at))) if declined_at else 0,
        },
        "slots": state.snapshot(),
        "heard_to_echo_once": state.heard(),
    }


async def rebuild_writes(analyzer: Any, conversation: Any) -> list[tuple[str, Any]]:
    """Addendum 5.2: the state was lost. Rebuild it from the last visitor messages, marking
    every value HEARD so Hayat confirms it with the visitor before relying on it."""
    recent = [m.content for m in conversation.messages if m.role == "user"][-4:]
    if not recent:
        return []
    analysis = await analyzer.analyze(
        text=" / ".join(recent), last_assistant="", pending_field=None, known={}, state={"rebuild": True},
    ) if getattr(analyzer, "slots_mode", False) else None
    if analysis is None or not (analysis.slots or analysis.facts):
        return []
    # Every rebuilt value is HEARD (applied below). The analysis itself is never modified.
    state = SlotState(conversation.case_facts)
    writes: list[tuple[str, Any]] = []
    touched: set[str] = set()
    for slot_id, (value, _status) in slot_updates(conversation, analysis).items():
        if value:
            writes += state.apply(slot_id, value, HEARD, user_turn_count(conversation))
            if BY_ID[slot_id].lane != SHARED:
                touched.add(BY_ID[slot_id].lane)
    if touched:
        focus = next(iter(touched)) if len(touched) == 1 else sorted(touched)[0]
        writes += [
            ("lanes_active", ",".join(l for l in (MEDICAL, WELLNESS) if l in touched)),
            ("focus_lane", focus), ("customer_category", _LANE_CATEGORY[focus]),
        ]
    return writes
