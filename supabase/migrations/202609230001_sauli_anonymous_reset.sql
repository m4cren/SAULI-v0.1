-- SAULI anonymous prototype database reset
-- Version: 2026-09-23
--
-- WARNING: This migration permanently deletes all records in the prior SAULI
-- prototype tables. It intentionally does NOT drop the entire public schema,
-- Supabase Auth, or Supabase-managed schemas.
--
-- Storage note:
-- Supabase files must be deleted through the Storage API or Dashboard, not by
-- deleting rows from storage.objects. If you want to remove files from the old
-- `found-item-images` bucket, empty and delete that bucket in Storage first.
-- This migration creates/updates a new private bucket: `sauli-item-images`.

begin;

create extension if not exists pgcrypto;
create extension if not exists pg_trgm;

-- ---------------------------------------------------------------------------
-- Remove only objects owned by the previous SAULI prototype.
-- CASCADE removes the old SAULI triggers, indexes, and dependent functions.
-- ---------------------------------------------------------------------------

drop table if exists public.retrieval_events cascade;
drop table if exists public.match_results cascade;
drop table if exists public.search_requests cascade;
drop table if exists public.found_items cascade;

drop function if exists public.complete_simulated_retrieval(uuid, uuid, numeric, jsonb);
drop function if exists public.complete_simulated_retrieval(uuid, uuid, uuid);
drop function if exists public.get_eligible_found_items(timestamptz, integer);
drop function if exists public.set_updated_at();
drop function if exists public.set_sauli_updated_at();
drop function if exists public.generate_sauli_item_code();
drop function if exists public.sauli_normalize_text(text);

drop sequence if exists public.sauli_item_code_seq cascade;

-- ---------------------------------------------------------------------------
-- Shared helpers
-- ---------------------------------------------------------------------------

create sequence public.sauli_item_code_seq start with 1 increment by 1;

create function public.generate_sauli_item_code()
returns text
language sql
volatile
set search_path = ''
as $$
  select
    'SL-'
    || to_char(timezone('Asia/Manila', now()), 'YYYYMMDD')
    || '-'
    || lpad(nextval('public.sauli_item_code_seq'::regclass)::text, 6, '0');
$$;

create function public.sauli_normalize_text(p_value text)
returns text
language sql
immutable
set search_path = ''
as $$
  select regexp_replace(lower(trim(coalesce(p_value, ''))), '[[:space:]]+', ' ', 'g');
$$;

create function public.set_sauli_updated_at()
returns trigger
language plpgsql
set search_path = ''
as $$
begin
  new.updated_at = now();
  return new;
end;
$$;

-- ---------------------------------------------------------------------------
-- Found items submitted through the simulated hardware station
-- ---------------------------------------------------------------------------

create table public.found_items (
  id uuid primary key default gen_random_uuid(),
  item_code text not null unique default public.generate_sauli_item_code(),
  idempotency_key uuid not null unique,

  status text not null default 'available'
    check (status in ('available', 'retrieved')),

  found_location text not null
    check (length(trim(found_location)) between 2 and 300),
  found_location_normalized text generated always as
    (public.sauli_normalize_text(found_location)) stored,

  -- FastAPI supplies the authoritative server timestamp. Values are stored as UTC.
  found_at timestamptz not null default now(),

  -- Paths in the private `sauli-item-images` bucket, never permanent URLs.
  front_image_path text not null unique,
  back_image_path text not null unique,

  -- Searchable fields extracted from the complete validated local-AI response.
  views_consistent boolean,
  generic_name text,
  object_name text,
  alternative_names text[] not null default array[]::text[],
  object_count integer check (object_count is null or object_count > 0),
  category text,
  subcategory text,
  colors text[] not null default array[]::text[],
  materials text[] not null default array[]::text[],
  brand text,
  model_or_variant text,
  visible_markings text[] not null default array[]::text[],
  functional_components text[] not null default array[]::text[],
  condition text,
  condition_details text[] not null default array[]::text[],
  patterns text[] not null default array[]::text[],
  distinctive_features text[] not null default array[]::text[],
  likely_use text,
  short_description text,
  extraction_summary text,
  confidence text check (confidence is null or confidence in ('high', 'medium', 'low')),
  needs_review boolean not null default false,

  analysis_model text not null,
  analysis_duration_ms integer check (
    analysis_duration_ms is null or analysis_duration_ms >= 0
  ),
  analysis_json jsonb not null
    check (jsonb_typeof(analysis_json) = 'object'),

  -- FastAPI builds this denormalized document for deterministic pre-ranking.
  search_document text not null default '',

  -- Demonstration only; this is not a real hardware compartment assignment.
  prototype_compartment text not null default 'C3',

  retrieved_at timestamptz,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),

  constraint found_items_retrieval_state_check check (
    (status = 'available' and retrieved_at is null)
    or
    (status = 'retrieved' and retrieved_at is not null)
  )
);

