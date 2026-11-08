# HAYAT — API Reference

Base: `/v1` · Auth: `X-Service-Token` JWT required on all routes except
`/health` (and docs in dev). Session routes additionally need
`X-Session-ID` + `X-Session-Token` + `X-Visitor`.

## Sessions & conversations
| Method | Path | Body/Headers | Returns |
|---|---|---|---|
| POST | `/v1/sessions/guest` | `{locale}` | `{session_id, session_token}` |
| POST | `/v1/conversations` | `{guest_session_id}` | `{id, ...}` |
| GET | `/v1/conversations/{id}/messages` | session headers | `{messages[]}` |
| GET | `/v1/conversations/{id}/handoff` | session headers | handoff state |
| GET | `/v1/conversations/{id}/programme-enquiry` | session headers | enquiry |

## Chat
`POST /v1/chat` — `{conversation_id, message, client_message_id?}`
Headers: `X-Session-ID`, `X-Session-Token`, `X-Visitor`, `X-Reply-Language`.
Response: `{reply, detected_language, next_action, conversation_state,
sources[], profile_updates[], missing_required_fields[],
escalation_required, escalation_reason, coordinator_handoff, message_id}`.
Errors: 400/403 (ownership)/422 (validation).

## Voice
`POST /v1/voice/chat` — multipart `file` (wav/mp3/m4a/ogg/webm, ≤10MB)
+ `conversation_id`. Returns transcript + same chat fields.
`POST /v1/voice/synthesize` — `{conversation_id, message_id}`; only
stored assistant messages of that conversation; returns `audio/wav`.
Errors: 400 empty, 403 ownership, 404 message, 413 oversized, 415 type,
503 not-configured/provider-error.

## Knowledge (service-token)
| Method | Path | Notes |
|---|---|---|
| POST | `/v1/knowledge/documents` | multipart file+title → index/dedup/version |
| GET | `/v1/knowledge/documents` | list metadata |
| PUT | `/v1/knowledge/documents/{id}` | **update in place** (v+1, audit kept) |
| DELETE | `/v1/knowledge/documents/{id}` | removes all versions → 404 after |

## Consultations (approval-gated)
`POST /v1/consultations/otp/start`, `POST /v1/consultations` — require
Firebase creds + Addendum 1.1; currently 503 by design.

## Coordinator (service-token + trusted coordinator headers)
`GET /v1/coordinator/handoffs/{id}`,
`POST .../assign`, `.../progress`, `.../confirm-appointment`.
Visitor-supplied coordinator identity is never trusted.

## Programmes
`POST /v1/programmes/enquiries`,
`POST /v1/programmes/enquiries/{id}/register-interest`.

## Errors
Standard FastAPI `{detail}`; auth 401/403; validation 422; provider
unavailable 503; EF-8 safe-fallback reply on store errors.
