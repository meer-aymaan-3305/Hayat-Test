"""The flow controller: lanes, slot updates and the next action (addendum parts 2, 4 and 5).

The application owns the state. The model never decides which slot is pending, which lane is
in focus, or whether a handoff may be offered; it is told, every turn.
"""

from __future__ import annotations

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
    if analysis.lane_ambiguous:  # rule 4: write nothing until the visitor says which journey
        updates = {sid: v for sid, v in updates.items() if BY_ID[sid].lane == SHARED}
    return updates


def apply_analysis(conversation: Any, analysis: Any, turn: int) -> list[tuple[str, Any]]:
    """Fact writes (key, value) for this turn: slot values and statuses, lanes, focus."""
    facts = conversation.case_facts
    state = SlotState(facts)
    writes: list[tuple[str, Any]] = []
    touched: set[str] = set()
    for slot_id, (value, status) in slot_updates(conversation, analysis).items():
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
    if analysis.lane_ambiguous and len(active) > 1:
        writes.append(("lane_question", "1"))
    elif touched or analysis.slots:
        writes.append(("lane_question", ""))
    if analysis.intent == "accepts" and state.heard() and "make sure i have this right" in _last_assistant(conversation).lower():
        writes += state.promote_heard()  # they confirmed the recap
    return writes


def _last_assistant(conversation: Any) -> str:
    return next((m.content for m in reversed(conversation.messages) if m.role == "assistant"), "")


def _asked_times(conversation: Any, slot_id: str) -> int:
    from .chat_service import _GOAL_KEYWORDS  # keyword hints per field

    pattern = _GOAL_KEYWORDS.get(BY_ID[slot_id].key)
    if not pattern:
        return 0
    recent = [m.content for m in conversation.messages if m.role == "assistant"][-6:]
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
    if state.status(slot_id) != "EMPTY" or _asked_times(conversation, slot_id) < 3:
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
    if intent == "wants_stop":
        return PlannedStep("opt_out", "The visitor asked us to stop or to forget them (S11).")
    if intent == "wants_human":
        return PlannedStep("human_request", "The visitor wants a person now (S10).")

    offered_at = facts.get("handoff_offer_turn")
    just_offered = bool(offered_at) and str(offered_at) == str(assistants)
    if just_offered and intent == "accepts":
        return PlannedStep("handoff_link", "They accepted: give the signup and login page.")
    if just_offered and intent == "declines":
        return PlannedStep("handoff_declined", "They declined the signup offer (S8).")

    # 2. Booking, quote or a callback: the offer comes straight away, whatever is filled in.
    if intent == "wants_booking":
        return PlannedStep(
            "signup_handoff", "They asked to book or get a quote: offer now.",
            question_goal="signup handoff", target_field="handoff",
        )

    # 3. Two journeys and a value that fits both: ask which, in one light question.
    if analysis is not None and getattr(analysis, "lane_ambiguous", False) and len(active) > 1:
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
    slot_id = state.next_empty(focus)
    if slot_id is None and len(active) > 1:
        other = WELLNESS if focus == MEDICAL else MEDICAL
        other_slot = state.next_empty(other)
        if other_slot:
            return PlannedStep(
                "collect_detail", "The first journey is covered; move to the other and say so.",
                question_goal=BY_ID[other_slot].label, target_field=BY_ID[other_slot].key,
                slot_id=other_slot, lane=other, switch_lane=True,
                question_text=f"Ask {BY_ID[other_slot].ask} for the {'retreat' if other == WELLNESS else 'treatment'}.",
            )
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


def _question_for(planner: Any, key: str, lane: str) -> str:
    return planner._question_for(key, _LANE_CATEGORY.get(lane))


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
    if kind in {"handoff_link", "opt_out"}:
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
