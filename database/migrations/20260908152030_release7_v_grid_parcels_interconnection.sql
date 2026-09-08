-- v_grid_parcels names its columns explicitly, so adding them to the table
-- did not expose them. The client selects * from this view, which means
-- the interconnection layer would have been computed, staged, promoted and
-- then invisible.
--
-- Appended rather than grouped with the other site factors: CREATE OR
-- REPLACE VIEW may only add columns at the end, and dropping the view to
-- reorder them would break every reader mid-deploy for cosmetics.
CREATE OR REPLACE VIEW public.v_grid_parcels AS
 SELECT id, grid_id, state_code, county_name, region, area_sq_km,
    st_x(centroid) AS lon,
    st_y(centroid) AS lat,
    st_asgeojson(geom)::jsonb AS geojson_geom,
    power_distance_miles, substation_distance_miles, substation_voltage_kv,
    substation_name, grid_operator, groundwater_depth_ft,
    surface_water_distance_miles, water_availability_index, nearest_gauge_id,
    seismic_hazard_pga, flood_risk_score, hurricane_risk_score,
    aggregate_risk_score, cooling_degree_days, ambient_avg_temp_f,
    free_cooling_potential_hours, power_score, water_score, risk_score,
    climate_score, composite_score, cluster_zone_id, cluster_label,
    is_prime_zone, megawatt_capacity_estimate, metadata,
    created_at, updated_at, source_run_id,
    ixp_nearest_facility, ixp_nearest_distance_miles, ixp_latency_floor_ms,
    ixp_networks_at_nearest, ixp_facilities_within_25mi,
    ixp_networks_within_25mi, ixp_best_networks_within_25mi
   FROM grid_parcels gp;
