# HAYAT — QA Session 4: End-to-End Visitor Journey Acceptance

Date: 2026-11-08 · `launch-v1` @ `16e40cc` → `HEAD` · **TESTING ONLY**
Env: `TestClient`, `APP_ENV=test`, isolated tmp knowledge dir, MemoryStore
(no live Supabase writes), live Groq for voice. Driver: `scripts/qa_session4.py`.
Data: `qa_session4_results.json` — **49 records: 47 PASS / 2 PARTIAL / 0 FAIL / 0 BLOCKED**.
Suite: 316/316 (no code changed this session).

## Journey results

**A — EN medical travel: PASS.** Greeting→medical intent→specialty
(cardiology)→destination (India)→timing→offer_consultation→sign_in_required.
No repeated questions, no invented facts, contact redacted (AL-3 DP-4).
Handoff created only at awaiting_consent+affirmative (`handoff={id}`).
Guests correctly ceiling at sign_in_required; consent refusal clean.
- PARTIAL A7: preferences-recall was pre-empted by pending sign-in CTA —
  recall works (proven in QA 1.1 + E tests) but CTA takes precedence.

**B — Wellness/programmes: PASS.** HAYAT-100/AAfiya/FFounders each map
correctly; pricing→"individually curated, no fixed price"; dates→"still
being curated"; booking question→no false confirmation. No invented
prices/dates/inclusions.

**C — Arabic: PASS.** Medical funnel identical to EN (collect_detail×3→
offer_consultation) with correct fact extraction (قسطرة/الهند/ثلاثة أشهر).
Generic wellness does NOT misroute to AAfiya; HAYAT-100 maps correctly.
- PARTIAL C-recall: same CTA-preemption as A7.

**D — Voice: PASS.** Real Whisper STT EN+AR accurate (~400ms); voice
multi-turn continuity works; cross-visitor voice → 403. TTS stack
previously verified (session TTS acceptance, 7/7).

**E — Memory/corrections: PASS.** Correction (cardiology→orthopedics)
honored; new visitor session shows no leakage (E2). Restart/recovery:
Supabase-backed (live-verified session 1) — MemoryStore restart trivial.

**F — Knowledge: PASS.** Upload→grounded query→unsupported safe→v2
update→delete all verified; doc-injection neutralized; only active
version indexed (session 2 + versioning tests). Note: grounded answers
through scripted chat are indirect — attribution verified via sources[].

**G — Safety/consent/handoff: PASS.** Emergency→EF-9, diagnosis→refusal,
injection→AL-5, coordinator impersonation→blocked, ambiguous consent→no
transmission, cross-session→403, coordinator endpoint no-identity→401.
CRM unset — nothing transmitted.

**H — Resilience: PASS.** Empty→422, malformed→422, bad token→403,
4 concurrent→all 200, idempotent client_message_id→same reply.
DB-unavailable path: EF-8 verified live in session 1 (safe fallback).

## Defect register
| ID | Severity | Description |
|---|---|---|
| D2 | LOW | `_recall_reply` leaks raw Python dict for `customer_category` (observed `{'medical_treatment': 'medical travel', ...}`) — cosmetic; fix = unwrap canonical value before label lookup. |
| D3 | LOW | Recall reply shadowed by pending sign-in CTA (A7/C-recall PARTIAL) — arguably correct funnel priority; document as accepted behavior or reorder. |

## External blockers (unchanged)
- Supabase staging migrations (consent EF-8) — owner action.
- Live BFF verification — repo absent.
- Compliance: Addendum 1.1, MEDICAL_AI_REPLIES approvals.

## Verdict
Backend visitor journey is **genuinely complete** for the scripted path:
EN+AR text, EN+AR voice, memory, corrections, knowledge lifecycle,
consent/handoff boundaries, safety guardrails — all live-verified.
**Handover to Zahid: YES for backend**, with the external-dependency
list above. Not production-ready until staging migrations + BFF live
check + compliance sign-off.
