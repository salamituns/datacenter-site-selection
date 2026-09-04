-- ============================================================================
-- Migration: 20260902000000_map_features.sql
-- Description: Persist real HIFLD power features and USGS NWIS wells per
--              survey region so the map renders live infrastructure
--              markers (transmission corridors, substations, wells)
--              instead of demo-hardcoded Loudoun points.
-- ============================================================================

-- 1. Transmission lines (HIFLD Electric_Power_Transmission_Lines)
--    One row per simple line segment; MultiLineStrings are exploded by the
--    worker (feature_id gains a -1/-2 part suffix).
CREATE TABLE IF NOT EXISTS public.transmission_lines (
    id UUID PRIMARY KEY DEFAULT extensions.gen_random_uuid(),
    feature_id VARCHAR(64) NOT NULL,                 -- HIFLD GLOBALID (plus part suffix)
    state_code VARCHAR(2) NOT NULL,
    owner VARCHAR(150),
    voltage_kv NUMERIC(8, 2) NOT NULL,               -- normalized kV (upper bound of class)
    volt_class VARCHAR(50),                          -- raw VOLT_CLASS label, e.g. "230 kV"
    line_name VARCHAR(255),                          -- "SUB_1 → SUB_2"
    geom extensions.geometry(LineString, 4326) NOT NULL,
    created_at TIMESTAMPTZ DEFAULT TIMEZONE('utc'::text, NOW()) NOT NULL,

    UNIQUE (state_code, feature_id)
);

-- 2. Substations (HIFLD Electric_Substations, >= 100 kV)
CREATE TABLE IF NOT EXISTS public.substations (
    id UUID PRIMARY KEY DEFAULT extensions.gen_random_uuid(),
    feature_id VARCHAR(64) NOT NULL,                 -- HIFLD GLOBALID
    state_code VARCHAR(2) NOT NULL,
    substation_name VARCHAR(150) NOT NULL,
    voltage_kv NUMERIC(8, 2) NOT NULL,               -- MAX_VOLT (transmission floor applied)
    geom extensions.geometry(Point, 4326) NOT NULL,
    created_at TIMESTAMPTZ DEFAULT TIMEZONE('utc'::text, NOW()) NOT NULL,

    UNIQUE (state_code, feature_id)
);

-- 3. Observation wells (USGS NWIS groundwater sites, parameter 72019)
CREATE TABLE IF NOT EXISTS public.observation_wells (
    id UUID PRIMARY KEY DEFAULT extensions.gen_random_uuid(),
    site_no VARCHAR(50) NOT NULL,                    -- NWIS site number
    state_code VARCHAR(2) NOT NULL,
    water_depth_ft NUMERIC(8, 2),                    -- depth to water table (ft)
    geom extensions.geometry(Point, 4326) NOT NULL,
    created_at TIMESTAMPTZ DEFAULT TIMEZONE('utc'::text, NOW()) NOT NULL,

    UNIQUE (state_code, site_no)
);

-- 4. Spatial + attribute indexes
CREATE INDEX IF NOT EXISTS idx_transmission_lines_geom
    ON public.transmission_lines USING GIST (geom);
CREATE INDEX IF NOT EXISTS idx_transmission_lines_state
    ON public.transmission_lines (state_code);

CREATE INDEX IF NOT EXISTS idx_substations_geom
    ON public.substations USING GIST (geom);
CREATE INDEX IF NOT EXISTS idx_substations_state
    ON public.substations (state_code);

CREATE INDEX IF NOT EXISTS idx_observation_wells_geom
    ON public.observation_wells USING GIST (geom);
CREATE INDEX IF NOT EXISTS idx_observation_wells_state
    ON public.observation_wells (state_code);

-- 5. Client-facing views (GeoJSON / lon-lat decoded, matching v_grid_parcels)
CREATE OR REPLACE VIEW public.v_transmission_lines AS
SELECT
    id,
    feature_id,
    state_code,
    owner,
    voltage_kv,
    volt_class,
    line_name,
    extensions.ST_AsGeoJSON(geom)::jsonb AS geojson_geom
FROM public.transmission_lines;

CREATE OR REPLACE VIEW public.v_substations AS
SELECT
    id,
    feature_id,
    state_code,
    substation_name,
    voltage_kv,
    extensions.ST_X(geom) AS lon,
    extensions.ST_Y(geom) AS lat
FROM public.substations;

CREATE OR REPLACE VIEW public.v_observation_wells AS
SELECT
    id,
    site_no,
    state_code,
    water_depth_ft,
    extensions.ST_X(geom) AS lon,
    extensions.ST_Y(geom) AS lat
FROM public.observation_wells;

-- 6. Row Level Security — public read, service-role write
--    (the anonymous write policies were a later, separate migration —
--    see 20260902025419_map_features_anon_write.sql, revoked in Release 0)
DROP POLICY IF EXISTS "Allow public read access to transmission lines"
    ON public.transmission_lines;
CREATE POLICY "Allow public read access to transmission lines"
    ON public.transmission_lines FOR SELECT TO anon, authenticated USING (true);
DROP POLICY IF EXISTS "Allow service role full access to transmission lines"
    ON public.transmission_lines;
CREATE POLICY "Allow service role full access to transmission lines"
    ON public.transmission_lines FOR ALL TO service_role USING (true) WITH CHECK (true);

ALTER TABLE public.substations ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS "Allow public read access to substations"
    ON public.substations;
CREATE POLICY "Allow public read access to substations"
    ON public.substations FOR SELECT TO anon, authenticated USING (true);
DROP POLICY IF EXISTS "Allow service role full access to substations"
    ON public.substations;
CREATE POLICY "Allow service role full access to substations"
    ON public.substations FOR ALL TO service_role USING (true) WITH CHECK (true);

ALTER TABLE public.observation_wells ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS "Allow public read access to observation wells"
    ON public.observation_wells;
CREATE POLICY "Allow public read access to observation wells"
    ON public.observation_wells FOR SELECT TO anon, authenticated USING (true);
DROP POLICY IF EXISTS "Allow service role full access to observation wells"
    ON public.observation_wells;
CREATE POLICY "Allow service role full access to observation wells"
    ON public.observation_wells FOR ALL TO service_role USING (true) WITH CHECK (true);
