# HAYAT — Frontend Integration Contract

Base URL: `http://127.0.0.1:2005` (local). All routes except `GET /health`
(and `/docs`, `/openapi.json`, `/redoc` in `APP_ENV=development` only) require
the BFF service token.

## Authentication headers (every request)

| Header | Value |
|---|---|
| `X-Service-Token` | JWT signed with `JWT_SYSTEM_SECRET`, `sub` must start `system:`, must have `exp`. Issued by trawellcare-bff. |

Visitor-scoped endpoints additionally require the guest session:

| Header | Value |
|---|---|
| `X-Session-ID` | `session_id` from `POST /v1/sessions/guest` |
| `X-Session-Token` | `session_token` from `POST /v1/sessions/guest` |
| `X-Visitor` | `guest` or `customer` (always send; missing → scripted replies in staging/prod) |
| `X-Contact-Consent` | `true`/`false` (only meaningful with Addendum 1.1 approved) |
| `X-Reply-Language` | `en` or `ar` (optional override) |

Coordinator endpoints additionally require `X-Coordinator-ID` and
`X-Coordinator-Role` (`wellness_curator` | `case_manager` | `lead_coordinator`),
asserted by the BFF after authenticating the human coordinator.

Errors: `{"detail": "..."}` — 400 validation, 401 unauthenticated,
403 forbidden/ownership, 404 not found, 413 too large, 415 bad media type,
422 unprocessable, 503 integration unavailable.

## Sessions & text chat

`POST /v1/sessions/guest` → `{"session_id","session_token","expires_at"}`

`POST /v1/conversations` (header `X-Session-Token`, body `{"guest_session_id"}`)
→ `{"id","session_id","state","language","greeting","suggestions","suggested_actions"}`

`POST /v1/chat` (headers above; body `{"conversation_id","message","client_message_id"?}`)
→ large JSON: `reply`, `answer`, `language`, `suggested_actions[]`
(`action_id,type,label,payload,relevance`), `conversation_state`,
`next_action`, `follow_up_question`, `programme_enquiry`,
`coordinator_handoff`, `consultation`, `escalation_required`, `sources[]`.

`GET /v1/conversations/{id}/messages` → `{"messages","conversation_state","suggested_actions","persona_profile","consultation_progress"}`

`GET /v1/conversations/{id}/handoff` → `{"id","status","assigned_coordinator_name","appointment_confirmed","appointment_details",...}`

## Voice

`POST /v1/voice/chat` — `multipart/form-data`:
- file field `file`: audio (audio/*, octet-stream, video/webm|mp4), ≤ `MAX_UPLOAD_MB`
- field `conversation_id`: UUID
- headers: session + visitor headers as above
→ `{"conversation_id","transcript","detected_language","reply","language","escalation_required","suggested_actions","conversation_state","message_id"}`
- 503 when `GROQ_API_KEY` missing or provider fails.

`POST /v1/voice/synthesize` — JSON `{"conversation_id","message_id"}` where
`message_id` is an **assistant** message id returned by chat/voice-chat.
→ `audio/wav` bytes (Orpheus TTS; EN `canopylabs/orpheus-v1-english`,
AR `canopylabs/orpheus-arabic-saudi`). 404 if message not found / not
assistant / wrong conversation; 503 if TTS unconfigured.

Frontend flow: record audio → POST `/v1/voice/chat` → show `reply` →
POST `/v1/voice/synthesize` with returned `message_id` → play audio.

## Knowledge (staff/BFF only)

`POST /v1/knowledge/documents` — multipart `file` (PDF/DOCX/TXT ≤
`MAX_UPLOAD_MB`), optional field `title`. → `{"document_id","filename",
"title","version","status","chunk_count","error"}`. Status `indexed` =
retrievable; `failed` = extraction failed (see `error`).

`GET /v1/knowledge/documents` → list of `{document_id,filename,title,
version,status,chunk_count,error,uploaded_at}`.

## Visitor document uploads (flag-gated: `VISITOR_ATTACHMENTS_ENABLED`)

Two distinct endpoints — do not confuse them:

- **Medical documents Hayat should read** → `POST /v1/conversations/{id}/documents`
  (multipart `file` PDF/DOCX/PNG/JPG/JPEG + form field `consent=true`,
  optional `X-Reply-Language: en|ar`). Returns document metadata plus
  `reply`/`message_id` — the acknowledgement is also appended to the
  conversation. Statuses: `processed` (text extracted, usable in chat),
  `needs_clearer_upload`, `failed`. Manage via `GET`/`DELETE
  .../documents[/{doc_id}]` and `POST .../documents/consent/withdraw`.
- **Plain file attachments** → `POST /v1/conversations/{id}/attachments`
  (opaque storage only — Hayat never reads them; staff download via
  service-token routes). Do NOT send medical documents here expecting
  Hayat to understand them — the acknowledgement explicitly says it
  cannot read files.

While the flag is off both return 403.

## Programmes

`GET /v1/programmes`, `GET /v1/programmes/{id}`,
`POST /v1/programmes/enquiries` (session headers),
`GET /v1/conversations/{id}/programme-enquiry`,
`POST /v1/programmes/enquiries/{id}/register-interest` (body
`{"full_name","phone_number","email","preferred_contact_method","contact_consent"}`
— contact fields only stored when Addendum 1.1 approved),
`GET /v1/coordinator/programme-enquiries/{uuid-or-ENQ-XXXX}` (coordinator
headers).

## Coordinator handoff

`GET /v1/coordinator/handoffs/{id}`,
`POST .../assign` `{coordinator_id,coordinator_name,role,notes}`,
`POST .../progress` `{status,notes,contact_channel_used}`,
`POST .../confirm-appointment` `{coordinator_id,coordinator_name,
appointment_time,provider_or_clinic,mode,notes}` — `coordinator_id` must
equal `X-Coordinator-ID` header or 403. `appointment_confirmed` via
`/progress` is rejected (HB-8).

## Consultations

`POST /v1/consent`, `POST /v1/leads`, `POST /v1/consultations/otp/start`,
`POST /v1/consultations/otp/verify`, `POST /v1/consultations` — all
session-scoped; OTP fails closed (503) without Firebase config.