comment on table public.found_items is
  'Found-item records created anonymously by the simulated SAULI station.';

-- ---------------------------------------------------------------------------
-- Anonymous retriever searches
-- No Supabase Auth user ID is stored or required.
-- ---------------------------------------------------------------------------

create table public.search_requests (
  id uuid primary key default gen_random_uuid(),
  anonymous_session_id uuid not null,
  idempotency_key uuid not null unique,

  description text not null
    check (length(trim(description)) between 3 and 2000),
  last_seen_location text not null
    check (length(trim(last_seen_location)) between 2 and 300),
  last_seen_location_normalized text generated always as
    (public.sauli_normalize_text(last_seen_location)) stored,
  last_seen_at timestamptz not null,

  category_filter text,
  primary_color_filter text,
  brand_filter text,

  -- Optional path in the same private bucket.
  query_image_path text,
  query_analysis_json jsonb
    check (query_analysis_json is null or jsonb_typeof(query_analysis_json) = 'object'),

  processing_status text not null default 'processing'
    check (processing_status in ('processing', 'completed', 'failed')),
  result_count integer not null default 0 check (result_count >= 0),
  error_message text,

  created_at timestamptz not null default now(),
  completed_at timestamptz,

  constraint search_requests_completion_check check (
    (processing_status = 'processing' and completed_at is null)
    or
    (processing_status in ('completed', 'failed') and completed_at is not null)
  )
);

comment on table public.search_requests is
  'Anonymous lost-item searches submitted through FastAPI.';

-- ---------------------------------------------------------------------------
-- Auditable candidate scores
-- Only temporally eligible candidates should be inserted here.
-- ---------------------------------------------------------------------------

create table public.match_results (
  id uuid primary key default gen_random_uuid(),
  search_request_id uuid not null
    references public.search_requests(id) on delete cascade,
  found_item_id uuid not null
    references public.found_items(id) on delete cascade,

  rank integer not null check (rank > 0),
  eligible boolean not null default true,

  ai_similarity_score numeric(6, 3) not null
    check (ai_similarity_score between 0 and 100),
  deterministic_feature_score numeric(6, 3) not null
    check (deterministic_feature_score between 0 and 100),
  location_score numeric(6, 3) not null
    check (location_score between 0 and 100),
  time_proximity_score numeric(6, 3) not null
    check (time_proximity_score between 0 and 100),
  final_score numeric(6, 3) not null
    check (final_score between 0 and 100),

  matched_features text[] not null default array[]::text[],
  conflicting_features text[] not null default array[]::text[],
  explanation text not null default '',
  needs_review boolean not null default false,
  ai_model text not null,
  score_breakdown jsonb not null default '{}'::jsonb
    check (jsonb_typeof(score_breakdown) = 'object'),
  ai_match_json jsonb not null default '{}'::jsonb
    check (jsonb_typeof(ai_match_json) = 'object'),

  created_at timestamptz not null default now(),

  unique (search_request_id, found_item_id),
  unique (search_request_id, rank)
);

comment on table public.match_results is
  'Hybrid deterministic and local-Qwen match scores for anonymous searches.';

-- ---------------------------------------------------------------------------
-- Completed prototype retrievals
-- ---------------------------------------------------------------------------

