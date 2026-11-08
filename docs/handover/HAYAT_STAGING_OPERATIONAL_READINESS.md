# HAYAT — Staging Operational Readiness

Date: 2026-11-08 · `launch-v1` @ `a007f0f` · Tests: 286/286 (re-run below)

Classification: ✅ verified in code · 🧪 verified by automated test ·
🌐 verified against live staging · ⬜ not yet verified · 🔒 requires approval

## Workstream 1 — Supabase staging readiness
- ✅ `SupabaseStore` implements sessions/messages/case_facts(+versions)/
  consultations/handoffs/programme-enquiries/idempotent chat cache.
- ✅ 8 migrations, chronological, additive (`create table if not exists`),
  ordered by timestamp prefix — safe ordering, no destructive changes.
- 🧪 Schema↔store consistency covered by unit tests with MemoryStore;
  SupabaseStore itself has no live-DB tests (requires staging project).
- ⬜ Live connectivity, RLS review, restart recovery, multi-instance —
  all pending staging migration (see runbook).
- Process-local fields: CP-5 confirmation timestamp/payload, knowledge
  index, in-flight shadow-AI tasks, rate-limit counters.

## Workstream 2 — Knowledge storage
- ✅ Local FS store: SHA-256 dedup, versioning, atomic index, chunk
  persistence, startup reload — all implemented + tested.
- ✅ Segregation: company knowledge vs visitor attachments separate;
  attachments disabled by flag.
- ⬜ Durable shared storage (R2/Supabase) — plan in
  HAYAT_KNOWLEDGE_STORAGE_MIGRATION_PLAN.md; not implemented (needs approval).

## Workstream 3 — BFF contract
- ✅ Hayat-side authN/Z fully specified — see
  HAYAT_BFF_INTEGRATION_CONTRACT.md.
- ⬜ BFF-side behavior — repo unavailable; live staging request required.

## Workstream 4 — Voice readiness
- ✅ Whisper STT: live-verified (~320ms, graceful non-speech handling).
- 🔒 Orpheus TTS: `model_terms_required` — org admin must accept terms at
  console.groq.com, then run acceptance tests (documented in contract).
- ✅ Text staging validation does NOT depend on TTS.

## Workstream 5 — Safety & Arabic regression
- 🧪 Safety eval: 292/308 (95%) post-hardening; 16 residual fails are
  harness artifacts (no greeting) — manually verified.
- 🧪 Cross-modal J11 EN==AR multi-turn parity after extraction fix.
- Known limits documented: MSA-only, partial code-switching, Arabic-Indic
  digits, missing AR budget/insurance/value-priority, unverified AR Whisper.

## Verdict
Backend is staging-ready **pending**: staging Supabase migration +
recovery test, live BFF verification, knowledge storage decision.
Production remains NO-GO.
