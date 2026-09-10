-- ============================================================================
-- Test: promote_sibling_regions
-- Guard for the Phase 0 region re-key: a promote scoped to one region must
-- leave a sibling region in the same state completely alone.
--
-- The defect this guards: promote_ingestion_run used to scope its swap by
-- state_code, so publishing a second county in a state with a live county
-- (Licking after Franklin, Prince William after Loudoun) would delete the
-- sibling's screening cells and deactivate all of its parcels — atomically,
-- in a run that reports success.
--
-- Runs two synthetic sibling regions ('ZZ-ALPHA', 'ZZ-BETA') through the
-- real promote RPC, including the is_active sweep and a shared map feature,
-- asserts the sibling survives everything, and rolls the whole transaction
-- back so the live database is untouched.
--
-- Run with a role that can execute promote_ingestion_run (service role).
-- The final SELECT reports 'PASS' only when every assertion held.
-- ============================================================================

BEGIN;

-- 1. Two sibling runs in the same fake state.
INSERT INTO public.ingestion_runs (run_key, region_code, pipeline_version, status, trigger) VALUES
    ('TEST-SIB-A-0001', 'ZZ-ALPHA', 'test', 'running', 'manual'),
    ('TEST-SIB-B-0001', 'ZZ-BETA',  'test', 'running', 'manual');

-- 2. Each stages one screening cell, one parcel, and a map feature that
--    deliberately shares its feature_id with the sibling (the edge a
--    state-scoped unique constraint used to reject).
INSERT INTO public.stg_grid_parcels
    (grid_id, geom, centroid, area_sq_km, state_code, county_name, region,
     region_key, composite_score_unrisked, evidence_coverage, evidence_tier, run_id)
SELECT 'TEST-A-1',
       extensions.ST_GeomFromText('POLYGON((0 0, 0 1, 1 1, 1 0, 0 0))', 4326),
       extensions.ST_Centroid(extensions.ST_GeomFromText('POLYGON((0 0, 0 1, 1 1, 1 0, 0 0))', 4326)),
       10, 'ZZ', 'Alpha', 'TEST', 'ZZ-ALPHA', 70.0, 0.9, 'parcel',
       id FROM public.ingestion_runs WHERE run_key = 'TEST-SIB-A-0001';

INSERT INTO public.stg_grid_parcels
    (grid_id, geom, centroid, area_sq_km, state_code, county_name, region,
     region_key, composite_score_unrisked, evidence_coverage, evidence_tier, run_id)
SELECT 'TEST-B-1',
       extensions.ST_GeomFromText('POLYGON((2 0, 2 1, 3 1, 3 0, 2 0))', 4326),
       extensions.ST_Centroid(extensions.ST_GeomFromText('POLYGON((2 0, 2 1, 3 1, 3 0, 2 0))', 4326)),
       10, 'ZZ', 'Beta', 'TEST', 'ZZ-BETA', 60.0, 0.5, 'screening',
       id FROM public.ingestion_runs WHERE run_key = 'TEST-SIB-B-0001';

INSERT INTO public.stg_land_parcels
    (parcel_key, source_parcel_id, state_code, county_name, region_key,
     geom, gis_acreage, legal_acreage, run_id)
SELECT 'ZZ-ALPHA-P1', 'P1', 'ZZ', 'Alpha', 'ZZ-ALPHA',
       extensions.ST_Multi(extensions.ST_GeomFromText('POLYGON((0 0, 0 0.01, 0.01 0.01, 0.01 0, 0 0))', 4326)),
       100, 100, id FROM public.ingestion_runs WHERE run_key = 'TEST-SIB-A-0001';

INSERT INTO public.stg_land_parcels
    (parcel_key, source_parcel_id, state_code, county_name, region_key,
     geom, gis_acreage, legal_acreage, run_id)
SELECT 'ZZ-BETA-P1', 'P1', 'ZZ', 'Beta', 'ZZ-BETA',
       extensions.ST_Multi(extensions.ST_GeomFromText('POLYGON((2 0, 2 0.01, 2.01 0.01, 2.01 0, 2 0))', 4326)),
       100, 100, id FROM public.ingestion_runs WHERE run_key = 'TEST-SIB-B-0001';

