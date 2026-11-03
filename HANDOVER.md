# HAYAT — Engineering Handover

**Project:** Hayat — Trawellcare medical-travel and wellness intake assistant
**Handover date:** 4 November 2026
**Repository:** `https://github.com/Trawell-Care/Hayat.git`
**Working directory:** `D:\trawellcare\hayat-backend`
**Handover branch:** `feature/hayat-coordinator-handoff`
**Status:** Development handover; not a production-readiness certification.

> This document consolidates the implementation history and the latest Antigravity diagnostic report. Test results and code changes described as “reported” were supplied by the previous developer/agent and have not been independently re-run as part of this handover. The receiving engineer should verify the checked-out branch and environment before relying on them.

---

## 1. Product purpose and scope

Hayat is Trawellcare's conversational intake and routing assistant. It supports two distinct journeys:

1. **Medical travel / care consultation:** gathers permitted administrative preferences and routes the visitor towards a human consultation/coordinator.
2. **Signature Wellness Programmes:** explains and captures interest in three separate wellness-retreat programmes:
   - **HAYAT-100** — longevity and healthy ageing.
   - **AAfiya** — women's fitness and wellness.
   - **FFounders** — executive fitness and wellness.

Hayat is an intake assistant, not a medical professional, clinical decision-maker, travel agent, provider recommender, or autonomous booking system. A human coordinator owns follow-up and appointment confirmation.

## 2. Current implementation — reported

### 2.1 Backend and runtime

- Python backend using FastAPI.
- LLM integration uses `groq.AsyncGroq` through the project's `GroqChatModel`.
- Configured model reported as `allam-2-7b`; configured API key is read from environment configuration.
- An in-memory/offline model path is used for tests/offline environments.
- Persistence adapters include an in-memory store and Supabase-backed store.
- Streamlit is used as the current testing/demo interface.
- Do not assume the Supabase project, external CRM, or production environment has been validated end-to-end.

### 2.2 Medical-travel workflow and coordinator handoff

The coordinator handoff implementation reportedly includes service/schema logic, API routes, persistence and tests.

Reported handoff states:

`awaiting_registration → awaiting_coordinator → coordinator_assigned → contact_pending → coordinator_contacted → appointment_coordination → appointment_confirmed → handoff_closed`

Reported endpoints:

| Method | Endpoint | Purpose |
|---|---|---|
| GET | `/v1/conversations/{id}/handoff` | Read handoff associated with a conversation |
| GET | `/v1/coordinator/handoffs/{id}` | Retrieve a handoff |
| POST | `/v1/coordinator/handoffs/{id}/assign` | Assign a coordinator |
| POST | `/v1/coordinator/handoffs/{id}/progress` | Progress the handoff |
| POST | `/v1/coordinator/handoffs/{id}/confirm-appointment` | Human coordinator confirms an appointment |

Appointment confirmation is intended to require an authorized coordinator identity and appointment/provider details. The chatbot must not perform this action itself. Verify the exact request schemas, authentication/authorization implementation and role checks in the current code before integrating.

### 2.3 Signature Wellness Programmes

The source of truth for programme descriptions is:

`docs/knowledge/signature_programmes.md`

The catalogue and enquiry workflow reportedly include:

- Programme intent mapping:
  - healthy ageing/longevity → HAYAT-100
  - women's wellness/fitness/Pilates → AAfiya
  - executive wellness/leadership resilience → FFounders
- A staged conversational flow:
  `DISCOVERY → PROGRAMME_SELECTED → PREFERENCE_COLLECTION → DESTINATION_PREFERENCE → TRAVEL_PERIOD → GROUP_PREFERENCES → OPTIONAL_BUDGET → SUMMARY_REVIEW → REGISTERED_INTEREST → COORDINATOR_HANDOFF`
- Conditional/optional stages; phrases such as “flexible”, “skip”, “no preference”, and “not sure” are intended to let users move on.
- Destination options reportedly include USA, Spain, Japan, Singapore, India, UAE, plus Other/Undecided.
- A separate programme enquiry schema and persistence path. Programme preferences must not be merged into the medical Appendix A payload or sent to the clinical CRM webhook.
- Streamlit UI changes reportedly include a service selector, programme cards, contextual prompts, enquiry summary and scoped FAQs.

