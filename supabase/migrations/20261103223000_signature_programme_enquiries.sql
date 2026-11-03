-- 20261103223000_signature_programme_enquiries.sql
-- Signature Wellness Programmes (HAYAT-100, AAfiya, FFounders) Schema
-- Separate Service Category from Medical Travel Intake (Governed by docs/knowledge/signature_programmes.md)

create table if not exists public.signature_programme_enquiries (
    enquiry_id uuid primary key default gen_random_uuid(),
    conversation_id uuid not null references public.conversations(id) on delete cascade,
    session_id uuid not null references public.guest_sessions(id) on delete cascade,
    interested_programmes jsonb not null default '[]'::jsonb,
    primary_programme text,
    destination_preference text,
    preferred_region text,
    preferred_travel_period text,
    preferred_month text,
    expected_experience text,
    activity_interests jsonb not null default '[]'::jsonb,
    group_participation boolean not null default false,
    group_size integer,
    budget_range text,
    preferred_contact_method text,
    enquiry_status text not null default 'draft' check (
        enquiry_status in ('draft', 'submitted', 'assigned', 'proposal_exploring', 'closed')
    ),
    contact_consent_status text not null default 'pending' check (
        contact_consent_status in ('pending', 'granted', 'refused')
    ),
    registration_status text not null default 'unregistered' check (
        registration_status in ('unregistered', 'interest_registered')
    ),
    assigned_coordinator_id text,
    coordinator_notes jsonb not null default '[]'::jsonb,
    lead_name text,
    lead_phone text,
    lead_email text,
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now()
);

-- Indices for rapid lookup by conversation, session, and status
create index if not exists idx_signature_programme_enquiries_conversation_id
    on public.signature_programme_enquiries(conversation_id);

create index if not exists idx_signature_programme_enquiries_session_id
    on public.signature_programme_enquiries(session_id);

create index if not exists idx_signature_programme_enquiries_status
    on public.signature_programme_enquiries(enquiry_status);

create index if not exists idx_signature_programme_enquiries_reg_status
    on public.signature_programme_enquiries(registration_status);

-- Enable Row Level Security (RLS)
alter table public.signature_programme_enquiries enable row level security;

-- Service role has full administrative access
drop policy if exists "service_role_all_signature_programme_enquiries" on public.signature_programme_enquiries;
create policy "service_role_all_signature_programme_enquiries"
    on public.signature_programme_enquiries
    for all
    to service_role
    using (true)
    with check (true);

-- Authenticated coordinators can view and update enquiries
drop policy if exists "coordinator_read_signature_programme_enquiries" on public.signature_programme_enquiries;
create policy "coordinator_read_signature_programme_enquiries"
    on public.signature_programme_enquiries
    for select
    to authenticated
    using (true);

drop policy if exists "coordinator_update_signature_programme_enquiries" on public.signature_programme_enquiries;
create policy "coordinator_update_signature_programme_enquiries"
    on public.signature_programme_enquiries
    for update
    to authenticated
    using (true)
    with check (true);
