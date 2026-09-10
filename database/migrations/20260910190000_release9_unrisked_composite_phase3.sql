-- ============================================================================
-- Migration: release9_unrisked_composite_phase3
-- Description: Make the risked composite a generated column and stop storing it.
--
--   Phase 3 of docs/unrisked-composite-spec.md. The worker no longer writes
--   composite_score at all: the database derives it from the measurement, so
--   no multiplication can ever overwrite a measurement again. The 0.0 case is
--   handled once, in one expression, in the schema.
--
--   Phase 2 republished all four regions and the gate query found 2 rows out
--   of 1,338 where the two sides disagreed — both Loudoun cells whose product
--   lands exactly on 69.65 (70.00 x 0.995). numpy's .round(1) is half-to-even
--   and wrote 69.6; SQL round() is half away from zero and writes 69.7. This
--   migration therefore moves those two cells by 0.1, deliberately, onto the
--   convention this project already adopted in worker/parcel_gates.py
--   (_round_half_away, added after a p90 read 47 in Python and 48 in SQL).
--   Deleting the worker's multiplication removes the divergence at its source
--   rather than papering over it.
--
--   composite_score_unrisked becomes NOT NULL: every row now carries a
--   measurement, and the generated expression must never yield NULL.
-- ============================================================================

-- Guard: phase 3 is only safe once every row carries a measurement.
DO $$
DECLARE v_missing INT;
BEGIN
    SELECT count(*) INTO v_missing
    FROM public.grid_parcels WHERE composite_score_unrisked IS NULL;
    IF v_missing > 0 THEN
        RAISE EXCEPTION
          'phase 3 blocked: % grid cells have no unrisked composite — republish them first',
          v_missing;
    END IF;
END $$;

ALTER TABLE public.grid_parcels
    ALTER COLUMN composite_score_unrisked SET NOT NULL;
ALTER TABLE public.stg_grid_parcels
    ALTER COLUMN composite_score_unrisked SET NOT NULL;

-- The view depends on composite_score, and a column cannot be made generated
-- in place, so both come down and go back up. This is also the only chance to
-- put composite_score_unrisked in its logical position: CREATE OR REPLACE VIEW
-- matches columns by position and can only append, so the column order set
-- here is the order the view keeps until it is next dropped.
DROP VIEW IF EXISTS public.v_grid_parcels;

-- Dropping the column takes idx_grid_parcels_composite_score and
-- idx_grid_parcels_prime_zone with it; both are recreated below.
ALTER TABLE public.grid_parcels DROP COLUMN composite_score;

ALTER TABLE public.grid_parcels
    ADD COLUMN composite_score NUMERIC(6, 2)
    GENERATED ALWAYS AS (
        round(composite_score_unrisked *
              (CASE WHEN evidence_tier = 'parcel' THEN evidence_coverage ELSE 1 END),
              1)
    ) STORED;

COMMENT ON COLUMN public.grid_parcels.composite_score IS
    'Derived decision figure: the unrisked screening measurement risked by evidence_coverage inside the parcel tier, unscaled outside it. Generated — never written by the worker. See docs/unrisked-composite-spec.md.';

CREATE INDEX idx_grid_parcels_composite_score
    ON public.grid_parcels USING btree (composite_score DESC);
CREATE INDEX idx_grid_parcels_prime_zone
    ON public.grid_parcels USING btree (is_prime_zone, composite_score DESC);

-- Staging no longer carries the risked figure: the worker stops writing it and
-- the promote no longer reads it. A column left behind holding its 0.0 default
-- would be a value nothing produced and nothing consumes.
ALTER TABLE public.stg_grid_parcels DROP COLUMN IF EXISTS composite_score;

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
    evidence_tier
FROM public.grid_parcels gp;
ALTER VIEW public.v_grid_parcels SET (security_invoker = true);

CREATE OR REPLACE FUNCTION public.promote_ingestion_run(p_run_id UUID)
RETURNS JSONB
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path TO 'public', 'extensions'
SET statement_timeout TO '10min'
AS $function$
DECLARE
    v_region TEXT;
    v_state VARCHAR(2);
    v_counts JSONB;
BEGIN
    SELECT region_code INTO v_region FROM public.ingestion_runs
    WHERE id = p_run_id AND status = 'running';
    IF v_region IS NULL THEN
        RAISE EXCEPTION 'ingestion run % is not in running state', p_run_id;
    END IF;
    v_state := v_region;

    DELETE FROM public.grid_parcels WHERE state_code = v_state;
    INSERT INTO public.grid_parcels (
        id, grid_id, geom, centroid, area_sq_km, state_code, county_name, region,
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
        s.id, s.grid_id, s.geom, s.centroid, s.area_sq_km, s.state_code, s.county_name, s.region,
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

    DELETE FROM public.transmission_lines WHERE state_code = v_state;
    INSERT INTO public.transmission_lines (
        id, feature_id, state_code, owner, voltage_kv, volt_class, line_name, geom, created_at
    )
    SELECT s.id, s.feature_id, s.state_code, s.owner, s.voltage_kv, s.volt_class,
           s.line_name, s.geom, s.created_at
    FROM public.stg_transmission_lines s WHERE s.run_id = p_run_id;

    DELETE FROM public.substations WHERE state_code = v_state;
    INSERT INTO public.substations (id, feature_id, state_code, substation_name, voltage_kv, geom, created_at)
    SELECT s.id, s.feature_id, s.state_code, s.substation_name, s.voltage_kv, s.geom, s.created_at
    FROM public.stg_substations s WHERE s.run_id = p_run_id;

    DELETE FROM public.observation_wells WHERE state_code = v_state;
    INSERT INTO public.observation_wells (id, site_no, state_code, water_depth_ft, geom, created_at)
    SELECT s.id, s.site_no, s.state_code, s.water_depth_ft, s.geom, s.created_at
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
        id, parcel_key, source_parcel_id, state_code, county_name, geom,
        gis_acreage, legal_acreage, first_run_id, latest_run_id, is_active
    )
    SELECT s.id, s.parcel_key, s.source_parcel_id, s.state_code, s.county_name, s.geom,
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
    WHERE lp.state_code = v_state
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
        'grid_parcels', (SELECT COUNT(*) FROM public.grid_parcels WHERE state_code = v_state AND source_run_id = p_run_id),
        'grid_parcels_with_interconnection', (SELECT COUNT(*) FROM public.grid_parcels WHERE state_code = v_state AND source_run_id = p_run_id AND ixp_best_networks_within_25mi IS NOT NULL),
        'land_parcels_active', (SELECT COUNT(*) FROM public.land_parcels WHERE state_code = v_state AND is_active),
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

REVOKE ALL ON FUNCTION public.promote_ingestion_run(UUID) FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION public.promote_ingestion_run(UUID) TO service_role;
