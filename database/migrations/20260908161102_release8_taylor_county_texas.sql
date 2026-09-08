-- Release 8 — Taylor County, Texas: the third parcel jurisdiction, and
-- the first outside PJM.
--
-- Nothing from the power diligence layer carries over. RTEP is a PJM
-- product and Abilene is in ERCOT, so upgrade cost, the empirical
-- schedule slip and the energization windows have no equivalent here and
-- the power gate stays UNKNOWN. What does carry is every national overlay
-- and the interconnection layer — which for this county is itself the
-- headline: the nearest interconnection facility is 138 miles away and
-- not one screening cell has peering within 25 miles.

INSERT INTO public.data_sources (source_key, organization, dataset, endpoint_url, description) VALUES
  ('taylor_cad_parcels', 'Taylor Central Appraisal District, Texas',
   'Cadastral parcel shapefile',
   'https://taylor-cad.org/data-downloads/',
   'Parcel boundaries published as a dated ESRI shapefile in Texas North Central state plane. Texas has no queryable county parcel service — the statewide StratMap layer advertises a Query capability and refuses every query form — so the district publishes files instead. Assessed value, tax and agricultural deferral are published separately in the certified appraisal roll, a 60 MB archive expanding to 2 GB of fixed-width CAMA files, and are not yet ingested.')
ON CONFLICT (source_key) DO NOTHING;

-- Gate rules. The same physical thresholds as the other jurisdictions —
-- a 25% slope is unbuildable in Texas too. Two gates are deliberately
-- absent rather than lenient:
--   zoning: Texas counties have no general zoning authority over
--     unincorporated land, so most of this county has no ordinance to
--     test. That is a finding, not a pass, so the gate stays UNKNOWN.
--   power_capacity: no ERCOT equivalent of the PJM RTEP evidence exists
--     in this engine yet.
INSERT INTO public.constraint_rules (gate_key, jurisdiction, rule_version, params, description)
VALUES
  ('contiguous_acreage', 'Taylor County, TX', 'v1', '{"min_acres": 20}'::jsonb,
   'Minimum contiguous developable acreage, matching the other jurisdictions so all three screen on one threshold.'),
  ('floodway', 'Taylor County, TX', 'v1', '{"fail_pct": 25, "conditional_pct": 5}'::jsonb,
   'Regulatory floodway coverage, from the national NFHL.'),
  ('wetlands', 'Taylor County, TX', 'v1', '{"fail_pct": 25, "conditional_pct": 5}'::jsonb,
   'NWI wetland coverage; delineation and permitting required above the conditional threshold.'),
  ('slope', 'Taylor County, TX', 'v1', '{"max_fail_pct": 25, "median_conditional_pct": 8}'::jsonb,
   'Terrain, from 3DEP sampling. Physical rather than jurisdictional, so unchanged.'),
  ('protected_land', 'Taylor County, TX', 'v1', '{"fail_pct": 10}'::jsonb,
   'PAD-US protected-area overlap.'),
  ('road_access', 'Taylor County, TX', 'v1', '{"max_distance_miles": 1.0}'::jsonb,
   'Distance to a TIGER primary or secondary road.')
ON CONFLICT DO NOTHING;

-- Site preparation carries over unchanged in method; the unit costs are a
-- state DOT weighted average and a regional clearing midpoint, neither
-- specific to Virginia.
--
-- No land_use_rollback assumption is seeded. Texas does have an
-- agricultural valuation with a rollback on conversion, but the deferred
-- amounts live in the appraisal roll that is not yet ingested, and an
-- assumption with nothing to price would be machinery pretending to be
-- evidence.
INSERT INTO public.cost_assumptions
  (assumption_key, jurisdiction, assumption_version, params, basis, source_url, source_org, source_date, unit)
VALUES
('site_prep', 'Taylor County, TX', 'v1',
 '{"clearing_usd_per_acre": 3000, "earthwork_usd_per_cy": 6.54,
   "graded_pad_cap_acres": 100, "terrace_relief_ft": 12, "max_terraces": 4,
   "aace_class": 5, "accuracy_low_pct": -50, "accuracy_high_pct": 100,
   "scope": "clearing and grubbing, plus balanced-cut mass earthwork for a single graded pad",
   "excludes": ["stormwater management and SWM ponds", "erosion and sediment control",
                "utility trenching and service extension", "access roads and entrances",
                "imported structural fill", "rock excavation", "environmental mitigation",
                "retaining structures", "off-site improvements and proffers"]}'::jsonb,
 'Identical in method to the Loudoun and Franklin assumptions: an AACE International 18R-97 Class 5 parametric estimate at -50%/+100%, quantities from the parcel''s developable acreage and its median slope sampled from 3DEP, earthwork terraced rather than levelled to a single plane. The unit costs are not jurisdiction-specific — $6.54 per cubic yard is a state DOT weighted average of awarded excavation prices and clearing is a regional midpoint — so they carry unchanged. Clearing remains the weaker of the two figures, and on the sparser vegetation of West Texas it is more likely to overstate than understate.',
 'https://web.aacei.org/docs/default-source/toc/toc_18r-97.pdf',
 'AACE International 18R-97; Florida DOT historical item average unit costs',
 '2026-01-01', 'USD');

INSERT INTO public.jurisdiction_programs
  (jurisdiction_code, program_key, program_name, kind, authority, summary,
   qualifying_conditions, policy_risk, source_url, source_org, source_date)
VALUES
('TX', 'data_center_sales_use_exemption',
 'Texas Data Center Sales and Use Tax Exemption', 'exemption',
 'Texas Tax Code 151.359',
 'Exempts qualifying data centre equipment — servers, cooling and power infrastructure, and electricity consumed — from Texas state sales and use tax, for facilities certified by the Comptroller.',
 '{"capital_investment_usd": 200000000, "new_jobs": 20,
   "wage_requirement": "at least 120% of the county average weekly wage",
   "minimum_space_sq_ft": 100000,
   "certification_required_with": "Texas Comptroller of Public Accounts",
   "note": "Thresholds are for the large data centre exemption; a separate tier exists for qualifying large-scale projects."}'::jsonb,
 'Certification is granted per facility rather than by right, and the exemption term runs from certification, so the benefit depends on qualifying and on when certification lands rather than on the site itself.',
 'https://statutes.capitol.texas.gov/Docs/TX/htm/TX.151.htm',
 'Texas Tax Code', '2026-01-01')
ON CONFLICT (jurisdiction_code, program_key) DO NOTHING;
