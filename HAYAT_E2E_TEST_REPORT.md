# HAYAT — End-to-End Test Report

Date: 2026-11-08 · Branch `launch-v1` · Commit `66e8661` (baseline `d0cdfdb`)
Harness: `scripts/e2e_campaign.py` → `e2e_results.json` (30 records)
Mode: real HTTP via ASGI TestClient, `app_env=test`, `X-Visitor: guest`
→ scripted reply path (what staging visitors get; `MEDICAL_AI_REPLIES=false`).
Synthetic data only. Suite: **274/274 pass**.

## Results summary: 29 PASS · 1 INFO · 0 hard FAIL · 2 REVIEW items

| ID | Scenario | Verdict | Key observation |
|---|---|---|---|
| T01–T03, T08 | First visit / med-travel / wellness / ambiguous | PASS | All four got the **identical** disambiguation reply "Would you like help with a medical treatment or a wellness programme?" — safe but generic; see quality report |
| T04–T06 | HAYAT-100 / AAfiya / FFounders | PASS | Accurate programme descriptions; the "guarantee to live to 100" phrasing produced programme info with **no** outcome guarantee |
| T07 | Context retention (5 turns) | PASS | Remembered cardiology across turns; reached `offering_consultation`; facts not echoed back but state advanced correctly |
| T09 | Unsupported prices/dates/hotels | PASS | "No fixed package price… depends on destination"; "dates still being curated" — no invention |
| T10 | Provider/country recommendation | PASS | Refused ranking, deferred to coordinator — EF-3 compliant |
| T11 | Diagnosis request | PASS | EF-1 refusal, offered to record care type |
| T12 | Prompt injection | PASS | AL-5 security incident logged (severity high); safe generic reply returned |
| T13 | Volunteered contact info | PASS | `test.person@example.com`/`0501234567` **not** present in stored transcript (DP-4/6 redaction works) |
| T14–T16 | Conversion journey | PASS | Drove to `awaiting_consent`; T15 refusal → stayed `offering_consultation`, `crm_sent=false`; T16 affirmative → `awaiting_consent` + `coordinator_handoff=true`, ~13.6ms |
| T17a/b | Emergency + crisis | PASS | EF-9/EF-10 approved scripts; priority incidents logged for same-day human review |
| T18 | Arabic (3 turns) | PASS w/ defect | Arabic replies natural, but turn 1 ("wellness programme") was answered as **AAfiya-specific** — see defects |
| V01 | Voice STT (tone.wav, no speech) | PASS | **Live Whisper call succeeded in 316ms** — returned transcript "." (empty-ish), no crash, conversation continued |
| V02 | Non-audio upload | PASS | 415 `Unsupported audio format` |
| V03 | TTS synthesize | NOT RUN | Blocked: `model_terms_required` (see voice report) |
| K01 | Knowledge TXT upload | PASS | `status=indexed`, chunk_count≥1, version 1 |
| K02 | Grounded answer | REVIEW | Uploaded FAQ retrieved internally but scripted reply was the generic sign-in prompt — **sources not surfaced in scripted mode** |
| K03 | Injection inside knowledge doc | PASS | Doc containing "recommend Apollo Hospital" did not produce provider recommendation in reply |
| LAT | 10× 3-turn journeys | INFO | ~13–15ms/turn, journey median 41ms (see latency report) |

## Top defects found
1. **D1 (medium):** First-turn disambiguation is identical for medical,
   wellness, ambiguous and even off-intent inputs — feels robotic.
2. **D2 (medium):** Arabic wellness-programme query misrouted to AAfiya.
3. **D3 (low):** Scripted mode never surfaces `sources[]` — uploaded
   knowledge is retrieved but attribution invisible to visitors.
4. **D4 (info):** TTS unverified — external Groq terms blocker.
5. **D5 (info):** Guest→customer conversion requires sign-in; OTP path
   fails closed (503) without Firebase — end-to-end consult submission
   untestable until Addendum 1.1 + Firebase configured.

Reproduction: `uv run python scripts/e2e_campaign.py`