### 2.4 Programme enquiry reference and coordinator retrieval

The latest diagnostic report says:

- Registered enquiries receive a reference such as `ENQ-A1B2C3D4`.
- The reference is derived from the enquiry UUID and saved with the enquiry in the in-memory and Supabase stores.
- A coordinator can retrieve an enquiry by UUID or reference code using:

`GET /v1/coordinator/programme-enquiries/{identifier}`

Reported headers:

- `X-Coordinator-ID`
- `X-Coordinator-Role`

Verify the actual authorization middleware/dependencies and whether these headers are cryptographically or otherwise securely authenticated. Headers alone are not proof of secure coordinator authentication.

The latest code changes reportedly added `get_programme_enquiry_by_reference_code` to both stores, wired it through the programme service and exposed the route. The associated regression test is reported as passing.

### 2.5 Contact capture and follow-up messaging

The latest report says the registration response now distinguishes whether an authorized contact method exists:

- If authorized contact details exist through an approved secure flow, the message may explain that a coordinator will use the registered contact method.
- If no contact details were collected in chat, the response explicitly says the team will not initiate unsolicited outreach and the user can use the reference code through secure/authorized channels.

This is important: **an enquiry reference code does not itself provide a contact channel or guarantee follow-up.** Verify that the actual UI makes this distinction clear.

---

## 3. Latest diagnostic: `/v1/models` 404

The latest Antigravity report attributes recurring requests to:

`opencode-cli.exe ... serve --service`

It reports live TCP connections from that process to `127.0.0.1:8000` and binary strings indicating that OpenCode Desktop probes common local inference ports and requests `/v1/models`.

Hayat reportedly does not call `/v1/models`. It calls Groq's chat-completions API directly through `groq.AsyncGroq`, and the offline test model is in-memory. Therefore the 404 is reported to be an unrelated OpenCode local-model discovery probe, not a Hayat LLM initialization failure.

**No fake `/v1/models` endpoint was added.** The 404 is expected if Hayat does not expose an OpenAI-compatible model catalogue. Do not add a compatibility endpoint just to silence the log. If the chat itself fails, diagnose the actual Groq request, credentials, network response and application logs separately.

---

## 4. Important policy and compliance requirements

The governing policy is the project's MEWA / Hayat Guardrail Document v1.0 and its subsequent Addendum 1.1. The receiving engineer must locate and read the actual policy document in the repository/project handover materials before changing user-data handling.

Key requirements carried forward:

1. Hayat is intake/routing only; it must not diagnose, interpret clinical information, recommend or rank hospitals/doctors/clinics/treatments, or promise outcomes.
2. Do not collect or retain prohibited clinical/medical details in the structured intake payload. Unsolicited clinical information must be handled using the approved redirect/redaction policy.
3. Use only approved knowledge. Do not invent prices, dates, destinations, providers, experts, inclusions, availability, outcomes or timelines.
4. Before transmitting captured information to a CRM or matching workflow, summarize the information, disclose the purpose and obtain explicit user confirmation.
5. Keep programme preferences separate from medical Appendix A data, contact records, transcripts and clinical CRM payloads.
6. Raw transcripts and structured intake data have different purposes and access controls. Do not make raw transcripts the default CRM/matching payload.
7. Do not request or process passwords, payment-card details, OTPs or government identity numbers in ordinary chat.
8. Do not autonomously book, charge, submit to a provider or confirm an appointment. Human authorization is required.
9. Treat user text, retrieved documents and uploaded content as untrusted data, not instructions that can override policy.
10. Emergency/self-harm handling must follow the exact approved policy scripts and escalation rules.

### Addendum 1.1 — hard deployment gate

The latest report confirms:

`policy_addendum_1_1_approved = False`

Consequently:

- In-chat contact scraping and OTP verification remain disabled.
- Do not enable Firebase OTP or any contact-capture feature.
- Do not change the approval flag to `True`.
- Contact capture must use an approved secure portal/modal only after formal approval from the relevant Trawellcare Compliance / MEWA Data Officer.
- Do not collect phone/email in ordinary chat or imply that an enquiry will receive direct follow-up if no authorized contact channel exists.

