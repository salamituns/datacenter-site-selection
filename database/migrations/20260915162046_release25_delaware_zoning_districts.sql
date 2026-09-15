-- ============================================================================
-- Migration: release25_delaware_zoning_districts
-- Description: Delaware County, OH — township zoning districts ingested, no
--   use table yet.
--
--   Delaware publishes zoning for all eighteen townships as sixteen feature
--   services (Thompson, Radnor and Marlboro share one, having adopted the
--   county code under ORC 303). 3,492 polygons, 79 distinct district codes,
--   100% coverage of the county's 2,760 qualifying parcels.
--
--   They were missed on the first pass because nobody names these services
--   the way a searcher would guess — porterzon, harlemzon, sciotozon, one per
--   township, owned by a named individual at the planning commission rather
--   than an organisation account. An ArcGIS Online title search returns a
--   single township. Tracing the county's public zoning web map to its
--   operationalLayers returns all sixteen.
--
--   This row exists because qualify_parcels REFUSES a zoning-supplying
--   jurisdiction with no zoning_dc_use row, and it is deliberately EMPTY: the
--   districts are ingested so a use table can drop in later as a row rather
--   than a re-survey, exactly as Fauquier was done. Every district reads
--   UNKNOWN with a rationale naming why.
--
--   WHY THE USE TABLE MUST BE SCOPED PER TOWNSHIP, when it is written:
--
--     Each township adopted its own resolution, so a district code means what
--     that township's resolution says it means. Measured on the live layer:
--     FR-1 appears in 12 of the 16, PRD in 7, PCD in 7, PID in 6, C-2 in 6,
--     R-2 in 6 — and the names do not agree between them. Berkshire's FR-1 is
--     a "Farm Residential District"; Brown's FR-1 is a "Farm Residence
--     District". Two instruments, one code.
--
--     So the mapping belongs in district_classes keyed "CODE|Township", which
--     outranks the flat lists, and NOT in by_right / prohibited. A flat entry
--     for FR-1 would decide twelve townships from whichever one was read.
--     This is the Licking C-1 problem, and the engine already refuses to
--     guess at it: a colliding code with no scoped row stays unmapped.
--
--   The sixteenth "township" is labelled "Delaware County code" rather than
--   named for one of Thompson, Radnor or Marlboro. All three read the same
--   instrument, and labelling its polygons with one township's name would
--   imply the other two had been surveyed separately.
--
--   reviewed_at is NULL: nothing has been reviewed. review_due_months is 6
--   rather than 12 because this is a placeholder and should be chased.
--
--   Applied 2026-09-15.
-- ============================================================================

INSERT INTO public.constraint_rules
    (gate_key, jurisdiction, rule_version, params, description, basis,
     reviewed_at, reviewed_against, review_due_months)
VALUES (
  'zoning_dc_use', 'Delaware County, OH', '2026-districts-only',
  '{"by_right": [], "special_exception": [], "prohibited": [],
    "district_classes": {}}'::jsonb,
  'Township zoning districts ingested; no use table yet. Every district reads UNKNOWN.',
  'DELIBERATELY EMPTY. Delaware County publishes township zoning for all eighteen townships as sixteen ArcGIS feature services — 3,492 polygons across 79 district codes — found by tracing the county''s public zoning web map to its operationalLayers, because the services are named per township (porterzon, harlemzon, sciotozon) and owned by an individual at the planning commission, so a title search returns one township and invites the conclusion that nothing is published. The districts are ingested now so that a use table can later be added as a row rather than requiring a re-survey. Until then every district reads UNKNOWN with a rationale naming why. When the use table is written it MUST be scoped per township in district_classes keyed "CODE|Township": each township adopted its own resolution, and the live layer shows FR-1 in 12 of the 16 townships, PRD in 7, PCD in 7, PID in 6, C-2 in 6 and R-2 in 6 — with the district names differing between them, Berkshire''s FR-1 being a "Farm Residential District" and Brown''s a "Farm Residence District". A flat by_right or prohibited entry for FR-1 would decide twelve townships from whichever single resolution happened to be read, which is the Licking C-1 failure the engine already refuses to repeat. The resolutions themselves are published as PDFs by the Delaware County Regional Planning Commission alongside the map. Thompson, Radnor and Marlboro adopted the county code under ORC 303 rather than writing their own, so their polygons arrive under the label "Delaware County code" rather than under any one township''s name.',
  NULL,
  'Delaware County Regional Planning Commission township zoning web map and published resolutions (regionalplanning.co.delaware.oh.us)',
  6);
