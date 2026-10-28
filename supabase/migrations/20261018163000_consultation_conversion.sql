-- Consultation conversion workflow. The backend service role performs
-- ownership checks before writing these tables.
alter table public.guest_sessions
  add column if not exists token_hash text,
  add column if not exists locale text not null default 'en';

alter table public.messages
  add column if not exists language text not null default 'en',
  add column if not exists sequence integer;

create table if not exists public.leads (
  id uuid primary key default gen_random_uuid(),
  conversation_id uuid not null unique references public.conversations(id) on delete cascade,
  name text not null,
  phone_number text not null,
  phone_verified boolean not null default false,
  email text,
  preferred_contact_method text not null,
  care_category text not null,
  details jsonb not null default '{}'::jsonb,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

create table if not exists public.phone_verifications (
  id uuid primary key default gen_random_uuid(),
  lead_id uuid not null references public.leads(id) on delete cascade,
  provider_challenge_id text not null,
  status text not null check (status in ('pending', 'verified', 'failed', 'expired')),
  attempts integer not null default 0,
  created_at timestamptz not null default now(),
  verified_at timestamptz
);

create table if not exists public.consultation_requests (
  id uuid primary key default gen_random_uuid(),
  lead_id uuid not null references public.leads(id) on delete cascade,
  conversation_id uuid not null references public.conversations(id) on delete cascade,
  status text not null default 'pending'
    check (status in ('pending', 'confirmed', 'cancelled')),
  consent_policy_version text not null,
  preferred_dates_times text,
  timezone text,
  coordinator_notes jsonb not null default '{}'::jsonb,
  submitted_at timestamptz not null default now(),
  confirmed_at timestamptz
);

-- Upgrade an older consultation table in place. Nullable additions preserve
-- existing rows; new application writes still provide the required values.
alter table public.leads
  add column if not exists conversation_id uuid,
  add column if not exists name text,
  add column if not exists phone_number text,
  add column if not exists phone_verified boolean not null default false,
  add column if not exists email text,
  add column if not exists preferred_contact_method text,
  add column if not exists care_category text,
  add column if not exists details jsonb not null default '{}'::jsonb,
  add column if not exists updated_at timestamptz not null default now();

alter table public.phone_verifications
  add column if not exists lead_id uuid,
  add column if not exists provider_challenge_id text,
  add column if not exists status text not null default 'pending',
  add column if not exists attempts integer not null default 0,
  add column if not exists verified_at timestamptz;

alter table public.consultation_requests
  add column if not exists lead_id uuid,
  add column if not exists conversation_id uuid,
  add column if not exists status text not null default 'pending',
  add column if not exists consent_policy_version text,
  add column if not exists preferred_dates_times text,
  add column if not exists timezone text,
  add column if not exists coordinator_notes jsonb not null default '{}'::jsonb,
  add column if not exists submitted_at timestamptz not null default now(),
  add column if not exists confirmed_at timestamptz;

-- Repository invariants: opaque tokens are never stored in plaintext and
-- message ordering remains deterministic under concurrent requests.
alter table public.guest_sessions
  add column if not exists token_hash text;
create unique index if not exists guest_sessions_token_hash_idx
  on public.guest_sessions (token_hash)
  where token_hash is not null;

alter table public.messages
  add column if not exists sequence integer;
alter table public.messages
  add column if not exists language text not null default 'en';
update public.messages m
set sequence = numbered.sequence
from (
  select id, row_number() over (partition by conversation_id order by created_at, id)::integer as sequence
  from public.messages
) numbered
where m.id = numbered.id and m.sequence is null;
alter table public.messages alter column sequence set not null;
create unique index if not exists messages_conversation_sequence_idx
  on public.messages (conversation_id, sequence);

alter table public.leads enable row level security;
alter table public.phone_verifications enable row level security;
alter table public.consultation_requests enable row level security;

create index if not exists messages_conversation_created_idx
  on public.messages (conversation_id, created_at, id);
create index if not exists consultation_requests_status_idx
  on public.consultation_requests (status, submitted_at);
