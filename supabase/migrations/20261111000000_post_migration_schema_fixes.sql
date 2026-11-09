-- Post-migration alignment fixes applied to the live project after running
-- the 2026-11 migrations. The live tables predated parts of the contract:
-- case_fact_versions still carried a legacy NOT NULL version_number that the
-- hayat_upsert_case_facts RPC does not populate, and
-- signature_programme_enquiries lacked the columns the
-- SignatureProgrammeEnquiry model upserts (current_stage, reference_code).
--
-- Written defensively: every change is guarded so the file is a no-op on a
-- fresh database that never had the legacy columns, and applies the relaxations
-- on databases that did.

alter table public.signature_programme_enquiries
  add column if not exists current_stage text not null default 'discovery',
  add column if not exists reference_code text;

create unique index if not exists signature_programme_enquiries_reference_code_key
  on public.signature_programme_enquiries(reference_code)
  where reference_code is not null;

-- Legacy NOT NULL columns the current code paths do not populate:
-- the hayat_upsert_case_facts RPC writes version/facts/extraction_schema_version
-- only, record_consent writes the new consent columns only, and consent is
-- session-scoped (no conversation_id).
do $$
declare
  fixes text[][] := array[
    ['case_fact_versions', 'version_number'],
    ['case_fact_versions', 'schema_version'],
    ['case_fact_versions', 'validation_status'],
    ['consent_records', 'conversation_id'],
    ['consent_records', 'purpose'],
    ['consent_records', 'consent_status'],
    ['consent_records', 'consent_version']
  ];
  pair text[];
begin
  foreach pair slice 1 in array fixes loop
    if exists (
      select 1 from information_schema.columns
      where table_schema = 'public'
        and table_name = pair[1]
        and column_name = pair[2]
        and is_nullable = 'NO'
    ) then
      execute format(
        'alter table public.%I alter column %I drop not null',
        pair[1], pair[2]
      );
    end if;
  end loop;
end $$;