INSERT INTO public.stg_transmission_lines
    (feature_id, state_code, region_key, owner, voltage_kv, line_name, geom, run_id)
SELECT 'SHARED-LINE-1', 'ZZ', 'ZZ-ALPHA', 'Test Owner', 500, 'Test Line',
       extensions.ST_GeomFromText('LINESTRING(0 0, 1 1)', 4326),
       id FROM public.ingestion_runs WHERE run_key = 'TEST-SIB-A-0001';

INSERT INTO public.stg_transmission_lines
    (feature_id, state_code, region_key, owner, voltage_kv, line_name, geom, run_id)
SELECT 'SHARED-LINE-1', 'ZZ', 'ZZ-BETA', 'Test Owner', 500, 'Test Line',
       extensions.ST_GeomFromText('LINESTRING(2 0, 3 1)', 4326),
       id FROM public.ingestion_runs WHERE run_key = 'TEST-SIB-B-0001';

-- 3. Promote both siblings.
SELECT public.promote_ingestion_run(
    (SELECT id FROM public.ingestion_runs WHERE run_key = 'TEST-SIB-A-0001'));
SELECT public.promote_ingestion_run(
    (SELECT id FROM public.ingestion_runs WHERE run_key = 'TEST-SIB-B-0001'));

-- 4. The regression trap: a later ALPHA run that does not restage its
--    parcel. The is_active sweep must deactivate ALPHA's parcel only —
--    BETA's parcel and cells must be untouched.
INSERT INTO public.ingestion_runs (run_key, region_code, pipeline_version, status, trigger)
VALUES ('TEST-SIB-A-0002', 'ZZ-ALPHA', 'test', 'running', 'manual');

INSERT INTO public.stg_grid_parcels
    (grid_id, geom, centroid, area_sq_km, state_code, county_name, region,
     region_key, composite_score_unrisked, evidence_coverage, evidence_tier, run_id)
SELECT 'TEST-A-2',
       extensions.ST_GeomFromText('POLYGON((0 0, 0 1, 1 1, 1 0, 0 0))', 4326),
       extensions.ST_Centroid(extensions.ST_GeomFromText('POLYGON((0 0, 0 1, 1 1, 1 0, 0 0))', 4326)),
       10, 'ZZ', 'Alpha', 'TEST', 'ZZ-ALPHA', 71.0, 0.9, 'parcel',
       id FROM public.ingestion_runs WHERE run_key = 'TEST-SIB-A-0002';

SELECT public.promote_ingestion_run(
    (SELECT id FROM public.ingestion_runs WHERE run_key = 'TEST-SIB-A-0002'));

-- 5. Assertions.
SELECT CASE
    WHEN
        -- Final state, after all three promotes:
        -- Each region still has its one cell.
        (SELECT COUNT(*) FROM public.grid_parcels WHERE region_key = 'ZZ-ALPHA') = 1
        AND (SELECT COUNT(*) FROM public.grid_parcels WHERE region_key = 'ZZ-BETA')  = 1
        -- The is_active sweep is region-scoped: ALPHA's parcel (not
        -- restaged by run 2) is deactivated, BETA's parcel survives.
        AND (SELECT COUNT(*) FROM public.land_parcels WHERE region_key = 'ZZ-ALPHA' AND is_active) = 0
        AND (SELECT COUNT(*) FROM public.land_parcels WHERE region_key = 'ZZ-BETA'  AND is_active) = 1
        -- Map features are region-scoped: ALPHA's copy of the shared line
        -- is gone (not restaged by run 2), but BETA's copy survives.
        AND (SELECT COUNT(*) FROM public.transmission_lines WHERE region_key = 'ZZ-BETA' AND feature_id = 'SHARED-LINE-1') = 1
        AND (SELECT COUNT(*) FROM public.transmission_lines WHERE region_key = 'ZZ-ALPHA') = 0
        -- Supersession is per region: ALPHA's first run superseded, BETA's
        -- still succeeded.
        AND (SELECT status FROM public.ingestion_runs WHERE run_key = 'TEST-SIB-A-0001') = 'superseded'
        AND (SELECT status FROM public.ingestion_runs WHERE run_key = 'TEST-SIB-B-0001') = 'succeeded'
    THEN 'PASS'
    ELSE 'FAIL: sibling region was touched by a promote'
END AS result;

ROLLBACK;