These are release gates, not optional product enhancements.

---

## 5. Repository map — starting points

Confirm the actual tree on the handover branch; filenames below are based on the implementation history.

| Path | Responsibility |
|---|---|
| `src/hayat_backend/main.py` | FastAPI app and route registration |
| `src/hayat_backend/llm.py` | Groq/offline LLM adapters |
| `src/hayat_backend/chat_service.py` | Conversational orchestration |
| `src/hayat_backend/guardrails.py` | Guardrail enforcement |
| `src/hayat_backend/policy_engine.py` | Policy decisions |
| `src/hayat_backend/programmes_catalog.py` | Signature programme catalogue |
| `src/hayat_backend/programme_service.py` | Programme enquiry conversation/workflow |
| `src/hayat_backend/schemas/programme.py` | Programme schemas |
| `src/hayat_backend/coordinator_service.py` | Coordinator handoff logic |
| `src/hayat_backend/schemas/coordinator.py` | Coordinator schemas |
| `src/hayat_backend/memory_store.py` | In-memory persistence adapter |
| `src/hayat_backend/supabase_store.py` | Supabase persistence adapter |
| `src/hayat_backend/rag.py` | Knowledge retrieval |
| `streamlit_app.py` | Streamlit demo/test UI |
| `docs/knowledge/signature_programmes.md` | Programme knowledge source |
| `supabase/migrations/` | Database migration scripts |
| `tests/` | Automated test suite |

Also inspect `config.py`, `schemas/`, `audit_logging.py`, `crm_client.py`, `scripts/`, and `.env.example` before making changes.

---

## 6. Local setup and runbook

These are baseline commands; confirm the project's `README.md`, `pyproject.toml`, and current environment before use.

### 6.1 Activate environment / install dependencies

From PowerShell:

```powershell
cd D:\trawellcare\hayat-backend
uv sync
```

If the project is not using `uv` in the current checkout, follow the dependency manager declared in `pyproject.toml` instead.

### 6.2 Configure environment

- Copy `.env.example` to `.env` only if the example exists and contains placeholders.
- Populate required values locally using approved credentials.
- Never commit `.env`.
- Never paste API keys, service-role keys or tokens into handover documents, chat, logs or Git.
- Check the actual names/defaults in `src/hayat_backend/config.py`; do not assume this document lists every required variable.

The latest diagnostic reports Groq configuration via `GROQ_API_KEY` and `GROQ_MODEL` (reported model: `allam-2-7b`).

### 6.3 Start the API

```powershell
uv run uvicorn hayat_backend.main:app --host 127.0.0.1 --port 8000
```

If the package import path differs in the current checkout, use the command documented in the repository README/pyproject.

### 6.4 Start the Streamlit UI

In a second PowerShell terminal:

```powershell
cd D:\trawellcare\hayat-backend
uv run streamlit run streamlit_app.py
```

### 6.5 Port 8000 already in use

Check the owning process before stopping anything:

```powershell
netstat -ano | findstr :8000
Get-Process -Id <PID>
```

Only stop a process after confirming it is the stale Hayat server and not another project/service:

```powershell
Stop-Process -Id <PID> -Force
```

---

## 7. API and integration guidance

Use the FastAPI OpenAPI page as the authoritative live contract once the API is running:

- `http://127.0.0.1:8000/docs`
- `http://127.0.0.1:8000/openapi.json`

Do not build a second, guessed request schema from this handover. Inspect the Pydantic request/response models and OpenAPI output for exact field names, required headers, status codes and error shapes.

### Reported route inventory

