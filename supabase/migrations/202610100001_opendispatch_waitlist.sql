create table public.opend_dispatch_waitlist_signups (
  id uuid primary key default gen_random_uuid(),
  spot integer not null unique check (spot > 0),
  email text not null check (email = lower(btrim(email))),
  name text,
  company text,
  trade text,
  crew_size text,
  plan text not null default 'undecided'
    check (plan in ('hosted_monthly', 'annual', 'perpetual', 'self_hosted', 'undecided')),
  current_tool text,
  region text,
  created_at timestamptz not null default now()
);

create unique index uq_opendispatch_waitlist_email_lower
  on public.opend_dispatch_waitlist_signups (lower(email));

alter table public.opend_dispatch_waitlist_signups enable row level security;
revoke all on table public.opend_dispatch_waitlist_signups from anon, authenticated;
grant select, insert, update on table public.opend_dispatch_waitlist_signups to service_role;

create table public.opend_dispatch_waitlist_rate_limits (
  subject_hash text not null,
  bucket_start timestamptz not null,
  hits integer not null check (hits > 0),
  primary key (subject_hash, bucket_start)
);

alter table public.opend_dispatch_waitlist_rate_limits enable row level security;
revoke all on table public.opend_dispatch_waitlist_rate_limits from anon, authenticated;
grant select, insert, update, delete on table public.opend_dispatch_waitlist_rate_limits to service_role;

create or replace function public.opend_dispatch_waitlist_consume_rate_limit(
  p_subject_hash text,
  p_limit integer default 3
) returns boolean
language plpgsql
security invoker
set search_path = ''
as $$
declare
  v_bucket timestamptz := date_trunc('hour', pg_catalog.now());
  v_hits integer;
begin
  insert into public.opend_dispatch_waitlist_rate_limits (subject_hash, bucket_start, hits)
  values (p_subject_hash, v_bucket, 1)
  on conflict (subject_hash, bucket_start)
  do update set hits = public.opend_dispatch_waitlist_rate_limits.hits + 1
  returning hits into v_hits;

  -- Keep the small limiter table bounded without exposing any client-side cleanup path.
  delete from public.opend_dispatch_waitlist_rate_limits
   where bucket_start < v_bucket - interval '24 hours';

  return v_hits <= p_limit;
end;
$$;

create or replace function public.opend_dispatch_waitlist_status()
returns jsonb
language sql
security invoker
set search_path = ''
as $$
  select pg_catalog.jsonb_build_object(
    'founding_spots', 100,
    'spots_left', greatest(0, 100 - count(*))::integer,
    'launch', 'Winter 2027'
  )
  from public.opend_dispatch_waitlist_signups;
$$;

create or replace function public.opend_dispatch_waitlist_join(
  p_email text,
  p_name text default null,
  p_company text default null,
  p_trade text default null,
  p_crew_size text default null,
  p_plan text default 'undecided',
  p_current_tool text default null,
  p_region text default null
) returns jsonb
language plpgsql
security invoker
set search_path = ''
as $$
declare
  v_signup public.opend_dispatch_waitlist_signups%rowtype;
  v_spot integer;
  v_total integer;
  v_existing boolean := false;
begin
  perform pg_catalog.pg_advisory_xact_lock(1937010540);

  select * into v_signup
    from public.opend_dispatch_waitlist_signups
   where email = pg_catalog.lower(pg_catalog.btrim(p_email));

  if found then
    v_existing := true;
  else
    select coalesce(max(spot), 0) + 1 into v_spot
      from public.opend_dispatch_waitlist_signups;

    insert into public.opend_dispatch_waitlist_signups (
      spot, email, name, company, trade, crew_size, plan, current_tool, region
    ) values (
      v_spot,
      pg_catalog.lower(pg_catalog.btrim(p_email)),
      nullif(pg_catalog.btrim(coalesce(p_name, '')), ''),
      nullif(pg_catalog.btrim(coalesce(p_company, '')), ''),
      nullif(pg_catalog.btrim(coalesce(p_trade, '')), ''),
      nullif(pg_catalog.btrim(coalesce(p_crew_size, '')), ''),
      p_plan,
      nullif(pg_catalog.btrim(coalesce(p_current_tool, '')), ''),
      nullif(pg_catalog.btrim(coalesce(p_region, '')), '')
    ) returning * into v_signup;
  end if;

  select count(*)::integer into v_total from public.opend_dispatch_waitlist_signups;
  return pg_catalog.jsonb_build_object(
    'spot', v_signup.spot,
    'is_founding', v_signup.spot <= 100,
    'already_on_list', v_existing,
    'spots_left', greatest(0, 100 - v_total)
  );
end;
$$;

revoke all on function public.opend_dispatch_waitlist_consume_rate_limit(text, integer) from public, anon, authenticated;
revoke all on function public.opend_dispatch_waitlist_status() from public, anon, authenticated;
revoke all on function public.opend_dispatch_waitlist_join(text, text, text, text, text, text, text, text) from public, anon, authenticated;
grant execute on function public.opend_dispatch_waitlist_consume_rate_limit(text, integer) to service_role;
grant execute on function public.opend_dispatch_waitlist_status() to service_role;
grant execute on function public.opend_dispatch_waitlist_join(text, text, text, text, text, text, text, text) to service_role;
