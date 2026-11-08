# HAYAT — Backend Handover (for Zahid)

Date: 2026-11-08 · Branch `launch-v1` · Commit `a0725f9`+ (D2 fix pending commit)

## 1. Product overview
Hayat is TrawellCare's conversational medical-tourism & wellness assistant.
It guides visitors toward a **consented human coordinator consultation**.
It must NOT diagnose, give medical advice, rank providers, book
appointments, or transmit visitor data without authorization.

## 2. Architecture
- **FastAPI** app (`src/hayat_backend/main.py`) — single entry, creates
  `ChatService`, `KnowledgeStore`, `KnowledgeRetriever`, Supabase/Memory store.
- **ChatService** (`chat_service.py`) — orchestration: language detect,
  fact extraction (`_extract_facts`), redaction, guardrails (EF-1..EF-9,
  AL-1..AL-6), `QuestionPlanner` for one-question-at-a-time funnel.
- **QuestionPlanner** (`question_planner.py`) — deterministic next-best-
  step; pending-field progression (category→detail→destination→timing→
  offer_consultation→sign_in_required/awaiting_consent).
- **ProgrammeConversationService** (`programme_service.py`) — HAYAT-100,
  AAfiya, FFounders journeys + signature-programme enquiries.
- **SupabaseStore** (`supabase_store.py`) — durable sessions, messages,
  case_facts+versions, consultations, handoffs, enquiries, idempotency.
- **MemoryStore** — test/local fallback.
- **KnowledgeStore/KnowledgeRetriever** (`knowledge.py`, `rag.py`) —
  approved company docs, SHA-256 dedup, document-addressed versioning
  (PUT endpoint), scored retrieval with honest `sources[]` attribution.
- **Speech** (`speech.py`) — Groq Whisper STT (`whisper-large-v3`) +
  Orpheus TTS (`orpheus-v1-english`/`austin`, `orpheus-arabic-saudi`/`abdullah`).
- **service_auth** — JWT `X-Service-Token` (BFF-only), fail-closed.

## 3. Repository structure
```
src/hayat_backend/   main.py chat_service.py question_planner.py
                     programme_service.py knowledge.py rag.py speech.py
                     supabase_store.py memory_store.py coordinator_service.py
                     service_auth.py config.py llm.py models.py audit.py
tests/               300+ tests incl. QA regression files
supabase/migrations/ 8 SQL files (NOT yet applied to live project)
scripts/             e2e_campaign.py cross_modal_audit.py qa_session*.py
HAYAT_*.md           all QA/architecture/runbook reports
data/knowledge/      default local knowledge dir (gitignored)
```

## 4. API endpoints
See `HAYAT_API_REFERENCE.md` for full schemas. Summary:
`POST /v1/chat`, `POST /v1/voice/chat`, `POST /v1/voice/synthesize`,
`GET /v1/conversations/{id}/messages`, `POST /v1/sessions/guest`,
`POST /v1/conversations`, knowledge CRUD (`POST/GET/PUT/DELETE
/v1/knowledge/documents[/{id}]`), consultation + OTP (approval-gated),
coordinator handoff routes (service-token + coordinator identity),
programme enquiries.

## 5. Auth & isolation
- All `/v1/*` (except `/health`, docs in dev) require `X-Service-Token`
  JWT signed with `JWT_SYSTEM_SECRET` (`sub` must start `system:`).
- Guest sessions: `X-Session-ID` + `X-Session-Token`; conversations are
  session-scoped — cross-visitor access → 403.
- `X-Visitor: guest|customer` gates AI replies; `X-Reply-Language` en/ar.
- Coordinator routes require trusted coordinator headers — visitor-
  supplied identity never trusted.

## 6. Conversation flow
first turn → intent classify (EN+AR) → collect_detail (one question at
a time) → offer_consultation → sign_in_required → awaiting_consent →
coordinator handoff. Sign-in CTA never repeated consecutively; recall
questions echo stored facts (see D3 note).

## 7. EN/AR
MSA + partial dialects (عايز/أبغى/بدّي/محتاج/ودي), Arabic-Indic digits
normalized, AR extraction for category/specialty/destination/timing/
budget/insurance/value-priority. AR voice verified end-to-end.

## 8. Voice
`POST /v1/voice/chat` (multipart audio → Whisper → same ChatService
pipeline → reply + transcript). `POST /v1/voice/synthesize` — only
stored assistant messages, conversation-owned, never arbitrary text.

## 9. Knowledge lifecycle
Upload (PDF/DOCX/TXT, ≤max_upload_mb) → extract → chunk → index.
PUT = document-addressed version update (v-file preserved, only active
version retrieved). DELETE removes all versions. Identical bytes dedup.

## 10. Consent & handoff
Consultation submission → summary → explicit consent → coordinator
handoff (`coordinator_handoffs` table, assign/progress/confirm routes).
CRM webhook unset; nothing transmitted without approval.

## 11. Safety
Guardrail scripts EF-1..EF-9 (emergency, crisis, clinical refusal,
provider refusal, injection AL-5, redaction DP-4, escalation EF-8/EF-9).
Flags: `POLICY_ADDENDUM_1_1_APPROVED=false`, `MEDICAL_AI_REPLIES=false`,
`VISITOR_ATTACHMENTS_ENABLED=false` — **do not change without approval**.

## 12. Setup
```
uv sync
cp .env.example .env   # fill GROQ_API_KEY, JWT_SYSTEM_SECRET, SUPABASE_*
uv run uvicorn hayat_backend.main:app --host 0.0.0.0 --port 8000
uv run pytest tests -q
```

## 13. Known limitations
- Supabase live schema is legacy (migrations unapplied) → consent-path
  EF-8 until reconciled (see DEPLOYMENT_RUNBOOK + SCHEMA_INVESTIGATION).
- Recall reply shadowed by pending sign-in CTA (D3, documented).
- Knowledge store is local-FS (single instance) until object storage.
- AR dialect coverage partial; code-switching partial.
