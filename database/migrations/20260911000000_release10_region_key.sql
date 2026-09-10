-- ============================================================================
-- Migration: release10_region_key
-- Description: Re-key the region model from state to county.
--
--   The engine modeled one region per state: ingestion_runs.region_code held
--   'OH' and promote_ingestion_run scoped its swap by state_code. Publishing
--   a second Ohio county (Licking) would have deleted every Franklin
--   screening cell and deactivated all 982 Franklin parcels — atomically, in
--   a run that reports success. Both PJM Tier-1 candidates collide this way.
--
--   region_code becomes a county slug ('OH-FRANKLIN', 'OH-LICKING', ...).
--   grid_parcels / land_parcels / transmission_lines / substations /
--   observation_wells gain region_key (backfilled from state + county —
--   exact today because exactly one county per state has ever published),
--   and the promote scopes every region-scoped swap by it. The map-feature
--   unique constraints move from (state_code, feature_id) to
--   (region_key, feature_id) so a feature crossing two counties of one
--   state cannot collide. power_rtep_upgrades stays state-scoped: the RTEP
--   dataset is fetched per state and every run of either county stages the
--   full state set, so the state-scoped replace is idempotent.
--
--   Layer caches (PAD-US / NWI / TIGER clips) stay keyed by state in the
--   worker where the artefact is a state file; only the promote's scoping
--   changes here.
-- ============================================================================

-- ── 1. ingestion_runs: region_code becomes the county slug ────────────────

-- v_ingestion_runs depends on region_code, so it is dropped for the type
-- change and recreated identically (security_invoker + the same grants).
DROP VIEW public.v_ingestion_runs;

ALTER TABLE public.ingestion_runs
    ALTER COLUMN region_code TYPE VARCHAR(24);

CREATE VIEW public.v_ingestion_runs AS
SELECT id, run_key, region_code, pipeline_version, status, trigger, config,
       stats, error, started_at, finished_at
FROM public.ingestion_runs;
ALTER VIEW public.v_ingestion_runs SET (security_invoker = true);
GRANT ALL ON public.v_ingestion_runs TO anon, authenticated, service_role;

UPDATE public.ingestion_runs SET region_code = CASE region_code
    WHEN 'VA' THEN 'VA-LOUDOUN'
    WHEN 'TX' THEN 'TX-TAYLOR'
    WHEN 'OH' THEN 'OH-FRANKLIN'
    WHEN 'OR' THEN 'OR-MORROW'
    ELSE region_code
END
WHERE region_code IN ('VA', 'TX', 'OH', 'OR');

-- ── 2. region_key on every region-scoped table (+ staging mirrors) ────────

ALTER TABLE public.grid_parcels        ADD COLUMN IF NOT EXISTS region_key VARCHAR(24);
ALTER TABLE public.land_parcels        ADD COLUMN IF NOT EXISTS region_key VARCHAR(24);
ALTER TABLE public.transmission_lines  ADD COLUMN IF NOT EXISTS region_key VARCHAR(24);
ALTER TABLE public.substations         ADD COLUMN IF NOT EXISTS region_key VARCHAR(24);
ALTER TABLE public.observation_wells   ADD COLUMN IF NOT EXISTS region_key VARCHAR(24);
ALTER TABLE public.stg_grid_parcels       ADD COLUMN IF NOT EXISTS region_key VARCHAR(24);
ALTER TABLE public.stg_land_parcels       ADD COLUMN IF NOT EXISTS region_key VARCHAR(24);
ALTER TABLE public.stg_transmission_lines ADD COLUMN IF NOT EXISTS region_key VARCHAR(24);
ALTER TABLE public.stg_substations        ADD COLUMN IF NOT EXISTS region_key VARCHAR(24);
ALTER TABLE public.stg_observation_wells  ADD COLUMN IF NOT EXISTS region_key VARCHAR(24);

-- Backfill. grid/land parcels carry county_name; the map-feature tables do
-- not, but exactly one county per state has published so far, so the state
-- map is exact for them (and a county-based fallback for null county names).
UPDATE public.grid_parcels SET region_key = state_code || '-' ||
    UPPER(REPLACE(COALESCE(NULLIF(county_name, ''),
        CASE state_code WHEN 'VA' THEN 'Loudoun' WHEN 'TX' THEN 'Taylor'
             WHEN 'OH' THEN 'Franklin' WHEN 'OR' THEN 'Morrow' END), ' ', '-'))
WHERE region_key IS NULL OR region_key = '';

