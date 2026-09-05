-- ============================================================================
-- Migration: release2_power_diligence
-- Description: Power diligence — utility territory, PJM RTEP upgrade
--              evidence (study/construction status, upgrade requirements,
--              energization dates), curated utility documents, and removal
--              of the unsupported area-derived MW capacity estimates.
--
--   Rule: no parcel displays a feasible MW figure without a dated source
--   that supports it. PJM RTEP records are AREA-level evidence (a dated
--   source for regional reinforcements and their energization dates) —
--   they never assert parcel-specific capacity, so no parcel-level MW is
--   displayed at all.
-- ============================================================================

-- ── 1. PJM RTEP upgrade records (area-level, dated, official) ─────────────

CREATE TABLE public.power_rtep_upgrades (
    id UUID PRIMARY KEY DEFAULT extensions.gen_random_uuid(),
    upgrade_id VARCHAR(40) NOT NULL,             -- PJM project id ('b3800.213', 's0286')
    state_code VARCHAR(2) NOT NULL,
    project_type VARCHAR(20) NOT NULL,           -- Baseline / Network / Supplemental
    description TEXT NOT NULL,
    transmission_owner VARCHAR(80),
    substation VARCHAR(120),                     -- named substation parsed from the record
    in_area BOOLEAN NOT NULL DEFAULT FALSE,      -- tagged Loudoun-area by the matcher
    voltage_kv NUMERIC(8, 1),
    status VARCHAR(16) NOT NULL,                 -- IS / EP / UC / PL / Cancelled
    equipment VARCHAR(160),
    driver VARCHAR(240),
    cost_estimate_musd NUMERIC(12, 2),           -- $M as published
    board_approval_date DATE,                    -- PJM Board approval (dated evidence)
    required_date DATE,                          -- PJM required-in-service
    projected_in_service_date DATE,              -- planned energization
    revised_in_service_date DATE,
    actual_in_service_date DATE,                 -- actual energization
    source_updated DATE,                         -- PJM LastUpdated for the record
    run_id UUID NOT NULL REFERENCES public.ingestion_runs (id),
    created_at TIMESTAMPTZ NOT NULL DEFAULT TIMEZONE('utc', NOW())
);

CREATE INDEX idx_power_rtep_upgrades_state ON public.power_rtep_upgrades (state_code, status);
CREATE INDEX idx_power_rtep_upgrades_area ON public.power_rtep_upgrades (in_area) WHERE in_area;
CREATE INDEX idx_power_rtep_upgrades_substation ON public.power_rtep_upgrades (substation);

-- ── 2. Curated utility documents (dated sources behind every claim) ──────

CREATE TABLE public.power_documents (
    id UUID PRIMARY KEY DEFAULT extensions.gen_random_uuid(),
    doc_key VARCHAR(80) UNIQUE NOT NULL,
    title VARCHAR(240) NOT NULL,
    publisher VARCHAR(160) NOT NULL,             -- 'PJM Interconnection', 'Dominion Energy Virginia'
    doc_type VARCHAR(40) NOT NULL,               -- dataset / report / study_agreement / utility_letter
    published_date DATE,                         -- the date the document supports figures as of
    url TEXT NOT NULL,
    summary TEXT,
    ingested_at TIMESTAMPTZ NOT NULL DEFAULT TIMEZONE('utc', NOW())
);

-- ── 3. Staging + atomic promote (state-scoped replace, like map features) ─

CREATE TABLE public.stg_power_rtep_upgrades (LIKE public.power_rtep_upgrades INCLUDING DEFAULTS);
CREATE INDEX idx_stg_power_rtep_upgrades_run ON public.stg_power_rtep_upgrades (run_id);

-- ── 4. Retire the area-derived MW placeholder ─────────────────────────────

ALTER TABLE public.grid_parcels ALTER COLUMN megawatt_capacity_estimate DROP DEFAULT;
UPDATE public.grid_parcels SET megawatt_capacity_estimate = NULL;

