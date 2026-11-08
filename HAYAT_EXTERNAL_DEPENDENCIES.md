# HAYAT — External Dependencies & Owner Matrix

| # | Item | Owner | Action required | Status | Acceptance evidence |
|---|---|---|---|---|---|
| 1 | Supabase staging migration + EF-8 | Backend/DB owner | Confirm project is staging; write ALTER for legacy `consent_records`; apply 8 migrations; verify consent path | **BLOCKED** — needs staging creds + authorization | `record_consent` insert succeeds; QA G2 no EF-8 |
| 2 | BFF live integration | BFF/frontend owner | Provide repo/env; verify X-Service-Token, session propagation, coordinator identity server-side | **BLOCKED** — repo absent | One live Website→BFF→Hayat request succeeds |
| 3 | Addendum 1.1 approval | Compliance | Sign off policy addendum | **PENDING** — flag stays false | `POLICY_ADDENDUM_1_1_APPROVED=true` only after sign-off |
| 4 | `MEDICAL_AI_REPLIES` | Compliance + product | Approve enabling visitor-facing AI replies | **PENDING** — flag stays false | Guardrail eval re-run green |
| 5 | Firebase OTP | Backend + compliance | Provide creds + Addendum 1.1 | **BLOCKED** | OTP start→verify→consultation flow live |
| 6 | CRM webhook | Product/compliance | Approve endpoint + transmission authorization | **BLOCKED** — unset | Consent-approved handoff reaches CRM |
| 7 | Object storage (knowledge) | Infra | Approve provider + creds for durable shared store | **PENDING** — local FS works single-instance | Multi-instance knowledge consistency test |
| 8 | Sentry | Infra | Provide DSN if monitoring wanted | **OPTIONAL** — not configured | Error events visible in Sentry |
| 9 | Frontend knowledge-admin PUT | Frontend | Update "edit doc" to call `PUT /v1/knowledge/documents/{id}` (D1 fix) | **PENDING** — contract documented | Edit→v2→old version audit |
| 10 | Arabic dialect review | Product/native speaker | Review AR extraction terms before wider rollout | **PENDING** | Native-speaker sign-off |

## Resolved this cycle
- ✅ Orpheus TTS terms — accepted; EN+AR synthesis + Whisper round-trips live-verified.
- ✅ Knowledge versioning D1 — PUT endpoint implemented + tested.
- ✅ Conversation defects (flexible dest, timing, recall) — fixed + tested.