UPDATE public.land_parcels SET region_key = state_code || '-' ||
    UPPER(REPLACE(COALESCE(NULLIF(county_name, ''),
        CASE state_code WHEN 'VA' THEN 'Loudoun' WHEN 'TX' THEN 'Taylor'
             WHEN 'OH' THEN 'Franklin' WHEN 'OR' THEN 'Morrow' END), ' ', '-'))
WHERE region_key IS NULL OR region_key = '';

UPDATE public.transmission_lines SET region_key = CASE state_code
    WHEN 'VA' THEN 'VA-LOUDOUN' WHEN 'TX' THEN 'TX-TAYLOR'
    WHEN 'OH' THEN 'OH-FRANKLIN' WHEN 'OR' THEN 'OR-MORROW' END
WHERE region_key IS NULL OR region_key = '';

UPDATE public.substations SET region_key = CASE state_code
    WHEN 'VA' THEN 'VA-LOUDOUN' WHEN 'TX' THEN 'TX-TAYLOR'
    WHEN 'OH' THEN 'OH-FRANKLIN' WHEN 'OR' THEN 'OR-MORROW' END
WHERE region_key IS NULL OR region_key = '';

UPDATE public.observation_wells SET region_key = CASE state_code
    WHEN 'VA' THEN 'VA-LOUDOUN' WHEN 'TX' THEN 'TX-TAYLOR'
    WHEN 'OH' THEN 'OH-FRANKLIN' WHEN 'OR' THEN 'OR-MORROW' END
WHERE region_key IS NULL OR region_key = '';

ALTER TABLE public.grid_parcels       ALTER COLUMN region_key SET NOT NULL;
ALTER TABLE public.land_parcels       ALTER COLUMN region_key SET NOT NULL;
ALTER TABLE public.transmission_lines ALTER COLUMN region_key SET NOT NULL;
ALTER TABLE public.substations        ALTER COLUMN region_key SET NOT NULL;
ALTER TABLE public.observation_wells  ALTER COLUMN region_key SET NOT NULL;

CREATE INDEX IF NOT EXISTS idx_grid_parcels_region       ON public.grid_parcels (region_key);
CREATE INDEX IF NOT EXISTS idx_land_parcels_region       ON public.land_parcels (region_key);
CREATE INDEX IF NOT EXISTS idx_transmission_lines_region ON public.transmission_lines (region_key);
CREATE INDEX IF NOT EXISTS idx_substations_region        ON public.substations (region_key);
CREATE INDEX IF NOT EXISTS idx_observation_wells_region  ON public.observation_wells (region_key);

-- A feature crossing two counties of one state is a legitimate second row:
-- uniqueness moves from (state_code, feature_id) to (region_key, feature_id).
ALTER TABLE public.transmission_lines DROP CONSTRAINT transmission_lines_state_code_feature_id_key;
ALTER TABLE public.transmission_lines ADD CONSTRAINT transmission_lines_region_feature_id_key
    UNIQUE (region_key, feature_id);
ALTER TABLE public.substations DROP CONSTRAINT substations_state_code_feature_id_key;
ALTER TABLE public.substations ADD CONSTRAINT substations_region_feature_id_key
    UNIQUE (region_key, feature_id);
ALTER TABLE public.observation_wells DROP CONSTRAINT observation_wells_state_code_site_no_key;
ALTER TABLE public.observation_wells ADD CONSTRAINT observation_wells_region_site_no_key
    UNIQUE (region_key, site_no);

-- ── 3. Views expose region_key (appended last: CREATE OR REPLACE VIEW
--      matches columns by position and may only add at the end) ────────────

CREATE OR REPLACE VIEW public.v_grid_parcels AS
SELECT id,
    grid_id,
    state_code,
    county_name,
    region,
    area_sq_km,
    extensions.ST_X(centroid) AS lon,
    extensions.ST_Y(centroid) AS lat,
    (extensions.ST_AsGeoJSON(geom))::jsonb AS geojson_geom,
    power_distance_miles,
    substation_distance_miles,
    substation_voltage_kv,
    substation_name,
    grid_operator,
    groundwater_depth_ft,
    surface_water_distance_miles,
    water_availability_index,
    nearest_gauge_id,
    seismic_hazard_pga,
    flood_risk_score,
    hurricane_risk_score,
    aggregate_risk_score,
    cooling_degree_days,
    ambient_avg_temp_f,
    free_cooling_potential_hours,
    power_score,
    water_score,
    risk_score,
    climate_score,
    composite_score,
    composite_score_unrisked,
    cluster_zone_id,
    cluster_label,
    is_prime_zone,
    megawatt_capacity_estimate,
    metadata,
    created_at,
    updated_at,
    source_run_id,
    ixp_nearest_facility,
    ixp_nearest_distance_miles,
    ixp_latency_floor_ms,
    ixp_networks_at_nearest,
    ixp_facilities_within_25mi,
    ixp_networks_within_25mi,
    ixp_best_networks_within_25mi,
    evidence_coverage,
    evidence_tier,
    region_key
