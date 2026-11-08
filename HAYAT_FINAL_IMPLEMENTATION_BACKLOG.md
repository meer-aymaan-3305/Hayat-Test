# HAYAT — Final Implementation Backlog

Ordered by dependency. ✅ = done this session.

## A. Implementable now (no external deps)
1. ✅ **Knowledge DELETE** — `DELETE /v1/knowledge/documents/{id}` +
   `KnowledgeStore.remove()` + retriever resync + test (287 tests pass).
2. **Arabic-Indic digit parsing** (٣٤٥ → 345) in `_extract_facts` — small,
   safe; improves AR intake.
3. **Arabic budget/insurance/value-priority patterns** — extend existing
   Appendix A extraction; needs native-speaker review of terms.
4. **Dialect coverage** — Gulf/Levantine/Egyptian variants for key
   intents; requires dialect review before merge.

## B. Requires infrastructure/access
5. **Staging Supabase migration** — runbook ready; needs staging project
   credentials + authorization. Then restart/multi-instance recovery test.
6. **Knowledge durable storage** — implement `R2KnowledgeStore`/
   `SupabaseKnowledgeStore` behind `KNOWLEDGE_BACKEND` env (interface
   already isolated); needs bucket/project + approval.
7. **Live BFF verification** — one staging request chain; needs BFF repo
   or staging URL.
8. **Sentry/error tracking** — DSN + dependency decision.

## C. Requires external approval
9. **Groq Orpheus terms** — org admin accepts → run TTS acceptance tests
   (EN `austin`, AR `abdullah`, WAV, latency, failure modes).
10. **Firebase OTP** — credentials + Addendum 1.1 → activate customer path.
11. **CRM webhook** — staging URL + DP-2 review → live transmission test.
12. **Addendum 1.1 / MEDICAL_AI_REPLIES** — compliance sign-off → enable.
13. **Visitor attachments** — only after 11; clinical processing stays off.

## D. BFF/frontend work (other repos)
14. BFF: assert `X-Coordinator-ID`/`Role` server-side; issue `system:`
    service tokens; proxy session creation; map website routes.
15. Frontend: voice UI (record/playback), knowledge admin UI, handoff
    status polling — contracts in HAYAT_FRONTEND_INTEGRATION.md.
