-- case_facts is the current profile: one row per conversation.
create unique index if not exists case_facts_conversation_id_key
  on public.case_facts (conversation_id);

create or replace function public.hayat_upsert_case_facts(
  p_conversation_id uuid,
  p_facts jsonb,
  p_changed_facts jsonb
)
returns integer
language plpgsql
security definer
set search_path = public
as $$
declare
  case_facts_row_id uuid;
  current_version integer;
  next_version integer;
begin
  perform 1 from public.conversations
    where id = p_conversation_id
    for update;

  select id, version into case_facts_row_id, current_version
    from public.case_facts
    where conversation_id = p_conversation_id
    for update;

  if current_version is not null
     and (select facts from public.case_facts
          where conversation_id = p_conversation_id) = p_facts then
    return current_version;
  end if;

  select coalesce(max(version), 0) + 1 into next_version
    from public.case_fact_versions
    where case_facts_id = case_facts_row_id;

  insert into public.case_facts (conversation_id, facts, version, captured_at)
  values (p_conversation_id, p_facts, next_version, now())
  on conflict (conversation_id) do update
    set facts = excluded.facts,
        version = excluded.version,
        captured_at = excluded.captured_at;

  select id into case_facts_row_id
    from public.case_facts
    where conversation_id = p_conversation_id;

  insert into public.case_fact_versions (
    case_facts_id, version, facts, extraction_schema_version, captured_at
  )
  values (
    case_facts_row_id, next_version, p_changed_facts,
    'facts_v1', now()
  );

  return next_version;
end;
$$;

revoke all on function public.hayat_upsert_case_facts(uuid, jsonb, jsonb)
  from public, anon, authenticated;
grant execute on function public.hayat_upsert_case_facts(uuid, jsonb, jsonb)
  to service_role;
