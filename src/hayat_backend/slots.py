"""Slot based memory with two journeys (lanes), from the flow and state addendum.

Hayat does not rely on remembering the chat. Every turn she is given a snapshot of what the
visitor has told her. Each slot belongs to a lane: shared (person level), MEDICAL or
WELLNESS. A visitor can have both journeys open at once; their trip details are never merged.

Values are stored as flat facts (so the coordinator card and the other code keep working);
the status of each slot, and the values it replaced, live in one JSON fact, "slot_meta".
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

# Statuses (addendum 2.2)
EMPTY, HEARD, CONFIRMED, UNSURE, DECLINED = "EMPTY", "HEARD", "CONFIRMED", "UNSURE", "DECLINED"
NEVER_ASK_AGAIN = {CONFIRMED, UNSURE, DECLINED}

SHARED, MEDICAL, WELLNESS = "SHARED", "MEDICAL", "WELLNESS"


@dataclass(frozen=True)
class SlotDef:
    id: str
    lane: str
    key: str          # the flat fact that holds the value
    label: str        # plain words, used in the state snapshot and lane questions
    ask: str          # a natural way to ask, as guidance for the model (never copied)


SLOTS: tuple[SlotDef, ...] = (
    SlotDef("s.preferred_name", SHARED, "preferred_name", "what to call them", "what they would like to be called"),
    SlotDef("s.residence_country", SHARED, "current_country", "country of residence", "which country they are based in"),
    SlotDef("s.language", SHARED, "visitor_language", "language", "never asked: taken from the first message"),
    SlotDef("m.service_category", MEDICAL, "procedure_or_service", "treatment type", "what kind of treatment or specialty"),
    SlotDef("m.destination_country", MEDICAL, "destination_preference", "treatment destination", "which country they would travel to for treatment"),
    SlotDef("m.timeline_window", MEDICAL, "preferred_timing", "treatment timeframe", "a rough window for the treatment"),
    SlotDef("m.budget_band", MEDICAL, "budget_range", "treatment budget band", "a rough budget band for the treatment"),
    SlotDef("m.travellers_count", MEDICAL, "travellers_count", "travellers for the treatment", "how many people are travelling"),
    SlotDef("m.named_provider", MEDICAL, "preferred_provider", "hospital or doctor they already have", "only recorded if they mention one"),
    SlotDef("w.experience_type", WELLNESS, "wellness_programme_or_goal", "kind of wellness experience", "what kind of wellness experience"),
    SlotDef("w.goal_category", WELLNESS, "wellness_goal", "wellness goal", "the feeling or goal they want from it"),
    SlotDef("w.destination", WELLNESS, "w_destination", "retreat destination", "where they would like the retreat to be"),
    SlotDef("w.dates_window", WELLNESS, "w_dates_window", "retreat dates window", "a rough window for the retreat"),
    SlotDef("w.duration_nights", WELLNESS, "trip_duration", "retreat length", "roughly how long"),
    SlotDef("w.participants_count", WELLNESS, "w_participants", "participants for the retreat", "how many people are joining"),
    SlotDef("w.budget_band", WELLNESS, "w_budget_band", "retreat budget band", "a rough budget band for the retreat"),
    SlotDef("w.programme_interest", WELLNESS, "preferred_programme", "programme of interest", "only recorded as it emerges"),
)
BY_ID = {s.id: s for s in SLOTS}
BY_KEY = {s.key: s for s in SLOTS}

# Default order of questions per lane (addendum 5.5). The named provider and the programme of
# interest are recorded when the visitor mentions them; Hayat never asks for them.
ORDER = {
    MEDICAL: (
        "m.service_category", "m.destination_country", "m.timeline_window", "m.budget_band",
        "s.residence_country", "m.travellers_count",
    ),
    WELLNESS: (
        "w.experience_type", "w.goal_category", "w.destination", "w.dates_window",
        "w.duration_nights", "w.participants_count", "w.budget_band",
    ),
}
# What is enough to offer the free consultation (addendum 5.4).
HANDOFF_MINIMUM = {
    MEDICAL: ("m.service_category", ("m.destination_country", "m.timeline_window")),
    WELLNESS: ("w.experience_type", ("w.destination", "w.goal_category", "w.programme_interest")),
}

# Legacy flat keys that mean the same thing in either lane, with each lane's slot.
LANE_KEYS = {
    "destination_preference": {MEDICAL: "m.destination_country", WELLNESS: "w.destination"},
    "preferred_timing": {MEDICAL: "m.timeline_window", WELLNESS: "w.dates_window"},
    "budget_range": {MEDICAL: "m.budget_band", WELLNESS: "w.budget_band"},
    "travellers_count": {MEDICAL: "m.travellers_count", WELLNESS: "w.participants_count"},
}
LANE_OF_KEY = {
    "procedure_or_service": MEDICAL, "preferred_provider": MEDICAL,
    "wellness_programme_or_goal": WELLNESS, "wellness_goal": WELLNESS,
    "preferred_programme": WELLNESS, "trip_duration": WELLNESS,
}

META_KEY = "slot_meta"


def _clean(value: Any) -> str:
    return str(value).strip()[:120]


class SlotState:
    """A view of a conversation's slots. Writes return the facts to persist."""

    def __init__(self, case_facts: dict[str, Any]) -> None:
        self.facts = case_facts
        try:
            meta = json.loads(case_facts.get(META_KEY) or "{}")
        except (TypeError, ValueError):
            meta = {}
        self.meta: dict[str, dict[str, Any]] = meta if isinstance(meta, dict) else {}
        # Writes made this turn are kept here and returned for saving; the conversation's own
        # facts are only changed by the normal save path.
        self.overlay: dict[str, Any] = {}

    # ---- reading -------------------------------------------------------------------------
    def value(self, slot_id: str) -> str | None:
        key = BY_ID[slot_id].key
        raw = self.overlay[key] if key in self.overlay else self.facts.get(key)
        return None if raw in (None, "") or isinstance(raw, dict) else str(raw)

    def status(self, slot_id: str) -> str:
        recorded = self.meta.get(slot_id, {}).get("status")
        if recorded:
            return recorded
        return CONFIRMED if self.value(slot_id) is not None else EMPTY

    def history(self, slot_id: str) -> list[str]:
        return list(self.meta.get(slot_id, {}).get("history", []))

    def asked_enough(self, slot_id: str) -> bool:
        """True when the slot must not be asked about again."""
        return self.status(slot_id) in NEVER_ASK_AGAIN

    def lane_values(self, lane: str) -> dict[str, str]:
        return {
            s.id: v for s in SLOTS
            if s.lane == lane and self.status(s.id) in (HEARD, CONFIRMED)
            and (v := self.value(s.id)) is not None
        }

    def has_lane(self, lane: str) -> bool:
        return bool(self.lane_values(lane))

    def next_empty(self, lane: str) -> str | None:
        for slot_id in ORDER.get(lane, ()):
            if self.status(slot_id) != EMPTY:
                continue
            if slot_id == "w.experience_type" and self.lane_values(lane):
                continue  # a goal, destination or programme already says what kind of experience it is
            return slot_id
        return None

    def meets_handoff_minimum(self, lane: str) -> bool:
        needed, any_of = HANDOFF_MINIMUM[lane]
        known = lambda i: self.status(i) in (HEARD, CONFIRMED) and self.value(i) is not None  # noqa: E731
        return known(needed) and any(known(i) for i in any_of)

    def snapshot(self) -> dict[str, Any]:
        """What Hayat is told about the visitor every turn (values, never sensitive text)."""
        out: dict[str, Any] = {}
        for slot in SLOTS:
            status = self.status(slot.id)
            if status == EMPTY:
                continue
            entry: dict[str, Any] = {"status": status}
            if status in (HEARD, CONFIRMED):
                entry["value"] = self.value(slot.id)
            if self.history(slot.id):
                entry["was"] = self.history(slot.id)[-1]
            out[slot.id] = entry
        return out

    # ---- writing -------------------------------------------------------------------------
    def apply(self, slot_id: str, value: Any, status: str, turn: int) -> list[tuple[str, Any]]:
        """Set a slot. A correction keeps the old value in history. Returns (key, value) to save."""
        slot = BY_ID[slot_id]
        entry = self.meta.setdefault(slot_id, {})
        old = self.value(slot_id)
        value = None if value is None else _clean(value)
        if status in (UNSURE, DECLINED):
            value = status.lower()  # the flat fact records that it was answered
        if old is not None and value is not None and old != value and self.status(slot_id) in (HEARD, CONFIRMED):
            entry["history"] = (entry.get("history", []) + [old])[-5:]
        entry.update({"status": status, "turn": turn})
        self.overlay[slot.key] = value
        return [(slot.key, value), (META_KEY, json.dumps(self.meta, ensure_ascii=False))]

    def promote_heard(self) -> list[tuple[str, Any]]:
        """The visitor accepted a recap: everything HEARD becomes CONFIRMED."""
        changed = False
        for slot_id, entry in self.meta.items():
            if entry.get("status") == HEARD:
                entry["status"] = CONFIRMED
                changed = True
        return [(META_KEY, json.dumps(self.meta, ensure_ascii=False))] if changed else []

    def heard(self) -> list[str]:
        return [s.id for s in SLOTS if self.status(s.id) == HEARD and self.value(s.id) is not None]


def slot_for(key: str, lane: str | None) -> str | None:
    """The slot a legacy flat key means, in the given lane."""
    if key in LANE_KEYS:
        return LANE_KEYS[key].get(lane or "")
    slot = BY_KEY.get(key)
    return slot.id if slot else None
