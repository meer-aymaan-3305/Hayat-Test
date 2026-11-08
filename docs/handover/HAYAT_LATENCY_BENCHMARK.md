# HAYAT — Latency & Performance Benchmark

Date: 2026-11-08 · Local in-process ASGI (TestClient), MemoryStore,
scripted reply path, no external LLM/STT/TTS calls except V01.

## Scripted text turns (n=10 journeys × 3 turns)

| Turn | Median | Min | Max | P95 |
|---|---|---|---|---|
| Turn 1 (intent) | 12.8 ms | ~11 | ~15 | ~15 |
| Turn 2 (preference) | 13.4 ms | ~12 | ~16 | ~16 |
| Turn 3 (preference) | 14.8 ms | ~13 | ~17 | ~17 |
| **Journey total (3 turns)** | **41.0 ms** | 40.0 | 44.4 | 41.7 |

Local processing only — no LLM, DB or network latency included.
Supabase persistence will add per-turn DB latency in staging (unmeasured).

## Voice

| Operation | Latency | Notes |
|---|---|---|
| STT `/v1/voice/chat` (tone.wav → Whisper) | **316 ms** end-to-end | Live Groq Whisper call incl. HTTP; returned "." for non-speech audio |
| TTS `/v1/voice/synthesize` | untested | Blocked `model_terms_required` |
| Voice error paths | <5 ms | 415/403 rejections are local |

## LLM path (not benchmarked live)

`use_ai` requires `MEDICAL_AI_REPLIES=true` (currently false) — the AI
path was not exercised in this campaign. Groq call timeout is bounded by
`GROQ_TIMEOUT_SECONDS` (default 20s); `GROQ_MAX_TOKENS=160`,
`GROQ_TEMPERATURE=0.2`. Shadow mode capped 20 calls/min, off request path.
Safety-eval offline run: 308 prompts ≈ seconds total.

## Response sizes

Scripted replies: ~120–400 chars (1–3 sentences). Chat JSON payload:
~1–3 KB (includes actions, state, sources). Audio in: arbitrary ≤10MB;
audio out: untested (TTS blocked).

## Conclusion

Scripted path is effectively instant (<50ms/journey). The only material
latency sources are external: Groq Whisper (~300ms observed), Groq LLM
(unmeasured, bounded 20s timeout), PlayAI/Orpheus TTS (blocked), and
Supabase writes in staging (unmeasured). No performance defects found.
