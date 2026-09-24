-- Run after SAULI_Anonymous_Reset.sql as the database owner.
-- Every fixture is rolled back; Storage objects are never created or deleted.
begin;

insert into public.found_items (
  id, idempotency_key, found_location, found_at,
  front_image_path, back_image_path, generic_name, object_name,
  colors, materials, analysis_model, analysis_json, search_document
) values (
  '10000000-0000-4000-8000-000000000001',
  '10000000-0000-4000-8000-000000000002',
  'LSPU Library, second floor', '2026-09-23 12:00:00+00',
  'found-items/fixture/front.jpg', 'found-items/fixture/back.jpg',
  'wallet', 'Black leather wallet', array['black'], array['leather'],
  'qwen3.5:9b-q8_0', '{"object_name":"Black leather wallet"}'::jsonb,
  'wallet black leather'
);

do $$
begin
  if (select count(*) from public.get_eligible_found_items(
        '2026-09-23 11:59:00+00', 100)) <> 1 then
    raise exception '11:59 temporal boundary failed';
  end if;
  if (select count(*) from public.get_eligible_found_items(
        '2026-09-23 12:00:00+00', 100)) <> 1 then
    raise exception '12:00 equality boundary failed';
  end if;
  if (select count(*) from public.get_eligible_found_items(
        '2026-09-23 12:01:00+00', 100)) <> 0 then
    raise exception '12:01 exclusion boundary failed';
  end if;
end;
$$;

insert into public.search_requests (
  id, anonymous_session_id, idempotency_key, description,
  last_seen_location, last_seen_at, processing_status,
  result_count, completed_at
) values (
  '20000000-0000-4000-8000-000000000001',
  '20000000-0000-4000-8000-000000000002',
  '20000000-0000-4000-8000-000000000003',
  'Black leather wallet', 'LSPU Library',
  '2026-09-23 11:59:00+00', 'completed', 1, now()
);

insert into public.match_results (
  search_request_id, found_item_id, rank, eligible,
  ai_similarity_score, deterministic_feature_score,
  location_score, time_proximity_score, final_score,
  matched_features, explanation, ai_model,
  score_breakdown, ai_match_json
) values (
  '20000000-0000-4000-8000-000000000001',
  '10000000-0000-4000-8000-000000000001',
  1, true, 90, 80, 70, 60, 80.5,
  array['black', 'wallet'], 'Strong visible feature match',
  'qwen3.5:9b-q8_0',
  '{"ai_similarity":90,"deterministic_feature":80,"location":70,"time_proximity":60}'::jsonb,
  '{"candidate_id":"10000000-0000-4000-8000-000000000001","ai_similarity":0.9}'::jsonb
);

do $$
begin
  begin
    perform * from public.complete_simulated_retrieval(
      '10000000-0000-4000-8000-000000000001',
      '20000000-0000-4000-8000-000000000001',
      '29999999-0000-4000-8000-000000000099'
    );
    raise exception 'session mismatch was incorrectly accepted';
  exception when others then
    if sqlerrm = 'session mismatch was incorrectly accepted' then raise; end if;
  end;
  if (select status from public.found_items
      where id = '10000000-0000-4000-8000-000000000001') <> 'available' then
    raise exception 'failed retrieval changed item state';
  end if;
end;
$$;

select * from public.complete_simulated_retrieval(
  '10000000-0000-4000-8000-000000000001',
  '20000000-0000-4000-8000-000000000001',
  '20000000-0000-4000-8000-000000000002'
);

do $$
begin
  if (select status from public.found_items
      where id = '10000000-0000-4000-8000-000000000001') <> 'retrieved' then
    raise exception 'retrieval did not update item atomically';
  end if;
  if (select count(*) from public.retrieval_events
      where found_item_id = '10000000-0000-4000-8000-000000000001'
        and retriever_label = 'Anonymous retriever') <> 1 then
    raise exception 'retrieval audit event missing';
  end if;
  begin
    perform * from public.complete_simulated_retrieval(
      '10000000-0000-4000-8000-000000000001',
      '20000000-0000-4000-8000-000000000001',
      '20000000-0000-4000-8000-000000000002'
    );
    raise exception 'duplicate retrieval was incorrectly accepted';
  exception when others then
    if sqlerrm = 'duplicate retrieval was incorrectly accepted' then raise; end if;
  end;
  if has_table_privilege('anon', 'public.found_items', 'select')
     or has_table_privilege('authenticated', 'public.found_items', 'select') then
    raise exception 'browser database role has table access';
  end if;
  if has_function_privilege(
       'anon', 'public.complete_simulated_retrieval(uuid,uuid,uuid)', 'execute') then
    raise exception 'anon can execute retrieval RPC';
  end if;
  if (select public from storage.buckets where id = 'sauli-item-images') then
    raise exception 'image bucket is public';
  end if;
end;
$$;

rollback;
