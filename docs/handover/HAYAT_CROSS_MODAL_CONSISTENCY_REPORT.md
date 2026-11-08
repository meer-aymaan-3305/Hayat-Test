# HAYAT — Cross-Modal Consistency Report

Date: 2026-11-08 · Commit `1acc59c`+audit fixes · Harness:
`scripts/cross_modal_audit.py` → `cross_modal_results.json` (25 records)
Modes tested: text-EN, text-AR (real ASGI requests, scripted path).
Voice: STT live-verified; TTS blocked externally; no speech samples
available for true audio-in journeys — voice journeys tested at the
pipeline edge only (see below).

## Journey parity matrix (next_action after turn 1)

| Journey | EN | AR | Consistent? |
|---|---|---|---|
| J01 first visit (mixed) | collect_detail | collect_detail | YES (post-fix) |
| J02 medical | collect_detail | collect_detail | YES (post-fix) |
| J03 wellness | collect_detail | collect_detail | YES (post-fix) |
| J04 HAYAT-100 (+guarantee q) | explore_programmes | explore_programmes | YES |
| J05 AAfiya (women's) | explore_programmes | explore_programmes | YES |
| J06 FFounders | explore_programmes | explore_programmes | YES |
| J07 ambiguous | clarify_category | clarify_category | YES |
| J08 unsupported price/dates | explore_programmes (no invention) | same | YES |
| J09 provider ranking | answer→EF-3 refusal | answer→EF-3 refusal | YES |
| J10 clinical/diagnosis | escalate (EF-1) | escalate (EF-1) | YES |

**Fix applied during audit:** Arabic first turns previously returned
`answer` (English-biased planner gate + missing Arabic medical terms).
Added Arabic medical/wellness/intent-declaration patterns and an
Arabic both-signals ambiguous pattern; first-turn EN/AR now identical.

## Special-attention checks

- **Arabic transcription → programme classification:** N/A live (no AR
  speech sample); text-AR classification verified identical to EN.
- **General wellness ≠ AAfiya:** confirmed — J03 AR/EN both route to
  wellness-goal collection, not AAfia.
- **Voice bypasses guardrails:** NO — `/v1/voice/chat` feeds the
  transcript through the identical `ChatService.respond()` pipeline.
- **TTS authorization:** only stored assistant message IDs in the
  caller's own conversation; arbitrary text impossible (unit-tested).
- **Unclear transcription:** Whisper returned "you" for a pure tone
  (hallucination) → chat produced the generic clarify, **no fabricated
  intent** — safe failure mode. Low-severity note: STT hallucination on
  non-speech audio is a Whisper trait; guardrails absorb it.
- **Consent explicit / refusal blocks CRM / no false booking:** verified
  in J12/J13 — guests reach `sign_in_required` (by design); consent
  states unreachable for guests without an account. Customer-path
  consent verified in unit tests (T15/T16 E2E).

## Defects found this audit
1. **AR multi-turn fact extraction weak (medium):** J11-AR turn 1 now
   collects, but turns 2–4 ("قسطرة قلب", "الهند", "خلال ثلاثة أشهر")
   return clarify — Arabic preference facts aren't extracted into
   `case_facts`, so the funnel stalls. EN equivalent progresses to
   `offer_consultation`. Recommend extending `_extract_facts` Arabic
   patterns (specialty/destination/timing).
2. **TTS unverified (external):** Orpheus `model_terms_required` still
   active — owner: Groq org admin.
3. **STT hallucination on non-speech (low):** returns single-word
   transcripts; harmless under guardrails.
