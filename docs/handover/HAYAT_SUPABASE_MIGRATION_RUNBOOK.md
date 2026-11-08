# HAYAT — Supabase Migration Runbook (STAGING ONLY)

## Prerequisites
- Staging Supabase project (never production).
- `SUPABASE_URL` + `SUPABASE_SERVICE_ROLE_KEY` for staging in env.
- Explicit authorization before applying.

## Migration order (apply in timestamp order)
1. `20261017190000_hayat_contracts.sql` — core tables: guest_sessions,
   conversations, messages, case_facts, case_fact_versions,
   consultation_requests, chat idempotency. Enables `vector` ext.
2. `20261018163000_consultation_conversion.sql` — conversion fields.
3. `20261018190000_upgrade_existing_case_facts.sql` — upgrades existing
   case_facts rows (no-op on fresh staging).
4. `20261027170000_hayat_orchestration.sql` — orchestration tables.
5. `20261027210000_dynamic_consultation_persistence.sql`
6. `20261027223000_case_facts_atomic_upsert.sql` — `hayat_upsert_case_facts`
   RPC used by SupabaseStore for atomic fact writes.
7. `20261103210000_coordinator_handoffs.sql`
8. `20261103223000_signature_programme_enquiries.sql`

All additive (`if not exists`); rollback = drop the new tables/functions;
no data-loss risk on fresh staging.

## Procedure
```bash
# 1. Apply to STAGING project only (Supabase CLI or dashboard SQL editor)
supabase link --project-ref <staging-ref>
supabase db push   # or apply files manually in order

# 2. Point Hayat at staging
SUPABASE_URL=https://<staging-ref>.supabase.co
SUPABASE_SERVICE_ROLE_KEY=<staging-service-role-key>
uv run uvicorn hayat_backend.main:app --host 127.0.0.1 --port 2005

# 3. Verify
# - guest session → rows in guest_sessions
# - chat turns → rows in messages + case_facts
# - restart service → session/conversation resume (token_hash auth)
# - second instance on same DB → no state corruption
```

## Recovery test plan
- Kill -9 mid-conversation → restart → verify history + facts intact.
- Two uvicorn workers → concurrent chats on different sessions → verify
  no cross-talk; concurrent fact updates on same conversation → verify
  `hayat_upsert_case_facts` RPC atomicity.
- Expired session token → 401/403; tampered token_hash → rejected.

## Known process-local state (won't survive restart — by design or gap)
- CP-5 confirmation fields → re-confirmation required (fail-safe).
- Knowledge index → rebuilt from disk at startup (see storage plan).
- Shadow-AI tasks, rate-limit counters → ephemeral.

## Do NOT
- Apply to production without separate authorization.
- Enable RLS bypass assumptions — service role bypasses RLS; verify no
  anon/authenticated grants on Hayat tables.
