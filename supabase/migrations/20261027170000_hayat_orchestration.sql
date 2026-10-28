-- Structured orchestration state and append-only persona-ready fact history.
alter table public.conversations
  add column if not exists state text not null default 'requested';
alter table public.leads
  add column if not exists firebase_uid text;

do $$
begin
  alter table public.conversations
    add constraint conversations_state_check check (state in (
      'requested', 'awaiting_details', 'awaiting_verification',
      'pending_coordinator_confirmation', 'confirmed', 'cancelled'
    ));
exception when duplicate_object then null;
end $$;

create table if not exists public.case_fact_versions (
  id uuid primary key default gen_random_uuid(),
  case_facts_id uuid not null references public.case_facts(id) on delete cascade,
  version integer not null check (version > 0),
  facts jsonb not null default '[]'::jsonb,
  extraction_schema_version text not null default 'facts_v1',
  captured_at timestamptz not null default now(),
  unique (case_facts_id, version)
);

alter table public.case_fact_versions enable row level security;
drop policy if exists case_fact_versions_owner_select
  on public.case_fact_versions;
create policy case_fact_versions_owner_select
  on public.case_fact_versions for select to authenticated
  using (exists (
    select 1
    from public.case_facts as cf
    join public.conversations as c
      on c.id = cf.conversation_id
    where cf.id = case_fact_versions.case_facts_id
      and c.owner_id = (select auth.uid())
  ));

drop policy if exists case_fact_versions_owner_insert
  on public.case_fact_versions;
create policy case_fact_versions_owner_insert
  on public.case_fact_versions for insert to authenticated
  with check (exists (
    select 1
    from public.case_facts as cf
    join public.conversations as c
      on c.id = cf.conversation_id
    where cf.id = case_fact_versions.case_facts_id
      and c.owner_id = (select auth.uid())
  ));

drop index if exists public.case_fact_versions_conversation_idx;
create index if not exists case_fact_versions_case_facts_idx
  on public.case_fact_versions (case_facts_id, version desc);
