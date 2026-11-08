# HAYAT — QA Acceptance Summary (all sessions)

## Test totals (latest run)
**316/316 automated tests pass.** QA sessions added ~90 scenario records.

## Session log
| Session | Commit | Scope | Result |
|---|---|---|---|
| 1 | `5ad20dd` | Live Supabase-backed conversations (17) | 14P/2PART/1F — found EF-8 (unapplied migrations), repeated-question, recall gaps |
| 1.1 | `85ee303` | Fix those defects | 305/305; flexible-dest, timing, recall implemented |
| 2 | `c4c1a3b` | Knowledge lifecycle (17) | 15P/1PART/1F — found D1 versioning defect |
| 2.1 | `35123ff` | D1 fix: PUT versioning | 316/316; 11 new tests |
| 3 | `ad407bb` | Voice STT/TTS (13) | EN Whisper live PASS; TTS BLOCKED (terms) |
| TTS unblock | `1b11827`,`7a4cea6`,`5432d03` | Orpheus terms diagnosis | confirmed terms blocker + org-probe limitation |
| TTS accept | `16e40cc` | EN+AR synthesis + round-trips | **7/7 PASS live** |
| 4 | `a0725f9` | E2E journeys A–H (49) | **47P/2PART/0F/0B** |

## Defects (all resolved or documented)
- D1 knowledge versioning → FIXED (`35123ff`, PUT endpoint).
- D2 recall dict-leak → FIXED this sprint (canonical unwrap + planner `_category` dict-safety).
- D3 recall-vs-CTA priority → DOCUMENTED (accepted funnel priority).
- EF-8 Supabase schema → EXTERNAL (migrations pending owner).

## Evidence files
`qa_results.json`, `knowledge_qa_results.json`, `voice_qa_results.json`,
`tts_acceptance_results.json`, `qa_session4_results.json`, WAV files
(`tts_*.wav`, `qa_en*.wav`), all `HAYAT_*.md` reports, `scripts/qa_*.py`.

## External blockers (see HAYAT_EXTERNAL_DEPENDENCIES.md)
Supabase staging migration · BFF live check · Addendum 1.1 ·
MEDICAL_AI_REPLIES · Firebase OTP · CRM · object storage · frontend PUT.

## Bottom line
Backend is feature-complete and live-verified for the scripted EN+AR
text+voice journey. Production NO-GO pending external approvals only.
