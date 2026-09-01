-- ============================================================================
-- Migration: 20260831000000_init_postgis_parcels.sql
-- Description: Initialize PostGIS extension and schema for 10-sq-km parcel grids
-- Engine: AI Data Center Site Selection Engine (100+ MW Hyperscale)
-- ============================================================================

-- 1. Enable PostGIS and UUID Extensions
CREATE EXTENSION IF NOT EXISTS postgis WITH SCHEMA extensions;
CREATE EXTENSION IF NOT EXISTS "uuid-ossp" WITH SCHEMA extensions;
CREATE EXTENSION IF NOT EXISTS pgcrypto WITH SCHEMA extensions;

-- Grant permissions if necessary in Supabase
GRANT USAGE ON SCHEMA extensions TO postgres, anon, authenticated, service_role;

-- 2. Create Grid Parcels Table
CREATE TABLE IF NOT EXISTS public.grid_parcels (
    id UUID PRIMARY KEY DEFAULT extensions.gen_random_uuid(),
    grid_id VARCHAR(64) UNIQUE NOT NULL,                       -- e.g. "US-VA-LOUDOUN-10KM-0482"
    
    -- Spatial Geometry (WGS84 EPSG:4326)
    geom extensions.geometry(Polygon, 4326) NOT NULL,          -- 10 km x 10 km bounding polygon
    centroid extensions.geometry(Point, 4326) NOT NULL,        -- Center point for fast coordinate lookups
    area_sq_km NUMERIC(10, 2) DEFAULT 10.00 NOT NULL,
    
    -- Geographic identifiers
    state_code VARCHAR(2),
    county_name VARCHAR(120),
    region VARCHAR(60),                                        -- e.g. "PJM Interconnection", "ERCOT", "MISO"
    
    -- 1. Power Grid Proximity (HIFLD)
    power_distance_miles NUMERIC(8, 2) NOT NULL DEFAULT 999.0, -- Distance to nearest 115kV+ transmission line
    substation_distance_miles NUMERIC(8, 2) NOT NULL DEFAULT 999.0,
    substation_voltage_kv NUMERIC(8, 2) DEFAULT 0.0,           -- e.g. 230kV, 500kV
    substation_name VARCHAR(150),
    grid_operator VARCHAR(60),                                 -- ISO / RTO (e.g. "PJM", "CAISO", "ERCOT")
    
    -- 2. Water Availability (USGS NWIS dataretrieval)
    groundwater_depth_ft NUMERIC(8, 2),                         -- Depth to water table in feet
    surface_water_distance_miles NUMERIC(8, 2),
    water_availability_index NUMERIC(5, 2) DEFAULT 0.0,        -- Normalized 0 - 100 availability score
    nearest_gauge_id VARCHAR(50),
    
    -- 3. Geological & Climate Risk (FEMA NRI & USGS Seismic)
    seismic_hazard_pga NUMERIC(6, 4) DEFAULT 0.0,              -- Peak Ground Acceleration (%g with 2% in 50 yrs)
    flood_risk_score NUMERIC(5, 2) DEFAULT 0.0,                -- FEMA NRI flood composite risk (0 - 100)
    hurricane_risk_score NUMERIC(5, 2) DEFAULT 0.0,            -- FEMA NRI hurricane composite risk (0 - 100)
    aggregate_risk_score NUMERIC(5, 2) DEFAULT 0.0,            -- Combined hazard risk penalty (0 - 100)
    
    -- 4. Ambient Temperature (NOAA NCEI)
    cooling_degree_days NUMERIC(8, 2) DEFAULT 0.0,             -- Annual Cooling Degree Days (Base 65°F)
    ambient_avg_temp_f NUMERIC(5, 2) DEFAULT 60.0,
    free_cooling_potential_hours INTEGER DEFAULT 0,            -- Hours/yr ambient temp < 65°F (economizer hours)
    
    -- Scoring & Machine Learning Clusters
    power_score NUMERIC(5, 2) DEFAULT 0.0,                     -- Sub-score 0 - 100
    water_score NUMERIC(5, 2) DEFAULT 0.0,                     -- Sub-score 0 - 100
    risk_score NUMERIC(5, 2) DEFAULT 0.0,                      -- Sub-score 0 - 100 (100 = lowest risk)
    climate_score NUMERIC(5, 2) DEFAULT 0.0,                   -- Sub-score 0 - 100 (100 = cold / ideal)
    composite_score NUMERIC(6, 2) NOT NULL DEFAULT 0.0,        -- Weighted multi-factor composite (0 - 100)
    
    -- ML Clustering (Scikit-Learn DBSCAN / K-Means)
    cluster_zone_id INTEGER DEFAULT -1,                        -- -1 denotes noise / unclustered
    cluster_label VARCHAR(100),                                -- e.g. "Zone A - Northern Virginia Hyper-Cluster"
    is_prime_zone BOOLEAN DEFAULT FALSE,                       -- True if part of a top contiguous prime cluster
    megawatt_capacity_estimate INTEGER DEFAULT 100,            -- Estimated feasible capacity (e.g. 100MW, 250MW, 500MW+)
    
    -- Metadata and Audit Timestamps
    metadata JSONB DEFAULT '{}'::jsonb,                        -- Extended properties & ingestion lineage
    created_at TIMESTAMPTZ DEFAULT TIMEZONE('utc'::text, NOW()) NOT NULL,
    updated_at TIMESTAMPTZ DEFAULT TIMEZONE('utc'::text, NOW()) NOT NULL
);

-- 3. Spatial Indexes (GiST) & Attribute Performance Indexes
CREATE INDEX IF NOT EXISTS idx_grid_parcels_geom 
    ON public.grid_parcels USING GIST (geom);

