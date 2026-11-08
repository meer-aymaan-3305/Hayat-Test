# HAYAT — BFF Integration Contract

Status legend: ✅ Hayat-side verified in code/tests · ⬜ BFF-side
unverified (repo unavailable) · 🔒 requires approval/live test.

## 1. Service authentication (all `/v1/*` routes)
```
X-Service-Token: <JWT or opaque token issued by BFF>
```
- Hayat validates `system:` subject + expiry; fail-closed in
  staging/production — missing/invalid → **401**.
- BFF MUST: mint token server-side per request, never expose to browser.
- ⬜ BFF-side: confirm token issuance, rotation, and that visitors cannot
  obtain a service token.

## 2. Visitor session (chat/voice/programme routes)
```
X-Session-ID: <uuid>          # guest_sessions.id
X-Session-Token: <raw token>  # shown once at session creation
X-Visitor: guest | customer   # Literal; missing → scripted replies only
X-Contact-Consent: true|false # contact capture gate (also needs Addendum)
X-Reply-Language: en | ar     # optional override
```
- Hayat verifies token hash + expiry + ownership → **403** on mismatch.
- ⬜ BFF-side: session creation proxy, token storage (httpOnly cookie or
  BFF session), guest→customer upgrade path.

## 3. Coordinator routes (`/v1/coordinator/*`, `/v1/handoff`)
```
X-Service-Token: <system token>
X-Coordinator-ID: <uuid or staff id>
X-Coordinator-Role: coordinator | supervisor | admin
```
- Role enum-validated; missing/invalid → **401/403**.
- `confirm-appointment` binds asserted ID to recorded coordinator →
  **403** on mismatch (no self-asserted approvals).
- ⬜ BFF-side: MUST assert these from the authenticated staff session —
  never pass through client-supplied headers. THIS IS THE KEY UNVERIFIED
  CONTROL.

## 4. Error contract
| Condition | Status | Body |
|---|---|---|
| Missing/invalid service token | 401 | `{"detail": "..."}` |
| Session token/ownership fail | 403 | `{"detail": "Conversation access denied."}` |
| Wrong visitor type for route | 401/403 | per-route |
| Rate limit | 429 | `{"detail": "Rate limit exceeded."}` |
| AI disabled | 503 | voice endpoints only |
| Oversize upload | 413 | `{"detail": "File too large."}` |
| Bad file/audio type | 415 | `{"detail": "Unsupported ..."}` |

## 5. Required live staging verification (human action)
1. BFF → `POST /v1/sessions/guest` → chat → verify headers present.
2. Visitor token → `POST /v1/knowledge/documents` → expect 401.
3. Coordinator flow with asserted headers → handoff → confirm.
4. Voice endpoints through BFF (if enabled).
