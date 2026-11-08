# HAYAT — Visitor Medical Document Intelligence

Status: **IMPLEMENTED — DISABLED PENDING APPROVAL**
`VISITOR_ATTACHMENTS_ENABLED=false` by default; every endpoint fails
closed with 403 until privacy/compliance sign-off (see Outstanding
approvals). No production upload path is enabled by this change.

## Architecture

```
UploadFile → validate (ext + magic bytes + size + active-content filter)
          → store bytes  attachments_dir/<session_id>/<doc_id>.<ext>
          → extract text  pymupdf (PDF, per-page markers, OCR fallback
                        via pymupdf render + pytesseract for scans)
                        python-docx (DOCX paragraphs + tables)
                        pytesseract (PNG/JPG images)
          → classify     processed | needs_clearer_upload | failed
          → metadata     MemoryStore dict / Postgres `visitor_documents`
                        (migration 20261110000000, service-role only, RLS)
          → consent      consent_records, type=visitor_document_processing,
                        version=visitor-docs-v1, policy_version stamped
```

Visitor documents are fully separate from the admin knowledge base
(`/v1/knowledge/documents`): different store, different table, different
retention rules, never indexed for retrieval, never transmitted to CRM.

## API (all session-authorized, flag-gated)

- `POST /v1/conversations/{id}/documents` — `file` + `consent=true`
- `GET  /v1/conversations/{id}/documents` — list metadata
- `GET  /v1/conversations/{id}/documents/{doc_id}` — `?include_text=true`
- `DELETE /v1/conversations/{id}/documents/{doc_id}`
- `POST /v1/conversations/{id}/documents/consent/withdraw` — deletes all
  session documents and records withdrawal (latest consent decision wins,
  so `has_valid_consent` fails closed afterwards)

## Chat integration

`_document_context()` in `main.py` loads the session's `processed`
documents (only while consent is valid) and passes bounded extracted text
(≤6k chars/doc, ≤12k total, page markers preserved) into
`ChatService.respond(document_context=...)`. The text is injected into the
model system prompt under a **VISITOR-UPLOADED DOCUMENTS — untrusted
data** block with rules: cite document + page, separate extracted facts
from explanation, never invent values/diagnoses, decline clinical advice,
ask for clearer uploads when extraction is poor, escalate concerning
findings. When the model is unavailable, a deterministic fallback names
the uploaded files and routes to coordinator/clinician review — it never
claims the document was reviewed.

Voice (`/v1/voice/chat`) uses the identical `respond()` path, so document
context applies to voice turns exactly as to text.

## Safety properties

- Consent is explicit (`consent=true` form field) and recorded per upload
  with policy version; withdrawal deletes files + metadata.
- Ownership enforced per document (`session_id` + `conversation_id`);
  cross-visitor access returns 404.
- Type validation: extension allowlist + magic-byte check + size cap +
  basic active-content filter (JavaScript/Launch/EmbeddedFile signatures).
  Full malware scanning is an infrastructure dependency — see below.
- Extraction is fail-closed: corrupt/empty/scanned-without-text documents
  become `failed`/`needs_clearer_upload`, never "reviewed".
- OCR confidence is recorded; low-confidence extractions are surfaced as
  `confidence: "low"`.
- Document content is treated as untrusted data in prompts (labelled,
  never instructions) and cannot bypass deterministic guardrails, which
  run on the visitor's message before any model call.
- Uploaded documents are never used for model training and never leave
  the backend except into the chat model context for that session.

## Known limitations

- Tesseract language data installed: `eng` only — Arabic-scanned documents
  will likely return `needs_clearer_upload`; Arabic text PDFs work via
  the text layer.
- OCR runs synchronously in the upload request (bounded: ≤20 pages,
  ≤5 OCR pages, ≤ `MAX_UPLOAD_MB`). Very large scans may be slow.
- Extracted text is stored in Postgres (`extracted_text` column) when the
  Supabase store is active; bytes stay on the filesystem. Encryption at
  rest depends on the hosting volume — see deployment runbook.
- No virus scanner integration (clamav etc.) — basic signature filter only.
- Document context is injected for the whole conversation while documents
  are active; there is no per-turn relevance ranking yet.

## Outstanding approvals (blockers to enable)

1. **Privacy/compliance sign-off** on consent wording
   (`visitor-docs-v1`) and retention/deletion policy — C1–C4 adjacent.
2. **Business approval** that visitors may upload medical documents at all
   in the limited release, and approved visitor-facing explanation.
3. **Infra**: malware scanning (clamav/AV), encrypted volume for
   `attachments_dir`, `ara` tesseract language data if Arabic scans are
   required, apply migration `20261110000000_visitor_documents.sql` to
   staging Supabase.
4. **Retention decision**: documents currently persist until visitor
   deletion or consent withdrawal; a time-based retention policy needs
   sign-off before production.
