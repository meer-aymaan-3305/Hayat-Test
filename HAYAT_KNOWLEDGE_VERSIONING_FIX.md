# HAYAT — Knowledge Versioning Fix (Defect D1)

Date: 2026-11-08 · Commit pending · Tests: **316/316** (11 new)

## Problem
`POST /v1/knowledge/documents` deduplicated/versioned **by content hash
only**. Changed content under the same title produced a *new* `doc_id` at
v1 while the old version's chunks stayed retrievable → stale + updated
knowledge coexisted.

## Fix — document-addressed updates (additive, contract-preserving)
- New endpoint: **`PUT /v1/knowledge/documents/{document_id}`**
  (multipart `file`, optional `title`). Same service-token authorization.
- `KnowledgeStore.update()`: preserves `document_id`, increments
  `version`, stores `{doc_id}-v{n}.txt`, updates index atomically under
  the existing lock. Extraction runs **before** any index mutation — a
  failed update leaves the previous active version untouched.
- `indexed_chunks()` already reads only the active `version` file →
  retriever serves v(n) only; older `v*.txt` files remain on disk for
  audit/history.
- `POST` upload semantics **unchanged** — identical bytes still dedup to
  same doc_id + version bump; different content still creates a new doc
  (two same-title docs stay independent by design).
- `DELETE` unchanged — removes index entry + all `v*.txt` files.

## API contract delta (frontend/BFF)
| Route | Change |
|---|---|
| `POST /v1/knowledge/documents` | unchanged |
| `GET /v1/knowledge/documents` | unchanged (version now reflects active) |
| **`PUT /v1/knowledge/documents/{id}`** | **NEW** — use for updates |
| `DELETE /v1/knowledge/documents/{id}` | unchanged |

Frontend change required: knowledge-admin "edit" action should call
`PUT …/{document_id}` instead of re-`POST`ing. Re-`POST` of changed
content still creates a separate document (documented behavior, not a
bug — use PUT for updates).

## Regression coverage (tests/test_knowledge_versioning.py)
v1 creation, id-preserving v2, retriever v2-only, v1 file preserved,
same-title independence, identical-content dedup, failed-update safety,
404 on missing, delete-all-versions, restart-active-only, concurrent
update serialization. All PASS.
