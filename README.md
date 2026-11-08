# Hayat backend

Start with the handover from the backend developer: `docs/handover/HAYAT_BACKEND_HANDOVER.md`, `docs/handover/HAYAT_API_REFERENCE.md` and `docs/handover/HAYAT_EXTERNAL_DEPENDENCIES.md`. All other QA and readiness reports are in `docs/handover/`, and the QA scripts are in `scripts/qa/`.

The API uses Supabase as the durable repository whenever valid server-side
Supabase settings are configured. Local tests inject an in-memory repository
and never write test data to Supabase.

The bounded persistence contracts live in `src/hayat_backend/schemas`. They
cover guest sessions, conversations/messages, consent, intake case facts,
source references, and placeholder persona/plans results. Example payloads
and a contract JSON schema are in `examples/` and `schemas/`. The Supabase
migration in `supabase/migrations/` enables row-level security and keeps
anonymous clients denied by default; server-side persistence must use the
service role and must never expose that key to a browser.

## Requirements

- Windows PowerShell
- Python 3.14 (the repository is currently pinned by `.python-version`)
- `uv`

## Setup

From `D:\trawellcare\hayat-backend`:

```powershell
uv sync
Copy-Item .env.example .env
```

Replace the placeholders in `.env` with server-only values before enabling
staging or production. Never expose `GROQ_API_KEY` or
`SUPABASE_SERVICE_ROLE_KEY` to Streamlit or a browser frontend.

Apply the versioned migrations to the connected Supabase project before
starting the live API:

```powershell
supabase db push
```

If the API logs `column conversations.state does not exist`, the database is
running an older schema. Run `supabase db push` against the same project, then
restart the API. The repository has a compatibility fallback during rollout,
but durable conversation states and persona fact history require the
`20261027170000_hayat_orchestration.sql` migration to be applied.

The migration adds the guest-token hash, stable message ordering, lead,
phone-verification, pending consultation, orchestration-state, and append-only
persona fact-version tables.

Firebase phone OTP requires these server-side settings:

```env
FIREBASE_API_KEY=...
FIREBASE_PROJECT_ID=...
FIREBASE_SERVICE_ACCOUNT_JSON=...
```

The OTP start request must include a Firebase reCAPTCHA token obtained by the
approved client flow. The frontend completes Firebase Phone Authentication and
sends the resulting Firebase ID token to
`POST /v1/consultations/otp/verify` as `firebase_id_token`. The backend
verifies that token with Firebase Admin, checks its trusted `phone_number`
claim against the lead, and stores only verification state and the Firebase
user id. The backend never stores the OTP code, ID token, or credentials.
`FIREBASE_SERVICE_ACCOUNT_JSON` is a server-only secret and must be supplied by
a secret manager in staging/production. If Firebase configuration is absent,
OTP endpoints fail closed with a safe `503`; there is no fake production
fallback.

## Consultation API contract

The lifecycle is intentionally coordinator-led:

`requested` -> `awaiting_details` -> `awaiting_verification` ->
`pending_coordinator_confirmation` -> `confirmed` (or `cancelled`).

Creating `POST /v1/consultations` only creates a pending request. It never
creates a calendar event and never returns `confirmed`. A coordinator's
separate authorized workflow must update the backend state before a confirmed
appointment may be shown to a customer. Consultation-processing consent is
stored separately from marketing consent.

`POST /v1/chat` persists the complete message history and returns
`conversation_state`, a deterministic `next_action`, a structured `suggestions`
array, and a `persona_profile`. Each suggestion has an `action_id`, localized
`label`, executable `payload`, and `relevance`. The Streamlit client submits
the payload through the same chat endpoint and sends a `client_message_id` to
prevent rerun duplicates. Facts are
append-only, versioned, and carry a status, source message id, confidence,
timestamp, and extraction schema version. Repeated facts are not re-added;
contradictory values remain historical until clarified.

