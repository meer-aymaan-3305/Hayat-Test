# HAYAT — Knowledge Storage Migration Plan

## Current state (✅ verified in code)
- `data/knowledge/` local FS: `index.json` + per-doc chunk files.
- SHA-256 dedup, versioning, atomic index writes, startup reload,
  lock-serialized mutations.
- Single-instance only: redeploy loses data unless volume-mounted;
  multi-instance would diverge.

## Process-local vs durable
| State | Location | Durable? |
|---|---|---|
| Document bytes+chunks | `data/knowledge/*.json` | FS only |
| Upload metadata | `index.json` | FS only |
| KnowledgeRetriever index | memory, rebuilt at startup | derived |

## Target design (requires approval — NOT implemented)
Object storage (Cloudflare R2 or Supabase Storage):
- `PUT /v1/knowledge/documents` → validate → extract → chunk →
  upload `docs/{doc_id}/v{n}/chunks.json` + `index.json` manifest to bucket.
- Startup: download manifest + chunks → rebuild retriever.
- Preserve: SHA-256 dedup (hash of bytes), version increment on re-upload,
  `SourceReference(document_id, title, version)` attribution.
- Segregation unchanged: visitor attachments NEVER enter this bucket path.
- No clinical-document processing — flag-gated as today.

## Migration steps (when approved)
1. Add storage backend interface (`KnowledgeStore` already isolates FS —
   add `R2KnowledgeStore`/`SupabaseKnowledgeStore` implementing same API).
2. One-time export: upload existing `data/knowledge` content to bucket.
3. Switch `KNOWLEDGE_DIR`→`KNOWLEDGE_BACKEND` env; keep FS fallback for dev.
4. Tests: dedup/versioning/attribution/restart-reload parity suite.

## Until then
Staging single-instance with persistent volume is acceptable; document
that knowledge is ephemeral otherwise.
