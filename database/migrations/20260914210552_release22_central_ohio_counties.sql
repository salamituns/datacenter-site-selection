-- ============================================================================
-- Migration: release22_central_ohio_counties
-- Description: Fairfield, Union and Delaware counties, Ohio — three
--   jurisdictions added on ONE adapter, because the City of Columbus
--   publishes a regional parcels layer covering seven central Ohio counties.
--
--   That is the opposite shape from Virginia, where three counties cost three
--   adapters. It is also the finding worth keeping from the Ohio probe:
--   repeatability is a property of the state, not of the engine.
--
--   Seven gates each, same parameters as Franklin and Licking. The thresholds
--   are project judgement about earthwork, constructability and federal
--   regulation rather than anything jurisdictional, already recorded with
--   their basis, and they carry across one market unchanged.
--
--   THERE IS DELIBERATELY NO zoning_dc_use ROW FOR ANY OF THE THREE.
--
--   Ohio zones by municipality and township, not by county, so none of them
--   publishes a county-wide layer to read: Delaware publishes one township of
--   about nineteen, Union nothing county-wide, and Fairfield nothing at all —
--   the LancasterGIS zoning layers belong to the city of Lancaster, and the
--   county's own CALU service is Current Agricultural Land Use. The regional
--   parcels service carries no zoning either, and neither does MORPC.
--
--   Their adapter returns zoning: None, which is the case qualify_parcels
--   does NOT refuse — the refusal exists to stop a county that supplies a
--   zoning layer being decided by another county's use table, and there is no
--   layer here to misread. The zoning gate reads UNKNOWN in the words that
--   fit, "this jurisdiction publishes no zoning layer", carrying
--   zoning_grade: screening rather than implying a map with a gap in it.
--
--   These three join Franklin in that state. It is honest, and the
--   county-entry test names it: all four fall below the 80% zoning bar and
--   say why on the same line that scores them. Township zoning is research,
--   per township — Licking proves it is obtainable, just not from GIS.
--
--   Measured before applying, at the 20-acre floor:
--     Fairfield  3,541 parcels, acreage from ACRES,      218,033 stated / 219,074 drawn (0.5%)
--     Union      3,332 parcels, acreage from STATEDAREA, 219,491 / 216,216 (1.5%)
--     Delaware   2,760 parcels, acreage from STATEDAREA, 162,994 / 162,846 (0.1%)
--
--   Madison and Pickaway are in the same layer and are NOT added: they carry
--   no acreage in either field, so nothing could decide their acreage gate.
--
--   Applied 2026-09-14.
-- ============================================================================

INSERT INTO public.constraint_rules
    (gate_key, jurisdiction, rule_version, params, description, basis,
     reviewed_at, reviewed_against, review_due_months)
SELECT g.gate_key, j.jurisdiction, 'v1', g.params, g.description,
       g.basis || j.suffix, NULL, NULL, 12
FROM (VALUES
  ('Fairfield County, OH', ' Acreage for Fairfield comes from the regional layer''s ACRES field.'),
  ('Union County, OH',     ' Acreage for Union comes from the regional layer''s STATEDAREA field, ACRES being unpopulated there; both fields are in acres, checked on Licking rows carrying both.'),
  ('Delaware County, OH',  ' Acreage for Delaware comes from the regional layer''s STATEDAREA field, ACRES being unpopulated there; both fields are in acres, checked on Licking rows carrying both.')
) AS j(jurisdiction, suffix)
CROSS JOIN (VALUES
  ('contiguous_acreage',
   '{"min_pass_acres": 100, "min_conditional_acres": 25}'::jsonb,
   'Contiguous developable acreage thresholds.',
   'Project judgement, identical to the other five counties: a 100+ MW campus needs a large contiguous pad, and 100 acres is the working floor for one. Not jurisdiction-specific.'),
  ('floodway',
   '{"floodway_fail_pct": 0.5, "floodplain_conditional": true}'::jsonb,
   'Regulatory floodway encroachment.',
   'Near-zero by regulation rather than preference: 44 CFR 60.3(d)(3) prohibits development in a regulatory floodway that would raise base flood elevation, so any material floodway area on a pad is a federal obstacle, not a cost. Federal rule, identical in every county.'),
  ('wetlands',
   '{"fail_pct": 30, "conditional_pct": 5}'::jsonb,
   'NWI wetland coverage thresholds.',
   'Project judgement, identical across jurisdictions. NWI is a remote-sensed inventory rather than a jurisdictional determination, so these thresholds flag the need for a delineation; they never stand in for one.'),
  ('protected_land',
   '{"fail_pct": 0.5}'::jsonb,
   'PAD-US protected area overlap.',
   'Project judgement, deliberately strict: fee-protected land and conservation easements are not ordinarily available for development at any price, so even slight overlap is treated as disqualifying rather than as a cost.'),
  ('slope',
   '{"max_fail_pct": 25, "median_conditional_pct": 8}'::jsonb,
   'Terrain thresholds from 3DEP sampling.',
   'Project judgement informed by earthwork cost, which rises with the cube of the fall (see underwriting._graded_cut_cy). 25% max is where a graded pad stops being economic at screening scale; 8% median is where terracing becomes the dominant cost. Neither is a code limit.'),
  ('road_access',
   '{"fail_miles": 5, "conditional_miles": 2}'::jsonb,
   'Distance to a primary or secondary road.',
   'Project judgement. Distance to a TIGER primary or secondary road stands in for constructability of heavy-haul access during build-out; a proxy for cost and schedule, not a legal constraint.'),
  ('power_capacity',
   '{"active_statuses": ["EP", "UC", "PL"], "queue_radius_miles": 3}'::jsonb,
   'PJM RTEP upgrade activity and queue proximity.',
   'Status codes are PJM''s own. The 3-mile queue radius is project judgement: far enough to catch interconnection activity that bears on a site, near enough not to credit a site with a project it cannot reach. Central Ohio is PJM, so the RTEP and queue evidence carries from Franklin and Licking unchanged.')
) AS g(gate_key, params, description, basis);
