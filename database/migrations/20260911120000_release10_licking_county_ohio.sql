-- Release 10 — Licking County, Ohio: the fourth parcel jurisdiction, and
-- the first that shares a state with one (OH-FRANKLIN). That is only
-- possible because Phase 0 re-keyed regions to county slugs; this
-- migration adds the jurisdiction's own half and nothing that touches
-- Franklin's rows.
--
-- Central Ohio is a PJM market, so power diligence, the national overlays
-- and PeeringDB carry over unchanged. What Licking adds beyond Franklin:
-- a published township zoning layer (the one thing Franklin lacks), and
-- per-parcel CAUV acres and land value on the auditor's roll itself.

INSERT INTO public.data_sources (source_key, organization, dataset, endpoint_url, description) VALUES
  ('licking_tax_parcels', 'Licking County Auditor, Ohio',
   'Tax parcel boundaries with assessment',
   'https://gis.lickingcounty.gov/server/rest/services/Auditor/Parcels/FeatureServer/0',
   'Cadastral boundaries carrying the CAMA assessment inline: market land, improvement and total value, CAUV acres and CAUV land value for enrolled farmland, abated improvement value, TIF standing, property class and township, plus the three most recent transfers. Parcel ids are unique on every non-null row; the 1,180 null rows are non-parcel slivers that filter at query time. Acreage fields are uniformly acres (probed per row, 2026-09-10).'),
  ('licking_township_zoning', 'Licking County, Ohio — Planning',
   'Township zoning districts (25 per-township layers)',
   'https://gis.lickingcounty.gov/server/rest/services/Planning/Zoning/FeatureServer',
   'One polygon layer per township: zoning class, description, overlay, township, resolution and URL. Six townships carry a single blanket Unzoned (UZ) polygon. Municipal zoning (Newark, Granville, Pataskala, Johnstown) is not in the service; municipal parcels keep no district and their gates record UNKNOWN.')
ON CONFLICT (source_key) DO NOTHING;

-- Gate rules. The seven physical gates are deliberately Franklin's
-- thresholds verbatim: a 25% slope is as unbuildable in Licking as in
-- Franklin and Loudoun. The zoning rule is what Licking has that Franklin
-- cannot: a real district layer, mapped at screening level.
INSERT INTO public.constraint_rules (gate_key, jurisdiction, rule_version, params, description)
VALUES
  ('contiguous_acreage', 'Licking County, OH', 'v1', '{"min_acres": 20}'::jsonb,
   'Minimum contiguous developable acreage, matching the pilot and Franklin so all parcel jurisdictions screen on one threshold.'),
  ('floodway', 'Licking County, OH', 'v1', '{"fail_pct": 25, "conditional_pct": 5}'::jsonb,
   'Regulatory floodway coverage from the federal NFHL. Fails outright above a quarter of the parcel.'),
  ('wetlands', 'Licking County, OH', 'v1', '{"fail_pct": 25, "conditional_pct": 5}'::jsonb,
   'NWI wetland coverage; delineation and permitting required above the conditional threshold.'),
  ('slope', 'Licking County, OH', 'v1', '{"max_fail_pct": 25, "median_conditional_pct": 8}'::jsonb,
   'Terrain, from 3DEP sampling. Physical rather than jurisdictional, so unchanged.'),
  ('protected_land', 'Licking County, OH', 'v1', '{"fail_pct": 10}'::jsonb,
   'PAD-US protected-area overlap.'),
  ('road_access', 'Licking County, OH', 'v1', '{"max_distance_miles": 1.0}'::jsonb,
   'Distance to a TIGER primary or secondary road (county TIGER/Line fallback 39089).'),
  ('power_capacity', 'Licking County, OH', 'v1',
   '{"active_statuses": ["EP", "UC", "PL"], "queue_radius_miles": 3, "slip_min_sample": 30}'::jsonb,
   'PJM RTEP evidence. West Licking is in PJM, so this is the identical rule Loudoun and Franklin use.'),
  ('zoning_dc_use', 'Licking County, OH', '2025-township-screening',
   '{"by_right": ["M-1", "M-2", "I", "M&D"],
     "special_exception": ["IE-W", "PUD", "PMUD"],
     "prohibited": ["AG", "R", "R-1", "R-2", "R-3", "R-15", "R-45", "R-70",
                    "R-87", "R-E", "RR", "RR-3", "RR-4", "RS", "SER",
                    "ER-NEOD", "MHP", "PRCD", "CCRC", "B-1", "B-2", "GB",
                    "GB1", "GB-1", "GB-2", "LB", "NB", "IB", "BLB", "JB",
                    "AB", "CN"],
     "unknown_jurisdiction": ["UZ"]}'::jsonb,
   'SCREENING MAPPING, NOT AN ORDINANCE REVIEW. Class is read from the county''s own district descriptions: manufacturing and industrial districts (M-1 Light/General Manufacturing, M-2 Heavy/General Manufacturing, I Industrial And Manufacturing, M&D Manufacturing & Distribution) screen as by-right; planned districts (PUD, PMUD) and Jersey township''s Innovation Employment overlay (IE-W) screen as special exception; agricultural, residential and business/commercial districts screen as prohibited. UZ is the six townships that administer no zoning — unknown_jurisdiction, a real finding. Anything not listed (the Jersey Mink Corridor overlay subareas MCOA-MCOD, mixed-use and overlay districts, the ambiguous C-1 which means Conservancy in one township and Local Commercial in another) is deliberately UNMAPPED: the gate engine records UNKNOWN rather than guess, and the use tables should be read before those districts are mapped.')
