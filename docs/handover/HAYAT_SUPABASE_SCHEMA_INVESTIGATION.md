# HAYAT — Supabase Schema Mismatch Investigation (READ-ONLY)

Date: 2026-11-08 · QA session 1.1 · No writes applied.

## Finding
`consent_type` **is** defined in `supabase/migrations/20261017190000_hayat_contracts.sql`
(`consent_records.consent_type text not null`, line 38). The live error
`PGRST204: column 'consent_type' of 'consent_records'` therefore means the
connected project's `consent_records` table was created by a **different /
older schema** — likely predating Hayat's migrations or belonging to a
shared trawellcare schema (admin-be also uses `consent_records`-like tables).

## Live evidence (from uvicorn logs)
- `POST /rest/v1/consent_records` → 400 PGRST204 (missing `consent_type`)
- `GET /rest/v1/conversations?select=state` → 400 (no `state` column)
- `GET /rest/v1/coordinator_handoffs` → 404 (table absent)
- `GET /rest/v1/signature_programme_enquiries` → 404 (table absent)
- Core tables (guest_sessions, conversations, messages, case_facts,
  leads, consultation_requests) exist and accept writes (201s).

## Conclusion
The connected Supabase project has a **partial/legacy schema** — core
Hayat tables exist but later migrations (orchestration `state` column,
coordinator_handoffs, signature_programme_enquiries, consent_records
columns) are absent. This is consistent with migrations never having been
applied to this project.

## Which migration is required
All 8 in timestamp order (see HAYAT_SUPABASE_MIGRATION_RUNBOOK.md):
1. `20261017190000_hayat_contracts.sql` — defines `consent_records`
   WITH `consent_type`. ⚠️ If a legacy `consent_records` already exists,
   `create table if not exists` will SKIP it → `consent_type` still
   missing. **Requires `alter table … add column if not exists` or a
   reviewed merge migration — cannot be solved by re-running file 1.**
2.–8. Remaining files add orchestration/handoff/programme tables.

## Project identity
URL `ykhggqiyjzqisgolataa.supabase.co` — cannot confirm staging vs dev vs
production from here; owner must confirm before any migration.

## Execution checklist (requires authorization)
- [ ] Owner confirms project is staging/dev (NOT production).
- [ ] Backup/snapshot consent_records + conversations.
- [ ] Write a reviewed `alter table` migration for legacy
      `consent_records` (add `consent_type` etc.) OR rename legacy table.
- [ ] Apply migrations 2–8 in order.
- [ ] Verify: `record_consent` insert succeeds; `conversations.state`
      readable; handoffs/programme tables exist.
- [ ] Re-run QA G2 scenario — expect normal reply, no EF-8.
