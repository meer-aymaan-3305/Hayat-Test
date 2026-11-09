-- Post-migration alignment fixes applied to the live project after running
-- the 2026-11 migrations. The live tables predated parts of the contract:
-- case_fact_versions still carried a legacy NOT NULL version_number that the
-- hayat_upsert_case_facts RPC does not populate, and
-- signature_programme_enquiries lacked the columns the
-- SignatureProgrammeEnquiry model upserts (current_stage, reference_code).

alter table public.case_fact_versions
  alter column version_number drop not null;

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
alter table public.case_fact_versions
  alter column schema_version drop not null,
  alter column validation_status drop not null;

alter table public.consent_records
  alter column conversation_id drop not null,
  alter column purpose drop not null,
  alter column consent_status drop not null,
  alter column consent_version drop not null;
