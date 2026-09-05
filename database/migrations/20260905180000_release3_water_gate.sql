-- ============================================================================
-- Migration: release3_water_gate
-- Description: Water availability becomes a real parcel gate (Release 3).
--
--   Loudoun Water (LCSA) publishes its service-area boundary on a public
--   ArcGIS server (Boundary/MapServer/2): water/wastewater service areas
--   (ServiceType W/Both, including the Central System that covers Data
--   Center Alley), small community systems — some flagged "Additional
--   Connections Not Permitted" — and an explicit "NOT Served by LW"
--   polygon for where the utility does not provide service.
--
--   Gate semantics (rules-as-data, evidence discipline):
--     PASS         >= 50% of the parcel inside a water-servicing area
--                  (connections not restricted by the utility's record)
--     CONDITIONAL  5-50% overlap (service extension needed), or inside a
--                  serving area whose record says additional connections
--                  are not permitted
--     FAIL         >= 50% inside the utility's explicit "NOT Served"
--                  polygon (outside towns) — no mapped public provider;
--                  on-site wells would be required
--     UNKNOWN      incorporated towns (municipal providers not covered
--                  by this layer) or unmapped gaps
--
--   Capacity, pressure, and connection fees are diligence items — the
--   gate records availability from the utility's own dated boundary, and
--   nothing else.
-- ============================================================================

-- ── 1. Source ─────────────────────────────────────────────────────────────

INSERT INTO public.data_sources (source_key, organization, dataset, endpoint_url, description) VALUES
    ('loudoun_water_service_area', 'Loudoun Water (LCSA)', 'Service Area boundary (water / wastewater / NOT-served)',
     'https://gportal.loudounwater.org/gis/rest/services/Boundary/MapServer/2',
     'The utility''s own published service-area polygons: Central System and community systems (ServiceType W/Both), per-area connection records, and the explicit "NOT Served by LW" boundary. Per-feature last-edited dates (2026).')
ON CONFLICT (source_key) DO NOTHING;

-- ── 2. Metrics ────────────────────────────────────────────────────────────

INSERT INTO public.metric_definitions (metric_key, label, gate_key, unit, description) VALUES
    ('water_service_provider', 'Water service provider', 'water_availability', NULL,
     'Loudoun Water serving-area name for the parcel (observed from the utility''s published service-area boundary)'),
    ('water_service_area_pct', 'Water service-area overlap', 'water_availability', 'percent',
     'Share of the parcel inside Loudoun Water''s published water-servicing boundary (derived)')
ON CONFLICT (metric_key) DO NOTHING;

-- ── 3. Gate rule ──────────────────────────────────────────────────────────

INSERT INTO public.constraint_rules (gate_key, jurisdiction, rule_version, params, description) VALUES
    ('water_availability', 'Loudoun County, VA', 'v1',
     $json${"pass_overlap_pct": 50, "conditional_overlap_pct": 5}$json$,
     'Public water availability from Loudoun Water''s own published service-area boundary: PASS when at least half the parcel lies in a water-servicing area whose record permits connections; CONDITIONAL when only partially inside (extension needed) or the area record says additional connections are not permitted; FAIL when at least half the parcel lies in the utility''s explicit NOT-Served boundary outside incorporated towns (no mapped public provider — on-site wells would be required); UNKNOWN inside incorporated towns (municipal providers are not covered by this layer) or in unmapped gaps. Capacity, pressure, and connection fees remain diligence items.')
ON CONFLICT (gate_key, jurisdiction, rule_version) DO NOTHING;
