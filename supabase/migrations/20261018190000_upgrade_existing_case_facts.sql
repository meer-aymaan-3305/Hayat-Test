-- Upgrade case_facts created by an older deployment.
-- This migration is additive and preserves existing JSONB facts.
alter table public.case_facts
  add column if not exists version integer;

alter table public.case_facts
  add column if not exists captured_at timestamptz;

update public.case_facts
set version = 1
where version is null;

update public.case_facts
set captured_at = now()
where captured_at is null;

alter table public.case_facts
  alter column version set default 1,
  alter column version set not null,
  alter column captured_at set default now(),
  alter column captured_at set not null;

create index if not exists case_facts_conversation_version_idx
  on public.case_facts (conversation_id, version desc);
