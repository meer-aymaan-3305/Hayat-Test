# HAYAT — Master Requirements Matrix

Date: 2026-11-08 · `launch-v1` · Tests: 295/295
Legend: ✅ done+tested · 🟡 partial · ❌ missing · 🔒 needs approval/access

| # | Requirement | Implementation | Status | Approval? |
|---|---|---|---|---|
| 1 | Conversation engine + one-question follow-ups | ChatService + QuestionPlanner + enforce_single_question | ✅ | — |
| 2 | EN/AR support | detect_language, AR scripts, AR extraction incl. digits/budget/insurance/value-priority/dialect intents | ✅ (MSA+dialects partial; code-switching partial) | — |
| 3 | Medical tourism intake | Appendix A facts, funnel states, summary | ✅ | — |
| 4 | Wellness intake | wellness category + goal extraction | ✅ | — |
| 5 | Signature programmes | ProgrammeConversationService, 3 programmes, registration, summary, FAQ | ✅ | — |
| 6 | HAYAT-100 / AAfiya / FFounders | dedicated branches EN+AR | ✅ | — |
| 7 | Knowledge mgmt + RAG | upload/list/**delete**(new)/extract/chunk/index/retrieve/sources | ✅ FS; 🟡 durable storage | storage decision |
| 8 | Persistence + session recovery | SupabaseStore + 8 migrations (unapplied); MemoryStore | 🟡 code done, staging pending | migration auth |
| 9 | Guest users | guest sessions, token authz, sign-in gate | ✅ | — |
| 10 | Authenticated users | owner_id links, customer path | 🟡 needs Firebase OTP live | 🔒 OTP approval |
| 11 | Sign-in/OTP | endpoints exist → 503 unconfigured | 🟡 | 🔒 Firebase creds |
| 12 | Consent + transmission | CP-5 explicit confirm, idempotent, fact-change invalidation | ✅ | Addendum for contact capture |
| 13 | Coordinator handoff | handoffs, assign/progress/confirm, asserted identity | ✅ code; ⬜ BFF verify | live BFF test |
| 14 | Voice input | Whisper STT via /v1/voice/chat | ✅ live-verified | — |
| 15 | Voice output | Orpheus TTS /v1/voice/synthesize | 🔒 `model_terms_required` | Groq org admin |
| 16 | BFF/frontend integration | contract documented; Hayat-side enforced | 🟡 BFF unverified | BFF repo access |
| 17 | Admin/coordinator workflows | coordinator endpoints + asserted headers | ✅ code | BFF assertion verify |
| 18 | Monitoring/reliability | audit log, AL-x incidents, EF-x fallbacks | ✅ basic; ❌ Sentry | infra decision |
| 19 | Deployment | uvicorn documented; no CI/CD pipeline | ❌ | infra |
| 20 | Security/privacy/compliance | guardrails, redaction, fail-closed flags | ✅ | Addendum 1.1 sign-off |

**Score: ~17/20 substantially complete; 3 require external access/approval.**
