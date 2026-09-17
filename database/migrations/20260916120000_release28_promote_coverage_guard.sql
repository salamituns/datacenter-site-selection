-- ============================================================================
-- Migration: release28_promote_coverage_guard
-- Description: promote refuses a coverage regression, and the runs now
--              record which layers answered.
--
--   Taylor County was republished to fix a wetlands bug, PAD-US was
--   unreachable that afternoon, and the pipeline degraded honestly —
--   layers missing, protected-land verdicts UNKNOWN — and promoted anyway.
--   91 decided verdicts were replaced with 4,356 UNKNOWNs, and nothing in
--   the promote path could see the difference between "the layer answered
--   and agreed" and "nobody looked".
--
--   The worker now records stats.layers as {layer: "present"|"missing"} on
--   every run before promote (both tiers, one shape — the screening tier
--   uses the parcel tier's layer names so a county that gains a cadastral
--   adapter does not read as losing its screening layers to a rename).
--   This migration gives promote_ingestion_run the guard that map exists
--   for: before the first DELETE, the run's layer map is compared against
--   the live succeeded generation for the same region, and a layer that was
--   present and is now missing fails the publish by name.
--
--   Scope of the comparison, deliberately narrow:
--     * Layer availability is categorical and computed; gate counts are
--       not comparable across a rule change or a new evidence layer, and a
--       difference there is a correction, not a regression.
--     * A first publish proceeds: no live generation, nothing to lose.
--     * A legacy live generation without stats.layers proceeds: nothing to
--       compare against. The map lands with this generation and the next
--       publish is guarded.
--     * Adding a layer proceeds: the guard only fires on present→missing.
--     * A run with no map at all (worker predating this change, or a
--       --no-parcels run that measured nothing) against a live generation
--       WITH a map reads as missing every live layer and is refused — a
--       --no-parcels republish would deactivate every parcel in the region
--       anyway, so refusing it is the conservative reading, not a quirk.
--     * p_allow_coverage_regression is the operator override: a deliberate,
--       named decision to publish a regression, never something a
--       scheduled run passes.
--
--   The signature change (new parameter, defaulted) is a DROP + CREATE, not
--   CREATE OR REPLACE: Postgres would keep the old one-argument function as
--   a live overload, and an unguarded promote_ingestion_run(uuid) still
--   callable on production is exactly the hole this closes.
--
--   Applied 2026-09-16, before the PJM screening sweep.
-- ============================================================================

DROP FUNCTION IF EXISTS public.promote_ingestion_run(uuid);

CREATE FUNCTION public.promote_ingestion_run(
    p_run_id uuid,
    p_allow_coverage_regression boolean DEFAULT false
)
 RETURNS jsonb
 LANGUAGE plpgsql
 SECURITY DEFINER
 SET search_path TO 'public', 'extensions'
 SET statement_timeout TO '10min'
AS $function$
DECLARE
    v_region TEXT;
    v_state VARCHAR(2);
    v_counts JSONB;
    v_new_layers JSONB;
    v_live_layers JSONB;
    v_lost TEXT;
BEGIN
    SELECT region_code INTO v_region FROM public.ingestion_runs
    WHERE id = p_run_id AND status = 'running';
    IF v_region IS NULL THEN
        RAISE EXCEPTION 'ingestion run % is not in running state', p_run_id;
    END IF;
    v_state := SPLIT_PART(v_region, '-', 1);

    -- ── Coverage guard, before the first DELETE ────────────────────────
    -- A publish may not silently drop a layer the live generation had.
    -- Everything below this point deletes the live generation's evidence;
    -- a run that would fail it is refused here, inside the same
    -- transaction, so a refused publish leaves the live data untouched.
    IF NOT p_allow_coverage_regression THEN
        SELECT stats -> 'layers' INTO v_new_layers
        FROM public.ingestion_runs WHERE id = p_run_id;

        SELECT r.stats -> 'layers' INTO v_live_layers
        FROM public.ingestion_runs r
        WHERE r.region_code = v_region AND r.status = 'succeeded'
        ORDER BY r.finished_at DESC NULLS LAST
        LIMIT 1;

        -- No live generation (first publish) or one that predates
        -- stats.layers: nothing to compare against, the publish proceeds.
        IF v_live_layers IS NOT NULL THEN
            SELECT string_agg(l.key, ', ' ORDER BY l.key) INTO v_lost
            FROM jsonb_each_text(v_live_layers) l
            WHERE l.value = 'present'
              AND COALESCE(v_new_layers ->> l.key, 'missing') = 'missing';

            IF v_lost IS NOT NULL THEN
                RAISE EXCEPTION USING
                    ERRCODE = 'assert_failure',
                    MESSAGE = format(
                        'coverage regression for %s: layers present in the '
                        'live generation are missing from run %s: %s',
                        v_region, p_run_id, v_lost),
                    HINT = 'Re-run when the layer is reachable, or pass '
                           'p_allow_coverage_regression=true to publish the '
                           'regression deliberately.';
            END IF;
        END IF;
    END IF;

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

    UPDATE public.ingestion_runs
    SET status = 'superseded'
    WHERE region_code = v_region AND status = 'succeeded' AND id <> p_run_id;

    RETURN v_counts;
END;
$function$;

COMMENT ON FUNCTION public.promote_ingestion_run(uuid, boolean) IS
    'Atomically publishes a staged run. Refuses, before any DELETE, a run whose stats.layers marks missing a layer the live succeeded generation for the region had present — the Taylor County PAD-US incident. p_allow_coverage_regression=true overrides deliberately.';
