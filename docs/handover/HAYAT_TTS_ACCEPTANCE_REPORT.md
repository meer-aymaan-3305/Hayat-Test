# HAYAT — TTS Acceptance Report

Date: 2026-11-08 · `launch-v1` @ `5432d03`+ · **LIVE VERIFIED — all PASS**

Orpheus terms confirmed accepted for the org owning `GROQ_API_KEY`.
Real audio generated, decoded (24kHz mono WAV), synthesized through the
API endpoint, and round-tripped through Whisper STT.

## Results (`tts_acceptance_results.json`, 7/7 PASS)

| Test | Verdict | Evidence |
|---|---|---|
| EN synthesize (stored msg, `austin`) | PASS | 200 `audio/wav`, 441,670 B, ~1.6s → `tts_endpoint_en.wav` |
| AR synthesize (stored msg, `abdullah`) | PASS | 200 `audio/wav`, 361,030 B, ~1.3s → `tts_endpoint_ar.wav` |
| EN TTS→STT round-trip | PASS | Whisper transcript: "Hello. Welcome to Hayat. How can I help you today?" — accurate, lang=English |
| AR TTS→STT round-trip | PASS | Whisper transcript: "مرحبا بك في حياة كيف يمكنني مساعدتك اليوم؟" — accurate, lang=Arabic |
| Other visitor's message | PASS | 404 — cannot synthesize |
| Arbitrary/missing message_id | PASS | 404 — arbitrary text impossible |
| No API key (TTS+STT) | PASS | 503 fail-closed both |

## Voice stack status — COMPLETE
- **STT**: Whisper `whisper-large-v3` live-verified EN+AR.
- **TTS**: Orpheus EN (`austin`) + AR (`abdullah`) live-verified,
  WAV output, sub-2s synthesis latency.
- Full loop proven: text → validated reply → speech → speech →
  transcript → same ChatService pipeline.
- Guardrails/ownership/fail-closed all verified (QA sessions 1–3).

## Remaining blockers (non-voice)
- Supabase staging migrations (schema mismatch → EF-8 on consent path).
- Live BFF verification (repo absent).
- Compliance approvals (Addendum 1.1, MEDICAL_AI_REPLIES).

No code changes; flags untouched; nothing pushed/deployed.
