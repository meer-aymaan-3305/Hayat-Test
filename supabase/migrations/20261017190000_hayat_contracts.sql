-- Active: 1752295713555@@127.0.0.1@3306
-- Hayat persistence contracts. Application writes use the server-side service role.
create extension if not exists vector;

create table if not exists public.guest_sessions (
  id uuid primary key default gen_random_uuid(),
  owner_id uuid references auth.users(id) on delete set null,
  token_hash text not null,
  locale text not null default 'en',
  client_metadata jsonb not null default '{}'::jsonb,
  expires_at timestamptz,
  created_at timestamptz not null default now()
);
create table if not exists public.conversations (
  id uuid primary key default gen_random_uuid(),
  guest_session_id uuid not null references public.guest_sessions(id) on delete cascade,
  owner_id uuid references auth.users(id) on delete set null,
  title text,
  status text not null default 'active' check (status in ('active','closed')),
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);
create table if not exists public.messages (
  id uuid primary key default gen_random_uuid(),
  conversation_id uuid not null references public.conversations(id) on delete cascade,
  owner_id uuid references auth.users(id) on delete set null,
  role text not null check (role in ('user','assistant','system')),
  content text not null check (char_length(content) between 1 and 8000),
  language text not null default 'en',
  sequence integer not null,
  source_references jsonb not null default '[]'::jsonb,
  created_at timestamptz not null default now()
);
create table if not exists public.consent_records (
  id uuid primary key default gen_random_uuid(),
  guest_session_id uuid not null references public.guest_sessions(id) on delete cascade,
  owner_id uuid references auth.users(id) on delete set null,
  consent_type text not null,
  granted boolean not null,
  policy_version text not null,
  recorded_at timestamptz not null default now()
);
create table if not exists public.case_facts (
  id uuid primary key default gen_random_uuid(),
  conversation_id uuid not null references public.conversations(id) on delete cascade,
  owner_id uuid references auth.users(id) on delete set null,
  facts jsonb not null,
  version integer not null default 1 check (version > 0),
  captured_at timestamptz not null default now()
);
create table if not exists public.audit_events (
  id uuid primary key default gen_random_uuid(),
  owner_id uuid references auth.users(id) on delete set null,
  actor_id uuid references auth.users(id) on delete set null,
  event_type text not null,
  payload jsonb not null default '{}'::jsonb,
  created_at timestamptz not null default now()
);
create table if not exists public.knowledge_documents (
  id uuid primary key default gen_random_uuid(),
  owner_id uuid references auth.users(id) on delete set null,
  title text not null,
  uri text,
  metadata jsonb not null default '{}'::jsonb,
  created_at timestamptz not null default now()
);
create table if not exists public.knowledge_chunks (
  id uuid primary key default gen_random_uuid(),
  document_id uuid not null references public.knowledge_documents(id) on delete cascade,
  owner_id uuid references auth.users(id) on delete set null,
  content text not null,
  embedding vector(1536),
  chunk_index integer not null check (chunk_index >= 0),
  created_at timestamptz not null default now()
);

-- Upgrade installations that created these tables before owner-scoped RLS
-- was introduced. CREATE TABLE IF NOT EXISTS does not add missing columns.
do $$
declare table_name text;
begin
  foreach table_name in array array[
    'guest_sessions','conversations','messages','consent_records','case_facts',
    'audit_events','knowledge_documents','knowledge_chunks'
  ] loop
    execute format(
      'alter table public.%I add column if not exists owner_id uuid references auth.users(id) on delete set null',
      table_name
    );
  end loop;
end $$;

-- Default deny is retained for anonymous clients; authenticated access is owner-scoped.
do $$
declare table_name text;
begin
  foreach table_name in array array[
    'guest_sessions','conversations','messages','consent_records','case_facts',
    'audit_events','knowledge_documents','knowledge_chunks'
  ] loop
    execute format('alter table public.%I enable row level security', table_name);
    execute format('drop policy if exists owner_select on public.%I', table_name);
    execute format('drop policy if exists owner_insert on public.%I', table_name);
    execute format('drop policy if exists owner_update on public.%I', table_name);
    execute format('create policy owner_select on public.%I for select to authenticated using (owner_id = (select auth.uid()))', table_name);
    execute format('create policy owner_insert on public.%I for insert to authenticated with check (owner_id = (select auth.uid()))', table_name);
    execute format('create policy owner_update on public.%I for update to authenticated using (owner_id = (select auth.uid())) with check (owner_id = (select auth.uid()))', table_name);
  end loop;
end $$;