| Method | Route | Notes |
|---|---|---|
| GET | `/v1/programmes` | List programme catalogue |
| GET | `/v1/programmes/{id}` | Read one programme |
| POST | `/v1/programmes/enquiries` | Create/start programme enquiry |
| GET | `/v1/conversations/{id}/programme-enquiry` | Retrieve enquiry for conversation |
| POST | `/v1/programmes/enquiries/{id}/register-interest` | Register interest and produce reference |
| GET | `/v1/coordinator/programme-enquiries/{identifier}` | Coordinator retrieval by enquiry UUID/reference |
| GET | `/v1/conversations/{id}/handoff` | Read conversation handoff |
| GET | `/v1/coordinator/handoffs/{id}` | Read coordinator handoff |
| POST | `/v1/coordinator/handoffs/{id}/assign` | Assign coordinator |
| POST | `/v1/coordinator/handoffs/{id}/progress` | Update handoff state |
| POST | `/v1/coordinator/handoffs/{id}/confirm-appointment` | Human coordinator appointment confirmation |

### Recommended frontend integration sequence

1. Fetch the programme catalogue from `GET /v1/programmes`.
2. Start or identify a conversation using the existing chat API contract.
3. Keep the selected service journey explicit: medical travel versus Signature Wellness Programme.
4. For programme enquiries, use the programme endpoints and preserve the returned conversation/enquiry identifiers.
5. Render one conversational question at a time and retain the current enquiry state between turns.
6. Show a reviewable summary before registration.
7. On registration, display the returned reference code and the exact contact/follow-up qualification returned by the backend.
8. Provide the reference code to the user. Do not promise outbound contact unless an approved contact method exists.
9. Keep coordinator-only retrieval/actions behind real server-side authorization. Do not trust frontend-supplied role headers as the sole security control.
10. Treat appointment confirmation as a human coordinator action only.

---

## 8. Signature Programme facts the UI must preserve

The detailed source is `docs/knowledge/signature_programmes.md`. Do not replace it with assumptions.

- Each programme is a **7-day experience: 5 retreat days + 2 travel days**.
- Programmes are premium and individually curated; there is no fixed/standard package price.
- Registration of interest is free and is not a booking, reservation or payment commitment.
- Candidate destinations discussed in the knowledge base are exploratory, not confirmed retreat locations.
- Dates, itinerary, partners, accommodation, meals, flights, experts, final inclusions and capacity are not confirmed unless the source is formally updated.
- HAYAT-100 is about healthy ageing/longevity; it is not a promise to live to 100.
- AAfiya is women-focused fitness and wellness; specific sessions/experts/activities may still be under consideration.
- FFounders is executive fitness and wellness; it is not a business conference.
- Do not guarantee health, anti-ageing, fitness or longevity outcomes.
- Ask one relevant follow-up question at a time; avoid overwhelming the visitor with the entire catalogue.

---

## 9. Verification status and limitations

### 9.1 Latest reported automated test run

The latest diagnostic report records:

```text
platform win32 -- Python 3.14.0, pytest-9.1.1
collected 177 items
177 passed, 1 warning in 53.52s
```

Reported subsets:

- Signature Programmes: 22/22 passed.
- Coordinator Handoff: 13/13 passed.
- Full backend suite: 177/177 passed.

The test run reportedly included the new reference-code persistence and coordinator retrieval regression test.

**Interpretation:** this is a reported local automated test result. It does not establish production readiness, real Supabase connectivity, external CRM delivery, coordinator identity security, migration safety, SMS delivery or full browser-to-database integration.

### 9.2 `/v1/models`

- Reported caller: OpenCode Desktop background service.
- Hayat does not use that endpoint.
- No compatibility endpoint was added.
- Expected 404 for this route does not by itself indicate that Groq chat is broken.

### 9.3 Still requiring verification

- Run the test suite from a clean checkout of the handover branch.
- Confirm current `git status`, branch and commit history.
- Confirm Streamlit UI and FastAPI work together in a fresh local session.
- Exercise a full programme enquiry from discovery through review, registration, reference display and coordinator retrieval.
- Verify persistence after process restart using the actual configured Supabase project (in a non-production/test environment).
- Verify RLS, grants, service-role use and coordinator authorization against the actual database.
- Verify that coordinator endpoints cannot be accessed by an unauthenticated or unauthorized caller.
- Verify the exact migration SQL against the target schema; do not apply to production without review/approval.
- Verify external CRM/webhook integration; it has not been established as live by the reported tests.
- Verify contact capture remains disabled and Addendum 1.1 remains unapproved.
- Review the one pytest warning and determine whether it is material.
- Investigate any live UX issues that remain after a clean restart.

