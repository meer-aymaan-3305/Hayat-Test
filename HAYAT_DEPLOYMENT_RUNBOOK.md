# HAYAT — Deployment Runbook (staging first; NO production actions taken)

## Required env vars
`APP_ENV`, `GROQ_API_KEY`, `JWT_SYSTEM_SECRET` (must match BFF/admin-be),
`SUPABASE_URL`, `SUPABASE_SERVICE_ROLE_KEY`, `SUPABASE_ANON_KEY`(optional),
`GROQ_TTS_MODEL_EN/AR`, `GROQ_TTS_VOICE_EN/AR`, `GROQ_STT_MODEL`,
`MAX_UPLOAD_MB`, `KNOWLEDGE_DIR`, `CRM_WEBHOOK_URL` (unset),
`FIREBASE_*` (unset until approved), `SENTRY_DSN` (optional, unset).
Never commit `.env`. Never print secrets.

## Supabase schema reconciliation (BLOCKER — EF-8 on consent path)
Live project has a **legacy/partial schema**: `consent_records` lacks
`consent_type`, `conversations.state` missing, `coordinator_handoffs` and
`signature_programme_enquiries` tables absent (see
`HAYAT_SUPABASE_SCHEMA_INVESTIGATION.md`).
- `create table if not exists` will NOT fix existing `consent_records` —
  a reviewed `ALTER TABLE` merge migration is required.
- Order: snapshot → owner confirms staging (NOT prod) → ALTER consent_records
  → apply migrations 2–8 in timestamp order → verify record_consent,
  conversations.state, handoffs, enquiries → re-run QA G2 scenario.

## Migration order
`20261017190000_hayat_contracts` → `20261018163000_consultation_conversion`
→ `20261018190000_upgrade_existing_case_facts` → `20261027170000_hayat_orchestration`
→ `20261027210000_dynamic_consultation_persistence` → `20261027223000_case_facts_atomic_upsert`
→ `20261103210000_coordinator_handoffs` → `20261103223000_signature_programme_enquiries`.

## BFF requirements
BFF must: inject `X-Service-Token` (JWT `system:*`), propagate
`X-Session-ID`/`X-Session-Token`/`X-Visitor`, set `X-Reply-Language`,
assert coordinator identity server-side for `/v1/coordinator/*`, and
never expose Hayat directly. Live verification pending (repo absent).

## Health checks
`GET /health` → `{status:ok, integrations:{groq,supabase}}`.
Smoke: guest session → conversation → chat → messages → voice/chat →
voice/synthesize (stored msg only) → knowledge list.

## Voice
Whisper STT + Orpheus TTS both live-verified (terms accepted).
AR STT verified via TTS-generated sample; recommend one human AR sample.

## Rollback
Stateless API: redeploy previous image; Supabase changes are additive —
rollback = restore snapshot (migrations are non-destructive `if not exists`).
Knowledge: filesystem dir — back up `data/knowledge` before migration to
object storage.

## Staging verification checklist
- [ ] Migrations applied + consent path no longer EF-8
- [ ] Restart recovery + multi-instance session test
- [ ] One live Website→BFF→Hayat request verified end-to-end
- [ ] Knowledge PUT/DELETE lifecycle on staging
- [ ] Voice EN+AR round-trip on staging
- [ ] CRM/Firebase still disabled; flags unchanged
