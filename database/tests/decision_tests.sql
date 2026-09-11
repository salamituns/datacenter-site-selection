-- ============================================================================
-- Parcel decision contracts — fingerprint and staleness, per
-- docs/parcel-decisions-brief.md. Run against the live database after
-- the rls_tests.sql suite (it reuses the same SET LOCAL ROLE /
-- request.jwt.claim.sub technique). Raises on the first failure.
--
--   1. Order independence: gate rows have no guaranteed order, so two
--      runs holding the same (gate_key, status) pairs — inserted in
--      different orders — must fingerprint identically, and one changed
--      status must fingerprint differently.
--   2. Staleness: a decision recorded against run A, with the parcel's
--      current run now holding different verdicts, must read as stale
--      from the view with the moved gates named — never auto-voided,
--      never silently refreshed.
--   3. The append-only invariant holds even for the table owner: an
--      in-place edit or a delete is refused; the only legal mutation is
--      the supersede write.
-- ============================================================================

DO $test$
DECLARE
    v_run_a uuid := '44444444-4444-4444-4444-444444444444';
    v_run_b uuid := '55555555-5555-5555-5555-555555555555';
    v_run_c uuid := '66666666-6666-6666-6666-666666666666';
    v_user  uuid := '77777777-7777-7777-7777-777777777777';
    v_parcel_id uuid;
    v_fp_a  text;
    v_fp_b  text;
    v_fp_c  text;
    v_dec_a uuid;
    v_dec_b uuid;
    v_stale boolean;
    v_moved jsonb;
    v_current text;
