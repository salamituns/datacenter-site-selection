-- ============================================================================
-- Migration: release0_provenance
-- Description: Evidence-safe foundation, part 2 — provenance, versioned
--              ingestion runs, cadastral land parcels with typed metric and
--              gate tables, staging tables and an atomic promote RPC.
--
--   Spatial hierarchy: survey region → screening cell (grid_parcels) →
--   cadastral land parcel → candidate site (later release).
--
--   Typed tables hold operational data; JSON only carries source-specific
--   metadata (quality payloads, rule params, transformation notes).
-- ============================================================================

-- ── 1. Provenance registry ─────────────────────────────────────────────────

CREATE TABLE public.data_sources (
    id UUID PRIMARY KEY DEFAULT extensions.gen_random_uuid(),
    source_key VARCHAR(80) UNIQUE NOT NULL,        -- 'loudoun_parcels', 'nwi_wetlands'
    organization VARCHAR(200) NOT NULL,
    dataset VARCHAR(200) NOT NULL,
    endpoint_url TEXT NOT NULL,
    license VARCHAR(200),
    description TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT TIMEZONE('utc', NOW())
);

CREATE TABLE public.ingestion_runs (
    id UUID PRIMARY KEY DEFAULT extensions.gen_random_uuid(),
    run_key VARCHAR(140) UNIQUE NOT NULL,          -- 'VA-20260904T2015Z-a3f2'
    region_code VARCHAR(8) NOT NULL,               -- 'VA', 'TX', ...
    pipeline_version VARCHAR(40) NOT NULL,
    status VARCHAR(16) NOT NULL DEFAULT 'running'
        CHECK (status IN ('running', 'succeeded', 'failed', 'superseded')),
    trigger VARCHAR(30) NOT NULL DEFAULT 'manual'
        CHECK (trigger IN ('manual', 'scheduled', 'backfill', 'operator')),
    config JSONB NOT NULL DEFAULT '{}',            -- bbox, thresholds, flags
    stats JSONB NOT NULL DEFAULT '{}',             -- counts, quality rollup
    error TEXT,
    started_at TIMESTAMPTZ NOT NULL DEFAULT TIMEZONE('utc', NOW()),
    finished_at TIMESTAMPTZ
);

CREATE INDEX idx_ingestion_runs_region_status
    ON public.ingestion_runs (region_code, status, started_at DESC);

CREATE TABLE public.source_snapshots (
    id UUID PRIMARY KEY DEFAULT extensions.gen_random_uuid(),
    run_id UUID NOT NULL REFERENCES public.ingestion_runs (id) ON DELETE CASCADE,
    source_id UUID REFERENCES public.data_sources (id),
    layer VARCHAR(80) NOT NULL,                    -- 'zoning', 'wetlands', 'power_lines'
    endpoint_url TEXT NOT NULL,
    retrieved_at TIMESTAMPTZ NOT NULL DEFAULT TIMEZONE('utc', NOW()),
    record_count INTEGER,
    dataset_version VARCHAR(80),                   -- e.g. zoning ordinance vintage
    evidence_class VARCHAR(16) NOT NULL DEFAULT 'observed'
        CHECK (evidence_class IN ('observed', 'derived', 'estimated', 'manual', 'fallback')),
    quality JSONB NOT NULL DEFAULT '{}',           -- null rates, geom validity, coverage
    notes TEXT
);

CREATE INDEX idx_source_snapshots_run ON public.source_snapshots (run_id);

CREATE TABLE public.metric_definitions (
    metric_key VARCHAR(80) PRIMARY KEY,
    label VARCHAR(120) NOT NULL,
    gate_key VARCHAR(80),                          -- gate evaluated from this metric
    unit VARCHAR(40),
    description TEXT
);

CREATE TABLE public.constraint_rules (
    id UUID PRIMARY KEY DEFAULT extensions.gen_random_uuid(),
    gate_key VARCHAR(80) NOT NULL,                 -- 'zoning_dc_use', 'floodway', ...
    jurisdiction VARCHAR(120) NOT NULL,            -- 'Loudoun County, VA'
    rule_version VARCHAR(40) NOT NULL,
    params JSONB NOT NULL DEFAULT '{}',            -- thresholds, district mappings
    description TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT TIMEZONE('utc', NOW()),
    UNIQUE (gate_key, jurisdiction, rule_version)
);

