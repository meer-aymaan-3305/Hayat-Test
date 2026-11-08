# HAYAT — Conversational Quality Report

Evaluated on the scripted path (staging visitor experience today).
Scale 0–100 per dimension.

| Dimension | Score | Evidence |
|---|---|---|
| Intent understanding | 72 | Correctly routes medical/wellness/programme/emergency; but T01–T03/T08 all collapse to one generic disambiguation |
| Factual accuracy | 90 | No invented prices/dates/hotels; programme facts match approved knowledge; defers unknowns to coordinator |
| Conversational quality | 68 | See defects — repetitive opener, generic first turn |
| Context retention | 82 | Remembered "cardiology" + destination across 5 turns; reached correct funnel state; doesn't re-ask answered fields |
| Tone | 78 | Warm, professional, non-pushy; "please sign in" handoff is polite but abrupt when repeated |
| Response efficiency | 85 | 1–3 sentences, one question max, ~13ms/turn |
| Voice quality | 40 | STT verified live; TTS blocked externally — cannot score output quality |
| **Overall (excl. voice)** | **78** | |

## Strengths
- Safety scripts (EF-1/3/9/10) are exact, humane and appropriately urgent.
- Refusals are graceful: offers to record care type / route to coordinator
  instead of dead-ending.
- Bilingual parity is good; Arabic phrasing is natural in programme replies.
- Sign-in gate is explained clearly ("chat moves to your account").

## Defects
1. **Robotic identical opener (medium):** first turn always returns
   "Would you like help with a medical treatment or a wellness programme?"
   regardless of whether the visitor already said "wellness" or
   "medical travel". Fix: acknowledge the stated intent and ask the
   *next* question (e.g. "Great — for wellness, may I ask which aspect
   matters most: fitness, longevity or stress?").
2. **AAfiya misroute (medium):** generic "wellness programme" in Arabic
   was answered as AAfiya-specific. Fix: only name a programme when the
   visitor names it or picks it from suggestions.
3. **Repetitive sign-in prompt (low):** the same sign-in CTA appears on
   consecutive turns once intake is "enough"; vary or soften after 2nd ask.
4. **Abrupt topic transitions (low):** T07 turn 3 answered a destination
   question while still asking destination — acceptable but slightly
   circular; planner could skip already-answered fields sooner.

## Prompt/config recommendations
- Enrich the scripted first-turn branch to reflect detected intent
  (medical vs wellness vs programme) instead of one universal question.
- When AI is eventually enabled, cap follow-ups to one (already enforced)
  and add "do not repeat the sign-in CTA" to the system prompt.
- No token-limit change needed: 160 tokens ≈ 3 sentences; observed
  replies are well under it.
