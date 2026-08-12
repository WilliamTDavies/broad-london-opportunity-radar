create extension if not exists citext;
create extension if not exists pgcrypto;

create table if not exists public.subscribers (
  id uuid primary key default gen_random_uuid(),
  email citext not null unique,
  status text not null default 'pending' check (status in ('pending', 'confirmed', 'unsubscribed', 'bounced')),
  created_at timestamptz not null default now(),
  confirmed_at timestamptz,
  unsubscribed_at timestamptz,
  confirmation_token_hash text,
  confirmation_expires_at timestamptz,
  unsubscribe_token_hashes text[] not null default '{}',
  last_digest_sent text,
  delivery_failure_status text
);

comment on table public.subscribers is 'Private double-opt-in state; never exposed through a public select policy.';
alter table public.subscribers enable row level security;
revoke all on public.subscribers from anon, authenticated;

create table if not exists public.endpoint_rate_limits (
  key_hash text not null,
  window_started_at timestamptz not null,
  request_count integer not null default 1,
  primary key (key_hash, window_started_at)
);
alter table public.endpoint_rate_limits enable row level security;
revoke all on public.endpoint_rate_limits from anon, authenticated;

create or replace function public.consume_rate_limit(
  request_key_hash text,
  maximum_requests integer default 5,
  window_minutes integer default 60
) returns boolean
language plpgsql
security definer
set search_path = public
as $$
declare
  current_window timestamptz;
  resulting_count integer;
begin
  if window_minutes < 1 then
    raise exception 'window_minutes must be positive';
  end if;
  current_window := to_timestamp(
    floor(extract(epoch from now()) / (window_minutes * 60)) * (window_minutes * 60)
  );
  delete from public.endpoint_rate_limits
    where window_started_at < now() - interval '2 hours';
  insert into public.endpoint_rate_limits(key_hash, window_started_at, request_count)
  values (request_key_hash, current_window, 1)
  on conflict (key_hash, window_started_at)
  do update set request_count = endpoint_rate_limits.request_count + 1
  returning request_count into resulting_count;
  return resulting_count <= maximum_requests;
end;
$$;

create or replace function public.begin_subscription(
  subscriber_email citext,
  new_confirmation_hash text,
  new_confirmation_expiry timestamptz
) returns boolean
language plpgsql
security definer
set search_path = public
as $$
declare
  changed boolean := false;
begin
  insert into public.subscribers(
    email,
    status,
    confirmation_token_hash,
    confirmation_expires_at,
    delivery_failure_status
  ) values (
    subscriber_email,
    'pending',
    new_confirmation_hash,
    new_confirmation_expiry,
    null
  )
  on conflict (email) do update
  set status = 'pending',
      created_at = now(),
      confirmed_at = null,
      confirmation_token_hash = excluded.confirmation_token_hash,
      confirmation_expires_at = excluded.confirmation_expires_at,
      unsubscribed_at = null,
      delivery_failure_status = null
  where subscribers.status in ('unsubscribed', 'bounced')
     or (
       subscribers.status = 'pending'
       and (
         subscribers.confirmation_expires_at is null
         or subscribers.confirmation_expires_at < now()
       )
     )
  returning true into changed;
  return coalesce(changed, false);
end;
$$;

create or replace function public.prune_subscription_state() returns integer
language plpgsql
security definer
set search_path = public
as $$
declare
  deleted_count integer;
begin
  delete from public.subscribers
  where status = 'pending' and created_at < now() - interval '30 days';
  get diagnostics deleted_count = row_count;
  delete from public.endpoint_rate_limits
  where window_started_at < now() - interval '2 hours';
  return deleted_count;
end;
$$;

create or replace function public.add_unsubscribe_token(
  subscriber_email citext,
  new_token_hash text
) returns void
language sql
security definer
set search_path = public
as $$
  update public.subscribers
  set unsubscribe_token_hashes = (
    select array_agg(value order by ordinal)
    from unnest((unsubscribe_token_hashes || new_token_hash)[greatest(1, array_length(unsubscribe_token_hashes || new_token_hash, 1) - 19):])
      with ordinality as tokens(value, ordinal)
  )
  where email = subscriber_email and status = 'confirmed';
$$;

revoke all on function public.consume_rate_limit(text, integer, integer) from public, anon, authenticated;
revoke all on function public.begin_subscription(citext, text, timestamptz) from public, anon, authenticated;
revoke all on function public.prune_subscription_state() from public, anon, authenticated;
revoke all on function public.add_unsubscribe_token(citext, text) from public, anon, authenticated;
grant execute on function public.consume_rate_limit(text, integer, integer) to service_role;
grant execute on function public.begin_subscription(citext, text, timestamptz) to service_role;
grant execute on function public.prune_subscription_state() to service_role;
grant execute on function public.add_unsubscribe_token(citext, text) to service_role;