CREATE INDEX IF NOT EXISTS idx_grid_parcels_centroid 
    ON public.grid_parcels USING GIST (centroid);

CREATE INDEX IF NOT EXISTS idx_grid_parcels_composite_score 
    ON public.grid_parcels (composite_score DESC);

CREATE INDEX IF NOT EXISTS idx_grid_parcels_prime_zone 
    ON public.grid_parcels (is_prime_zone, composite_score DESC);

CREATE INDEX IF NOT EXISTS idx_grid_parcels_cluster_zone 
    ON public.grid_parcels (cluster_zone_id) WHERE cluster_zone_id >= 0;

CREATE INDEX IF NOT EXISTS idx_grid_parcels_state 
    ON public.grid_parcels (state_code);

-- 4. Automatic updated_at Trigger
CREATE OR REPLACE FUNCTION public.handle_updated_at()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = TIMEZONE('utc'::text, NOW());
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS set_grid_parcels_updated_at ON public.grid_parcels;
CREATE TRIGGER set_grid_parcels_updated_at
    BEFORE UPDATE ON public.grid_parcels
    FOR EACH ROW
    EXECUTE FUNCTION public.handle_updated_at();

-- 5. Stored Spatial RPC Functions for Web Client

-- 5.1 Query parcels within a map viewport bounding box (GeoJSON output)
CREATE OR REPLACE FUNCTION public.get_parcels_in_bbox(
    min_lon DOUBLE PRECISION,
    min_lat DOUBLE PRECISION,
    max_lon DOUBLE PRECISION,
    max_lat DOUBLE PRECISION,
    min_composite_score NUMERIC DEFAULT 0.0,
    only_prime_zones BOOLEAN DEFAULT FALSE,
    max_results INTEGER DEFAULT 500
)
RETURNS TABLE (
    id UUID,
    grid_id VARCHAR,
    geojson_geom JSONB,
    lon DOUBLE PRECISION,
    lat DOUBLE PRECISION,
    composite_score NUMERIC,
    power_score NUMERIC,
    water_score NUMERIC,
    risk_score NUMERIC,
    climate_score NUMERIC,
    power_distance_miles NUMERIC,
    substation_voltage_kv NUMERIC,
    water_availability_index NUMERIC,
    seismic_hazard_pga NUMERIC,
    cooling_degree_days NUMERIC,
    cluster_zone_id INTEGER,
    is_prime_zone BOOLEAN,
    megawatt_capacity_estimate INTEGER,
    state_code VARCHAR,
    county_name VARCHAR
) 
LANGUAGE sql
STABLE
AS $$
    SELECT 
        gp.id,
        gp.grid_id,
        extensions.ST_AsGeoJSON(gp.geom)::jsonb AS geojson_geom,
        extensions.ST_X(gp.centroid) AS lon,
        extensions.ST_Y(gp.centroid) AS lat,
        gp.composite_score,
        gp.power_score,
        gp.water_score,
        gp.risk_score,
        gp.climate_score,
        gp.power_distance_miles,
        gp.substation_voltage_kv,
        gp.water_availability_index,
        gp.seismic_hazard_pga,
        gp.cooling_degree_days,
        gp.cluster_zone_id,
        gp.is_prime_zone,
        gp.megawatt_capacity_estimate,
        gp.state_code,
        gp.county_name
    FROM public.grid_parcels gp
    WHERE 
        gp.geom && extensions.ST_MakeEnvelope(min_lon, min_lat, max_lon, max_lat, 4326)
        AND gp.composite_score >= min_composite_score
        AND (NOT only_prime_zones OR gp.is_prime_zone = TRUE)
    ORDER BY gp.composite_score DESC
    LIMIT max_results;
$$;

-- 5.2 Retrieve aggregated prime cluster zone polygons (ST_Union of contiguous cells)
CREATE OR REPLACE FUNCTION public.get_prime_cluster_polygons()
RETURNS TABLE (
    cluster_zone_id INTEGER,
    cluster_label VARCHAR,
    parcel_count BIGINT,
    avg_composite_score NUMERIC,
    total_area_sq_km NUMERIC,
    total_mw_capacity BIGINT,
    cluster_boundary_geojson JSONB
)
LANGUAGE sql
STABLE
AS $$
    SELECT 
        gp.cluster_zone_id,
        COALESCE(MAX(gp.cluster_label), 'Cluster Zone ' || gp.cluster_zone_id::text) AS cluster_label,
        COUNT(gp.id) AS parcel_count,
        ROUND(AVG(gp.composite_score), 2) AS avg_composite_score,
        ROUND(SUM(gp.area_sq_km), 2) AS total_area_sq_km,
        SUM(gp.megawatt_capacity_estimate) AS total_mw_capacity,
        extensions.ST_AsGeoJSON(extensions.ST_UnaryUnion(extensions.ST_Collect(gp.geom)))::jsonb AS cluster_boundary_geojson
    FROM public.grid_parcels gp
    WHERE gp.cluster_zone_id >= 0 AND gp.is_prime_zone = TRUE
    GROUP BY gp.cluster_zone_id
    ORDER BY avg_composite_score DESC;
$$;

-- 6. Row Level Security (RLS)
ALTER TABLE public.grid_parcels ENABLE ROW LEVEL SECURITY;

-- Allow public read-only access to grid parcels
CREATE POLICY "Allow public read access to grid parcels"
    ON public.grid_parcels
    FOR SELECT
    TO anon, authenticated
    USING (true);

-- Allow service role full read/write access for Python worker ingestion
CREATE POLICY "Allow service role full access"
    ON public.grid_parcels
    FOR ALL
    TO service_role
    USING (true)
    WITH CHECK (true);