### 9.4 Known unverified integrations

Do not assume these are complete merely because local tests pass:

- Real Supabase migration application and production persistence.
- External CRM webhook delivery.
- Firebase SMS OTP.
- Approved secure contact capture.
- Production coordinator authentication/authorization.
- Production deployment, observability, backups and retention configuration.

---

## 10. Database and migration handling

Migration files reported in the implementation history include:

- `supabase/migrations/20261103210000_coordinator_handoffs.sql`
- `supabase/migrations/20261103223000_signature_programme_enquiries.sql`

The latest report says no production migrations were applied. Preserve that state until the receiving engineer and project owner review the SQL, RLS policies, grants, constraints, indexes and rollback strategy.

Do not apply migrations to production as part of initial handover verification. Use a disposable/local or approved staging Supabase project first.

---

## 11. Next engineer — prioritized checklist

### P0 — Take ownership safely

- [ ] Check out `feature/hayat-coordinator-handoff`.
- [ ] Read this document, repository README, policy document and `docs/knowledge/signature_programmes.md`.
- [ ] Review `.env.example` and configure a local `.env` without committing it.
- [ ] Run the full test suite from a clean checkout.
- [ ] Start FastAPI and Streamlit; test both journeys manually.

### P1 — Verify programme registration end-to-end

- [ ] Complete HAYAT-100, AAfiya and FFounders enquiry paths.
- [ ] Verify optional/skip behaviour and destination choices.
- [ ] Verify summary review and registration.
- [ ] Verify reference code is persisted and retrievable by reference and UUID.
- [ ] Verify no-contact messaging does not imply unsolicited coordinator follow-up.
- [ ] Verify data survives a backend restart when using the approved persistence environment.

### P1 — Security and policy review

- [ ] Audit coordinator authentication/authorization; do not rely solely on client-provided headers.
- [ ] Review RLS/grants and service-role boundaries.
- [ ] Confirm programme preferences remain separate from Appendix A and clinical CRM payloads.
- [ ] Confirm transcript redaction, audit logging, consent and retention behaviour.
- [ ] Keep Addendum 1.1 approval false until formal approval.
- [ ] Keep OTP and in-chat contact capture disabled.

### P2 — Integration and deployment

- [ ] Validate migrations in staging and document rollback.
- [ ] Integrate the production frontend against the actual OpenAPI contract.
- [ ] Validate CRM integration only after policy approval and explicit consent flow.
- [ ] Add deployment configuration, monitoring and operational runbooks.
- [ ] Obtain compliance sign-off before enabling real-user contact capture or OTP.

---

## 12. Git handover and branch policy

The intended branch is `feature/hayat-coordinator-handoff`. Do not commit directly to `main`.

Before committing:

```powershell
cd D:\trawellcare\hayat-backend
git branch --show-current
git status --short
git remote -v
git diff --check
git check-ignore -v .env
git ls-files .env
```

Confirm the branch name is exactly `feature/hayat-coordinator-handoff`, the remote points to `Trawell-Care/Hayat.git`, `.env` is ignored, and `git ls-files .env` prints nothing.

Inspect `.env.example` and ensure it contains placeholders only. Inspect every untracked file. Do not stage temporary extracted text, local logs, credentials, cache files, or unrelated artefacts.

After reviewing the file list, stage only the intended source, tests, migration scripts, knowledge document and this handover. Then inspect the staged diff and scan for secrets before committing.

The exact commands are provided separately to the handover sender so they can be pasted and executed carefully.

---

## 13. Final handover statement

The current codebase contains a reported implementation of the Hayat medical-travel coordinator handoff and separate Signature Wellness Programme enquiry journey, with a reported local test result of 177 passing tests. The latest diagnostic attributes `/v1/models` 404 requests to OpenCode Desktop's local-model discovery rather than Hayat's Groq integration.

This is a **development handover**, not a declaration that the system is production-ready. The next engineer should first reproduce the test results, verify the actual UI and persistence, review coordinator authorization and migrations, and preserve all policy restrictions. In particular, Addendum 1.1 remains unapproved, contact capture/OTP remain disabled, and no production migration has been applied.