create table public.retrieval_events (
  id uuid primary key default gen_random_uuid(),
  found_item_id uuid not null
    references public.found_items(id) on delete restrict,
  search_request_id uuid not null
    references public.search_requests(id) on delete restrict,
  anonymous_session_id uuid not null,

  prototype_pass_id uuid not null unique default gen_random_uuid(),
  prototype_compartment text not null default 'C3',
  retriever_label text not null default 'Anonymous retriever',

  final_match_score numeric(6, 3) not null
    check (final_match_score between 0 and 100),
  score_breakdown jsonb not null default '{}'::jsonb
    check (jsonb_typeof(score_breakdown) = 'object'),
  item_snapshot jsonb not null
    check (jsonb_typeof(item_snapshot) = 'object'),

  qr_simulated boolean not null default true
    check (qr_simulated = true),
  retrieved_at timestamptz not null default now(),
  created_at timestamptz not null default now(),

  -- A found item can only be retrieved once.
  unique (found_item_id)
);

comment on table public.retrieval_events is
  'Anonymous, simulated retrieval audit events; no real QR or lock action occurs.';

-- ---------------------------------------------------------------------------
-- Triggers and indexes
-- ---------------------------------------------------------------------------

create trigger found_items_set_updated_at
before update on public.found_items
for each row
execute function public.set_sauli_updated_at();

create index found_items_status_found_at_idx
  on public.found_items (status, found_at desc);

create index found_items_category_subcategory_idx
  on public.found_items (category, subcategory);

create index found_items_location_trgm_idx
  on public.found_items
  using gin (found_location_normalized gin_trgm_ops);

create index found_items_search_document_trgm_idx
  on public.found_items
  using gin (search_document gin_trgm_ops);

create index found_items_colors_gin_idx
  on public.found_items using gin (colors);

create index found_items_features_gin_idx
  on public.found_items using gin (distinctive_features);

create index found_items_analysis_gin_idx
  on public.found_items using gin (analysis_json jsonb_path_ops);

create index search_requests_session_created_idx
  on public.search_requests (anonymous_session_id, created_at desc);

create index search_requests_last_seen_idx
  on public.search_requests (last_seen_at desc);

create index match_results_search_score_idx
  on public.match_results (search_request_id, final_score desc);

create index retrieval_events_session_time_idx
  on public.retrieval_events (anonymous_session_id, retrieved_at desc);

-- ---------------------------------------------------------------------------
-- Mandatory temporal filter
-- A found item is eligible only when found_at >= the reported last_seen_at.
-- Local AI is never allowed to override this rule.
-- ---------------------------------------------------------------------------

create function public.get_eligible_found_items(
  p_last_seen_at timestamptz,
  p_limit integer default 50
)
returns setof public.found_items
language sql
stable
security invoker
set search_path = ''
as $$
  select item.*
  from public.found_items as item
  where item.status = 'available'
    and item.found_at >= p_last_seen_at
  order by item.found_at asc
  limit least(greatest(coalesce(p_limit, 50), 1), 100);
$$;

-- ---------------------------------------------------------------------------
-- Atomic anonymous prototype retrieval
-- The score is read from match_results rather than trusted from the browser.
-- ---------------------------------------------------------------------------

create function public.complete_simulated_retrieval(
  p_found_item_id uuid,
  p_search_request_id uuid,
  p_anonymous_session_id uuid
)
returns table (
  retrieval_event_id uuid,
  prototype_pass_id uuid,
  retrieved_at timestamptz
)
language plpgsql
security definer
set search_path = ''
as $$
declare
  v_item public.found_items%rowtype;
  v_match public.match_results%rowtype;
  v_event public.retrieval_events%rowtype;
