-- Release 12 — Prince William County, Virginia: the fifth parcel
-- jurisdiction, and the second in Virginia beside Loudoun. Same PJM
-- market, so power diligence and the national overlays carry over
-- unchanged. What PW adds is a county-wide zoning layer whose by-right
-- status depends on the county's own Data Center Opportunity Zone
-- overlay, and a CAMA join that publishes everything except assessed
-- values (no bulk roll exists; the public roll is per-parcel on the
-- Assessor's Aumentum portal — value metrics record UNKNOWN).
--
-- The zoning rule is built from PW's own ordinance (Code of Prince
-- William County, Chapter 32, Municode current through the 2026-07-14
-- supplement), section by section — never derived from Loudoun's use
-- table, whose fallback this release also made unreachable.

INSERT INTO public.data_sources (source_key, organization, dataset, endpoint_url, description) VALUES
  ('pwc_tax_parcels', 'Prince William County, Virginia — GTS (GIS)',
   'Parcel boundaries with the nightly Real Estate Assessments CAMA join ("Parcel CAMA Public")',
   'https://gisweb.pwcva.gov/arcgis/rest/services/GTS/CAMA_Parcels/MapServer/4',
   'Cadastral boundaries carrying the nightly Real Estate Assessments join: GPIN parcel id (unique on every real parcel; the only duplicate value is the 9999-99-9999 right-of-way placeholder, filtered at query time and again in-row), deed acreage, tax acreage, REA use code and recordation status. Assessed values are deliberately NOT on this layer and are not published in bulk anywhere in county GIS or open data — the public roll is per-parcel on the Assessor''s Aumentum portal (pwc.publicaccessnow.com). Probed 2026-09-11: 158,482 features, 962 parcels at or above 20 acres county-wide, paging 2,000 with resultOffset, SR 2283 (queries pass outSR=4326).'),
  ('pwc_zoning_districts', 'Prince William County, Virginia — Planning',
   'County-wide zoning districts + Data Center Opportunity Zone overlay',
   'https://gisweb.pwcva.gov/arcgis/rest/services/Planning/Zoning/MapServer/5',
   'One county-wide district layer (2,230 polygons, 31 codes, per-feature edit dates, 2025-26 edits present). The layer''s name field holds the rezoning case, not the district; district names are read from the county''s own zoning ordinance (Code of Prince William County, Chapter 32). The companion layer 7 is the Data Center Opportunity Zone overlay (Sec. 32-509; one 9,698-acre polygon, Ord. No. 16-21, adopted 2016): Chapter 32 permits a Data Center by right in the industrial and office districts only within this overlay, and by Special Use Permit outside it, so the adapter tags overlay-affected district polygons (majority of the polygon''s area inside) as "{code} (DCOZ)". Towns (Dumfries, Occoquan, Haymarket, Quantico) are mapped as TWN and read as unknown jurisdiction.')
ON CONFLICT (source_key) DO NOTHING;

