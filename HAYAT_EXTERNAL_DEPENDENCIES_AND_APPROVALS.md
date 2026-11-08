# HAYAT — External Dependencies & Approvals

| Dependency | Needed for | Status | Owner | Action |
|---|---|---|---|---|
| Groq Orpheus terms | Voice TTS EN/AR | 🔒 `model_terms_required` | Groq org admin | Accept terms at console.groq.com → retest |
| Groq `allam-2-7b` | Live AI replies | configured, untested live | — | Enable only after MEDICAL_AI_REPLIES approval |
| Whisper STT | Voice input | ✅ live-verified | — | none |
| Firebase project | Customer OTP | unconfigured → 503 | Firebase admin | creds + Addendum 1.1 |
| CRM webhook | Consultation transmission | unset → mock | Integration owner | staging URL + DP-2 |
| Supabase staging | Persistence | code ready, 8 migrations unapplied | DB owner | authorize + apply per runbook |
| Cloudflare R2 / S3 | Durable knowledge | not implemented | DevOps | approve storage backend |
| BFF repo access | Integration verify | absent from workspace | Platform team | provide repo/URL |
| admin-be repo | Handoff sync verify | absent | Platform team | provide repo/URL |
| Sentry | Error monitoring | not integrated | DevOps | DSN + decision |
| Addendum 1.1 | Contact capture, attachments, customer path | `POLICY_ADDENDUM_1_1_APPROVED=false` | Compliance | formal sign-off |
| MEDICAL_AI_REPLIES | Live LLM replies | `false` | Compliance + safety eval | sign-off after live eval |
| VISITOR_ATTACHMENTS_ENABLED | Visitor doc upload | `false` | Compliance | only after Addendum 1.1 |

## Human approvals required before production
1. Addendum 1.1 compliance sign-off.
2. Groq org admin: Orpheus terms.
3. Firebase OTP activation approval.
4. CRM webhook staging test approval.
5. Supabase production migration approval (staging first).
6. BFF live verification sign-off.
7. Push `launch-v1` to origin.