The model receives the current user message exactly once, bounded chronological
history from the same conversation, approved knowledge only when relevant, and
structured facts plus journey state. Out-of-scope and safety responses do not
invoke the model or display irrelevant suggestions.

After changing the API contract, restart any already-running Uvicorn process.
An old process will report `client_message_id: Extra inputs are not
permitted`; Streamlit has a temporary compatibility retry for that rollout
case, but the updated server is required for durable duplicate protection and
structured startup actions.

## Short branching consultation flow

Every new conversation persists one exact welcome message and two category actions:
**Medical treatment** and **Wellness programme**. Selecting a category stores the
validated `customer_category` fact and routes the conversation into its own short
funnel. Medical journeys collect treatment or specialty, destination, and timeframe;
wellness journeys collect programme or goal, destination, and timeframe.

The chat response includes bounded conversation context, deterministic `next_action`,
structured `suggested_actions`, a persona-ready `profile_summary`, and
`consultation_progress`. Progress reports collected and missing required details
without preventing free-text questions. A visible consultation action is offered
throughout a selected journey. The lifecycle distinguishes detail collection,
verification, consent, ready-for-submission, pending coordinator confirmation,
confirmed, cancelled, escalated, and completed states. A request is never presented
as confirmed until a coordinator changes the persisted backend state.

The next-best-question planner runs after fact extraction and before the assistant
message is persisted. It answers the user's current question first, then asks at most
one contextual follow-up based on missing discovery or consultation details. It does
not collect name or phone information during exploration unless the customer has
expressed consultation intent. Suggested actions complement the planner's question
and are regenerated from the current target field rather than reused as a static
question list.

The Streamlit tester keeps chat as the primary interface and shows a compact,
read-only profile. Chat-extracted facts are persisted as canonical snapshots in
`case_facts` and as append-only provenance records in `case_fact_versions`. Lead
updates use the existing unique conversation constraint without inserting duplicate
current profiles. Consultation-processing consent is stored in `consent_records`,
phone verification is required before submission, and a submitted request remains
`pending` until coordinator confirmation.

Apply the latest persistence migration before using the live Supabase project:

```powershell
supabase db push
```

The Supabase CLI must be installed and the project linked first. The API uses the
server-only `SUPABASE_SERVICE_ROLE_KEY`; never place that key in Streamlit or expose
it to browser code.

## Manual end-to-end smoke test

1. Start the API with `uv run uvicorn hayat_backend.main:app --host 127.0.0.1 --port 8000`.
2. Create a guest session with `POST /v1/sessions/guest`, then create a conversation.
3. Send two chat messages using the returned session headers; verify the second
   answer can reference the first fact and that `suggestions` changes after a
   care category or destination is supplied.
4. Stop and restart Streamlit, use **Restore an existing guest conversation**,
   and confirm the chronological transcript is loaded.
5. Save lead details, record `consultation_processing` consent, start Firebase
   verification, and verify with a Firebase ID token in a configured
   environment. In development tests, use the injected synthetic provider only.
6. Submit the consultation request with preferred dates/times and timezone.
   Verify the response is `pending`, never `confirmed`, and that subsequent
   responses expose `pending_coordinator_confirmation`.
7. Test an emergency or diagnosis request and verify it escalates without a
   model-generated clinical answer.

Development mode intentionally permits missing integration credentials so that
the health endpoint can be used while the project is being configured. Staging
and production fail during application startup when required integration
configuration is missing or still uses a placeholder.

## Run the API

```powershell
uv run uvicorn hayat_backend.main:app --host 127.0.0.1 --port 8000
```

Check the foundation:

```powershell
Invoke-RestMethod http://127.0.0.1:8000/health
```

With the scaffold `.env`, the response is expected to report
`"status": "degraded"` and must not contain secret values.

## Test

```powershell
uv run pytest
```

The matching engine and automatic calendar booking remain disabled because
their endpoint contracts were not supplied. Consultation requests remain
`pending` until an authorized coordinator confirms them.
