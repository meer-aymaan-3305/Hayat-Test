-- 20261103210000_coordinator_handoffs.sql
-- Coordinator-Led Consultation Handoff Schema
-- Governed by: HAYAT_Guardrail_Document_v1.docx (CP-2, CP-5, CP-7, HB-8, DP-7)

create table if not exists public.coordinator_handoffs (
    id uuid primary key default gen_random_uuid(),
    conversation_id uuid not null references public.conversations(id) on delete cascade,
    session_id uuid not null references public.guest_sessions(id) on delete cascade,
    status text not null default 'awaiting_registration' check (
        status in (
            'awaiting_registration',
            'awaiting_coordinator',
            'coordinator_assigned',
            'contact_pending',
            'coordinator_contacted',
            'appointment_coordination',
            'appointment_confirmed',
            'handoff_closed'
        )
    ),
    assigned_coordinator_id text,
    assigned_coordinator_name text,
    coordinator_role text check (
        coordinator_role is null or coordinator_role in ('wellness_curator', 'case_manager', 'lead_coordinator')
    ),
    case_summary jsonb not null default '{}'::jsonb,
    contact_channel text,
    user_contact_authorized boolean not null default false,
    cp5_consent_verified boolean not null default false,
    registered_user_verified boolean not null default false,
    appointment_details jsonb,
    coordinator_notes jsonb not null default '[]'::jsonb,
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now()
);

-- Indices for rapid lookup by conversation and coordinator workflow status
create index if not exists idx_coordinator_handoffs_conversation_id
    on public.coordinator_handoffs(conversation_id);

create index if not exists idx_coordinator_handoffs_session_id
    on public.coordinator_handoffs(session_id);

create index if not exists idx_coordinator_handoffs_status
    on public.coordinator_handoffs(status);

-- Enable Row Level Security (RLS)
alter table public.coordinator_handoffs enable row level security;

-- Service role has full administrative access
drop policy if exists "Service role manages coordinator handoffs" on public.coordinator_handoffs;
create policy "Service role manages coordinator handoffs"
    on public.coordinator_handoffs
    for all
    to service_role
    using (true)
    with check (true);

-- Authenticated coordinators can view and update handoffs
drop policy if exists "Authorized coordinators can view handoffs" on public.coordinator_handoffs;
create policy "Authorized coordinators can view handoffs"
    on public.coordinator_handoffs
    for select
    to authenticated
    using (auth.jwt() ->> 'role' in ('coordinator', 'case_manager', 'wellness_curator', 'service_role'));

drop policy if exists "Authorized coordinators can update handoff progress" on public.coordinator_handoffs;
create policy "Authorized coordinators can update handoff progress"
    on public.coordinator_handoffs
    for update
    to authenticated
    using (auth.jwt() ->> 'role' in ('coordinator', 'case_manager', 'wellness_curator', 'service_role'))
    with check (auth.jwt() ->> 'role' in ('coordinator', 'case_manager', 'wellness_curator', 'service_role'));
