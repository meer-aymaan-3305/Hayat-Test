# Hayat — Staging Migration & Integration Runbook

Target project: `ykhggqiyjzqisgolataa` (the Supabase project in `SUPABASE_URL`).
Run in the **Supabase Dashboard → SQL Editor**, one file at a time, in the
order below. Everything is additive (`if not exists` / guarded alters) and the
reconcile script is transactional.

## Step 1 — Reconcile existing tables (run FIRST, once)

`supabase/reconcile_live_schema.sql`

Adds the columns the live tables are missing (`consent_records.consent_type`,
`conversations.state`, `case_fact_versions`, etc.). It refuses to run if a
table it must alter has rows — if it errors, stop and review before continuing.

## Step 2 — Migrations, in timestamp order

1. `supabase/migrations/20261017190000_hayat_contracts.sql`
2. `supabase/migrations/20261018163000_consultation_conversion.sql`
3. `supabase/migrations/20261018190000_upgrade_existing_case_facts.sql`
4. `supabase/migrations/20261027170000_hayat_orchestration.sql`
5. `supabase/migrations/20261027210000_dynamic_consultation_persistence.sql`
6. `supabase/migrations/20261027223000_case_facts_atomic_upsert.sql`
7. `supabase/migrations/20261103210000_coordinator_handoffs.sql`
8. `supabase/migrations/20261103223000_signature_programme_enquiries.sql`
9. `supabase/migrations/20261110000000_visitor_documents.sql`
10. `supabase/migrations/20261111000000_post_migration_schema_fixes.sql`

## Step 3 — Verify

Run in the SQL editor:

```sql
select table_name from information_schema.tables
where table_schema='public' and table_name in
  ('guest_sessions','conversations','messages','consent_records','case_facts',
   'case_fact_versions','audit_events','leads','phone_verifications',
   'consultation_requests','coordinator_handoffs',
   'signature_programme_enquiries','visitor_documents')
order by 1;
-- expect 13 rows

select column_name from information_schema.columns
where table_schema='public' and table_name='consent_records'
  and column_name in ('consent_type','granted','policy_version');
-- expect 3 rows
```

Then smoke-test the API: `GET /health` → all integrations `ok`.

## Backend env for the staging deployment

| Variable | Value |
|---|---|
| `APP_ENV` | `staging` |
| `SUPABASE_URL` / `SUPABASE_SERVICE_ROLE_KEY` | project credentials (server-side only) |
| `JWT_SYSTEM_SECRET` | strong random secret — BFF signs `system:*` tokens with it |
| `GROQ_API_KEY` / `GROQ_MODEL` | `openai/gpt-oss-120b` (verified on this account) |
| `GROQ_MAX_TOKENS` | `600` |
| `MEDICAL_AI_REPLIES` | `true` only after AI safety sign-off; `false` = scripted replies |
| `VISITOR_ATTACHMENTS_ENABLED` | `false` in production until upload approvals; `true` on staging for integration testing |
| `FIREBASE_API_KEY` / `FIREBASE_PROJECT_ID` / `FIREBASE_SERVICE_ACCOUNT_JSON` | required for phone-OTP consultation submission |

## BFF / frontend contract (unchanged)

- Every `/v1/*` call needs `X-Service-Token` (HS256 JWT, `system:*` subject,
  signed with `JWT_SYSTEM_SECRET`) **plus** visitor headers
  `X-Session-ID` + `X-Session-Token` (+ optional `X-Visitor`,
  `X-Contact-Conent`, `X-Reply-Language`).
- Guest session: `POST /v1/sessions/guest {"locale":"en"|"ar"}` → returns
  `session_id` + `session_token`.
- Chat: `POST /v1/chat {"conversation_id","message","client_message_id"}`.
- Voice: `POST /v1/voice/chat` (multipart `file` + `conversation_id`) and
  `POST /v1/voice/transcribe` for dictation.
- Medical documents: `POST /v1/conversations/{id}/documents` (multipart
  `file` + `consent=true`) — **not** `/attachments`, which is opaque storage.
- OTP: `POST /v1/consultations/otp/start` then `/otp/verify`, then
  `POST /v1/consultations` — requires Firebase configured.
- Full field-level contract: `docs/handover/HAYAT_FRONTEND_INTEGRATION.md` and
  `docs/handover/HAYAT_API_REFERENCE.md`.

## Still open before real production

- Privacy/compliance sign-off on consent wording + retention.
- Business approval for visitor medical uploads (`VISITOR_ATTACHMENTS_ENABLED`).
- AV/malware scanning + encrypted storage for uploads.
- `ara` Tesseract data for Arabic scanned documents.
- Firebase phone verification for consultation submission.
- Status 2026-11-09: the dev project (`ykhggqiyjzqisgolataa`) already has steps 1 and 2 applied (checked read-only). The production project (`vqptxtblvnufnhsvwywt`) has not been checked. Do not run them there again. A new, empty project skips step 1 and runs only the migration files; they are safe to run twice.
