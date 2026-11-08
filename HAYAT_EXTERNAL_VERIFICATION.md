# HAYAT — External / Live API Verification

Date: 2026-11-08. All tests used synthetic, non-clinical phrases only.

## Groq STT — Whisper (`whisper-large-v3`)

- Auth: `GROQ_API_KEY` from `.env` accepted (no 401).
- Endpoint `/openai/v1/audio/transcriptions` reachable; invalid media
  correctly rejected (`400 invalid_media_file`).
- **Real speech round-trip NOT completed**: no speech audio was available
  to transcribe (TTS was blocked — see below), so EN/AR transcription
  accuracy is UNVERIFIED live. Offline path and request plumbing tested.

## Groq TTS — DEFECT FOUND AND FIXED

- `playai-tts` / `playai-tts-arabic` were **decommissioned by Groq on
  2025-12-31** (live API returned `model_decommissioned`). Config and
  `speech.py` updated to Orpheus models.
- `canopylabs/orpheus-v1-english` / `canopylabs/orpheus-arabic-saudi`
  now configured (`GROQ_TTS_MODEL_EN/AR`, voices `austin`/`abdullah`,
  valid voice names per Groq docs).
- **BLOCKER:** live synthesis returns
  `400 model_terms_required` — "The model requires terms acceptance.
  Please have the org admin accept the terms at console.groq.com".
  This is an account-level approval only the Groq org admin can perform.
  EN/AR synthesis and the full TTS→STT round-trip remain UNVERIFIED
  until terms are accepted.

## Other external systems

- Supabase: configured in `.env` but NOT exercised — no live DB test run.
- CRM webhook (`TRAWELLCARE_CRM_WEBHOOK_URL`): unset; mock/log-only mode.
- Firebase OTP / SMS: unconfigured; endpoints fail closed 503.
- BFF (trawellcare-bff): not present in this workspace; the
  `X-Service-Token` contract is implemented and unit-tested locally,
  but no end-to-end BFF→Hayat request was performed.
