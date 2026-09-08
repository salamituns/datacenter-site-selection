-- Release 4e — site preparation becomes a real screening estimate.
--
-- v1 was a placeholder: a flat $1,500-8,000 per acre from contractor
-- pricing guides, which could not distinguish a flat site from a steep one
-- and had no professional standing.
--
-- v2 replaces it with a parametric model classified against a published
-- standard. AACE International 18R-97 classifies an estimate made at 0-2%
-- project definition, by parametric methods, for go/no-go screening, as
-- Class 5 with an expected accuracy of -50% to +100%. That is precisely
-- this tool's job, so the accuracy band is the standard's rather than one
-- invented here, and the estimate can be named for what it is.
--
-- Quantities are the parcel's own measurements: developable acreage, and
-- median slope sampled per parcel from the USGS 3DEP elevation model.
-- Earthwork is terraced rather than levelled to a single plane, which is
-- what brings volumes into the range site work on rolling ground actually
-- moves, while keeping the estimate sensitive to terrain.
INSERT INTO public.cost_assumptions
  (assumption_key, jurisdiction, assumption_version, params, basis, source_url, source_org, source_date, unit)
VALUES
('site_prep', 'Loudoun County, VA', 'v2',
 '{"clearing_usd_per_acre": 3000,
   "earthwork_usd_per_cy": 6.54,
   "graded_pad_cap_acres": 100,
   "terrace_relief_ft": 12,
   "max_terraces": 4,
   "aace_class": 5,
   "accuracy_low_pct": -50,
   "accuracy_high_pct": 100,
   "scope": "clearing and grubbing, plus balanced-cut mass earthwork for a single graded pad",
   "excludes": ["stormwater management and SWM ponds", "erosion and sediment control",
                "utility trenching and service extension", "access roads and entrances",
                "imported structural fill", "rock excavation", "environmental mitigation",
                "retaining structures", "off-site improvements and proffers"]}'::jsonb,
 'AACE International 18R-97 Class 5 parametric estimate — the recognised classification for a concept-screening, go/no-go estimate at 0-2% project definition, carrying a published accuracy of -50% to +100%. The band shown is that standard''s, not an invented range. UNIT COSTS: earthwork at $6.54 per cubic yard is the Florida DOT statewide weighted average of awarded contract prices for regular excavation, 2025-26 — an actual price paid on public contracts rather than a quoted rate. It is used as a Southeast proxy because a comparable VDOT weighted average is not published in retrievable form; it sits mid-range against Virginia contractor quotes of $3-12 per cubic yard, and regional variation is well inside the Class 5 band. Clearing at $3,000 per acre is the midpoint of converging Virginia land-clearing ranges ($1,500-5,000 and $1,500-8,000) and is the weaker of the two figures. QUANTITIES: the graded pad is the developable acreage capped at 100 acres, about the footprint of a 100 MW campus including buildings, substation, parking and stormwater; earthwork is balanced cut/fill, so nothing is imported or exported. SCOPE IS NARROW: clearing and mass earthwork only. Stormwater management, erosion and sediment control, utilities, access roads, structural fill, rock excavation, mitigation, retaining structures and proffers are all excluded, and any one of them can rival the whole figure on a constrained site. EARTHWORK IS TERRACED, NOT SINGLE-PLANE: levelling a pad to one plane implies cuts nobody makes — an 80-acre pad at 4% falls about 75 feet corner to corner — so the pad is stepped, each terrace carrying at most 12 feet of relief, capped at 4 steps because a hyperscale campus needs large contiguous pads and cannot be stepped indefinitely. Dividing by the terrace count is what brings volumes into the 2,000-5,000 cubic yards per acre range that site work on rolling ground actually moves. The cap is deliberate: past four steps a steeper site genuinely is moving more earth, and the details record when a parcel hit it.',
 'https://web.aacei.org/docs/default-source/toc/toc_18r-97.pdf',
 'AACE International 18R-97; Florida DOT historical item average unit costs',
 '2026-01-01',
 'USD')
ON CONFLICT (assumption_key, assumption_version) DO UPDATE
  SET params = excluded.params, basis = excluded.basis,
      source_url = excluded.source_url, source_org = excluded.source_org;

-- v1 stays in the table but stops being current: load_assumptions takes the
-- newest valid row, and history is the point of a versioned ledger.
UPDATE public.cost_assumptions
   SET valid_to = current_date
 WHERE assumption_key = 'site_prep' AND assumption_version = 'v1';
