-- ============================================================================
-- Migration: release0_security
-- Description: Evidence-safe foundation, part 1 — security posture.
--   * Remove anonymous/authenticated WRITE access from every ingestion
--     table (grid_parcels + the map feature tables carried full-write
--     policies since the map_features_anon_write migration).
--   * Revoke write grants from the API roles as belt-and-braces to RLS.
--   * Make all client-facing views security_invoker so they respect the
--     underlying RLS instead of evaluating as the view owner.
--   * Track v_grid_parcels (previously created outside any migration).
--   * Explicit Data API grants for everything the client reads.
-- ============================================================================

-- 1. Remove anonymous write policies
DROP POLICY IF EXISTS "Allow anon and service role write access" ON public.grid_parcels;
DROP POLICY IF EXISTS "Allow anon and service role write access" ON public.transmission_lines;
DROP POLICY IF EXISTS "Allow anon and service role write access" ON public.substations;
DROP POLICY IF EXISTS "Allow anon and service role write access" ON public.observation_wells;

-- 2. Grant-level hardening: the API roles may only read ingestion tables
REVOKE INSERT, UPDATE, DELETE, TRUNCATE
    ON public.grid_parcels, public.transmission_lines,
       public.substations, public.observation_wells
    FROM anon, authenticated;

-- 3. Client-facing views become security_invoker (Postgres 15+): view
--    queries run with the caller's rights and respect underlying RLS.
ALTER VIEW public.v_grid_parcels SET (security_invoker = true);
ALTER VIEW public.v_transmission_lines SET (security_invoker = true);
ALTER VIEW public.v_substations SET (security_invoker = true);
ALTER VIEW public.v_observation_wells SET (security_invoker = true);

-- 4. Bring v_grid_parcels under migration management — identical definition
--    to the manually created view, plus the invoker attribute above.
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
    updated_at
FROM public.grid_parcels gp;
ALTER VIEW public.v_grid_parcels SET (security_invoker = true);

-- 5. Explicit Data API grants (Supabase no longer auto-exposes tables —
--    enforcement across projects is scheduled for 2026-10-30)
GRANT SELECT ON public.grid_parcels, public.transmission_lines,
    public.substations, public.observation_wells,
    public.v_grid_parcels, public.v_transmission_lines,
    public.v_substations, public.v_observation_wells
    TO anon, authenticated;