ON CONFLICT (gate_key, jurisdiction, rule_version) DO NOTHING;

-- Cost assumptions. Per-jurisdiction rows even where the params are
-- identical: the jurisdiction column is what keeps one statute from being
-- described with another's citation (the test suite asserts this).
INSERT INTO public.cost_assumptions
  (assumption_key, jurisdiction, assumption_version, params, basis, source_url, source_org, source_date, unit)
VALUES
('land_use_rollback', 'Licking County, OH', 'v1',
 '{"tax_rate_per_100_usd": 1.50, "rollback_years": 3, "interest_included": false,
   "penalty_included": false, "deferral_held_constant": true}'::jsonb,
 'Ohio Revised Code 5713.34 — the same statute Franklin County is under, in its own row so the citation travels with the jurisdiction. Recoups the tax saved by Current Agricultural Use Valuation over the three tax years immediately preceding conversion, and the charge becomes a lien on the land. The deferred amount is the Auditor''s market land value less the CAUV land value, both carried on the parcel feature; Licking additionally publishes CAUVAcres per parcel (6,276 enrolled parcels county-wide), so enrollment is read rather than inferred from a class code. EVIDENCE IS WEAKER THAN IN LOUDOUN, and recorded as such: no per-parcel levy is published, so the rate is a countywide average effective rate of about 1.5% of market value from converging third-party aggregations, not from the county; actual rates vary by taxing and school district. Treat as an order-of-magnitude liability, not a settlement figure.',
 'https://codes.ohio.gov/ohio-revised-code/section-5713.34',
 'Ohio Revised Code; third-party effective-rate aggregations', '2026-01-01', 'USD'),

('site_prep', 'Licking County, OH', 'v1',
 '{"clearing_usd_per_acre": 3000, "earthwork_usd_per_cy": 6.54,
   "graded_pad_cap_acres": 100, "terrace_relief_ft": 12, "max_terraces": 4,
   "aace_class": 5, "accuracy_low_pct": -50, "accuracy_high_pct": 100,
   "scope": "clearing and grubbing, plus balanced-cut mass earthwork for a single graded pad",
   "excludes": ["stormwater management and SWM ponds", "erosion and sediment control",
                "utility trenching and service extension", "access roads and entrances",
                "imported structural fill", "rock excavation", "environmental mitigation",
                "retaining structures", "off-site improvements and proffers"]}'::jsonb,
 'Params copied verbatim from the Franklin row: the unit costs are not jurisdiction-specific ($6.54 per cubic yard is a state DOT weighted average of awarded excavation prices; clearing is a regional midpoint), so the row must exist for this jurisdiction — otherwise site prep prices at nothing — but need not differ. An AACE International 18R-97 Class 5 parametric estimate at -50%/+100%, with quantities from the parcel''s developable acreage and median slope sampled from 3DEP, terraced rather than levelled. Central Ohio''s gentler terrain produces lower figures through the slope input rather than through any change of assumption.',
 'https://web.aacei.org/docs/default-source/toc/toc_18r-97.pdf',
 'AACE International 18R-97; Florida DOT historical item average unit costs', '2026-01-01', 'USD')
ON CONFLICT (assumption_key, jurisdiction, assumption_version) DO NOTHING;
