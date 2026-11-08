# HAYAT — Architecture Reconciliation

Date: 2026-11-08 · Branch `launch-v1` · HEAD `33406ff` · Tests: **286/286**

## 1. AI safety & emergency handling — RECONCILED (improved)
Original eval: 256/308 (83%). Latest offline eval: **292/308 (95%)**.
Emergency 36%→100%, crisis 30%→100%, contact_capture 55%→100%.
Remaining 16 fails are eval-harness artifacts (no greeting message).
See HAYAT_SAFETY_REGRESSION_COMPARISON.md.

## 2. Supabase persistence — IMPLEMENTED, UNVERIFIED LIVE
`SupabaseStore` is wired via `create_store()` when `SUPABASE_URL` +
`SUPABASE_SERVICE_ROLE_KEY` are set; otherwise `MemoryStore`. It persists
guest_sessions (token-hash auth), conversations, messages, case_facts +
case_fact_versions, consultation_requests, coordinator_handoffs,
signature_programme_enquiries, and an idempotent chat cache.
8 migrations exist in `supabase/migrations/` — **none applied anywhere**.
NOT verified: live connectivity, RLS, restart recovery, multi-instance
safety (store is row-per-request; no in-process locks — relies on DB
constraints/RPC `hayat_upsert_case_facts` for atomicity). See
HAYAT_PERSISTENCE_READINESS.md.

## 3. BFF/platform integration — CONTRACT READY, LIVE UNVERIFIED
BFF repo is not in this workspace. Hayat enforces `X-Service-Token`
(`system:` sub + exp, fail-closed), session tokens, visitor headers, and
coordinator identity headers. Whether the BFF actually asserts these is
**unverified** — see HAYAT_PLATFORM_INTEGRATION_GAPS.md.

## 4. External integrations status
| Service | Status |
|---|---|
| Groq Whisper STT | LIVE-VERIFIED (auth, endpoint, 316ms call) |
| Groq chat `allam-2-7b` | configured, NOT live-tested this session |
| Groq Orpheus TTS | BLOCKED — `model_terms_required` (org admin) |
| Firebase OTP | unconfigured → endpoints 503 (by design) |
| CRM webhook | unset → log-only mock mode |
| Supabase | configured in .env; not exercised live |
| Sentry | not integrated |
| Cloudflare R2 | not integrated (knowledge stored on local FS) |

## Updated risk register
| # | Risk | Sev | Evidence | Owner | Action |
|---|---|---|---|---|---|
| R1 | TTS blocked | High | `model_terms_required` live | Groq admin | Accept Orpheus terms, retest |
| R2 | BFF assertions unverified | High | no BFF in workspace | BFF eng | Live staging request |
| R3 | Supabase unverified | High | migrations unapplied | DB owner | Staging migration + recovery test |
| R4 | Arabic dialects/digits gaps | Med | report §remaining | Eng | Post-staging backlog |
| R5 | cp5 state not in Supabase schema | Med | code review | Eng | Migration before prod |
| R6 | Coordinator identity is asserted | Med | design | Compliance | Accept or add credential |
| R7 | CRM webhook untested | Med | unset | Integration | Staging test w/ synthetic data |
| R8 | Knowledge FS not shared/persistent | Med | `data/knowledge` local | DevOps | Move to R2/Supabase before multi-instance |
