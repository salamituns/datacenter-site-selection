-- ============================================================================
-- Migration: release9_evidence_tier
-- Description: Rank by evidence tier first, then by coverage-weighted score.
--
--   Release 9 scaled the screening composite by evidence_coverage so an
--   under-evidenced site could not out-rank a fully diligenced one. That is
--   right for regions that HAVE a parcel tier — Ohio at 0.772 and Texas at
--   0.664 carry a real, proportionate penalty. It is wrong for a region with
--   no parcel tier at all: multiplying by 0.0 is not a penalty, it is an
--   annihilator. Morrow County, OR lost all 330 of its composites to a single
--   0.00, which
--     (a) discarded screening evidence that was actually observed — Oregon
--         carries the best climate score of the four regions (97.2), which is
--         precisely why the high desert is real data-centre country, and
--     (b) collapsed the region's internal ranking, so no Oregon cell could be
--         told from any other.
--
--   That is the zero-versus-absent error this engine refuses everywhere else:
--   a 0.00 composite reads as "measured, and worthless" when the truth is
--   "surveyed at screening tier, never underwritten at parcel tier".
--
--   The fix is lexicographic. evidence_tier records WHICH survey a cell has
--   had ('parcel' | 'screening'); evidence_coverage keeps recording HOW MUCH
--   of that survey resolved. Ranking compares tier first and score second, so
--   a diligenced site out-ranks an under-evidenced one whatever the scores,
--   while screening-tier regions keep their real numbers and their internal
--   order. The multiplicative coverage weight now applies only within the
--   parcel tier, where it is never degenerate.
--
--   evidence_tier is stored, not derived from evidence_coverage > 0: a region
--   that has parcels but decides none of their gates is a different fact from
--   a region with no parcels, and this engine keeps those apart.
-- ============================================================================

ALTER TABLE public.grid_parcels
    ADD COLUMN IF NOT EXISTS evidence_tier TEXT NOT NULL DEFAULT 'screening';
ALTER TABLE public.stg_grid_parcels
    ADD COLUMN IF NOT EXISTS evidence_tier TEXT NOT NULL DEFAULT 'screening';

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint WHERE conname = 'grid_parcels_evidence_tier_check'
    ) THEN
        ALTER TABLE public.grid_parcels
            ADD CONSTRAINT grid_parcels_evidence_tier_check
            CHECK (evidence_tier IN ('parcel', 'screening'));
    END IF;
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint WHERE conname = 'stg_grid_parcels_evidence_tier_check'
    ) THEN
        ALTER TABLE public.stg_grid_parcels
            ADD CONSTRAINT stg_grid_parcels_evidence_tier_check
            CHECK (evidence_tier IN ('parcel', 'screening'));
    END IF;
END $$;

-- Backfill: every region that decided any parcel gate had a parcel tier.
-- (A parcel tier that decided nothing would be indistinguishable here, but
-- no such run exists — VA/OH/TX all decided gates, OR has no parcel tier.)
UPDATE public.grid_parcels SET evidence_tier = 'parcel' WHERE evidence_coverage > 0;

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
        composite_score, evidence_coverage, evidence_tier, cluster_zone_id, cluster_label, is_prime_zone,
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
        s.composite_score, s.evidence_coverage, s.evidence_tier, s.cluster_zone_id, s.cluster_label, s.is_prime_zone,
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
