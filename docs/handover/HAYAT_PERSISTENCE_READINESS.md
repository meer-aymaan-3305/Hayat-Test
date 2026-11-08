# HAYAT — Persistence Readiness

## What exists
- `SupabaseStore` (supabase_store.py): full store implementation against
  Postgres via supabase-py — sessions, conversations, messages,
  case_facts(+versions), consultations, handoffs, programme enquiries,
  idempotent chat responses.
- 8 migrations in `supabase/migrations/` (contracts, consultation
  conversion, case-facts atomic upsert RPC, coordinator handoffs,
  programme enquiries).
- `create_store()` selects SupabaseStore when `SUPABASE_URL` +
  `SUPABASE_SERVICE_ROLE_KEY` are non-placeholder, else MemoryStore.

## Answers
- **Connected?** Code path exists; `.env` has placeholders/values —
  NOT verified against a live project this session.
- **Durable history?** Designed yes (messages/case_facts tables); unverified.
- **Restart survival?** Sessions are DB rows with token_hash + expiry —
  designed to survive; `cp5_confirmed_at`/`confirmed_appendix_a` are
  in-memory only → CP-5 re-confirmation required after restart (fail-safe).
- **Multi-instance safe?** No in-process locks; relies on DB constraints
  and `hayat_upsert_case_facts` RPC. Needs staging verification.
- **Knowledge docs persist?** NO — `data/knowledge/` is local filesystem;
  lost on redeploy, not shared across instances. Risk R8.
- **Admin-be ID consistency?** Cannot verify — admin-be not in workspace.
  Hayat exposes conversation_id consistently across chat/messages/handoff.

## Outstanding migration requirements (from prior reviews)
1. Apply the 8 migrations to **staging** Supabase project.
2. Add CP-5 confirmation columns (`cp5_confirmed_at`,
   `confirmed_appendix_a`, `crm_payload_transmitted`) to conversations
   or a dedicated table if durable consent is required.
3. RLS policies review — service-role key bypasses RLS; ensure no
   anon/authenticated access to Hayat tables.

## Recommended staging test plan
1. `supabase db push` (or apply SQL) to staging project only.
2. Point `SUPABASE_URL`/`SUPABASE_SERVICE_ROLE_KEY` at staging; restart;
   run a full guest journey; verify rows in tables.
3. Restart the service mid-conversation; verify session + history resume.
4. Run two app instances against staging; verify no state corruption.
5. Only then consider production — never without approval.
