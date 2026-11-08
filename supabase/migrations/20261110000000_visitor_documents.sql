-- Visitor medical document metadata.
-- Stores ownership, processing status and extracted text references for
-- visitor-uploaded documents. File bytes live on private backend storage;
-- this table holds metadata + extracted text only. Service-role only —
-- anon/authenticated roles can never reach it. Idempotent, non-destructive.
-- Apply only to confirmed staging after backup. Requires separate
-- privacy/compliance approval before any production enablement.

create table if not exists public.visitor_documents (
    id uuid primary key,
    session_id uuid not null
        references public.guest_sessions(id) on delete cascade,
    conversation_id uuid not null
        references public.conversations(id) on delete cascade,
    filename text not null,
    media_type text not null,
    size_bytes bigint not null check (size_bytes >= 0),
    status text not null default 'uploaded'
        check (status in ('uploaded','processed','needs_clearer_upload',
                          'failed','deleted')),
    extraction_method text,
    page_count integer,
    confidence text check (confidence in ('high','low') or confidence is null),
    extracted_chars integer not null default 0,
    extracted_text text,
    storage_path text,
    consent_version text,
    created_at timestamptz not null,
    processed_at timestamptz,
    deleted_at timestamptz
);

create index if not exists visitor_documents_session_idx
    on public.visitor_documents (session_id);
create index if not exists visitor_documents_conversation_idx
    on public.visitor_documents (conversation_id);

alter table public.visitor_documents enable row level security;

drop policy if exists "Service role manages visitor documents"
    on public.visitor_documents;
create policy "Service role manages visitor documents"
    on public.visitor_documents
    for all
    to service_role
    using (true)
    with check (true);

-- No anon/authenticated policies: visitor documents are reachable only
-- through the backend's service-role client after session authorization.
grant select, insert, update, delete on public.visitor_documents
    to service_role;
revoke all on public.visitor_documents from anon, authenticated;
