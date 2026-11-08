# HAYAT — Final Acceptance Report

Date: 2026-11-08 · Branch `launch-v1` · HEAD includes `1acc59c` + audit fixes
Tests: **286/286 pass** (re-run at end of audit).

## Acceptance summary

| Area | Verdict |
|---|---|
| Text EN journeys (10 scenarios) | PASS — differentiated intents, guardrails hold |
| Text AR journeys | PASS first-turn parity; **partial** multi-turn (fact-extraction gap) |
| Voice STT | PASS live (Whisper, ~320ms, safe hallucination handling) |
| Voice TTS | **BLOCKED** — Groq `model_terms_required` (org admin action) |
| Knowledge upload/retrieval | PASS — indexed, attributed only when grounded |
| Consultation funnel | PASS to `sign_in_required`; customer submit needs OTP+Addendum |
| Consent refusal → no CRM | PASS (unit + E2E) |
| Consent approval → handoff | PASS (unit + E2E, awaiting_consent + handoff) |
| No false appointment | PASS — coordinator-only confirmation (HB-8) |
| BFF live verification | **NOT DONE** — BFF not in workspace; needs live request |

## Cross-modal parity
First-turn classification is now identical EN/AR across all 10 journeys
(post-fix). Residual gap: Arabic multi-turn preference extraction.

## Decisions

- **Staging: GO** — text EN/AR first-turn journeys, guardrails, knowledge,
  consent mechanics, voice STT all verified. Voice TTS degrades to 503;
  frontend should handle gracefully.
- **Production: NO-GO** — blockers: (1) Groq Orpheus terms acceptance,
  (2) live BFF→Hayat verification, (3) Arabic multi-turn extraction gap,
  (4) compliance approvals (Addendum 1.1, MEDICAL_AI_REPLIES, CRM webhook,
  Supabase staging migration), (5) push `launch-v1` to origin.

## Required human actions (unchanged + new)
1. Groq org admin: accept Orpheus TTS terms → re-run voice round-trip.
2. BFF engineer: one live staging request; confirm coordinator headers
   are server-asserted; confirm visitors get 401/403 on knowledge routes.
3. Compliance: Addendum 1.1 sign-off before enabling OTP/contact/attachments.
4. Extend Arabic fact extraction (engineering task, post-staging).
5. Apply Supabase migrations to staging; review CRM webhook + DP-2.
