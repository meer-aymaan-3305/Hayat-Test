-- Brings the LIVE Supabase project's older tables up to what the code expects.
-- Written 2026-11-08 after comparing the live table list with supabase/migrations.
--
-- STATUS (checked 2026-11-09): already applied to the live project, together with
-- every file in supabase/migrations. Do not run it again there; it would change nothing.
--
-- Only for a project that still has the OLD table layout: run this first, then the
-- files in supabase/migrations in timestamp order. A brand-new, empty project
-- skips this script and runs only the migration files.
--
-- Safe by design:
--   * Only adds columns. Nothing is dropped, renamed or rewritten.
--   * Columns that must be filled in (NOT NULL, no default) are only added to tables
--     that are empty. If one of them has rows, the whole script stops and changes nothing.
--   * It runs in one transaction: all of it applies, or none of it does.
--
-- Row counts when checked: guest_sessions 65, conversations 66, messages 339, case_facts 38,
-- leads 2. consent_records, case_fact_versions, audit_events, knowledge_documents: 0.

begin;

-- Running it again is harmless: a table only has to be empty while one of its
-- required columns is still missing. Once the columns exist, rows are fine.
do $$
declare
  target record;
  n bigint;
begin
  for target in
    select * from (values
      ('consent_records', 'consent_type'),
      ('consent_records', 'granted'),
      ('consent_records', 'policy_version')
    ) as required(table_name, column_name)
  loop
    if not exists (
      select 1 from information_schema.columns
      where table_schema = 'public'
        and table_name = target.table_name
        and column_name = target.column_name
    ) then
      execute format('select count(*) from public.%I', target.table_name) into n;
      if n > 0 then
        raise exception 'Table % has % rows but no % column. Stop and review: this script only adds required columns to empty tables.',
          target.table_name, n, target.column_name;
      end if;
    end if;
  end loop;
end $$;

-- Empty tables: required columns can be added as the code expects them.
alter table public.consent_records
  add column if not exists consent_type text not null,
  add column if not exists granted boolean not null,
  add column if not exists policy_version text not null;

alter table public.case_fact_versions
  add column if not exists version integer not null default 1 check (version > 0),
  add column if not exists extraction_schema_version text not null default 'facts_v1',
  add column if not exists captured_at timestamptz not null default now();

alter table public.audit_events
  add column if not exists payload jsonb not null default '{}'::jsonb,
  add column if not exists actor_id uuid references auth.users(id) on delete set null;

-- Tables with data: only columns that are optional or have a default.
alter table public.conversations add column if not exists state text not null default 'requested';
alter table public.guest_sessions add column if not exists client_metadata jsonb not null default '{}'::jsonb;
alter table public.messages add column if not exists source_references jsonb not null default '[]'::jsonb;
alter table public.leads add column if not exists firebase_uid text;
alter table public.knowledge_documents add column if not exists uri text;

commit;

-- After this, run supabase/migrations/*.sql in order. The two missing tables
-- (coordinator_handoffs, signature_programme_enquiries) are created by files 7 and 8.
--
-- Check afterwards (each should return rows or zero, with no error):
--   select state from public.conversations limit 1;
--   select consent_type from public.consent_records limit 1;
--   select count(*) from public.coordinator_handoffs;
--   select count(*) from public.signature_programme_enquiries;
