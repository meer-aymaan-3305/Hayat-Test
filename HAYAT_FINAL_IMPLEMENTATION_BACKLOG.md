# HAYAT — Final Implementation Backlog

Ordered by dependency. ✅ = done this session.

## A. Implementable now (no external deps)
1. ✅ **Knowledge DELETE** — shipped (`717282e`).
2. ✅ **Arabic-Indic digit parsing** — `_normalize_digits` maps ٠-٩/۰-۹ → ASCII before extraction.
3. ✅ **Arabic budget/insurance/value-priority** — patterns added to `_extract_facts` (ميزانية، تأمين، أرخص/فاخر/أسرع…).
4. 🟡 **Dialect coverage** — intent verbs added (عايز/أبغى/بدّي/محتاج/ودي); deeper dialect review still recommended.

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
