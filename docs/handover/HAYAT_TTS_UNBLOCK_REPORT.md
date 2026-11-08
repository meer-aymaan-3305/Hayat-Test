# HAYAT — TTS Unblock Report

Date: 2026-11-08 · `launch-v1` @ `ad407bb` · **BLOCKED — external admin action required**

## Step 1 — Diagnosis (verified)
- Config: `canopylabs/orpheus-v1-english` (voice `austin`),
  `canopylabs/orpheus-arabic-saudi` (voice `abdullah`), WAV output —
  correct current Groq Orpheus IDs.
- API key present in `.env` (not exposed); STT/other Groq calls work.
- First raw `urllib` attempt returned Cloudflare `403 error code: 1010`
  (bot-block on default UA) — retried via `httpx` → reached the real API.

## Step 2 — Live API result (just now, sanitized)
Both models return **HTTP 400**:
```
{"error":{"message":"The model `canopylabs/orpheus-v1-english` requires
terms acceptance. Please have the org admin accept the terms at
https://console.groq.com/playground?model=canopylabs%2Forpheus-v1-english",
"type":"invalid_request_error","code":"model_terms_required"...}}
```
Same for `orpheus-arabic-saudi`. → **Unaccepted organisation terms**
confirmed; model IDs, key, and org access are all correct. Not a code
defect — nothing to fix in Hayat.

## Step 3/4 — Endpoint & Arabic tests
- `POST /v1/voice/synthesize` correctly fails closed (503) while blocked —
  verified in QA session 3 (T01 BLOCKED, T02 404 arbitrary-text, T03 503
  no-key). No code change needed.
- Arabic TTS/STT round-trip **cannot run** until terms are accepted.

## Exact action required (org admin)
1. Sign in to https://console.groq.com as org admin.
2. Open each playground link and accept terms:
   - `.../playground?model=canopylabs%2Forpheus-v1-english`
   - `.../playground?model=canopylabs%2Forpheus-arabic-saudi`
3. Notify — re-run `scripts/qa_session3_voice.py` T01 + AR round-trip.

## Re-check after reported acceptance (2026-11-08, commit ad407bb+)
Retried both models via httpx: **still HTTP 400 `model_terms_required`**.
API key verified valid (`GET /models` → 200). Conclusion: terms were
either accepted under a **different Groq organisation** than the one this
API key belongs to, acceptance hasn't propagated, or the wrong key is in
`.env`. Required: confirm the org that owns `GROQ_API_KEY` accepted terms
at the console links above — or supply the correct org's key.

## Acceptance tests once unblocked
- EN: synthesize stored assistant message → non-empty WAV, correct voice,
  playable; feed to `/v1/voice/chat` → Whisper transcript → chat reply.
- AR: synthesize Arabic assistant message → playable Arabic speech →
  `/v1/voice/chat` → verify transcription accuracy.

No credentials exposed; no flags changed; no deploy/migration/push.

## Org identification attempt (2026-11-08)
Probed Groq account/org metadata endpoints with the configured key:
`/organization`, `/v1/organization`, `/user`, `/api-keys`, `/billing` →
all 404 (not exposed by the public API). `GET /models` → 200 and lists
both Orpheus models `active: true` — the models are visible to this
key's org but carry **no terms-acceptance or org-identity fields**.
**Limitation: the organisation behind GROQ_API_KEY cannot be identified
via the API.** Whether it matches the org where terms were accepted
cannot be confirmed programmatically — admin must verify in the console
(API Keys page shows the owning org).
