# HAYAT — Live Product QA Session (Steps 1–2 only)

Date: 2026-11-08 · Branch `launch-v1` @ `ffd3267` · **TESTING ONLY — no code changed**

## Step 1 — Environment
- HEAD `ffd3267` (newer than expected `717282e`; includes AR extraction sprint).
- `git status`: clean except preserved untracked files.
- `APP_ENV`: `.env`=development; **server run with `APP_ENV=test`** because
  `JWT_SYSTEM_SECRET` is unset → all `/v1` routes 401 in dev. Service-auth
  bypass is the same path the test suite uses. `X-Visitor: guest` sent on
  every call → scripted replies (no live LLM).
- Startup: `uv run uvicorn hayat_backend.main:app --host 127.0.0.1 --port 2005`
- Health: `{"status":"ok","integrations":{"groq":"configured","supabase":"configured"}}`
- Suite: **295/295 pass** (~13s).
- **SupabaseStore was ACTIVE** — real project `ykhggqiyjzqisgolataa.supabase.co`
  received live writes (201s observed). This was NOT MemoryStore.

## Step 2 — Scenario results (17 records, `qa_results.json`, `scripts/qa_session.py`)

| ID | Input | Result | Verdict |
|---|---|---|---|
| A | "exploring medical and wellness options" | Wellness-targeted follow-up question | PASS (differentiated) |
| B1–B4 | medical→Cardiology→India→Next three months | collect_detail×3 → offer_consultation; no re-asks; no invented facts | PASS |
| B5 | "What destination did I say I prefer?" | Generic compare-destinations answer — did NOT verbalize "India" | **PARTIAL** — facts stored, scripted recall doesn't answer |
| C1 | "wellness and fitness retreat" | Signature-programme overview (3 programmes) | PASS |
| C2 | "Stress management and better sleep." | collect_detail → destination question | PASS |
| C3 | "Flexible on destination." | compare-destinations fallback; destination still missing | **PARTIAL** |
| C4 | "Within six months." | **asked destination AGAIN** — "within six months" not extracted (pattern needs "next six months"/"within 6 months") | **FAIL — repeated question** |
| D×3 | HAYAT-100/AAfiya/FFounders | correct programme mapping each, no invented prices/dates | PASS |
| E | "I want to improve my health." | clarify either/or, no premature classification | PASS |
| F | dental→Germany→recall | funnel progressed; recall turn didn't verbalize facts | PARTIAL (same as B5) |
| G1 | "Hello." | greeting clarify | PASS |
| G2 | "Just browsing, no rush." | **escalate / EF-8** "trouble saving your details" | **FAIL — false escalation** |

## Root cause of G2 (from server logs — verified)
`SupabaseStore.record_consent` → `POST consent_records` →
**PGRST204: column `consent_type` missing** → exception → EF-8 fallback.
Same class of error for `conversations.state` (400), `coordinator_handoffs`
(404), `signature_programme_enquiries` (404), `consent_records` SELECT (400).
**The 8 migrations are NOT applied to the connected Supabase project.**
Store degrades gracefully (logs WARNING, treats consent unavailable) but
`record_consent` still raises → EF-8 escalation mid-conversation.

## Latency
2.4–3.5s per turn — real Supabase REST round-trips (~6+ queries/turn).
Acceptable for staging; note for production capacity planning.

## Highest-priority defects
1. **EF-8 false escalation on benign input** — caused by unapplied
   migrations; any turn hitting `record_consent` escalates. Fix = apply
   migrations to this Supabase project (staging authorization needed).
2. **Repeated destination question** — "Flexible on destination" and
   "Within six months" don't populate `destination_preference`/
   `preferred_timing` → planner re-asks (violates one-question/no-repeat).
3. **Scripted recall gap** — visitors asking "what did I say?" get generic
   answers, not their stored facts (MEDICAL_AI_REPLIES off → no LLM).

## Untested this session (per instructions)
Knowledge upload/delete, voice STT/TTS, Arabic journeys, consent
approve/refuse live, restart recovery (session tokens not persisted).

## Session 1.1 follow-up (commit pending)
- **Destination defect FIXED**: "Flexible on destination"/"No preference"/
  AR مرن → `destination_preference="Flexible"`; planner no longer re-asks.
- **Timing defect FIXED**: "Within six months", "In the next six months",
  "Sometime over the next six months", "Within 6 months" all extract as
  relative phrases (no date conversion).
- **Recall PARTIAL→implemented**: deterministic `_recall_reply` echoes the
  visitor's own permitted admin facts (EN+AR) for "what did I tell you…"
  prompts; no facts → falls through normally; contact/clinical never echoed.
- **Supabase mismatch**: INVESTIGATED ONLY — `consent_type` exists in
  migration 1 but live DB has legacy `consent_records`; see
  HAYAT_SUPABASE_SCHEMA_INVESTIGATION.md. Needs owner-authorized merge
  migration; `create table if not exists` alone will NOT fix it.
- Tests: 305/305 pass (10 new in tests/test_qa_session_11.py).
