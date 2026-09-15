-- ============================================================================
-- Migration: release23_v_survey_regions
-- Description: The regions the client may offer, derived rather than restated.
--
--   client/src/lib/regions.ts carried its own hardcoded list of six, under a
--   comment claiming it matched the worker's presets. It did, until three
--   Ohio counties were published and it silently did not: the data was in the
--   database and the app simply never offered it. Somebody went looking for
--   Fairfield and could not find it.
--
--   That is the same class of defect as the hand-typed bounding boxes — a
--   second copy of a fact, kept by hand, drifting from the first. This one is
--   kinder, because it announces itself rather than surveying the wrong
--   ground quietly, but it is the same mistake and it was sitting in the
--   mirror nobody looked at while the original was being fixed.
--
--   This view is the one answer to "which regions exist". It also carries the
--   counts the client used to gather with one HEAD request per region, so a
--   growing region list now costs one query rather than N — it is a
--   simplification as well as a correction.
--
--   A region appears here as soon as it has published screening cells, which
--   is the same moment it is worth offering, so a new county needs no edit in
--   the client at all.
--
--   Applied 2026-09-15. Nine regions: five Ohio, two Virginia, Taylor TX and
--   Morrow OR, the last carrying 330 screening cells and no parcels.
-- ============================================================================

CREATE OR REPLACE VIEW public.v_survey_regions
WITH (security_invoker = true) AS
SELECT
    gp.region_key,
    max(gp.county_name)                                  AS county_name,
    max(gp.state_code)                                   AS state_code,
    max(gp.grid_operator)                                AS grid_operator,
    count(*)                                             AS screening_cells,
    -- Parcel count distinguishes a diligenced county from a screening-only
    -- one (Morrow has cells and no parcels). The client greys out a region
    -- with nothing to show rather than offering an empty map.
    (SELECT count(*) FROM public.land_parcels lp
      WHERE lp.region_key = gp.region_key AND lp.is_active) AS active_parcels
FROM public.grid_parcels gp
WHERE gp.region_key IS NOT NULL
GROUP BY gp.region_key;

COMMENT ON VIEW public.v_survey_regions IS
    'Regions available to the client, derived from published screening cells. Replaces the hand-maintained list in client/src/lib/regions.ts and the per-region count queries it drove.';

GRANT SELECT ON public.v_survey_regions TO anon, authenticated, service_role;