-- The prime-zone aggregate no longer sums a fabricated capacity figure.
DROP FUNCTION IF EXISTS public.get_prime_cluster_polygons();
CREATE OR REPLACE FUNCTION public.get_prime_cluster_polygons()
RETURNS TABLE (
    cluster_zone_id INTEGER,
    cluster_label VARCHAR,
    parcel_count BIGINT,
    avg_composite_score NUMERIC,
    total_area_sq_km NUMERIC,
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
        extensions.ST_AsGeoJSON(extensions.ST_UnaryUnion(extensions.ST_Collect(gp.geom)))::jsonb AS cluster_boundary_geojson
    FROM public.grid_parcels gp
    WHERE gp.cluster_zone_id >= 0 AND gp.is_prime_zone = TRUE
    GROUP BY gp.cluster_zone_id
    ORDER BY avg_composite_score DESC;
$$;

-- ── 5. Promote / fail RPCs gain the RTEP layer ────────────────────────────

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

    -- PJM RTEP upgrade records: region-scoped replace
    DELETE FROM public.power_rtep_upgrades WHERE state_code = v_state;
    INSERT INTO public.power_rtep_upgrades (
        id, upgrade_id, state_code, project_type, description, transmission_owner,
        substation, in_area, voltage_kv, status, equipment, driver, cost_estimate_musd,
        board_approval_date, required_date, projected_in_service_date,
        revised_in_service_date, actual_in_service_date, source_updated, run_id, created_at
    )
    SELECT
        s.id, s.upgrade_id, s.state_code, s.project_type, s.description, s.transmission_owner,
        s.substation, s.in_area, s.voltage_kv, s.status, s.equipment, s.driver, s.cost_estimate_musd,
        s.board_approval_date, s.required_date, s.projected_in_service_date,
        s.revised_in_service_date, s.actual_in_service_date, s.source_updated, s.run_id, s.created_at
    FROM public.stg_power_rtep_upgrades s WHERE s.run_id = p_run_id;

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
    DELETE FROM public.stg_power_rtep_upgrades WHERE run_id = p_run_id;
    DELETE FROM public.stg_land_parcels WHERE run_id = p_run_id;
    DELETE FROM public.stg_parcel_metric_values WHERE run_id = p_run_id;
    DELETE FROM public.stg_parcel_gate_results WHERE run_id = p_run_id;

    SELECT jsonb_build_object(
        'grid_parcels', (SELECT COUNT(*) FROM public.grid_parcels WHERE state_code = v_state AND source_run_id = p_run_id),
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
    DELETE FROM public.stg_power_rtep_upgrades WHERE run_id = p_run_id;
    DELETE FROM public.stg_land_parcels WHERE run_id = p_run_id;
    DELETE FROM public.stg_parcel_metric_values WHERE run_id = p_run_id;
    DELETE FROM public.stg_parcel_gate_results WHERE run_id = p_run_id;
END;
$$;

REVOKE ALL ON FUNCTION public.promote_ingestion_run(UUID) FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION public.promote_ingestion_run(UUID) TO service_role;
REVOKE ALL ON FUNCTION public.fail_ingestion_run(UUID, TEXT) FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION public.fail_ingestion_run(UUID, TEXT) TO service_role;

-- ── 6. Client views ───────────────────────────────────────────────────────

CREATE VIEW public.v_power_rtep_upgrades AS
SELECT pru.upgrade_id, pru.state_code, pru.project_type, pru.description,
       pru.transmission_owner, pru.substation, pru.in_area, pru.voltage_kv,
       pru.status, pru.equipment, pru.driver, pru.cost_estimate_musd,
       pru.board_approval_date, pru.required_date, pru.projected_in_service_date,
       pru.revised_in_service_date, pru.actual_in_service_date, pru.source_updated,
       pru.created_at AS ingested_at
FROM public.power_rtep_upgrades pru;
ALTER VIEW public.v_power_rtep_upgrades SET (security_invoker = true);

CREATE VIEW public.v_power_documents AS
SELECT pd.doc_key, pd.title, pd.publisher, pd.doc_type, pd.published_date,
       pd.url, pd.summary, pd.ingested_at
FROM public.power_documents pd;
ALTER VIEW public.v_power_documents SET (security_invoker = true);

-- ── 7. RLS + grants ───────────────────────────────────────────────────────

ALTER TABLE public.power_rtep_upgrades ENABLE ROW LEVEL SECURITY;
CREATE POLICY "Allow public read access to RTEP upgrades" ON public.power_rtep_upgrades
    FOR SELECT TO anon, authenticated USING (true);
CREATE POLICY "Allow service role write to RTEP upgrades" ON public.power_rtep_upgrades
    FOR ALL TO service_role USING (true) WITH CHECK (true);

ALTER TABLE public.power_documents ENABLE ROW LEVEL SECURITY;
CREATE POLICY "Allow public read access to power documents" ON public.power_documents
    FOR SELECT TO anon, authenticated USING (true);
CREATE POLICY "Allow service role write to power documents" ON public.power_documents
    FOR ALL TO service_role USING (true) WITH CHECK (true);

ALTER TABLE public.stg_power_rtep_upgrades ENABLE ROW LEVEL SECURITY;
REVOKE ALL ON public.stg_power_rtep_upgrades FROM anon, authenticated;
GRANT ALL ON public.stg_power_rtep_upgrades TO service_role;

GRANT SELECT ON public.power_rtep_upgrades, public.power_documents,
    public.v_power_rtep_upgrades, public.v_power_documents
    TO anon, authenticated;

-- ── 8. Reference data ─────────────────────────────────────────────────────

INSERT INTO public.data_sources (source_key, organization, dataset, endpoint_url, description) VALUES
    ('pjm_rtep_upgrades', 'PJM Interconnection', 'RTEP Project Construction Status — Upgrades & Costs',
     'https://www.pjm.com/pjmfiles/media/planning/projectConstruction-data/projectCostUpgrades.xml',
     'PJM Board-approved baseline/network/supplemental transmission upgrades with approval, required, and in-service dates'),
    ('hifld_utility_territories', 'HIFLD', 'Electric Retail Service Territories',
     'https://services6.arcgis.com/BAJNi3EgCdtQ1BCG/arcgis/rest/services/Electric_Retail_Service_Territories/FeatureServer/0',
     'Electric utility retail service territory polygons (sourced 2023): investor-owned, cooperative, municipal'),
    ('pjm_queue_map', 'PJM Interconnection', 'Interconnection Queue Map',
     'https://gis.pjm.com/arcgis/rest/services/Renewables/Queue/MapServer/0',
     'PJM queue interconnection request points with facility voltage')
ON CONFLICT (source_key) DO NOTHING;

INSERT INTO public.metric_definitions (metric_key, label, gate_key, unit, description) VALUES
    ('serving_utility', 'Serving electric utility', 'power_capacity', NULL,
     'Utility whose retail service territory covers the parcel (HIFLD)'),
    ('serving_utility_type', 'Utility type', 'power_capacity', NULL,
     'investor_owned / cooperative / municipal'),
    ('power_evidence_level', 'Power capacity evidence level', 'power_capacity', NULL,
     'parcel_study (dated parcel-specific source) / area_reinforcement (dated regional upgrades) / utility_identified / none'),
    ('rtep_area_active_upgrades', 'Active PJM upgrades in the county area', 'power_capacity', 'count',
     'Board-approved RTEP upgrades not yet in service, tagged to this county area'),
    ('rtep_area_energization_range', 'Documented energization range (area)', 'power_capacity', NULL,
     'Earliest..latest projected in-service dates among active area upgrades'),
    ('rtep_latest_board_approval', 'Latest PJM Board approval (area)', 'power_capacity', NULL,
     'Most recent Board approval date among area upgrades'),
    ('pjm_queue_points_within_3mi', 'PJM queue activity within 3 mi', 'power_capacity', 'count',
     'Interconnection request points within 3 miles of the parcel (PJM queue map)'),
    ('pjm_queue_max_kv', 'Highest queue interconnection voltage within 3 mi', 'power_capacity', 'kV',
     'Maximum facility voltage among nearby queue points')
ON CONFLICT (metric_key) DO NOTHING;

INSERT INTO public.constraint_rules (gate_key, jurisdiction, rule_version, params, description) VALUES
    ('power_capacity', 'Loudoun County, VA', 'v1',
     $json${"active_statuses": ["EP", "UC", "PL"], "queue_radius_miles": 3}$json$,
     'Power capacity evidence: PASS requires a dated parcel-specific source (utility study agreement/letter — none ingested yet); CONDITIONAL when the serving utility is identified AND dated PJM Board-approved area reinforcements exist; UNKNOWN otherwise. No MW figure is displayed without a dated supporting source.')
ON CONFLICT (gate_key, jurisdiction, rule_version) DO NOTHING;

-- Curated utility documents — every capacity/demand figure shown in the UI
-- traces to one of these dated documents.
INSERT INTO public.power_documents (doc_key, title, publisher, doc_type, published_date, url, summary) VALUES
    ('pjm_rtep_construction_status', 'RTEP Project Construction Status — Upgrades & Costs', 'PJM Interconnection', 'dataset', '2026-03-05',
     'https://www.pjm.com/planning/m/project-construction',
     'Machine-readable record of every PJM Board-approved baseline, network, and supplemental transmission upgrade: description, owner, voltage, status, Board approval date, required date, and projected/actual in-service (energization) dates. Records carry a per-row LastUpdated date.'),
    ('pjm_va_state_infrastructure_2025', '2025 Virginia State Infrastructure Report', 'PJM Interconnection', 'report', '2026-06-16',
     'https://www.pjm.com/-/media/DotCom/library/reports-notices/state-specific-reports/2025/virginia.pdf',
     'Virginia RTEP investment ($7.16B in 2025), queued capacity under study (45.4 GW), and DOM-zone large-load adjustments. Version 2 posted August 18, 2026 with updated queue data.'),
    ('pjm_load_forecast_2026', '2026 PJM Load Forecast Report', 'PJM Interconnection', 'report', '2026-01-14',
     'https://www.pjm.com/-/media/DotCom/library/reports-notices/load-forecast/2026-load-forecast-report.pdf',
     'Dominion (DOM) zone summer-peak large-load adjustments: 7,066 MW (2026) growing to 22,426 MW (2035) and 35,010 MW (2045), driven primarily by data center interconnection requests. Zone-level context — never a parcel capacity claim.')
ON CONFLICT (doc_key) DO NOTHING;
