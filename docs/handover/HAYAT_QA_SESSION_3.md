# HAYAT — QA Session 3: Voice Input & Output

Date: 2026-11-08 · `launch-v1` @ `35123ff` · **TESTING ONLY — no app code changed**
Driver: `scripts/qa_session3_voice.py` · Data: `voice_qa_results.json` (13 records)
Env: `TestClient`, `APP_ENV=test`, isolated tmp knowledge dir. Groq key loaded
via `load_settings()` (real Whisper calls made). Audio: SAPI-synthesized
en-US WAV (`qa_en.wav`, `qa_en2.wav`) — synthetic, non-clinical.

## Input (STT) results

| ID | Scenario | Verdict | Evidence |
|---|---|---|---|
| V01 | Valid EN speech | **PASS** | Real Whisper call: `"Hello, I would like to know about wellness programs."` → detected_language=English → normal chat reply (wellness follow-up). Same ChatService pipeline. |
| V02 | Second EN utterance, same conv | **PASS** | `"I need help with medical travel for cardiology."` → transcript → chat continues in same conversation. |
| V03 | Empty audio | PASS | 400 `"Empty audio file."` |
| V04 | Corrupt audio | PASS | 503 `"Speech recognition failed (400)."` — safe, no crash |
| V05 | Unsupported format (PDF) | PASS | 415 `"Unsupported audio format."` |
| V06 | Oversized (>10MB) | PASS | 413 `"Audio file too large."` |
| V07 | Audio → another visitor's conv | PASS | 403 `"Conversation access denied."` |
| V08 | Clinical content via pipeline | PASS | EF-9 emergency escalation (`possible_emergency`) — voice feeds identical guardrails |
| V09 | Prompt injection via pipeline | PASS | safe handling (AL incident logged) |

## Output (TTS) results

| ID | Scenario | Verdict | Evidence |
|---|---|---|---|
| T01 | TTS for stored assistant msg | **BLOCKED** | 503 `"Speech synthesis failed (400)."` = Groq `model_terms_required` — Orpheus terms not accepted |
| T02 | TTS arbitrary/missing message_id | PASS | 404 `"Assistant message not found."` — arbitrary text cannot be synthesized |
| T03 | TTS with no API key | PASS | 503 `"Text-to-speech is not configured."` — fail-closed |
| T04 | STT with no API key | PASS | 503 `"Speech-to-text is not configured."` — fail-closed |

## Language coverage
- **English STT: live-verified** with real synthesized speech (accurate
  transcription, ~latency included in response time).
- **Arabic STT: NOT verified** — no Arabic speech sample available
  (no ar-SA SAPI voice; Orpheus TTS blocked so can't generate one).
  Whisper `whisper-large-v3` nominally supports Arabic; accuracy
  unproven. Do not claim AR voice support until a real AR sample tests.

## Remaining dependencies
1. **TTS**: Groq org admin must accept Orpheus model terms at
   console.groq.com → then re-run T01 (expect WAV audio, voices
   `austin`/EN, `abdullah`/AR) + generate AR speech for STT round-trip.
2. **AR STT**: needs an Arabic speech sample (human recording or
   post-TTS-unblock synthesis).
3. BFF voice-route proxying — unverified (repo absent).

## Notes
- Voice chat requires session token + conversation ownership (403 cross-
  visitor verified); audio bounded-read enforced (413); content-type
  allowlist (415); empty rejected (400).
- No code changes made; suite re-run below.