begin
  select result.*
  into v_match
  from public.match_results as result
  join public.search_requests as request
    on request.id = result.search_request_id
  where result.search_request_id = p_search_request_id
    and result.found_item_id = p_found_item_id
    and result.eligible = true
    and request.anonymous_session_id = p_anonymous_session_id;

  if not found then
    raise exception 'No eligible match exists for this anonymous search and item';
  end if;

  select item.*
  into v_item
  from public.found_items as item
  where item.id = p_found_item_id
  for update;

  if not found then
    raise exception 'Found item does not exist';
  end if;

  if v_item.status <> 'available' then
    raise exception 'Item has already been retrieved';
  end if;

  update public.found_items
  set status = 'retrieved',
      retrieved_at = now()
  where id = p_found_item_id;

  insert into public.retrieval_events (
    found_item_id,
    search_request_id,
    anonymous_session_id,
    prototype_compartment,
    final_match_score,
    score_breakdown,
    item_snapshot,
    qr_simulated
  )
  values (
    v_item.id,
    p_search_request_id,
    p_anonymous_session_id,
    v_item.prototype_compartment,
    v_match.final_score,
    v_match.score_breakdown,
    jsonb_build_object(
      'id', v_item.id,
      'item_code', v_item.item_code,
      'generic_name', v_item.generic_name,
      'object_name', v_item.object_name,
      'found_location', v_item.found_location,
      'found_at', v_item.found_at,
      'prototype_compartment', v_item.prototype_compartment
    ),
    true
  )
  returning * into v_event;

  return query
  select v_event.id, v_event.prototype_pass_id, v_event.retrieved_at;
end;
$$;

-- ---------------------------------------------------------------------------
-- Anonymous UI, private database
--
-- There is no Supabase Auth in this prototype. The browser calls FastAPI
-- without login. FastAPI alone uses a server-side Supabase secret key.
-- No Data API access is granted to the anon or authenticated roles.
-- ---------------------------------------------------------------------------

alter table public.found_items enable row level security;
alter table public.search_requests enable row level security;
alter table public.match_results enable row level security;
alter table public.retrieval_events enable row level security;

revoke all on table public.found_items from anon, authenticated;
revoke all on table public.search_requests from anon, authenticated;
revoke all on table public.match_results from anon, authenticated;
revoke all on table public.retrieval_events from anon, authenticated;

revoke all on sequence public.sauli_item_code_seq from public, anon, authenticated;

revoke all on function public.generate_sauli_item_code()
  from public, anon, authenticated;
revoke all on function public.sauli_normalize_text(text)
  from public, anon, authenticated;
revoke all on function public.set_sauli_updated_at()
  from public, anon, authenticated;
revoke all on function public.get_eligible_found_items(timestamptz, integer)
  from public, anon, authenticated;
revoke all on function public.complete_simulated_retrieval(uuid, uuid, uuid)
  from public, anon, authenticated;

grant usage on schema public to service_role;
grant select, insert, update, delete on table public.found_items to service_role;
grant select, insert, update, delete on table public.search_requests to service_role;
grant select, insert, update, delete on table public.match_results to service_role;
grant select, insert, update, delete on table public.retrieval_events to service_role;
grant usage, select on sequence public.sauli_item_code_seq to service_role;
grant execute on function public.generate_sauli_item_code() to service_role;
grant execute on function public.sauli_normalize_text(text) to service_role;
grant execute on function public.set_sauli_updated_at() to service_role;
grant execute on function public.get_eligible_found_items(timestamptz, integer)
  to service_role;
grant execute on function public.complete_simulated_retrieval(uuid, uuid, uuid)
  to service_role;

-- ---------------------------------------------------------------------------
-- Private Storage bucket
-- No storage.objects policy is created. Only FastAPI's server-side secret may
-- upload, download, sign, or delete objects.
-- ---------------------------------------------------------------------------

insert into storage.buckets (
  id,
  name,
  public,
  file_size_limit,
  allowed_mime_types
)
values (
  'sauli-item-images',
  'sauli-item-images',
  false,
  10485760,
  array['image/jpeg', 'image/png', 'image/webp']::text[]
)
on conflict (id) do update
set public = excluded.public,
    file_size_limit = excluded.file_size_limit,
    allowed_mime_types = excluded.allowed_mime_types;

commit;

-- Verification queries:
--
-- select table_name
-- from information_schema.tables
-- where table_schema = 'public'
--   and table_name in (
--     'found_items',
--     'search_requests',
--     'match_results',
--     'retrieval_events'
--   )
-- order by table_name;
--
-- select id, name, public, file_size_limit, allowed_mime_types
-- from storage.buckets
-- where id = 'sauli-item-images';
--
-- select has_table_privilege('anon', 'public.found_items', 'select');
-- Expected: false