-- Gate rules. The physical gates are the same thresholds every parcel
-- jurisdiction uses (a 25% slope is as unbuildable in Prince William as
-- in Loudoun). The zoning rule is PW's own, read section by section from
-- Chapter 32; the DCOZ-composite codes carry the overlay dependence the
-- ordinance itself imposes.
INSERT INTO public.constraint_rules (gate_key, jurisdiction, rule_version, params, description)
VALUES
  ('contiguous_acreage', 'Prince William County, VA', 'v1',
   '{"min_pass_acres": 100, "min_conditional_acres": 25}'::jsonb,
   'Minimum contiguous developable acreage, matching Loudoun so all parcel jurisdictions screen on one threshold.'),
  ('floodway', 'Prince William County, VA', 'v1',
   '{"floodway_fail_pct": 0.5, "floodplain_conditional": true}'::jsonb,
   'Regulatory floodway coverage from the federal NFHL; Occoquan/Bull Run corridors are the live cases.'),
  ('wetlands', 'Prince William County, VA', 'v1',
   '{"fail_pct": 30, "conditional_pct": 5}'::jsonb,
   'NWI wetland coverage; delineation and permitting required above the conditional threshold.'),
  ('slope', 'Prince William County, VA', 'v1',
   '{"max_fail_pct": 25, "median_conditional_pct": 8}'::jsonb,
   'Terrain, from 3DEP sampling. Physical rather than jurisdictional, so unchanged.'),
  ('protected_land', 'Prince William County, VA', 'v1',
   '{"fail_pct": 0.5}'::jsonb,
   'PAD-US protected-area overlap (Prince William Forest Park, Manassas Battlefield are the large federal holdings).'),
  ('road_access', 'Prince William County, VA', 'v1',
   '{"conditional_miles": 2, "fail_miles": 5}'::jsonb,
   'Distance to a TIGER primary or secondary road (county TIGER/Line fallback 51153).'),
  ('power_capacity', 'Prince William County, VA', 'v1',
   '{"active_statuses": ["EP", "UC", "PL"], "queue_radius_miles": 3}'::jsonb,
   'PJM RTEP evidence. PW is in PJM, so this is the identical rule Loudoun, Franklin and Licking use.'),
  ('water_availability', 'Prince William County, VA', 'v1',
   '{"pass_overlap_pct": 50, "conditional_overlap_pct": 5}'::jsonb,
   'Two utilities publish the boundary as county Comprehensive Plan layers (Prince William Water pressure zones + sewershed, Virginia American Water): PASS discloses the 2017-10 planning-map vintage; no NOT-served polygon exists, so absence from the boundary stays UNKNOWN, never non-service.'),
  ('zoning_dc_use', 'Prince William County, VA', '2026-ch32-screening',
   '{"by_right": ["M-1 (DCOZ)", "M-2 (DCOZ)", "M/T (DCOZ)", "O(L) (DCOZ)",
                  "O(M) (DCOZ)", "O(H) (DCOZ)", "O(F) (DCOZ)"],
     "special_exception": ["M-1", "M-2", "M/T", "O(L)", "O(M)", "O(H)",
                           "O(F)", "B-1", "MXD-U"],
     "prohibited": ["A-1", "SR-1", "SR-3", "SR-5", "R-2", "R-4", "R-6",
                    "R-16", "R-30", "RPC", "PMR", "V", "B-2", "B-3",
                    "PBD"],
     "unknown_jurisdiction": ["TWN"]}'::jsonb,
   'SCREENING MAPPING FROM PW''s OWN ORDINANCE (Code of Prince William County, Ch. 32, Municode current through the 2026-07-14 supplement) — never derived from Loudoun''s use table. Read section by section: a Data Center is by right in the industrial districts (M-1 Sec. 32-403.11, M-2 32-403.21, M/T 32-403.31) and all four office districts (O(L) 32-402.11, O(H) 32-402.21, O(M) 32-402.31, O(F) 32-402.41) only WITHIN the Data Center Opportunity Zone overlay (Sec. 32-509, Ord. No. 16-21), and by Special Use Permit outside it — the "(DCOZ)" codes are those districts tagged by the adapter where the majority of the district polygon lies inside the overlay (measured: the overlay decides 71 of the 961 candidates, 51 by-right vs 20 SUP). B-1 permits a Data Center by unconditional Special Use Permit (Sec. 32-401.13, item 10); MXD-U permits a Small Urban Data Center outside the overlay by Special Use Permit (Secs. 32-307.23/.33). Prohibited (no Data Center use in the district''s permitted lists, checked part by part): agricultural and residential districts (Parts 301-304), PMR — which explicitly excepts data centers from its secondary office uses (Sec. 32-306.11.2) — RPC, V, B-2, B-3 and PBD. TWN is the town placeholder (Dumfries, Occoquan, Haymarket, Quantico administer their own ordinances). DELIBERATELY UNMAPPED, recording UNKNOWN rather than guessing: PMD (uses follow the parcel''s land bay designation, Sec. 32-405.03/32-280.11, which the zoning layer does not carry), the conditional C-suffixed variants (A-1C, R-2C, R-4C, SR-1C — not separately reviewed), and the FED/CTY placeholders.')
ON CONFLICT (gate_key, jurisdiction, rule_version) DO NOTHING;

