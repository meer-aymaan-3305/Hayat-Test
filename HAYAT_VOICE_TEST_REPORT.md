# HAYAT — Voice Test Report

Date: 2026-11-08 · Live Groq API used where noted.

## STT — Whisper `whisper-large-v3` (LIVE VERIFIED)

| Test | Result |
|---|---|
| Auth | `GROQ_API_KEY` accepted |
| Endpoint | `/openai/v1/audio/transcriptions` reachable |
| V01 tone.wav (non-speech) | **200 in 316ms** — transcript "." , `detected_language: English`; conversation continued normally |
| V02 `text/html` upload | **415** `Unsupported audio format` — content-type gate works |
| Wrong session | 403 (unit-tested) |
| Oversize audio | bounded read at `MAX_UPLOAD_MB` (unit-tested) |
| Empty audio | 400 |

**Not verified:** real EN/AR speech transcription accuracy — no speech
sample was available (TTS blocked). Whisper accepts the formats sent;
accuracy for Arabic (`ar`) unmeasured.

## TTS — Orpheus (BLOCKED, external)

- `playai-tts` decommissioned by Groq 2025-12-31 → migrated to
  `canopylabs/orpheus-v1-english` / `canopylabs/orpheus-arabic-saudi`
  (voices `austin`/`abdullah`, WAV).
- Live call returns **400 `model_terms_required`** — org admin must
  accept terms at console.groq.com. Re-verified 2026-11-08: still blocked.
- Endpoint contract verified by unit tests: only stored assistant
  messages in the caller's own conversation can be synthesized;
  arbitrary text impossible; wrong message → 404; unconfigured → 503.
- V03 (real synthesis) could not run — **not claimed as working**.

## Pipeline integrity

Voice chat reuses `ChatService.respond()` — identical guardrails, fact
extraction, consent and handoff logic as typed chat (verified: same
code path, same response schema + `transcript`/`detected_language`).
No separate voice conversation engine exists, per requirement.

## Blocker owner
**Groq org admin** — accept Orpheus model terms, then re-run:
`uv run python scripts/e2e_campaign.py` (V01/V03 records).