BEGIN
    -- Fixtures: one parcel, three runs. Runs A and B hold the same
    -- verdicts inserted in DIFFERENT orders; run C changes one status.
    INSERT INTO auth.users (id, email)
      VALUES (v_user, 'decision-contracts@test.invalid');
    INSERT INTO public.ingestion_runs (id, run_key, region_code, pipeline_version) VALUES
      (v_run_a, 'decision-contract-a', 'XX', 'test'),
      (v_run_b, 'decision-contract-b', 'XX', 'test'),
      (v_run_c, 'decision-contract-c', 'XX', 'test');
    INSERT INTO public.land_parcels
      (parcel_key, source_parcel_id, state_code, county_name, geom,
       first_run_id, latest_run_id, region_key)
    VALUES ('DECISION-CONTRACT-TEST', 'X', 'VA', 'Loudoun',
            'SRID=4326;MULTIPOLYGON(((0 0,0 1,1 1,0 0)))',
            v_run_a, v_run_a, 'VA-LOUDOUN')
    RETURNING id INTO v_parcel_id;

    -- run A: wetlands PASS, slope PASS, zoning FAIL
    INSERT INTO public.parcel_gate_results (parcel_id, run_id, gate_key, status, rationale) VALUES
      (v_parcel_id, v_run_a, 'wetlands', 'PASS', 'test'),
      (v_parcel_id, v_run_a, 'slope',    'PASS', 'test'),
      (v_parcel_id, v_run_a, 'zoning_dc_use', 'FAIL', 'test');
    -- run B: the same pairs, inserted in a different order
    INSERT INTO public.parcel_gate_results (parcel_id, run_id, gate_key, status, rationale) VALUES
      (v_parcel_id, v_run_b, 'zoning_dc_use', 'FAIL', 'test'),
      (v_parcel_id, v_run_b, 'slope',    'PASS', 'test'),
      (v_parcel_id, v_run_b, 'wetlands', 'PASS', 'test');
    -- run C: the wetlands gate flipped to FAIL
    INSERT INTO public.parcel_gate_results (parcel_id, run_id, gate_key, status, rationale) VALUES
      (v_parcel_id, v_run_c, 'wetlands', 'FAIL', 'test'),
      (v_parcel_id, v_run_c, 'slope',    'PASS', 'test'),
      (v_parcel_id, v_run_c, 'zoning_dc_use', 'FAIL', 'test');

    -- 1. Order independence
    v_fp_a := public.parcel_gate_fingerprint('DECISION-CONTRACT-TEST', v_run_a);
    v_fp_b := public.parcel_gate_fingerprint('DECISION-CONTRACT-TEST', v_run_b);
    v_fp_c := public.parcel_gate_fingerprint('DECISION-CONTRACT-TEST', v_run_c);
    IF v_fp_a IS NULL OR v_fp_a <> v_fp_b THEN
      RAISE EXCEPTION 'fingerprint is not order-independent: A=% B=%', v_fp_a, v_fp_b;
    END IF;
    IF v_fp_a = v_fp_c THEN
      RAISE EXCEPTION 'a changed gate status did not change the fingerprint';
    END IF;

    -- 2. Staleness: record against run A (the parcel's current run at
    --    decision time), then let run C become current — the shape of a
    --    region republishing between Tuesday and the decision.
    SET LOCAL ROLE authenticated;
    PERFORM set_config('request.jwt.claim.sub', v_user::text, true);

    PERFORM public.record_parcel_decision(
      'DECISION-CONTRACT-TEST', 'approve',
      'all three gates read favourably at decision time');
    SELECT id, gate_fingerprint INTO v_dec_a, v_current
      FROM public.parcel_decisions WHERE parcel_key = 'DECISION-CONTRACT-TEST';
    IF v_current <> v_fp_a THEN
      RAISE EXCEPTION 'the stored fingerprint does not match the run it claims';
    END IF;

    -- simulate the republish: run C becomes the parcel's current run.
    -- This write is the pipeline's job, so it runs as the table owner —
    -- authenticated has no UPDATE policy on land_parcels (correctly),
    -- and an invisible-row UPDATE here would fake a "not stale" result.
    RESET ROLE;
    UPDATE public.land_parcels
      SET latest_run_id = v_run_c
      WHERE parcel_key = 'DECISION-CONTRACT-TEST';
    SET LOCAL ROLE authenticated;
    PERFORM set_config('request.jwt.claim.sub', v_user::text, true);

    SELECT is_stale, gates_moved INTO v_stale, v_moved
      FROM public.v_parcel_decisions
      WHERE id = v_dec_a;
    IF v_stale IS NOT TRUE THEN
      RAISE EXCEPTION 'the view did not flag the decision as stale after the gates moved';
    END IF;
    IF v_moved IS NULL
       OR (SELECT count(*) FROM jsonb_array_elements(v_moved)) <> 1
       OR v_moved -> 0 ->> 'gate_key' IS DISTINCT FROM 'wetlands'
       OR v_moved -> 0 ->> 'was' IS DISTINCT FROM 'PASS'
       OR v_moved -> 0 ->> 'now' IS DISTINCT FROM 'FAIL' THEN
      RAISE EXCEPTION 'the view did not name the moved gate: %', v_moved;
    END IF;

    -- supersede and read the current state back
    PERFORM public.record_parcel_decision(
      'DECISION-CONTRACT-TEST', 'reject',
      'the wetlands flip changes the answer', NULL, v_dec_a);
    SELECT d.superseded_by INTO v_dec_b
      FROM public.parcel_decisions d WHERE d.id = v_dec_a;
    IF v_dec_b IS NULL THEN
      RAISE EXCEPTION 'the superseded row does not point at its replacement';
    END IF;
    IF (SELECT count(*) FROM public.v_parcel_decisions
        WHERE parcel_key = 'DECISION-CONTRACT-TEST' AND is_current) <> 1 THEN
      RAISE EXCEPTION 'there is not exactly one current decision';
    END IF;

    -- an override must accept a FAIL or UNKNOWN, naming its gate, and
    -- must record the verdict it accepts without changing it
    BEGIN
      PERFORM public.record_parcel_decision(
        'DECISION-CONTRACT-TEST', 'override',
        'accepting the slope gate despite its verdict', 'slope');
      RAISE EXCEPTION 'an override of a PASS gate was accepted';
    EXCEPTION
      WHEN insufficient_privilege THEN
        RAISE EXCEPTION 'authenticated was DENIED execute on record_parcel_decision';
      WHEN OTHERS THEN
        IF SQLERRM NOT LIKE '%an override accepts a FAIL or UNKNOWN verdict%' THEN
          RAISE EXCEPTION 'unexpected error overriding a PASS gate: %', SQLERRM;
        END IF;
    END;
    PERFORM public.record_parcel_decision(
      'DECISION-CONTRACT-TEST', 'override',
      'accepting the wetlands FAIL with mitigation in mind', 'wetlands');
    IF EXISTS (SELECT 1 FROM public.parcel_decisions
               WHERE parcel_key = 'DECISION-CONTRACT-TEST'
                 AND decision = 'override'
                 AND override_status <> 'FAIL') THEN
      RAISE EXCEPTION 'the override did not record the verdict it accepts';
    END IF;
    -- and the gate itself is untouched by the override
    IF EXISTS (SELECT 1 FROM public.v_parcel_gates
               WHERE parcel_key = 'DECISION-CONTRACT-TEST'
                 AND gate_key = 'wetlands' AND status <> 'FAIL') THEN
      RAISE EXCEPTION 'the override mutated the gate verdict it accepted';
    END IF;
    RESET ROLE;

    -- 3. Append-only even for the table owner: in-place edit and delete
    --    are refused outright.
    BEGIN
      UPDATE public.parcel_decisions SET rationale = 'rewritten history';
      RAISE EXCEPTION 'an in-place rationale edit was allowed';
    EXCEPTION WHEN OTHERS THEN
      IF SQLERRM NOT LIKE '%append-only%' THEN
        RAISE EXCEPTION 'unexpected error on in-place edit: %', SQLERRM;
      END IF;
    END;
    BEGIN
      DELETE FROM public.parcel_decisions WHERE parcel_key = 'DECISION-CONTRACT-TEST';
      RAISE EXCEPTION 'a delete was allowed';
    EXCEPTION WHEN OTHERS THEN
      IF SQLERRM NOT LIKE '%append-only%' THEN
        RAISE EXCEPTION 'unexpected error on delete: %', SQLERRM;
      END IF;
    END;

    -- cleanup (trigger disabled as owner: the deny above is the point).
    -- Gate rows go first: they reference the parcel and the run.
    ALTER TABLE public.parcel_decisions DISABLE TRIGGER trg_parcel_decisions_append_only;
    DELETE FROM public.parcel_decisions WHERE parcel_key = 'DECISION-CONTRACT-TEST';
    ALTER TABLE public.parcel_decisions ENABLE TRIGGER trg_parcel_decisions_append_only;
    DELETE FROM public.parcel_gate_results WHERE parcel_id = v_parcel_id;
    DELETE FROM public.land_parcels WHERE parcel_key = 'DECISION-CONTRACT-TEST';
    DELETE FROM public.ingestion_runs WHERE run_key IN
      ('decision-contract-a', 'decision-contract-b', 'decision-contract-c');
    DELETE FROM auth.users WHERE id = v_user;
END
$test$;

SELECT 'Decision contract suite: ALL PASSED' AS result;