-- ── 2. Cadastral land parcels (the pilot's real, purchasable units) ────────

CREATE TABLE public.land_parcels (
    id UUID PRIMARY KEY DEFAULT extensions.gen_random_uuid(),
    parcel_key VARCHAR(80) UNIQUE NOT NULL,        -- 'VA-LOUDOUN-<PIN>'
    source_parcel_id VARCHAR(80) NOT NULL,         -- county PIN (PA_MCPI)
    state_code VARCHAR(2) NOT NULL,
    county_name VARCHAR(120) NOT NULL,
    geom extensions.geometry(MultiPolygon, 4326) NOT NULL,
    gis_acreage NUMERIC(12, 3),                    -- computed from geometry
    legal_acreage NUMERIC(12, 3),                  -- county-recorded (PA_LEGAL_ACRE)
    first_run_id UUID NOT NULL REFERENCES public.ingestion_runs (id),
    latest_run_id UUID NOT NULL REFERENCES public.ingestion_runs (id),
    is_active BOOLEAN NOT NULL DEFAULT TRUE,       -- FALSE once absent from source
    created_at TIMESTAMPTZ NOT NULL DEFAULT TIMEZONE('utc', NOW()),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT TIMEZONE('utc', NOW())
);

CREATE INDEX idx_land_parcels_geom ON public.land_parcels USING GIST (geom);
CREATE INDEX idx_land_parcels_state ON public.land_parcels (state_code);
CREATE INDEX idx_land_parcels_active ON public.land_parcels (is_active) WHERE is_active;

DROP TRIGGER IF EXISTS set_land_parcels_updated_at ON public.land_parcels;
CREATE TRIGGER set_land_parcels_updated_at
    BEFORE UPDATE ON public.land_parcels
    FOR EACH ROW EXECUTE FUNCTION public.handle_updated_at();

CREATE TABLE public.parcel_metric_values (
    id UUID PRIMARY KEY DEFAULT extensions.gen_random_uuid(),
    parcel_id UUID NOT NULL REFERENCES public.land_parcels (id) ON DELETE CASCADE,
    run_id UUID NOT NULL REFERENCES public.ingestion_runs (id),
    metric_key VARCHAR(80) NOT NULL REFERENCES public.metric_definitions (metric_key),
    value NUMERIC(14, 4),                          -- numeric metrics
    text_value VARCHAR(200),                       -- categorical metrics
    unit VARCHAR(40),
    evidence_class VARCHAR(16) NOT NULL DEFAULT 'observed'
        CHECK (evidence_class IN ('observed', 'derived', 'estimated', 'manual', 'fallback')),
    source_snapshot_id UUID REFERENCES public.source_snapshots (id),
    retrieved_at TIMESTAMPTZ,
    details JSONB NOT NULL DEFAULT '{}',           -- source record id, urls, transforms
    UNIQUE (parcel_id, run_id, metric_key)
);

CREATE INDEX idx_parcel_metric_values_parcel ON public.parcel_metric_values (parcel_id);

CREATE TABLE public.parcel_gate_results (
    id UUID PRIMARY KEY DEFAULT extensions.gen_random_uuid(),
    parcel_id UUID NOT NULL REFERENCES public.land_parcels (id) ON DELETE CASCADE,
    run_id UUID NOT NULL REFERENCES public.ingestion_runs (id),
    gate_key VARCHAR(80) NOT NULL,
    status VARCHAR(12) NOT NULL
        CHECK (status IN ('PASS', 'CONDITIONAL', 'FAIL', 'UNKNOWN')),
    affected_area_pct NUMERIC(6, 3),               -- share of the parcel the gate touches
    rationale TEXT NOT NULL,
    rule_id UUID REFERENCES public.constraint_rules (id),
    details JSONB NOT NULL DEFAULT '{}',
    evaluated_at TIMESTAMPTZ NOT NULL DEFAULT TIMEZONE('utc', NOW()),
    UNIQUE (parcel_id, run_id, gate_key)
);

CREATE INDEX idx_parcel_gate_results_parcel ON public.parcel_gate_results (parcel_id);

-- Screening cells gain their source run (every displayed layer is traceable)
ALTER TABLE public.grid_parcels ADD COLUMN IF NOT EXISTS source_run_id UUID
    REFERENCES public.ingestion_runs (id);

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
    source_run_id
FROM public.grid_parcels gp;
ALTER VIEW public.v_grid_parcels SET (security_invoker = true);

-- ── 3. Staging tables — atomic publication via promote_ingestion_run() ────

CREATE TABLE public.stg_grid_parcels (LIKE public.grid_parcels INCLUDING DEFAULTS);
ALTER TABLE public.stg_grid_parcels ADD COLUMN run_id UUID NOT NULL;
CREATE INDEX idx_stg_grid_parcels_run ON public.stg_grid_parcels (run_id);

CREATE TABLE public.stg_transmission_lines (LIKE public.transmission_lines INCLUDING DEFAULTS);
ALTER TABLE public.stg_transmission_lines ADD COLUMN run_id UUID NOT NULL;
CREATE INDEX idx_stg_transmission_lines_run ON public.stg_transmission_lines (run_id);

CREATE TABLE public.stg_substations (LIKE public.substations INCLUDING DEFAULTS);
ALTER TABLE public.stg_substations ADD COLUMN run_id UUID NOT NULL;
CREATE INDEX idx_stg_substations_run ON public.stg_substations (run_id);

CREATE TABLE public.stg_observation_wells (LIKE public.observation_wells INCLUDING DEFAULTS);
ALTER TABLE public.stg_observation_wells ADD COLUMN run_id UUID NOT NULL;
CREATE INDEX idx_stg_observation_wells_run ON public.stg_observation_wells (run_id);

CREATE TABLE public.stg_land_parcels (LIKE public.land_parcels INCLUDING DEFAULTS);
ALTER TABLE public.stg_land_parcels ADD COLUMN run_id UUID NOT NULL;
CREATE INDEX idx_stg_land_parcels_run ON public.stg_land_parcels (run_id);

-- Metric/gate staging rows reference parcels by natural key (parcel_key):
-- the target parcel UUIDs are only known after the parcel upsert.
CREATE TABLE public.stg_parcel_metric_values (
    parcel_key VARCHAR(80) NOT NULL,
    run_id UUID NOT NULL,
    metric_key VARCHAR(80) NOT NULL,
    value NUMERIC(14, 4),
    text_value VARCHAR(200),
    unit VARCHAR(40),
    evidence_class VARCHAR(16) NOT NULL DEFAULT 'observed',
    source_snapshot_id UUID,
    retrieved_at TIMESTAMPTZ,
    details JSONB NOT NULL DEFAULT '{}'
);
CREATE INDEX idx_stg_parcel_metric_values_run ON public.stg_parcel_metric_values (run_id);

CREATE TABLE public.stg_parcel_gate_results (
    parcel_key VARCHAR(80) NOT NULL,
    run_id UUID NOT NULL,
    gate_key VARCHAR(80) NOT NULL,
    status VARCHAR(12) NOT NULL,
    affected_area_pct NUMERIC(6, 3),
    rationale TEXT NOT NULL,
    rule_id UUID,
    details JSONB NOT NULL DEFAULT '{}'
);
CREATE INDEX idx_stg_parcel_gate_results_run ON public.stg_parcel_gate_results (run_id);

-- ── 4. Atomic promote / fail RPCs (service-role only) ─────────────────────

CREATE OR REPLACE FUNCTION public.promote_ingestion_run(p_run_id UUID)
RETURNS JSONB
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = public, extensions
AS $$
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

    -- Screening cells: region-scoped replace, all-or-nothing
    DELETE FROM public.grid_parcels WHERE state_code = v_state;
    INSERT INTO public.grid_parcels (
        id, grid_id, geom, centroid, area_sq_km, state_code, county_name, region,
        power_distance_miles, substation_distance_miles, substation_voltage_kv,
        substation_name, grid_operator, groundwater_depth_ft, surface_water_distance_miles,
        water_availability_index, nearest_gauge_id, seismic_hazard_pga, flood_risk_score,
        hurricane_risk_score, aggregate_risk_score, cooling_degree_days, ambient_avg_temp_f,
        free_cooling_potential_hours, power_score, water_score, risk_score, climate_score,
        composite_score, cluster_zone_id, cluster_label, is_prime_zone,
        megawatt_capacity_estimate, metadata, created_at, updated_at, source_run_id
    )
    SELECT
        s.id, s.grid_id, s.geom, s.centroid, s.area_sq_km, s.state_code, s.county_name, s.region,
        s.power_distance_miles, s.substation_distance_miles, s.substation_voltage_kv,
        s.substation_name, s.grid_operator, s.groundwater_depth_ft, s.surface_water_distance_miles,
        s.water_availability_index, s.nearest_gauge_id, s.seismic_hazard_pga, s.flood_risk_score,
        s.hurricane_risk_score, s.aggregate_risk_score, s.cooling_degree_days, s.ambient_avg_temp_f,
        s.free_cooling_potential_hours, s.power_score, s.water_score, s.risk_score, s.climate_score,
        s.composite_score, s.cluster_zone_id, s.cluster_label, s.is_prime_zone,
        s.megawatt_capacity_estimate, s.metadata, s.created_at, s.updated_at, s.run_id
    FROM public.stg_grid_parcels s WHERE s.run_id = p_run_id;

    -- Map features: region-scoped replace, all-or-nothing
    DELETE FROM public.transmission_lines WHERE state_code = v_state;
    INSERT INTO public.transmission_lines (
        id, feature_id, state_code, owner, voltage_kv, volt_class, line_name, geom, created_at
    )
    SELECT
        s.id, s.feature_id, s.state_code, s.owner, s.voltage_kv, s.volt_class,
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

    -- Land parcels: upsert; anything absent from the run deactivates
    INSERT INTO public.land_parcels (
        id, parcel_key, source_parcel_id, state_code, county_name, geom,
        gis_acreage, legal_acreage, first_run_id, latest_run_id, is_active
    )
    SELECT
        s.id, s.parcel_key, s.source_parcel_id, s.state_code, s.county_name, s.geom,
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

    -- Metrics + gates for this run (idempotent: previous attempt cleaned first)
    DELETE FROM public.parcel_metric_values WHERE run_id = p_run_id;
    INSERT INTO public.parcel_metric_values (
        parcel_id, run_id, metric_key, value, text_value, unit,
        evidence_class, source_snapshot_id, retrieved_at, details
    )
    SELECT
        lp.id, s.run_id, s.metric_key, s.value, s.text_value, s.unit,
        s.evidence_class, s.source_snapshot_id, s.retrieved_at, s.details
    FROM public.stg_parcel_metric_values s
    JOIN public.land_parcels lp ON lp.parcel_key = s.parcel_key
    WHERE s.run_id = p_run_id;

    DELETE FROM public.parcel_gate_results WHERE run_id = p_run_id;
    INSERT INTO public.parcel_gate_results (
        parcel_id, run_id, gate_key, status, affected_area_pct, rationale, rule_id, details
    )
    SELECT
        lp.id, s.run_id, s.gate_key, s.status, s.affected_area_pct, s.rationale, s.rule_id, s.details
    FROM public.stg_parcel_gate_results s
    JOIN public.land_parcels lp ON lp.parcel_key = s.parcel_key
    WHERE s.run_id = p_run_id;

    -- Staging cleanup + run bookkeeping
    DELETE FROM public.stg_grid_parcels WHERE run_id = p_run_id;
    DELETE FROM public.stg_transmission_lines WHERE run_id = p_run_id;
    DELETE FROM public.stg_substations WHERE run_id = p_run_id;
    DELETE FROM public.stg_observation_wells WHERE run_id = p_run_id;
    DELETE FROM public.stg_land_parcels WHERE run_id = p_run_id;
    DELETE FROM public.stg_parcel_metric_values WHERE run_id = p_run_id;
    DELETE FROM public.stg_parcel_gate_results WHERE run_id = p_run_id;

    SELECT jsonb_build_object(
        'grid_parcels', (SELECT COUNT(*) FROM public.grid_parcels WHERE state_code = v_state AND source_run_id = p_run_id),
        'land_parcels_active', (SELECT COUNT(*) FROM public.land_parcels WHERE state_code = v_state AND is_active),
        'parcel_metrics', (SELECT COUNT(*) FROM public.parcel_metric_values WHERE run_id = p_run_id),
        'parcel_gates', (SELECT COUNT(*) FROM public.parcel_gate_results WHERE run_id = p_run_id)
    ) INTO v_counts;

    UPDATE public.ingestion_runs
    SET status = 'succeeded', finished_at = TIMEZONE('utc', NOW()), stats = stats || v_counts
    WHERE id = p_run_id;

    UPDATE public.ingestion_runs
    SET status = 'superseded'
    WHERE region_code = v_region AND status = 'succeeded' AND id <> p_run_id;

    RETURN v_counts;
END;
$$;

CREATE OR REPLACE FUNCTION public.fail_ingestion_run(p_run_id UUID, p_error TEXT)
RETURNS VOID
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = public, extensions
AS $$
BEGIN
    UPDATE public.ingestion_runs
    SET status = 'failed', finished_at = TIMEZONE('utc', NOW()),
        error = LEFT(COALESCE(p_error, 'unknown error'), 4000)
    WHERE id = p_run_id AND status = 'running';

    DELETE FROM public.stg_grid_parcels WHERE run_id = p_run_id;
    DELETE FROM public.stg_transmission_lines WHERE run_id = p_run_id;
    DELETE FROM public.stg_substations WHERE run_id = p_run_id;
    DELETE FROM public.stg_observation_wells WHERE run_id = p_run_id;
    DELETE FROM public.stg_land_parcels WHERE run_id = p_run_id;
    DELETE FROM public.stg_parcel_metric_values WHERE run_id = p_run_id;
    DELETE FROM public.stg_parcel_gate_results WHERE run_id = p_run_id;
END;
$$;

REVOKE ALL ON FUNCTION public.promote_ingestion_run(UUID) FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION public.promote_ingestion_run(UUID) TO service_role;
REVOKE ALL ON FUNCTION public.fail_ingestion_run(UUID, TEXT) FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION public.fail_ingestion_run(UUID, TEXT) TO service_role;

-- ── 5. Client-facing views (security_invoker, latest-run scoped) ──────────

CREATE VIEW public.v_ingestion_runs AS
SELECT id, run_key, region_code, pipeline_version, status, trigger,
       config, stats, error, started_at, finished_at
FROM public.ingestion_runs;
ALTER VIEW public.v_ingestion_runs SET (security_invoker = true);

CREATE VIEW public.v_source_snapshots AS
SELECT ss.id, ss.run_id, ss.layer, ss.evidence_class, ss.record_count,
       ss.dataset_version, ss.retrieved_at, ss.endpoint_url, ss.quality, ss.notes,
       ds.organization, ds.dataset
FROM public.source_snapshots ss
LEFT JOIN public.data_sources ds ON ds.id = ss.source_id;
ALTER VIEW public.v_source_snapshots SET (security_invoker = true);

CREATE VIEW public.v_land_parcels AS
SELECT lp.id,
    lp.parcel_key,
    lp.source_parcel_id AS pin,
    lp.state_code,
    lp.county_name,
    (extensions.ST_AsGeoJSON(lp.geom))::jsonb AS geojson_geom,
    extensions.ST_X(extensions.ST_Centroid(lp.geom)) AS lon,
    extensions.ST_Y(extensions.ST_Centroid(lp.geom)) AS lat,
    lp.gis_acreage,
    lp.legal_acreage,
    lp.is_active,
    lp.latest_run_id,
    r.run_key AS latest_run_key,
    (SELECT CASE
        WHEN COUNT(*) = 0 THEN NULL
        WHEN BOOL_OR(g.status = 'FAIL') THEN 'FAIL'
        WHEN BOOL_OR(g.status = 'UNKNOWN') THEN 'UNKNOWN'
        WHEN BOOL_OR(g.status = 'CONDITIONAL') THEN 'CONDITIONAL'
        ELSE 'PASS'
    END
    FROM public.parcel_gate_results g
    WHERE g.parcel_id = lp.id AND g.run_id = lp.latest_run_id) AS overall_status
FROM public.land_parcels lp
JOIN public.ingestion_runs r ON r.id = lp.latest_run_id
WHERE lp.is_active;
ALTER VIEW public.v_land_parcels SET (security_invoker = true);

CREATE VIEW public.v_parcel_gates AS
SELECT g.id, lp.parcel_key, g.gate_key, g.status, g.affected_area_pct,
       g.rationale, g.details, g.evaluated_at, g.run_id
FROM public.parcel_gate_results g
JOIN public.land_parcels lp ON lp.id = g.parcel_id
WHERE g.run_id = lp.latest_run_id;
ALTER VIEW public.v_parcel_gates SET (security_invoker = true);

CREATE VIEW public.v_parcel_metrics AS
SELECT lp.parcel_key, mv.metric_key, md.label, mv.value, mv.text_value, mv.unit,
       mv.evidence_class, mv.retrieved_at, mv.details,
       ds.organization AS source_organization, ds.dataset AS source_dataset
FROM public.parcel_metric_values mv
JOIN public.land_parcels lp ON lp.id = mv.parcel_id
JOIN public.metric_definitions md ON md.metric_key = mv.metric_key
LEFT JOIN public.source_snapshots ss ON ss.id = mv.source_snapshot_id
LEFT JOIN public.data_sources ds ON ds.id = ss.source_id
WHERE mv.run_id = lp.latest_run_id;
ALTER VIEW public.v_parcel_metrics SET (security_invoker = true);

-- ── 6. RLS: public read, service-role write; staging closed to API roles ──

ALTER TABLE public.data_sources ENABLE ROW LEVEL SECURITY;
CREATE POLICY "Allow public read access to data sources" ON public.data_sources FOR SELECT TO anon, authenticated USING (true);
CREATE POLICY "Allow service role write to data sources" ON public.data_sources FOR ALL TO service_role USING (true) WITH CHECK (true);

ALTER TABLE public.ingestion_runs ENABLE ROW LEVEL SECURITY;
CREATE POLICY "Allow public read access to ingestion runs" ON public.ingestion_runs FOR SELECT TO anon, authenticated USING (true);
CREATE POLICY "Allow service role write to ingestion runs" ON public.ingestion_runs FOR ALL TO service_role USING (true) WITH CHECK (true);

ALTER TABLE public.source_snapshots ENABLE ROW LEVEL SECURITY;
CREATE POLICY "Allow public read access to source snapshots" ON public.source_snapshots FOR SELECT TO anon, authenticated USING (true);
CREATE POLICY "Allow service role write to source snapshots" ON public.source_snapshots FOR ALL TO service_role USING (true) WITH CHECK (true);

ALTER TABLE public.metric_definitions ENABLE ROW LEVEL SECURITY;
CREATE POLICY "Allow public read access to metric definitions" ON public.metric_definitions FOR SELECT TO anon, authenticated USING (true);
CREATE POLICY "Allow service role write to metric definitions" ON public.metric_definitions FOR ALL TO service_role USING (true) WITH CHECK (true);

ALTER TABLE public.constraint_rules ENABLE ROW LEVEL SECURITY;
CREATE POLICY "Allow public read access to constraint rules" ON public.constraint_rules FOR SELECT TO anon, authenticated USING (true);
CREATE POLICY "Allow service role write to constraint rules" ON public.constraint_rules FOR ALL TO service_role USING (true) WITH CHECK (true);

ALTER TABLE public.land_parcels ENABLE ROW LEVEL SECURITY;
CREATE POLICY "Allow public read access to land parcels" ON public.land_parcels FOR SELECT TO anon, authenticated USING (true);
CREATE POLICY "Allow service role write to land parcels" ON public.land_parcels FOR ALL TO service_role USING (true) WITH CHECK (true);

ALTER TABLE public.parcel_metric_values ENABLE ROW LEVEL SECURITY;
CREATE POLICY "Allow public read access to parcel metrics" ON public.parcel_metric_values FOR SELECT TO anon, authenticated USING (true);
CREATE POLICY "Allow service role write to parcel metrics" ON public.parcel_metric_values FOR ALL TO service_role USING (true) WITH CHECK (true);

ALTER TABLE public.parcel_gate_results ENABLE ROW LEVEL SECURITY;
CREATE POLICY "Allow public read access to parcel gate results" ON public.parcel_gate_results FOR SELECT TO anon, authenticated USING (true);
CREATE POLICY "Allow service role write to parcel gate results" ON public.parcel_gate_results FOR ALL TO service_role USING (true) WITH CHECK (true);

-- Staging: never exposed to the API roles (RLS with no policies + no grants)
ALTER TABLE public.stg_grid_parcels ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.stg_transmission_lines ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.stg_substations ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.stg_observation_wells ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.stg_land_parcels ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.stg_parcel_metric_values ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.stg_parcel_gate_results ENABLE ROW LEVEL SECURITY;
REVOKE ALL ON public.stg_grid_parcels, public.stg_transmission_lines,
    public.stg_substations, public.stg_observation_wells, public.stg_land_parcels,
    public.stg_parcel_metric_values, public.stg_parcel_gate_results
    FROM anon, authenticated;
GRANT ALL ON public.stg_grid_parcels, public.stg_transmission_lines,
    public.stg_substations, public.stg_observation_wells, public.stg_land_parcels,
    public.stg_parcel_metric_values, public.stg_parcel_gate_results
    TO service_role;

-- Explicit Data API grants for everything the client reads
GRANT SELECT ON public.data_sources, public.ingestion_runs, public.source_snapshots,
    public.metric_definitions, public.constraint_rules, public.land_parcels,
    public.parcel_metric_values, public.parcel_gate_results,
    public.v_ingestion_runs, public.v_source_snapshots, public.v_land_parcels,
    public.v_parcel_gates, public.v_parcel_metrics
    TO anon, authenticated;

-- ── 7. Reference data (natural keys, no generated ids referenced) ─────────

INSERT INTO public.data_sources (source_key, organization, dataset, endpoint_url, description) VALUES
    ('loudoun_parcels', 'Loudoun County GIS', 'Parcel Boundaries (Land Records)',
     'https://logis.loudoun.gov/gis/rest/services/COL/LandRecords/MapServer/5',
     'County cadastral parcel boundaries with PIN and legal acreage'),
    ('loudoun_zoning', 'Loudoun County GIS', 'Zoning Ordinance districts',
     'https://logis.loudoun.gov/gis/rest/services/ZoningOrd/ZoningOrdinance/MapServer/0',
     'Authoritative digital zoning map: district code, ordinance vintage, encodeplus use-table links'),
    ('nwi_wetlands', 'USFWS', 'National Wetlands Inventory — Wetlands',
     'https://fwspublicservices.wim.usgs.gov/wetlandsarcgis/rest/services/Wetlands/MapServer/0',
     'Screening-grade wetland polygons; field delineation remains a diligence requirement'),
    ('fema_nfhl', 'FEMA', 'National Flood Hazard Layer — Flood Hazard Zones',
     'https://hazards.fema.gov/arcgis/rest/services/public/NFHL/MapServer/28',
     'FEMA flood hazard zones including regulatory floodway (ZONE_SUBTY)'),
    ('padus', 'USGS', 'Protected Areas Database of the U.S.',
     'https://www.usgs.gov/programs/gap-analysis-project/science/pad-us-data-download',
     'Official national aggregation of protected areas, easements, management designations'),
    ('usgs_3dep', 'USGS', '3DEP 1/3 arc-second digital elevation model',
     'https://elevation.nationalmap.gov/arcgis/rest/services/3DEPElevation/ImageServer',
     '~10 m national DEM; source for slope, relief, cut-and-fill proxies'),
    ('census_tiger_roads', 'U.S. Census Bureau', 'TIGER/Line roads',
     'https://tigerweb.geo.census.gov/arcgis/rest/services/TIGERweb',
     'National road baseline; state/local data preferred for truck class and restrictions'),
    ('hifld_lines', 'HIFLD', 'Electric Power Transmission Lines',
     'https://services1.arcgis.com/HZ6b99bXF6tCaCt2/arcgis/rest/services/Electric_Power_Transmission_Lines/FeatureServer',
     'Transmission corridors with owner and voltage class'),
    ('hifld_substations', 'HIFLD', 'Electric Substations',
     'https://services1.arcgis.com/HZ6b99bXF6tCaCt2/arcgis/rest/services/Electric_Substations/FeatureServer',
     'Named, voltage-tagged substations'),
    ('usgs_nwis', 'USGS', 'National Water Information System (parameter 72019)',
     'https://waterservices.usgs.gov/nwis/iv',
     'Groundwater level observations'),
    ('noaa_acis', 'NOAA', 'Applied Climate Information System — GridData (PRISM normals)',
     'https://data.rcc-acis.org/GridData',
     'Climate normals: CDD, mean temperature, free-cooling hours'),
    ('fema_nri', 'FEMA', 'National Risk Index — Counties',
     'https://hazards.fema.gov/gis/nri/services/nri counties',
     'County-level flood/hurricane composite risk — regional context only'),
    ('usgs_seismic', 'USGS', 'ASCE 7-16 design web service (uniform-hazard PGA)',
     'https://earthquake.usgs.gov/ws/designmaps/ashrae/conservative-site.json',
     '2% in 50-year PGA, site class BC, risk category III')
ON CONFLICT (source_key) DO NOTHING;

INSERT INTO public.metric_definitions (metric_key, label, gate_key, unit, description) VALUES
    ('total_acreage', 'Total acreage', 'contiguous_acreage', 'acres', 'County-recorded parcel acreage'),
    ('contiguous_developable_acreage', 'Contiguous developable acreage', 'contiguous_acreage', 'acres', 'Acreage minus wetland/floodway/protected overlaps'),
    ('wetland_pct', 'Wetland coverage', 'wetlands', 'percent', 'Share of parcel in NWI wetland polygons'),
    ('floodway_pct', 'Floodway coverage', 'floodway', 'percent', 'Share of parcel inside the regulatory floodway'),
    ('floodplain_pct', '100-year floodplain coverage', 'floodway', 'percent', 'Share of parcel in FEMA AE/A zones (non-floodway)'),
    ('slope_max_pct', 'Maximum slope', 'slope', 'percent', 'Steepest slope from 3DEP-derived raster'),
    ('slope_median_pct', 'Median slope', 'slope', 'percent', 'Median slope across the parcel footprint'),
    ('protected_land_pct', 'Protected-land overlap', 'protected_land', 'percent', 'Share of parcel in PAD-US protected areas'),
    ('zoning_district', 'Zoning district', 'zoning_dc_use', NULL, 'Applicable zoning district from the county zoning map'),
    ('zoning_ordinance_vintage', 'Zoning ordinance vintage', 'zoning_dc_use', NULL, 'Ordinance edition governing the district'),
    ('dc_use_status', 'Data-center use status', 'zoning_dc_use', NULL, 'by_right / special_exception / prohibited / unknown per district mapping'),
    ('road_distance_miles', 'Distance to nearest suitable road', 'road_access', 'miles', 'TIGER primary/secondary road proximity'),
    ('distance_to_transmission_miles', 'Distance to transmission', NULL, 'miles', 'Nearest 100 kV+ line (HIFLD)'),
    ('distance_to_substation_miles', 'Distance to substation', NULL, 'miles', 'Nearest named substation (HIFLD)'),
    ('assembly_adjoining_count', 'Adjoining parcel count', NULL, 'count', 'Abutting parcels of screening-relevant size'),
    ('assembly_total_acreage', 'Assembled acreage potential', NULL, 'acres', 'Combined acreage of the parcel and abutting candidates')
ON CONFLICT (metric_key) DO NOTHING;

-- Loudoun County gate rules. The zoning mapping is a SCREENING posture from
-- the 2023 zoning ordinance as amended by the March 2025 ZOAM (data centers
-- moved from by-right to special exception in many districts). Industrial
-- districts map by_right/special_exception; residential and commercial map
-- prohibited; incorporated towns (TOWNS) have their own ordinances and stay
-- UNKNOWN; any unmapped code stays UNKNOWN. Every mapping is reviewable in
-- this row — evidence_class 'manual', pending ordinance review.
INSERT INTO public.constraint_rules (gate_key, jurisdiction, rule_version, params, description) VALUES
    ('zoning_dc_use', 'Loudoun County, VA', '2023-ord+2025-zoam', $json${"by_right": ["PDGI", "PDIP", "GI", "IP", "MRHI"], "special_exception": ["CLI", "PDRDP", "PDCH"], "prohibited": ["A10", "A3", "AR1", "AR2", "CR1", "CR2", "CR3", "CR4", "RC", "R1", "R2", "R3", "R4", "R8", "R16", "R24", "SCN8", "SCN16", "SCN24", "PDH3", "PDH4", "PDH6", "PDAAAR", "PDRV", "PDCCRC", "PDSC", "C1", "GB", "CCCC", "CCNC", "CCSC", "OP", "PDOP", "TRC", "TC", "TR1LF", "TR1UBF", "TR2", "TR3LBR", "TR3LF", "TR3UBF", "TR10", "PUD-1", "JLMA1", "JLMA2", "JLMA3", "JLMA20"], "unknown_jurisdiction": ["TOWNS"]}$json$,
     'Data-center use status by zoning district: industrial by-right (post-ZOAM screening), CLI/PDRDP/PDCH special exception, residential/commercial prohibited, incorporated towns and unmapped codes UNKNOWN. Screening mapping pending ordinance review — see loudoun.gov/5990.'),
    ('contiguous_acreage', 'Loudoun County, VA', 'v1', $json${"min_pass_acres": 100, "min_conditional_acres": 25}$json$,
     'Contiguous developable acreage: PASS >= 100 acres, CONDITIONAL 25-99 (assembly required), FAIL < 25.'),
    ('floodway', 'Loudoun County, VA', 'v1', $json${"floodway_fail_pct": 0.5, "floodplain_conditional": true}$json$,
     'FEMA NFHL: FAIL when floodway overlap > 0.5% of parcel; CONDITIONAL when in AE/A floodplain without floodway.'),
    ('wetlands', 'Loudoun County, VA', 'v1', $json${"conditional_pct": 5, "fail_pct": 30}$json$,
     'NWI screening: PASS < 5% coverage, CONDITIONAL 5-30%, FAIL > 30%. Field delineation still required at diligence.'),
    ('protected_land', 'Loudoun County, VA', 'v1', $json${"fail_pct": 0.5}$json$,
     'PAD-US: FAIL when protected-area overlap exceeds 0.5% of the parcel.'),
    ('slope', 'Loudoun County, VA', 'v1', $json${"max_fail_pct": 25, "median_conditional_pct": 8}$json$,
     '3DEP-derived: FAIL when max slope > 25%, CONDITIONAL when median > 8%.'),
    ('road_access', 'Loudoun County, VA', 'v1', $json${"conditional_miles": 2, "fail_miles": 5}$json$,
     'TIGER primary/secondary roads: CONDITIONAL beyond 2 miles, FAIL beyond 5.')
ON CONFLICT (gate_key, jurisdiction, rule_version) DO NOTHING;