FROM public.grid_parcels gp;
ALTER VIEW public.v_grid_parcels SET (security_invoker = true);

CREATE OR REPLACE VIEW public.v_land_parcels_map AS
SELECT
    lp.parcel_key,
    lp.source_parcel_id AS pin,
    lp.state_code,
    lp.county_name,
    (extensions.ST_AsGeoJSON(
        extensions.ST_SimplifyPreserveTopology(lp.geom, 0.00005)
    ))::jsonb AS geojson_geom,
    extensions.ST_X(extensions.ST_Centroid(lp.geom)) AS lon,
    extensions.ST_Y(extensions.ST_Centroid(lp.geom)) AS lat,
    lp.gis_acreage,
    lp.legal_acreage,
    (SELECT CASE
        WHEN COUNT(*) = 0 THEN NULL
        WHEN BOOL_OR(g.status = 'FAIL') THEN 'FAIL'
        WHEN BOOL_OR(g.status = 'UNKNOWN') THEN 'UNKNOWN'
        WHEN BOOL_OR(g.status = 'CONDITIONAL') THEN 'CONDITIONAL'
        ELSE 'PASS'
    END
    FROM public.parcel_gate_results g
    WHERE g.parcel_id = lp.id AND g.run_id = lp.latest_run_id) AS overall_status,
    lp.region_key
FROM public.land_parcels lp
WHERE lp.is_active;

ALTER VIEW public.v_land_parcels_map SET (security_invoker = true);
GRANT SELECT ON public.v_land_parcels_map TO anon, authenticated;

-- Map-feature views: region_key appended so the client can scope a
-- region's infrastructure without filtering by state (two counties of
-- one state each carry their own copy of a shared feature now).
CREATE OR REPLACE VIEW public.v_transmission_lines AS
SELECT id,
    feature_id,
    state_code,
    owner,
    voltage_kv,
    volt_class,
    line_name,
    (extensions.ST_AsGeoJSON(geom))::jsonb AS geojson_geom,
    region_key
FROM public.transmission_lines;

CREATE OR REPLACE VIEW public.v_substations AS
SELECT id,
    feature_id,
    state_code,
    substation_name,
    voltage_kv,
    extensions.ST_X(geom) AS lon,
    extensions.ST_Y(geom) AS lat,
    region_key
FROM public.substations;

CREATE OR REPLACE VIEW public.v_observation_wells AS
SELECT id,
    site_no,
    state_code,
    water_depth_ft,
    extensions.ST_X(geom) AS lon,
    extensions.ST_Y(geom) AS lat,
    region_key
FROM public.observation_wells;

-- ── 4. promote: scope every region swap by region_key ─────────────────────

CREATE OR REPLACE FUNCTION public.promote_ingestion_run(p_run_id UUID)
RETURNS JSONB
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path TO 'public', 'extensions'
SET statement_timeout TO '10min'
AS $function$
DECLARE
    v_region TEXT;          -- county slug, e.g. 'OH-LICKING'
    v_state VARCHAR(2);     -- its state, for the genuinely state-scoped sets
    v_counts JSONB;
