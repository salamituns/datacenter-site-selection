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

  -- 5. parcel decisions: anon sees nothing and writes nothing;
  --    authenticated writes ONLY through record_parcel_decision.
  --    There is deliberately no INSERT policy on parcel_decisions: the
  --    fingerprint and authorship are computed server-side in the
  --    SECURITY DEFINER function, so even a correctly-attributed direct
  --    insert is denied (a superset of the brief's "insert claiming
  --    another user's id must fail").
  --
  --    anon HOLDS EXECUTE on decision_author — v_parcel_decisions
  --    (security_invoker) references it, and Postgres checks EXECUTE at
  --    planning time, before RLS filters rows: without the grant every
  --    anon dossier open errors with 42501 instead of returning an
  --    empty set. What protects the email is the guard inside the
  --    function (a JWT, or a non-API session_user), not the grant. A
  --    SET ROLE session cannot prove that guard — session_user stays
  --    postgres here — so the real-path verification is the PostgREST
  --    probe: anon GET on the view returns 200 [] and anon
  --    /rpc/decision_author returns null (checked 2026-09-11).
  SET LOCAL ROLE anon;
  IF (SELECT count(*) FROM public.parcel_decisions) <> 0 THEN
    RAISE EXCEPTION 'anon read rows from parcel_decisions';
  END IF;
  IF (SELECT count(*) FROM public.v_parcel_decisions) <> 0 THEN
    RAISE EXCEPTION 'anon read rows from v_parcel_decisions';
  END IF;
  -- The view query itself must PLAN as anon — this is the assertion
  -- that failed live before decision_author was granted: a 42501 here
  -- surfaces as an exception, not as zero rows.
  IF NOT has_function_privilege('anon', 'public.decision_author(uuid)', 'EXECUTE') THEN
    RAISE EXCEPTION 'anon lost EXECUTE on decision_author — v_parcel_decisions will error for anon instead of returning an empty set';
  END IF;
  BEGIN
    INSERT INTO public.parcel_decisions
      (parcel_key, decision, rationale, decided_by, run_id, gate_fingerprint)
    VALUES ('RLS-DECISION-TEST', 'approve', 'test rationale long enough',
            '00000000-0000-0000-0000-000000000000',
            '00000000-0000-0000-0000-000000000000', 'x');
    RAISE EXCEPTION 'anon was allowed to INSERT into parcel_decisions';
  EXCEPTION WHEN insufficient_privilege THEN NULL; END;
  BEGIN
    PERFORM public.record_parcel_decision(
      'RLS-DECISION-TEST', 'approve', 'test rationale long enough');
    RAISE EXCEPTION 'anon was allowed to call record_parcel_decision';
  EXCEPTION WHEN insufficient_privilege THEN NULL; END;
  RESET ROLE;

  -- Authenticated: two test users, a test parcel and run, then the
  -- deny cases. request.jwt.claim.sub is what auth.uid() reads, so
  -- setting it makes the SQL editor behave like PostgREST carrying a
  -- real user's JWT.
  INSERT INTO auth.users (id, email) VALUES
    ('11111111-1111-1111-1111-111111111111', 'rls-decisions-a@test.invalid'),
    ('22222222-2222-2222-2222-222222222222', 'rls-decisions-b@test.invalid');
  INSERT INTO public.ingestion_runs (id, run_key, region_code, pipeline_version)
    VALUES ('33333333-3333-3333-3333-333333333333', 'rls-decision-run', 'XX', 'test');
  INSERT INTO public.land_parcels
    (parcel_key, source_parcel_id, state_code, county_name, geom,
     first_run_id, latest_run_id, region_key)
  VALUES ('RLS-DECISION-TEST', 'X', 'VA', 'Loudoun',
          'SRID=4326;MULTIPOLYGON(((0 0,0 1,1 1,0 0)))',
          '33333333-3333-3333-3333-333333333333',
          '33333333-3333-3333-3333-333333333333', 'VA-LOUDOUN');
  INSERT INTO public.parcel_gate_results (parcel_id, run_id, gate_key, status, rationale)
  SELECT lp.id, lp.latest_run_id, g.k, g.s, 'test'
  FROM public.land_parcels lp,
       (VALUES ('wetlands','PASS'), ('slope','PASS')) AS g(k, s)
  WHERE lp.parcel_key = 'RLS-DECISION-TEST';

  SET LOCAL ROLE authenticated;
  SET LOCAL request.jwt.claim.sub = '11111111-1111-1111-1111-111111111111';
  BEGIN
    -- claiming ANOTHER user's id
    INSERT INTO public.parcel_decisions
      (parcel_key, decision, rationale, decided_by, run_id, gate_fingerprint)
    VALUES ('RLS-DECISION-TEST', 'approve', 'test rationale long enough',
            '22222222-2222-2222-2222-222222222222',
            '33333333-3333-3333-3333-333333333333', 'x');
    RAISE EXCEPTION 'authenticated was allowed to INSERT a decision as another user';
  EXCEPTION WHEN insufficient_privilege THEN NULL; END;
  BEGIN
    -- even a correctly-attributed direct insert: must go through the function
    INSERT INTO public.parcel_decisions
      (parcel_key, decision, rationale, decided_by, run_id, gate_fingerprint)
    VALUES ('RLS-DECISION-TEST', 'approve', 'test rationale long enough',
            '11111111-1111-1111-1111-111111111111',
            '33333333-3333-3333-3333-333333333333', 'x');
    RAISE EXCEPTION 'authenticated was allowed to bypass record_parcel_decision';
  EXCEPTION WHEN insufficient_privilege THEN NULL; END;
  -- the one path that must work: the function, attributed to the caller
  PERFORM public.record_parcel_decision(
    'RLS-DECISION-TEST', 'hold', 'holding until the survey republishes');
  IF (SELECT count(*) FROM public.v_parcel_decisions
      WHERE parcel_key = 'RLS-DECISION-TEST'
        AND decided_by_email = 'rls-decisions-a@test.invalid') <> 1 THEN
    RAISE EXCEPTION 'record_parcel_decision did not create a readable decision for its caller';
  END IF;
  -- UPDATE and DELETE are denied the same way RLS hides anything else:
  -- with no UPDATE/DELETE policy the row is not visible to the statement,
  -- so the write affects nothing. Denied is denied — but it must be
  -- asserted as the row surviving unchanged, not assumed as an error.
  UPDATE public.parcel_decisions SET rationale = 'rewritten history';
  DELETE FROM public.parcel_decisions WHERE parcel_key = 'RLS-DECISION-TEST';
  IF (SELECT count(*) FROM public.parcel_decisions
      WHERE parcel_key = 'RLS-DECISION-TEST'
        AND rationale = 'holding until the survey republishes') <> 1 THEN
    RAISE EXCEPTION 'authenticated was able to UPDATE or DELETE a decision';
  END IF;
  -- supersede: only your own, and atomically with the replacement
  PERFORM public.record_parcel_decision(
    'RLS-DECISION-TEST', 'reject', 'rejected on the wetlands evidence',
    NULL,
    (SELECT id FROM public.parcel_decisions
     WHERE parcel_key = 'RLS-DECISION-TEST' AND superseded_by IS NULL));
  IF (SELECT count(*) FROM public.v_parcel_decisions
      WHERE parcel_key = 'RLS-DECISION-TEST' AND is_current) <> 1 THEN
    RAISE EXCEPTION 'superseding did not leave exactly one current decision';
  END IF;
  SET LOCAL request.jwt.claim.sub = '22222222-2222-2222-2222-222222222222';
  BEGIN
    PERFORM public.record_parcel_decision(
      'RLS-DECISION-TEST', 'approve', 'someone else tries to supersede this',
      NULL,
      (SELECT id FROM public.parcel_decisions
       WHERE parcel_key = 'RLS-DECISION-TEST' AND superseded_by IS NULL));
    RAISE EXCEPTION 'a user was allowed to supersede another user''s decision';
  EXCEPTION
    WHEN insufficient_privilege THEN
      RAISE EXCEPTION 'authenticated was DENIED execute on record_parcel_decision';
    WHEN OTHERS THEN
      IF SQLERRM NOT LIKE '%cannot supersede that decision%' THEN
        RAISE EXCEPTION 'unexpected error cross-user supersede: %', SQLERRM;
      END IF;
  END;
  RESET ROLE;

  -- cleanup: the append-only trigger blocks DELETE (that is its job), so
  -- the suite disables it as the table owner, removes only its own rows,
  -- and re-enables it. Gate rows go first: they reference the parcel
  -- and the run.
  ALTER TABLE public.parcel_decisions DISABLE TRIGGER trg_parcel_decisions_append_only;
  DELETE FROM public.parcel_decisions WHERE parcel_key = 'RLS-DECISION-TEST';
  ALTER TABLE public.parcel_decisions ENABLE TRIGGER trg_parcel_decisions_append_only;
  DELETE FROM public.parcel_gate_results
   WHERE parcel_id IN (SELECT id FROM public.land_parcels
                       WHERE parcel_key = 'RLS-DECISION-TEST');
  DELETE FROM public.land_parcels WHERE parcel_key = 'RLS-DECISION-TEST';
  DELETE FROM public.ingestion_runs WHERE run_key = 'rls-decision-run';
  DELETE FROM auth.users WHERE id IN ('11111111-1111-1111-1111-111111111111',
                                      '22222222-2222-2222-2222-222222222222');
  RESET ROLE;
END
$test$;

SELECT 'RLS allow/deny suite: ALL PASSED' AS result;
