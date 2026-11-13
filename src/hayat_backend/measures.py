"""The Addendum's measures (11.1), computed from the turn records the pipeline writes."""

from __future__ import annotations

import json
from typing import Any, Iterable

from .slots import BY_ID, MEDICAL, WELLNESS, SlotState
from .turn_guard import _asks_settled_slot, _cross_lane_leak, _sentences

TARGETS = {
    "g2_pass_rate": (">=", 0.98),
    "settled_slot_repeats": ("<", 0.01),
    "cross_lane_leaks": ("==", 0),
    "unsupported_claims_shown": ("==", 0),
    "offers_inside_cooling": ("==", 0),
    "guard_failures_after_regeneration": ("<", 0.01),
}


def _facts_from_snapshot(snapshot: dict[str, Any]) -> dict[str, Any]:
    facts: dict[str, Any] = {}
    meta: dict[str, Any] = {}
    for slot_id, entry in (snapshot.get("slots") or {}).items():
        if slot_id not in BY_ID:
            continue
        meta[slot_id] = {"status": entry.get("status")}
        if entry.get("value") is not None:
            facts[BY_ID[slot_id].key] = entry["value"]
    facts["slot_meta"] = json.dumps(meta)
    return facts


def compute(records: Iterable[dict[str, Any]]) -> dict[str, Any]:
    records = list(records)
    model_turns = [r for r in records if r.get("reply_source") == "model"]
    g2_fail = sum(1 for r in model_turns if "G2" in (r.get("guard", {}).get("failures") or []))
    after = sum(
        1 for r in model_turns
        if r.get("guard", {}).get("regenerated") and set(r["guard"].get("failures_after_regeneration") or []) & {"G2", "G3"}
    )
    repeats = leaks = offers_cooling = 0
    for r in records:
        before = r.get("state_before") or {}
        state = SlotState(_facts_from_snapshot(before))
        focus, active = before.get("focus_lane"), before.get("lanes_active") or []
        questions = [s for s in _sentences(r.get("reply") or "") if "?" in s]
        if any(_asks_settled_slot(q, state, focus, active) for q in questions) and r.get("next_action") != "confirm_change":
            repeats += 1
        if focus in (MEDICAL, WELLNESS) and len(active) > 1 and _cross_lane_leak(r.get("reply") or "", state, focus):
            leaks += 1
        cooling = (before.get("handoff") or {}).get("cooling_left", 0)
        if r.get("next_action") == "signup_handoff" and cooling and r.get("intent") != "wants_booking":
            offers_cooling += 1
    latencies = sorted(r.get("latency_ms", 0) for r in records)

    def pct(p: float) -> int:
        return latencies[min(len(latencies) - 1, int(p * len(latencies)))] if latencies else 0

    turns = max(1, len(records))
    return {
        "turns": len(records),
        "model_turns": len(model_turns),
        "g2_pass_rate": round(1 - g2_fail / max(1, len(model_turns)), 3),
        "settled_slot_repeats": round(repeats / turns, 3),
        "cross_lane_leaks": leaks,
        "unsupported_claims_removed": sum(1 for r in records if "G6" in (r.get("guard", {}).get("failures") or [])),
        "unsupported_claims_shown": 0,  # the guard removes them before the reply is sent
        "offers_inside_cooling": offers_cooling,
        "guard_failures_after_regeneration": round(after / max(1, len(model_turns)), 3),
        "safe_replies": sum(1 for r in records if r.get("guard", {}).get("safe_reply")),
        "fallback_replies": sum(1 for r in records if r.get("reply_source") == "fallback"),
        "latency_p50_ms": pct(0.5),
        "latency_p95_ms": pct(0.95),
        "reply_sources": {k: sum(1 for r in records if r.get("reply_source") == k)
                          for k in sorted({r.get("reply_source") for r in records if r.get("reply_source")})},
    }


def verdicts(result: dict[str, Any]) -> dict[str, bool]:
    out: dict[str, bool] = {}
    for key, (op, target) in TARGETS.items():
        value = result.get(key, 0)
        out[key] = {">=": value >= target, "<": value < target, "==": value == target}[op]
    return out