-- Licking's water rule, landing with the provider config that makes it
-- live (the LRWD joint boundary ships in this same release). Values are
-- the same 50/5 every water gate uses; the row exists so the gate reads
-- its thresholds from data like every other jurisdiction, and so the
-- description can carry the boundary's own caveats.
INSERT INTO public.constraint_rules (gate_key, jurisdiction, rule_version, params, description)
VALUES
  ('water_availability', 'Licking County, OH', 'v1',
   '{"pass_overlap_pct": 50, "conditional_overlap_pct": 5}'::jsonb,
   'The Licking Regional Water District (formerly SWLCWSD) publishes a JOINT water/wastewater boundary for itself and the Pataskala Utility Department, dated June 2021 (Water_Service_2021_view / Waste_Water_Service_2021). Provider is attributed row-level from the layer''s Name field, and the 2021-06 vintage is stated in every rationale; the boundary covers the Etna/Pataskala/West-Licking quadrant, so townships outside it stay UNKNOWN — absence from a 2021 boundary is never evidence of non-service. Measured: 308 of 1,990 candidates decided against the joint layer (31 Pataskala-only).')
ON CONFLICT (gate_key, jurisdiction, rule_version) DO NOTHING;

-- Cost assumptions. Per-jurisdiction rows even where the method is
-- identical: the jurisdiction column is what keeps one county's adopted
-- rate from being described with another's citation.
INSERT INTO public.cost_assumptions
  (assumption_key, jurisdiction, assumption_version, params, basis, source_url, source_org, source_date, unit)
VALUES
('land_use_rollback', 'Prince William County, VA', 'v1',
 '{"tax_rate_per_100_usd": 0.865, "rollback_years": 5, "interest_included": false,
   "penalty_included": false, "deferral_held_constant": true,
   "statute": "Code of Virginia 58.1-3237",
   "excludes": ["statutory simple interest",
                "50% penalty where rezoned to a more intensive use within five years"]}'::jsonb,
 'Code of Virginia 58.1-3237 sets the roll-back at the deferred tax for the five most recent complete tax years plus simple interest — the same statute Loudoun is under, in its own row so the citation and the rate travel with the jurisdiction. The rate is Prince William County''s own adopted FY2027 real property rate of $0.865 per $100 of assessed value, reduced from $0.906 by the Board of County Supervisors on adoption of the FY2027 budget (April 21, 2026; county fiscal year runs July 1 through June 30). HONEST LIMITATION, RECORDED AS SUCH: unlike Loudoun, PW publishes no bulk assessment roll — the public roll is per-parcel on the Assessor''s portal — so no per-parcel deferred value exists to price, and this assumption CANNOT currently fire; the row exists so that when deferral values are ever sourced, the county''s own adopted rate is the one applied, never Loudoun''s borrowed $0.805. Treat any future figure as an order-of-magnitude liability, not a settlement figure.',
 'https://www.pwcva.gov/news/board-county-supervisors-adopts-fy2027-budget-and-reduces-real-estate-tax-rate',
 'Code of Virginia; Prince William County Board of County Supervisors FY2027 adopted budget', '2026-04-21', 'USD'),

('site_prep', 'Prince William County, VA', 'v1',
 '{"clearing_usd_per_acre": 3000, "earthwork_usd_per_cy": 6.54,
   "graded_pad_cap_acres": 100, "terrace_relief_ft": 12, "max_terraces": 4,
   "aace_class": 5, "accuracy_low_pct": -50, "accuracy_high_pct": 100,
   "scope": "clearing and grubbing, plus balanced-cut mass earthwork for a single graded pad",
   "excludes": ["stormwater management and SWM ponds", "erosion and sediment control",
                "utility trenching and service extension", "access roads and entrances",
                "imported structural fill", "rock excavation", "environmental mitigation",
                "retaining structures", "off-site improvements and proffers"]}'::jsonb,
 'Params copied verbatim from the Loudoun row (as Franklin, Licking and Taylor did): the unit costs are not jurisdiction-specific — $6.54 per cubic yard is a state DOT weighted average of awarded excavation prices, clearing is a regional midpoint — so the row must exist for this jurisdiction, or site prep would price at nothing, but need not differ. An AACE International 18R-97 Class 5 parametric estimate at -50%/+100%, with quantities from the parcel''s developable acreage and median slope sampled from 3DEP, terraced rather than levelled to a single plane. PW''s coastal-plain terrain is gentler than Loudoun''s Piedmont, which produces lower figures through the slope input rather than through any change of assumption.',
 'https://web.aacei.org/docs/default-source/toc/toc_18r-97.pdf',
 'AACE International 18R-97; Florida DOT historical item average unit costs', '2026-01-01', 'USD')
ON CONFLICT (assumption_key, jurisdiction, assumption_version) DO NOTHING;
