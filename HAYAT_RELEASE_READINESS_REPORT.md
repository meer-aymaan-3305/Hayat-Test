# HAYAT — Release Readiness Report

Date: 2026-11-08 · Branch `launch-v1` · HEAD `e989226`+audit fixes (unpushed)

## Verdict: **CONDITIONAL GO** for frontend integration on staging;
**NO-GO for production** until the external blockers below clear.

## 1. Git verification
- Branch `launch-v1` confirmed; `e989226` present.
- 8 commits ahead of `origin/launch-v1` (security fixes, voice/knowledge
  features, reports). All untracked reports preserved; nothing pushed.

## 2. Test results
- **274/274 pytest pass** (~12s, offline/in-memory).
- Safety eval (offline model): **292/308 (95%)**; emergency & crisis 100%.
- New coverage: voice fail-closed, wrong-session 403, non-audio 415,
  oversize bounds, knowledge upload validation, TTS message binding,
  attachment gate.

## 3. Live API verification — see HAYAT_EXTERNAL_VERIFICATION.md
- Whisper STT: auth + endpoint verified; real transcription UNVERIFIED.
- **Defect fixed:** `playai-tts` decommissioned → migrated to Orpheus.
- **Blocker:** Orpheus requires Groq org-admin terms acceptance
  (`model_terms_required`). TTS round-trip UNVERIFIED.
- Supabase, CRM webhook, Firebase, BFF: not exercised live.

## 4. Security & compliance gates — all held
- `POLICY_ADDENDUM_1_1_APPROVED=false`, `MEDICAL_AI_REPLIES=false`,
  `VISITOR_ATTACHMENTS_ENABLED=false` — unchanged.
- Coordinator auth: asserted `X-Coordinator-ID`/`X-Coordinator-Role`
  validated against enum; identity binding on confirm-appointment.
  NOTE: verified locally only — the actual BFF assertion path is
  untested end-to-end.
- BFF service token: fail-closed, `system:` sub + exp enforced —
  locally tested, not verified through a live BFF.

## 5. Known limitations
- TTS blocked on Groq terms acceptance (external).
- No live STT accuracy measurement; no audio duration limit (byte cap only).
- `cp5_confirmed_at` not persisted to Supabase (re-confirm after restart).
- Visitor attachments, when someday enabled, have no clinical-content
  inspection — requires compliance approval first.
- CRM webhook untested against a real endpoint.

## 6. Startup
```powershell
cd D:\trawellcare\hayat-backend
uv sync
uv run uvicorn hayat_backend.main:app --host 127.0.0.1 --port 2005
```
Env reference: `.env.example` (JWT_SYSTEM_SECRET, GROQ_API_KEY,
GROQ_STT_*/GROQ_TTS_* (Orpheus), SUPABASE_*, KNOWLEDGE_DIR,
MAX_UPLOAD_MB, APP_ENV, feature flags — all approval flags false).

## 7. Outstanding human approvals
1. **Groq org admin**: accept Orpheus TTS terms in console.groq.com.
2. BFF: confirm it asserts coordinator identity headers and issues
   `system:` service tokens; run one live BFF→Hayat request.
3. Compliance: Addendum 1.1 (contact capture/OTP/attachments),
   `MEDICAL_AI_REPLIES`, safety-eval sign-off for AI enablement.
4. CRM webhook URL + DP-2 disclosure review.
5. Supabase migrations to staging (never production without approval).
6. Push `launch-v1` to origin.