BEGIN
    SELECT region_code INTO v_region FROM public.ingestion_runs
    WHERE id = p_run_id AND status = 'running';
    IF v_region IS NULL THEN
        RAISE EXCEPTION 'ingestion run % is not in running state', p_run_id;
    END IF;
    v_state := SPLIT_PART(v_region, '-', 1);

    -- Screening cells: region-scoped replace. A sibling county in the same
    -- state must never be touched by this swap.
    DELETE FROM public.grid_parcels WHERE region_key = v_region;
    INSERT INTO public.grid_parcels (
        id, grid_id, geom, centroid, area_sq_km, state_code, county_name, region, region_key,
        power_distance_miles, substation_distance_miles, substation_voltage_kv,
        substation_name, grid_operator, groundwater_depth_ft, surface_water_distance_miles,
        water_availability_index, nearest_gauge_id, seismic_hazard_pga, flood_risk_score,
        hurricane_risk_score, aggregate_risk_score, cooling_degree_days, ambient_avg_temp_f,
        free_cooling_potential_hours, power_score, water_score, risk_score, climate_score,
        composite_score_unrisked, evidence_coverage, evidence_tier, cluster_zone_id, cluster_label, is_prime_zone,
        megawatt_capacity_estimate, metadata, created_at, updated_at, source_run_id,
        ixp_nearest_facility, ixp_nearest_distance_miles, ixp_latency_floor_ms,
        ixp_networks_at_nearest, ixp_facilities_within_25mi, ixp_networks_within_25mi,
        ixp_best_networks_within_25mi
    )
    SELECT
        s.id, s.grid_id, s.geom, s.centroid, s.area_sq_km, s.state_code, s.county_name, s.region, s.region_key,
        s.power_distance_miles, s.substation_distance_miles, s.substation_voltage_kv,
        s.substation_name, s.grid_operator, s.groundwater_depth_ft, s.surface_water_distance_miles,
        s.water_availability_index, s.nearest_gauge_id, s.seismic_hazard_pga, s.flood_risk_score,
        s.hurricane_risk_score, s.aggregate_risk_score, s.cooling_degree_days, s.ambient_avg_temp_f,
        s.free_cooling_potential_hours, s.power_score, s.water_score, s.risk_score, s.climate_score,
        s.composite_score_unrisked, s.evidence_coverage, s.evidence_tier, s.cluster_zone_id, s.cluster_label, s.is_prime_zone,
        s.megawatt_capacity_estimate, s.metadata, s.created_at, s.updated_at, s.run_id,
        s.ixp_nearest_facility, s.ixp_nearest_distance_miles, s.ixp_latency_floor_ms,
        s.ixp_networks_at_nearest, s.ixp_facilities_within_25mi, s.ixp_networks_within_25mi,
        s.ixp_best_networks_within_25mi
    FROM public.stg_grid_parcels s WHERE s.run_id = p_run_id;

    -- Map features: region-scoped replace. A line or substation crossing
    -- two counties of one state is a row per region under the new unique
    -- constraint, so neither county's promote deletes the other's.
    DELETE FROM public.transmission_lines WHERE region_key = v_region;
    INSERT INTO public.transmission_lines (
        id, feature_id, state_code, region_key, owner, voltage_kv, volt_class, line_name, geom, created_at
    )
    SELECT s.id, s.feature_id, s.state_code, s.region_key, s.owner, s.voltage_kv, s.volt_class,
           s.line_name, s.geom, s.created_at
    FROM public.stg_transmission_lines s WHERE s.run_id = p_run_id;

    DELETE FROM public.substations WHERE region_key = v_region;
    INSERT INTO public.substations (id, feature_id, state_code, region_key, substation_name, voltage_kv, geom, created_at)
    SELECT s.id, s.feature_id, s.state_code, s.region_key, s.substation_name, s.voltage_kv, s.geom, s.created_at
    FROM public.stg_substations s WHERE s.run_id = p_run_id;

    DELETE FROM public.observation_wells WHERE region_key = v_region;
    INSERT INTO public.observation_wells (id, site_no, state_code, region_key, water_depth_ft, geom, created_at)
    SELECT s.id, s.site_no, s.state_code, s.region_key, s.water_depth_ft, s.geom, s.created_at
    FROM public.stg_observation_wells s WHERE s.run_id = p_run_id;

    -- RTEP upgrades: genuinely state-scoped. The dataset is fetched per
    -- state and every run of either county in the state stages the full
    -- set, so the state-scoped replace stays idempotent.
    DELETE FROM public.power_rtep_upgrades WHERE state_code = v_state;
    INSERT INTO public.power_rtep_upgrades (
        id, upgrade_id, state_code, project_type, description, transmission_owner,
        substation, in_area, voltage_kv, status, equipment, driver, cost_estimate_musd,
        board_approval_date, required_date, projected_in_service_date,
        revised_in_service_date, actual_in_service_date, source_updated, run_id, created_at
    )
    SELECT s.id, s.upgrade_id, s.state_code, s.project_type, s.description, s.transmission_owner,
           s.substation, s.in_area, s.voltage_kv, s.status, s.equipment, s.driver, s.cost_estimate_musd,
           s.board_approval_date, s.required_date, s.projected_in_service_date,
           s.revised_in_service_date, s.actual_in_service_date, s.source_updated, s.run_id, s.created_at
    FROM public.stg_power_rtep_upgrades s WHERE s.run_id = p_run_id;

    -- Land parcels: upsert region-scoped; the is_active sweep is scoped to
    -- the region so a sibling county's parcels are never deactivated.
    INSERT INTO public.land_parcels (
        id, parcel_key, source_parcel_id, state_code, county_name, region_key, geom,
        gis_acreage, legal_acreage, first_run_id, latest_run_id, is_active
    )
    SELECT s.id, s.parcel_key, s.source_parcel_id, s.state_code, s.county_name, s.region_key, s.geom,
           s.gis_acreage, s.legal_acreage, p_run_id, p_run_id, TRUE
    FROM public.stg_land_parcels s WHERE s.run_id = p_run_id
    ON CONFLICT (parcel_key) DO UPDATE SET
        source_parcel_id = EXCLUDED.source_parcel_id,
        geom = EXCLUDED.geom,
        gis_acreage = EXCLUDED.gis_acreage,
        legal_acreage = EXCLUDED.legal_acreage,
        latest_run_id = p_run_id,
        is_active = TRUE;

    UPDATE public.land_parcels lp SET is_active = FALSE, updated_at = TIMEZONE('utc', NOW())
    WHERE lp.region_key = v_region
      AND lp.is_active
      AND NOT EXISTS (
          SELECT 1 FROM public.stg_land_parcels s
          WHERE s.run_id = p_run_id AND s.parcel_key = lp.parcel_key
      );

    DELETE FROM public.parcel_metric_values WHERE run_id = p_run_id;
    INSERT INTO public.parcel_metric_values (
        parcel_id, run_id, metric_key, value, text_value, unit,
        evidence_class, source_snapshot_id, retrieved_at, details
    )
    SELECT lp.id, s.run_id, s.metric_key, s.value, s.text_value, s.unit,
           s.evidence_class, s.source_snapshot_id, s.retrieved_at, s.details
    FROM public.stg_parcel_metric_values s
    JOIN public.land_parcels lp ON lp.parcel_key = s.parcel_key
    WHERE s.run_id = p_run_id;

    DELETE FROM public.parcel_gate_results WHERE run_id = p_run_id;
    INSERT INTO public.parcel_gate_results (
        parcel_id, run_id, gate_key, status, affected_area_pct, rationale, rule_id, details
    )
    SELECT lp.id, s.run_id, s.gate_key, s.status, s.affected_area_pct, s.rationale, s.rule_id, s.details
    FROM public.stg_parcel_gate_results s
    JOIN public.land_parcels lp ON lp.parcel_key = s.parcel_key
    WHERE s.run_id = p_run_id;

    DELETE FROM public.stg_grid_parcels WHERE run_id = p_run_id;
    DELETE FROM public.stg_transmission_lines WHERE run_id = p_run_id;
    DELETE FROM public.stg_substations WHERE run_id = p_run_id;
    DELETE FROM public.stg_observation_wells WHERE run_id = p_run_id;
    DELETE FROM public.stg_power_rtep_upgrades WHERE run_id = p_run_id;
    DELETE FROM public.stg_land_parcels WHERE run_id = p_run_id;
    DELETE FROM public.stg_parcel_metric_values WHERE run_id = p_run_id;
    DELETE FROM public.stg_parcel_gate_results WHERE run_id = p_run_id;

    SELECT jsonb_build_object(
        'region', v_region,
        'grid_parcels', (SELECT COUNT(*) FROM public.grid_parcels WHERE region_key = v_region AND source_run_id = p_run_id),
        'grid_parcels_with_interconnection', (SELECT COUNT(*) FROM public.grid_parcels WHERE region_key = v_region AND source_run_id = p_run_id AND ixp_best_networks_within_25mi IS NOT NULL),
        'land_parcels_active', (SELECT COUNT(*) FROM public.land_parcels WHERE region_key = v_region AND is_active),
        'parcel_metrics', (SELECT COUNT(*) FROM public.parcel_metric_values WHERE run_id = p_run_id),
        'parcel_gates', (SELECT COUNT(*) FROM public.parcel_gate_results WHERE run_id = p_run_id),
        'power_rtep_upgrades', (SELECT COUNT(*) FROM public.power_rtep_upgrades WHERE state_code = v_state)
    ) INTO v_counts;

    UPDATE public.ingestion_runs
    SET status = 'succeeded', finished_at = TIMEZONE('utc', NOW()), stats = stats || v_counts
    WHERE id = p_run_id;

    -- Supersession is per region (county slug), so a Licking run never
    -- supersedes Franklin's succeeded run.
    UPDATE public.ingestion_runs
    SET status = 'superseded'
    WHERE region_code = v_region AND status = 'succeeded' AND id <> p_run_id;

    RETURN v_counts;
END;
$function$;

REVOKE ALL ON FUNCTION public.promote_ingestion_run(UUID) FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION public.promote_ingestion_run(UUID) TO service_role;
