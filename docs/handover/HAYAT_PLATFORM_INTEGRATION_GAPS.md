# HAYAT — Platform Integration Gaps

## What is verified locally
- `X-Service-Token` middleware: fail-closed, `system:` sub + exp required;
  unit-tested incl. spoofed-header rejection.
- Session tokens: hash-based authz on every conversation/message route.
- Coordinator endpoints: require asserted `X-Coordinator-ID` +
  `X-Coordinator-Role` (enum-validated); confirm-appointment binds
  identity to recorded coordinator (403 on mismatch).
- Visitor isolation: `X-Visitor` Literal; guests→sign-in gate;
  knowledge/attachments staff-only via service token.
- CP-5 consent: explicit affirmative + valid timestamp + idempotent
  transmission + fact-change invalidation.

## What is NOT verified (BFF repo absent from workspace)
- Whether trawellcare-bff actually issues `system:` service tokens and
  attaches them to every Hayat call.
- Whether the BFF asserts `X-Coordinator-ID`/`X-Coordinator-Role` from a
  server-side authenticated coordinator session (vs trusting client
  headers — Hayat cannot distinguish; it trusts whatever the BFF sends).
- Whether website features map 1:1 to Hayat routes (chat, voice,
  programmes, handoff status, OTP).
- Whether admin-be consumes Hayat conversation/handoff data with matching
  IDs (Hayat exposes consistent UUIDs; admin-be side unverified).

## Required human action
Run ONE live staging request chain through the real BFF:
guest session → chat → coordinator handoff read → knowledge upload
(negative test: visitor token → expect 401) → voice/chat if enabled.
Confirm headers are set server-side in BFF code review.

## Other gaps
- Knowledge documents live on local FS (`data/knowledge`) — not durable
  or multi-instance safe; needs object storage (R2/Supabase) before
  staging scale.
- No Sentry/error tracking integration.
- Streamlit tester sends no `X-Visitor` — gets scripted replies in
  staging/prod (dev-only convenience).
