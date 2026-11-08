# HAYAT — QA Session 2: Knowledge Document Lifecycle

Date: 2026-11-08 · `launch-v1` @ `85ee303` · **TESTING ONLY — no app code changed**
Environment: `TestClient`, `APP_ENV=test`, isolated `tmp` knowledge_dir,
`max_upload_mb=1`. No real store touched. Driver: `scripts/qa_session2_knowledge.py`;
data: `knowledge_qa_results.json` (17 records).

## Results

| Test | Verdict | Evidence |
|---|---|---|
| T1a TXT upload | PASS | 200, status=indexed |
| T1b PDF upload (synthetic) | PASS | 200 (pypdf extracted) |
| T1c DOCX upload | PASS | 200, status=indexed |
| T1d metadata listing | PASS | all docs listed w/ id/version/status |
| T2a grounded query | PASS | reply + `sources[]` attributed `doc-… 'Cedar Policy' v1` + defaults |
| T2b unsupported query (wifi pw) | PASS | safe generic answer, no fabrication |
| T3a version increment | **PARTIAL** | see defect D1 |
| T4 identical re-upload | PASS | same doc_id, version 1→2, no dup chunks |
| T4b single index entry per title | **FAIL** | 2 "Cedar Policy" entries — same root cause as D1 |
| T5a delete | PASS | 200 `{"status":"deleted"}` |
| T5b delete again | PASS | 404 |
| T5c chunk files cleaned | PASS | 0 `doc-…-v*.txt` remain |
| T5d unrelated docs intact | PASS | PDF/DOCX docs unaffected |
| T6a corrupt PDF | PASS | status=failed, no crash (pypdf error logged) |
| T6b unsupported .exe | PASS | 4xx rejected |
| T6c empty TXT | PASS | failed/422, no crash |
| T6d oversized (>1MB) | PASS | rejected before full read |

## Defect D1 — versioning is content-addressed, not document-addressed (MEDIUM)
`KnowledgeStore.ingest` dedups/version-bumps **only by SHA-256**. Uploading
*changed* content under the same title creates a **new** `doc_id` at v1;
the previous version's chunks remain in `indexed_chunks()` → retriever
keeps serving stale content alongside the update. Verified: T3 produced
`doc-e97002a23e7e v1` while `doc-4bc5050b9f95` (old content) stayed live;
index ended with two "Cedar Policy" entries.
- Spec expectation: "updated version of the same document → version
  increments; old information not presented as current."
- Not fixed — requires a design decision (title+filename keyed versioning
  or supersede/deactivate semantics) and separate authorization.
- Workaround today: DELETE the old document after re-upload.

## Notes
- Authorization: all knowledge routes sit behind the service-token
  middleware (verified by test suite; this session ran in test env where
  auth is bypassed — staff-only enforcement verified separately).
- Visitor attachments unaffected; clinical processing still disabled.
- Retrieval attribution works (`sources[]` with document_id/title/version).

## Suite
295→305 tests pass after session 1.1; this session added no code.
Re-run below.
