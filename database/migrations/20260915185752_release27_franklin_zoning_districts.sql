-- ============================================================================
-- Migration: release27_franklin_zoning_districts
-- Description: Franklin County, OH — zoning districts ingested. The adapter
--   said for a long time that none existed.
--
--   worker/franklin_api.py carried "ZONING IS NOT AVAILABLE... there is no
--   county-wide ordinance layer to read", and Franklin sat at 0% zoning
--   across 2,178 parcels on the strength of it. Franklin County Economic
--   Development and Planning publishes a county zoning districts layer AND
--   separate layers for five of the seven townships that zone themselves.
--   An ArcGIS Online title search does not surface them; tracing the
--   county's own zoning web map does. 10,910 polygons, 40 district codes.
--
--   Franklin's seventeen townships split, and the split is why this county
--   has the best ratio in Ohio:
--
--     TEN adopt the Franklin County Zoning Resolution — Brown, Clinton,
--     Franklin, Hamilton, Mifflin, Madison, Norwich, Pleasant, Sharon,
--     Truro — so ONE instrument and ONE layer cover all of them. Delaware
--     needed sixteen resolutions for 1.3%; this is one document for ten.
--
--     SEVEN zone themselves. EDPGIS publishes layers for Blendon, Perry,
--     Plain, Prairie and Washington. Jackson and Jefferson publish none
--     here, so their parcels read UNKNOWN — named in the adapter rather
--     than silently absent, because "not published" and "not looked for"
--     are different facts.
--
--   WHAT THE RESOLUTION DOES NOT SAY, and why this row is empty:
--
--     The Franklin County Zoning Resolution as amended to 2026 runs 298
--     pages and names no data-centre use anywhere. "Computer" appears only
--     in "computer data entry error"; the telecommunication provision is
--     ORC 303.211 towers. So the districts are ingested and the use table
--     stays empty, exactly as Delaware and Fauquier were done.
--
--   WHEN THE USE TABLE IS WRITTEN IT MUST BE SCOPED. LI appears in the
--   county resolution AND in Blendon, Perry and Washington — four
--   instruments, one code. CC, CS and EU likewise. district_classes keyed
--   "CODE|Source" outranks the flat lists; a flat LI entry would decide
--   four jurisdictions from whichever one was read.
--
--   Two data hazards handled in the adapter: the layer's own
--   "NOT IN JURISDICTION" marker (plus blanks and "None") is treated as a
--   non-district and left unmapped rather than classified, and one county
--   value arrives mangled with embedded newlines ("PR-10\nPR-10\nPR-10\nPR-10")
--   and is collapsed before use.
--
--   reviewed_at NULL, review_due_months 6: a placeholder to be chased.
--
--   Applied 2026-09-15.
-- ============================================================================

INSERT INTO public.constraint_rules
    (gate_key, jurisdiction, rule_version, params, description, basis,
     reviewed_at, reviewed_against, review_due_months)
VALUES (
  'zoning_dc_use', 'Franklin County, OH', '2026-districts-only',
  '{"by_right": [], "special_exception": [], "prohibited": [],
    "district_classes": {}}'::jsonb,
  'Zoning districts ingested; no use table yet. Every district reads UNKNOWN.',
  'DELIBERATELY EMPTY. This adapter asserted for a long time that Franklin published no zoning — "ZONING IS NOT AVAILABLE... there is no county-wide ordinance layer to read" — and the county sat at 0% zoning across 2,178 parcels because of it. Franklin County Economic Development and Planning publishes a county zoning districts layer and separate layers for five of the seven townships that zone themselves: 10,910 polygons, 40 district codes, found by tracing the county''s public zoning web map rather than by title search. The county''s seventeen townships split ten to seven. Ten adopted the Franklin County Zoning Resolution — Brown, Clinton, Franklin, Hamilton, Mifflin, Madison, Norwich, Pleasant, Sharon and Truro — so one instrument and one layer cover all of them, which is the best ratio in Ohio; Delaware needed sixteen resolutions to decide 1.3% of its parcels. Seven zone themselves, and EDPGIS publishes layers for Blendon, Perry, Plain, Prairie and Washington while Jackson and Jefferson publish none, so those two townships'' parcels read UNKNOWN. The use table is empty because the Resolution as amended to 2026 runs 298 pages and names no data-centre use at all: "computer" appears only in the phrase "computer data entry error", and the telecommunication provision covers ORC 303.211 towers. When a use table is written it MUST be scoped in district_classes keyed "CODE|Source", because LI appears in the county resolution and in Blendon, Perry and Washington — four instruments sharing one code — and CC, CS and EU likewise; a flat entry would decide four jurisdictions from whichever one was read. The county layer''s rows carry the label "Franklin County resolution" rather than any township name, because ten townships read it in common. The layer''s own "NOT IN JURISDICTION" marker, blanks and "None" are treated as non-districts and left unmapped rather than classified, and one county value arrives mangled with embedded newlines and is collapsed before use.',
  NULL,
  'Franklin County Zoning Resolution as amended to 2026 (298pp, read and found silent on data centres); Franklin County EDP zoning web map and its county and township district layers',
  6);
