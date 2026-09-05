-- ============================================================================
-- RLS allow/deny suite — run against the live database (e.g. via the
-- Supabase SQL editor or `supabase db execute`) after every migration that
-- touches policies or grants. Raises on the first failure; success prints
-- the summary row. Covers every table/view exposed to API roles.
-- ============================================================================

DO $test$
BEGIN
  -- 1. anon reads everything the client needs
  SET LOCAL ROLE anon;
  PERFORM count(*) FROM public.grid_parcels;
  PERFORM count(*) FROM public.v_grid_parcels;
  PERFORM count(*) FROM public.v_transmission_lines;
  PERFORM count(*) FROM public.v_substations;
  PERFORM count(*) FROM public.v_observation_wells;
  PERFORM count(*) FROM public.data_sources;
  PERFORM count(*) FROM public.ingestion_runs;
  PERFORM count(*) FROM public.source_snapshots;
  PERFORM count(*) FROM public.metric_definitions;
  PERFORM count(*) FROM public.constraint_rules;
  PERFORM count(*) FROM public.land_parcels;
  PERFORM count(*) FROM public.parcel_metric_values;
  PERFORM count(*) FROM public.parcel_gate_results;
  PERFORM count(*) FROM public.v_ingestion_runs;
  PERFORM count(*) FROM public.v_source_snapshots;
  PERFORM count(*) FROM public.v_land_parcels;
  PERFORM count(*) FROM public.v_parcel_gates;
  PERFORM count(*) FROM public.v_parcel_metrics;
  PERFORM count(*) FROM public.power_rtep_upgrades;
  PERFORM count(*) FROM public.power_documents;
  PERFORM count(*) FROM public.v_power_rtep_upgrades;
  PERFORM count(*) FROM public.v_power_documents;
  PERFORM count(*) FROM public.power_parcel_evidence;
  PERFORM count(*) FROM public.v_power_parcel_evidence;
  RESET ROLE;

  -- 2. anon cannot mutate any ingestion data
  SET LOCAL ROLE anon;
  BEGIN
    INSERT INTO public.grid_parcels (grid_id, geom, centroid)
      VALUES ('RLS-TEST', 'SRID=4326;POLYGON((0 0,0 1,1 1,0 0))', 'SRID=4326;POINT(0.5 0.5)');
    RAISE EXCEPTION 'anon was allowed to INSERT into grid_parcels';
  EXCEPTION WHEN insufficient_privilege THEN NULL; END;
  BEGIN
    DELETE FROM public.transmission_lines;
    RAISE EXCEPTION 'anon was allowed to DELETE from transmission_lines';
  EXCEPTION WHEN insufficient_privilege THEN NULL; END;
  BEGIN
    UPDATE public.substations SET substation_name = 'x';
    RAISE EXCEPTION 'anon was allowed to UPDATE substations';
  EXCEPTION WHEN insufficient_privilege THEN NULL; END;
  BEGIN
    INSERT INTO public.observation_wells (site_no, state_code, geom)
      VALUES ('RLS-TEST', 'VA', 'SRID=4326;POINT(0 0)');
    RAISE EXCEPTION 'anon was allowed to INSERT into observation_wells';
  EXCEPTION WHEN insufficient_privilege THEN NULL; END;
  BEGIN
    INSERT INTO public.land_parcels (parcel_key, source_parcel_id, state_code, county_name, geom, first_run_id, latest_run_id)
      VALUES ('RLS-TEST', 'X', 'VA', 'Loudoun', 'SRID=4326;MULTIPOLYGON(((0 0,0 1,1 1,0 0)))', '00000000-0000-0000-0000-000000000000', '00000000-0000-0000-0000-000000000000');
    RAISE EXCEPTION 'anon was allowed to INSERT into land_parcels';
  EXCEPTION WHEN insufficient_privilege THEN NULL; END;
  BEGIN
    INSERT INTO public.parcel_gate_results (parcel_id, run_id, gate_key, status, rationale)
      VALUES ('00000000-0000-0000-0000-000000000000', '00000000-0000-0000-0000-000000000000', 'x', 'PASS', 'x');
    RAISE EXCEPTION 'anon was allowed to INSERT into parcel_gate_results';
  EXCEPTION WHEN insufficient_privilege THEN NULL; END;
  BEGIN
    INSERT INTO public.ingestion_runs (run_key, region_code, pipeline_version)
      VALUES ('RLS-TEST', 'VA', 'test');
    RAISE EXCEPTION 'anon was allowed to INSERT into ingestion_runs';
  EXCEPTION WHEN insufficient_privilege THEN NULL; END;
  BEGIN
    INSERT INTO public.constraint_rules (gate_key, jurisdiction, rule_version, description)
      VALUES ('x', 'x', 'x', 'x');
    RAISE EXCEPTION 'anon was allowed to INSERT into constraint_rules';
  EXCEPTION WHEN insufficient_privilege THEN NULL; END;
  BEGIN
    INSERT INTO public.power_rtep_upgrades (upgrade_id, state_code, project_type, description, status, run_id)
      VALUES ('RLS-TEST', 'VA', 'Baseline', 'x', 'IS', '00000000-0000-0000-0000-000000000000');
    RAISE EXCEPTION 'anon was allowed to INSERT into power_rtep_upgrades';
  EXCEPTION WHEN insufficient_privilege THEN NULL; END;
  BEGIN
    INSERT INTO public.power_documents (doc_key, title, publisher, doc_type, url)
      VALUES ('rls-test', 'x', 'x', 'report', 'x');
    RAISE EXCEPTION 'anon was allowed to INSERT into power_documents';
  EXCEPTION WHEN insufficient_privilege THEN NULL; END;
  BEGIN
    INSERT INTO public.power_parcel_evidence
      (parcel_key, application_number, approval_date, utility_statement,
       document_name, document_date, source_url)
      VALUES ('rls-test', 'rls-test', '2020-01-01', 'x', 'x', '2020-01-01', 'x');
    RAISE EXCEPTION 'anon was allowed to INSERT into power_parcel_evidence';
  EXCEPTION WHEN insufficient_privilege THEN NULL; END;
  RESET ROLE;

  -- 3. anon cannot see staging or call the publication RPCs
  SET LOCAL ROLE anon;
  BEGIN
    PERFORM count(*) FROM public.stg_grid_parcels;
    RAISE EXCEPTION 'anon was allowed to SELECT staging tables';
  EXCEPTION WHEN insufficient_privilege THEN NULL; END;
  BEGIN
    PERFORM count(*) FROM public.stg_power_rtep_upgrades;
    RAISE EXCEPTION 'anon was allowed to SELECT stg_power_rtep_upgrades';
  EXCEPTION WHEN insufficient_privilege THEN NULL; END;
  BEGIN
    PERFORM public.promote_ingestion_run('00000000-0000-0000-0000-000000000000');
    RAISE EXCEPTION 'anon was allowed to call promote_ingestion_run';
  EXCEPTION WHEN insufficient_privilege THEN NULL; END;
  RESET ROLE;

  -- 4. service_role drives the run lifecycle (expected: wrong-state guard)
  SET LOCAL ROLE service_role;
  BEGIN
    PERFORM public.promote_ingestion_run('00000000-0000-0000-0000-000000000000');
    RAISE EXCEPTION 'promote_ingestion_run accepted a non-existent run';
  EXCEPTION
    WHEN insufficient_privilege THEN RAISE EXCEPTION 'service_role was DENIED execute on promote_ingestion_run';
    WHEN OTHERS THEN
      IF SQLERRM NOT LIKE '%not in running state%' THEN
        RAISE EXCEPTION 'unexpected error from promote: %', SQLERRM;
      END IF;
  END;
  INSERT INTO public.ingestion_runs (run_key, region_code, pipeline_version, trigger)
    VALUES ('rls-smoke-test', 'XX', 'test', 'operator');
  UPDATE public.ingestion_runs SET status = 'failed', error = 'smoke' WHERE run_key = 'rls-smoke-test';
  DELETE FROM public.ingestion_runs WHERE run_key = 'rls-smoke-test';
  INSERT INTO public.stg_parcel_gate_results (parcel_key, run_id, gate_key, status, rationale)
    VALUES ('rls-test', '00000000-0000-0000-0000-000000000000', 'x', 'PASS', 'x');
  DELETE FROM public.stg_parcel_gate_results WHERE parcel_key = 'rls-test';
  INSERT INTO public.stg_power_rtep_upgrades (upgrade_id, state_code, project_type, description, status, run_id)
    VALUES ('rls-test', 'XX', 'Baseline', 'smoke', 'IS', '00000000-0000-0000-0000-000000000000');
  DELETE FROM public.stg_power_rtep_upgrades WHERE upgrade_id = 'rls-test';
  INSERT INTO public.power_parcel_evidence
    (parcel_key, application_number, approval_date, utility_statement,
     document_name, document_date, source_url)
    VALUES ('rls-test', 'rls-test', '2020-01-01', 'smoke', 'smoke.pdf', '2020-01-01', 'x');
  DELETE FROM public.power_parcel_evidence WHERE parcel_key = 'rls-test';
  RESET ROLE;
END
$test$;

SELECT 'RLS allow/deny suite: ALL PASSED' AS result;
