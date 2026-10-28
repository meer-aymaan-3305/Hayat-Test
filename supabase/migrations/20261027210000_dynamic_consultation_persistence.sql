-- Keep the database state contract aligned with the runtime orchestration policy.
alter table public.conversations
  drop constraint if exists conversations_state_check;

alter table public.conversations
  add constraint conversations_state_check check (state in (
    'exploring', 'discovering_needs', 'answering_questions',
    'offering_consultation', 'collecting_details', 'awaiting_consent',
    'ready_for_submission', 'requested', 'awaiting_details',
    'awaiting_verification', 'pending_coordinator_confirmation',
    'confirmed', 'cancelled', 'escalated', 'completed'
  ));

-- Chat turns append a canonical snapshot so the current profile can be restored
-- independently of the append-only extraction history.
create index if not exists case_facts_conversation_version_idx
  on public.case_facts (conversation_id, version desc);

create index if not exists leads_conversation_idx
  on public.leads (conversation_id);

create index if not exists phone_verifications_lead_status_idx
  on public.phone_verifications (lead_id, status);
