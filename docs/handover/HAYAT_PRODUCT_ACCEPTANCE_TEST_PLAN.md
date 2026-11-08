# HAYAT — Product Acceptance Test Plan

## Automated (all passing: 287/287)
- Unit: guardrails EF/AL, consent CP-5, coordinator authz, knowledge
  ingest/delete, voice ownership, AR extraction, planner intents.
- Safety eval: 292/308 offline (16 harness artifacts, manually verified).
- E2E campaign: 30 journeys EN/AR text + voice edges + knowledge + funnel.
- Cross-modal audit: EN/AR first-turn + J11 multi-turn parity.

## Manual staging acceptance (after migration+BFF)
1. Guest: greeting → medical journey → summary → consent → handoff →
   coordinator sees request in admin-be.
2. Same in Arabic end-to-end.
3. Visitor isolation: guest token cannot read another conversation;
   cannot hit `/v1/knowledge/*` or `/v1/coordinator/*`.
4. Consent refusal → verify NO CRM payload transmitted.
5. Consent approval → verify coordinator assignment + progress +
   appointment confirmation only by assigned coordinator.
6. Restart backend mid-conversation → session + history resume.
7. Two instances → concurrent sessions no cross-talk.
8. Voice: EN+AR STT→chat→(TTS when unblocked)→playback.
9. Knowledge: upload→grounded answer with sources→delete→no longer
   retrievable.
10. Prompt injection (EN+AR) → AL-5 incident, safe reply.

## Sign-off criteria
- All automated green; all manual staging checks pass; BFF assertions
  verified live; flags unchanged until approvals.
