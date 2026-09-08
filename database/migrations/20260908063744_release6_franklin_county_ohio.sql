-- Release 6 — Franklin County, Ohio: the second parcel jurisdiction.
--
-- Central Ohio is a PJM market, so power diligence, the national overlays
-- and PeeringDB all carried over with no change. What this adds is the
-- jurisdiction's own half: where its parcels come from, what its
-- ordinance-equivalent rules are, and what its deferral costs to unwind.

INSERT INTO public.data_sources (source_key, organization, dataset, endpoint_url, description) VALUES
  ('franklin_tax_parcels', 'Franklin County Auditor, Ohio',
   'Tax parcel boundaries with assessment',
   'https://gis.franklincountyohio.gov/hosting/rest/services/ParcelFeatures/Parcel_Features/FeatureServer/0',
   'Cadastral boundaries carrying the assessment on the same feature: land, building and total value, the CAUV land value for parcels in Current Agricultural Use Valuation, property class, and the most recent sale price and date. Ohio publishes in one place what Virginia splits between a parcel layer and an annual roll.')
ON CONFLICT (source_key) DO NOTHING;

-- Gate rules. Deliberately the same thresholds as the Loudoun pilot,
-- because they are physical rather than jurisdictional — a 25% slope is
-- as unbuildable in Ohio as in Virginia. The zoning rule is absent, not
-- lenient: Ohio zones by municipality and township, so no county-wide
-- ordinance layer exists to read and the gate stays UNKNOWN.
INSERT INTO public.constraint_rules (gate_key, jurisdiction, rule_version, params, description)
VALUES
  ('contiguous_acreage', 'Franklin County, OH', 'v1', '{"min_acres": 20}'::jsonb,
   'Minimum contiguous developable acreage, matching the Loudoun pilot so the two jurisdictions screen on one threshold.'),
  ('floodway', 'Franklin County, OH', 'v1', '{"fail_pct": 25, "conditional_pct": 5}'::jsonb,
   'Regulatory floodway coverage. Fails outright above a quarter of the parcel.'),
  ('wetlands', 'Franklin County, OH', 'v1', '{"fail_pct": 25, "conditional_pct": 5}'::jsonb,
   'NWI wetland coverage; delineation and permitting required above the conditional threshold.'),
  ('slope', 'Franklin County, OH', 'v1', '{"max_fail_pct": 25, "median_conditional_pct": 8}'::jsonb,
   'Terrain, from 3DEP sampling. Physical rather than jurisdictional, so unchanged from the pilot.'),
  ('protected_land', 'Franklin County, OH', 'v1', '{"fail_pct": 10}'::jsonb,
   'PAD-US protected-area overlap.'),
  ('road_access', 'Franklin County, OH', 'v1', '{"max_distance_miles": 1.0}'::jsonb,
   'Distance to a TIGER primary or secondary road.'),
  ('power_capacity', 'Franklin County, OH', 'v1',
   '{"active_statuses": ["EP", "UC", "PL"], "queue_radius_miles": 3, "slip_min_sample": 30}'::jsonb,
   'PJM RTEP evidence. Central Ohio is in PJM, so this is the identical rule the Loudoun pilot uses.')
ON CONFLICT DO NOTHING;

INSERT INTO public.cost_assumptions
  (assumption_key, jurisdiction, assumption_version, params, basis, source_url, source_org, source_date, unit)
VALUES
('land_use_rollback', 'Franklin County, OH', 'v1',
 '{"tax_rate_per_100_usd": 1.50, "rollback_years": 3, "interest_included": false,
   "penalty_included": false, "deferral_held_constant": true}'::jsonb,
 'Ohio Revised Code 5713.34 recoups the tax saved by Current Agricultural Use Valuation over the three tax years immediately preceding conversion — three, where Virginia recoups five — and the charge becomes a lien on the land. The deferred amount is the Auditor''s appraised land value less the CAUV value, both carried on the parcel feature. EVIDENCE IS WEAKER HERE THAN IN LOUDOUN, and deliberately recorded as such: Loudoun publishes a per-parcel estimated levy that independently confirmed its rate across 135,996 parcels, whereas Franklin County publishes no per-parcel levy, so this uses a countywide average effective rate of about 1.5% of market value drawn from converging third-party aggregations (1.40%, 1.47%, 1.69%) rather than from the county itself. Actual rates vary by taxing district and school district; the parcel''s district code is published but its millage is not. Ohio also assesses at 35% of market value, which the published effective rates already account for. Treat as an order-of-magnitude liability, not a settlement figure.',
 'https://codes.ohio.gov/ohio-revised-code/section-5713.34',
 'Ohio Revised Code; third-party effective-rate aggregations', '2026-01-01', 'USD'),

('site_prep', 'Franklin County, OH', 'v1',
 '{"clearing_usd_per_acre": 3000, "earthwork_usd_per_cy": 6.54,
   "graded_pad_cap_acres": 100, "terrace_relief_ft": 12, "max_terraces": 4,
   "aace_class": 5, "accuracy_low_pct": -50, "accuracy_high_pct": 100,
   "scope": "clearing and grubbing, plus balanced-cut mass earthwork for a single graded pad",
   "excludes": ["stormwater management and SWM ponds", "erosion and sediment control",
                "utility trenching and service extension", "access roads and entrances",
                "imported structural fill", "rock excavation", "environmental mitigation",
                "retaining structures", "off-site improvements and proffers"]}'::jsonb,
 'Identical in method to the Loudoun assumption: an AACE International 18R-97 Class 5 parametric estimate at -50%/+100%, with quantities from the parcel''s developable acreage and its median slope sampled from 3DEP, and earthwork terraced rather than levelled to a single plane. The unit costs are not Virginia-specific — $6.54 per cubic yard is a state DOT weighted average of awarded excavation prices, and clearing is a regional midpoint — so they carry to Ohio unchanged. Central Ohio''s gentler terrain will produce lower figures than Loudoun''s through the slope input rather than through any change of assumption.',
 'https://web.aacei.org/docs/default-source/toc/toc_18r-97.pdf',
 'AACE International 18R-97; Florida DOT historical item average unit costs', '2026-01-01', 'USD');

INSERT INTO public.jurisdiction_programs
  (jurisdiction_code, program_key, program_name, kind, authority, summary,
   qualifying_conditions, policy_risk, source_url, source_org, source_date)
VALUES
('OH', 'data_center_sales_use_exemption',
 'Ohio Data Center Sales and Use Tax Exemption', 'exemption',
 'Ohio Revised Code 122.175',
 'Exempts qualifying data centre equipment — computer equipment, servers, cooling and power infrastructure — from Ohio sales and use tax, under an agreement approved by the Ohio Tax Credit Authority.',
 '{"capital_investment_usd": 100000000, "annual_payroll_usd": 1500000,
   "agreement_required_with": "Ohio Tax Credit Authority",
   "note": "Thresholds are measured over a period set in the agreement; terms are negotiated per project rather than fixed by formula."}'::jsonb,
 'Granted by agreement rather than by right, so the benefit is neither automatic nor uniform between projects, and the term is whatever the approved agreement sets.',
 'https://codes.ohio.gov/ohio-revised-code/section-122.175', 'Ohio Revised Code', '2026-01-01')
ON CONFLICT (jurisdiction_code, program_key) DO NOTHING;
