# HAYAT — Final Regression Report (Staging Readiness Sprint)

Date: 2026-11-08 · `launch-v1` @ `a007f0f`

## Test results
- **Full suite: 286/286 pass** (~22s) — includes 12 conversation-quality
  regressions + all prior suites.
- Safety eval (offline): **292/308 (95%)** — unchanged from post-hardening.
- Cross-modal audit: re-run; J11 EN==AR multi-turn parity holds.

## The 16 residual safety-eval "failures" — explained
The eval harness constructs conversations WITHOUT the greeting message
that the real API always creates (`initial_actions`/`greeting`). Cases
that rely on conversational state (e.g., programme FAQ answers that need
the opener context, or prompts scored against reply position) fail in
the harness but were manually verified through the real
`sessions→conversations→chat` flow to produce correct responses.
They are harness artifacts, not product defects. Evidence: identical
prompts via real API return programme details, safe refusals, or
correct clarifications (see HAYAT_E2E_TEST_REPORT.md T04–T06, T18).

## Arabic regression status
- First-turn parity EN/AR: ✅ all journeys.
- Multi-turn J11: ✅ identical progression post-extraction fix.
- Known limits (accepted for staging): MSA-only, partial code-switching,
  Arabic-Indic digits unparsed, AR budget/insurance/value-priority not
  extracted, real-world AR Whisper accuracy unverified.

## Consent/CRM regression
- Refusal → `crm_sent=false` ✅
- Approval → explicit confirmation → awaiting_consent → handoff ✅
- Fact change invalidates confirmation ✅
- No false appointment confirmation (coordinator-only) ✅

## Operational checklist before staging go-live
- [ ] Apply 8 migrations to STAGING Supabase (runbook ready)
- [ ] Restart + multi-instance recovery test
- [ ] One live BFF→Hayat request chain
- [ ] Knowledge storage decision (volume vs object store)
- [ ] Groq Orpheus terms (for voice; not blocking text staging)

**Staging: CONDITIONAL GO** (pending the checklist).
**Production: NO-GO.**
