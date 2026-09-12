-- ============================================================================
-- Migration: release18_moratorium_gate
-- Description: The township layer and the plumbing for the moratorium gate.
--
--   Phase 1 of the gate order in docs/moratorium-gate-brief.md: persist
--   township from TIGER county subdivisions (layer 1 of the same
--   Places_CouSub_ConCity_SubMCD service the places layer uses), so the
--   gate can match restriction rows at the level that actually acts in
--   Ohio — the township, the zoning authority for unincorporated land.
--
--   Three things ship here, all plumbing; the gate itself is worker code
--   reading jurisdiction_restrictions, which is already populated and
--   public:
--     1. A data_sources row for the county-subdivisions layer.
--     2. A metric_definitions row for county_subdivision — the persisted
--        minor civil division, recorded beside incorporated_place.
--     3. v_jurisdiction_restrictions recreated. The view was created in
--        release17 with SELECT * and release17b added subdivision_name
--        afterwards, so the view still exposes the old column list —
--        the township level is invisible through it. CREATE OR REPLACE
--        re-expands the star against the current table.
--
--   Applied to production 2026-09-12.
-- ============================================================================

INSERT INTO public.data_sources (source_key, organization, dataset, endpoint_url, description) VALUES
    ('census_tiger_county_subdivisions', 'U.S. Census Bureau',
     'TIGER/Line County Subdivisions (minor civil divisions)',
     'https://tigerweb.geo.census.gov/arcgis/rest/services/TIGERweb/Places_CouSub_ConCity_SubMCD/MapServer/1',
     'Minor civil division polygons (MTFCC G4040): the township level of the moratorium gate and the county_subdivision metric. An MCD is only sometimes a government — an Ohio township (LSADC 44, functioning) is the zoning authority for unincorporated land, while a Virginia election district or a Texas CCD is a statistical artefact — so the governing-class test is made where rows are matched, not in the fetch. State-cached clip like the roads and places layers, with the TIGER/Line state COUSUB shapefile as fallback.')
ON CONFLICT (source_key) DO NOTHING;

INSERT INTO public.metric_definitions (metric_key, label, gate_key, unit, description) VALUES
    ('county_subdivision', 'County subdivision (township)', 'moratorium_status', NULL,
     'The minor civil division containing the parcel''s majority area (TIGER/Line County Subdivisions). In the township states this is the body that zones and can pause unincorporated land; the moratorium gate matches restriction rows at this level. Absent means the layer was unavailable, never "no township".')
ON CONFLICT (metric_key) DO NOTHING;

-- Recreated so subdivision_name (release17b) is visible through it.
-- The view was created with SELECT *, which Postgres expands at
-- creation time; release17b's ALTER TABLE ADD COLUMN therefore never
-- reached the view, and CREATE OR REPLACE cannot fix it — the expanded
-- star inserts the new column before in_force_today, which Postgres
-- reads as renaming a view column. So: drop, recreate identically (the
-- star now expands against the current table), and re-grant exactly as
-- release17 did.
DROP VIEW IF EXISTS public.v_jurisdiction_restrictions;
CREATE VIEW public.v_jurisdiction_restrictions AS
SELECT r.*,
       CASE
           WHEN r.status <> 'adopted' THEN NULL
           WHEN r.effective_date IS NOT NULL AND r.effective_date > CURRENT_DATE THEN FALSE
           WHEN r.expires_date IS NOT NULL AND r.expires_date <= CURRENT_DATE THEN FALSE
           ELSE TRUE
       END AS in_force_today,
       (CURRENT_DATE - r.reviewed_at) AS days_since_review
FROM public.jurisdiction_restrictions r;
ALTER VIEW public.v_jurisdiction_restrictions SET (security_invoker = true);
GRANT SELECT ON public.v_jurisdiction_restrictions TO anon, authenticated;
