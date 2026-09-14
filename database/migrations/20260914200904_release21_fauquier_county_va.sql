-- ============================================================================
-- Migration: release21_fauquier_county_va
-- Description: Fauquier County, VA — the sixth parcel jurisdiction and the
--   third in PJM's Virginia territory.
--
--   Seven gates carry the same parameters as Loudoun and Prince William. The
--   thresholds are not Virginia-specific: they are project judgement about
--   earthwork, constructability and federal regulation, already recorded with
--   their basis, and they carry to a third county in the same market
--   unchanged.
--
--   The eighth row is the reason this migration needs a comment.
--
--   Fauquier publishes a county-wide zoning layer — 433 district polygons, 23
--   classes, "a component of the official zoning ordinance" by the county's
--   own metadata — and qualify_parcels REFUSES a zoning-supplying
--   jurisdiction with no zoning_dc_use row, because the built-in default is
--   Loudoun's use table and a borrowed verdict is the failure this engine
--   exists to prevent.
--
--   So the row exists and is deliberately EMPTY. The ordinance could not be
--   retrieved (docs/fauquier-research.md): fauquiercounty.gov answers 403 to
--   every fetcher, Municode serves a JavaScript shell, and the one ordinance
--   PDF that surfaced in search amends the rules on nonagricultural fill
--   material. What is publicly reported — data centres confined to PCID and
--   Business Park, a March 2024 amendment requiring a special exception above
--   50,000 sq ft, under 10,000 sq ft by right — is journalism and a law-firm
--   note, not an instrument, and this project has three times been bitten by
--   a rule version named for an amendment it does not encode.
--
--   Two questions the reporting cannot answer would each change the gate:
--   whether the 50,000 sq ft threshold applies county-wide across PCID or
--   only to the Vint Hill PCID that every source names, and what Business
--   Park permits at all.
--
--   An empty use table produces UNKNOWN on every parcel WITH a rationale
--   naming why — "district is not in the reviewed mapping; use status remains
--   UNKNOWN until the ordinance use table is checked" — while still recording
--   which district each parcel sits in. Measured on 25 parcels before this
--   was applied: 25 UNKNOWN, 100% zoning coverage, every row carrying a
--   rationale.
--
--   reviewed_at is NULL on every row: nothing has been reviewed. The zoning
--   row carries review_due_months 6 rather than 12 because it is a placeholder
--   and should be chased, not left to age quietly for a year.
--
--   Replace the zoning row, do not edit it, once the adopted text of the
--   March 2024 amendment and the PCID and BP use tables are in hand.
--
--   No water_availability row: the Water and Sanitation Authority publishes
--   one static PDF dated 2017 and confirms service by telephone, and
--   Waterlines_DL is National Hydrography Dataset stream geometry rather than
--   mains. Water reads UNKNOWN county-wide and no proxy is offered.
--
--   Applied 2026-09-14.
-- ============================================================================

INSERT INTO public.constraint_rules
    (gate_key, jurisdiction, rule_version, params, description, basis,
     reviewed_at, reviewed_against, review_due_months)
VALUES
('contiguous_acreage', 'Fauquier County, VA', 'v1',
 '{"min_pass_acres": 100, "min_conditional_acres": 25}'::jsonb,
 'Contiguous developable acreage thresholds.',
 'Project judgement, identical to Loudoun and Prince William: a 100+ MW campus needs a large contiguous pad, and 100 acres is the working floor for one. The figure is not jurisdiction-specific and carries to a third Virginia county unchanged. Fauquier''s legal acreage comes from the county''s ACREAGE field, which is published as text: ''0'' and blank are read as UNKNOWN rather than zero, because zero acres would fail this gate where the county has simply not stated a figure.',
 NULL, NULL, 12),

('floodway', 'Fauquier County, VA', 'v1',
 '{"floodway_fail_pct": 0.5, "floodplain_conditional": true}'::jsonb,
 'Regulatory floodway encroachment.',
 'Near-zero by regulation rather than preference: 44 CFR 60.3(d)(3) prohibits development in a regulatory floodway that would raise base flood elevation, so any material floodway area on a pad is a federal obstacle, not a cost. Federal rule, identical in every county.',
 NULL, NULL, 12),

('wetlands', 'Fauquier County, VA', 'v1',
 '{"fail_pct": 30, "conditional_pct": 5}'::jsonb,
 'NWI wetland coverage thresholds.',
 'Project judgement, identical across jurisdictions. NWI is a remote-sensed inventory rather than a jurisdictional determination, so these thresholds flag the need for a delineation; they never stand in for one.',
 NULL, NULL, 12),

('protected_land', 'Fauquier County, VA', 'v1',
 '{"fail_pct": 0.5}'::jsonb,
 'PAD-US protected area overlap.',
 'Project judgement, deliberately strict: fee-protected land and conservation easements are not ordinarily available for development at any price, so even slight overlap is treated as disqualifying rather than as a cost. Fauquier carries an unusually large easement inventory, which makes the strictness more load-bearing here than elsewhere, not less.',
 NULL, NULL, 12),

('slope', 'Fauquier County, VA', 'v1',
 '{"max_fail_pct": 25, "median_conditional_pct": 8}'::jsonb,
 'Terrain thresholds from 3DEP sampling.',
 'Project judgement informed by earthwork cost, which rises with the cube of the fall (see underwriting._graded_cut_cy). 25% max is where a graded pad stops being economic at screening scale; 8% median is where terracing becomes the dominant cost. Neither is a code limit, and a site above them is expensive rather than forbidden.',
 NULL, NULL, 12),

('road_access', 'Fauquier County, VA', 'v1',
 '{"fail_miles": 5, "conditional_miles": 2}'::jsonb,
 'Distance to a primary or secondary road.',
 'Project judgement. Distance to a TIGER primary or secondary road stands in for constructability of heavy-haul access during build-out; it is a proxy for cost and schedule, not a legal constraint.',
 NULL, NULL, 12),

('power_capacity', 'Fauquier County, VA', 'v1',
 '{"active_statuses": ["EP", "UC", "PL"], "queue_radius_miles": 3}'::jsonb,
 'PJM RTEP upgrade activity and queue proximity.',
 'Status codes are PJM''s own. The 3-mile queue radius is project judgement: far enough to catch the interconnection activity that actually bears on a site, near enough not to credit a site with a project it cannot reach. Fauquier is in PJM, so the RTEP and queue evidence carries from the other Virginia counties unchanged.',
 NULL, NULL, 12),

('zoning_dc_use', 'Fauquier County, VA', '2026-districts-only',
 '{"by_right": [], "special_exception": [], "prohibited": []}'::jsonb,
 'Districts ingested; no use table yet. Every district reads UNKNOWN.',
 'DELIBERATELY EMPTY. Fauquier publishes its zoning districts (Zoning_Districts_DL, 433 polygons, 23 classes, described by the county as a component of the official zoning ordinance) but the ordinance text itself was not retrievable: fauquiercounty.gov returns 403 to every fetcher, Municode serves a JavaScript shell, and the one ordinance PDF that surfaced in search amends the rules on nonagricultural fill material. What is publicly reported -- that data centres are confined to the PCID and Business Park districts, that a March 2024 amendment requires a special exception above 50,000 square feet, and that under 10,000 square feet remains by right -- is journalism and a law-firm note, not an instrument, and this project has three times been bitten by a rule version named for an amendment it does not encode. Two questions the reporting cannot answer would each change the gate: whether the 50,000 sq ft threshold applies county-wide across PCID or only to the Vint Hill PCID that every source names, and what Business Park permits at all. An empty mapping therefore returns UNKNOWN for every district, with the rationale naming the reason, while still recording which district each parcel sits in. Replace this row -- do not edit it -- once the adopted text of the March 2024 amendment and the PCID and BP use tables are in hand.',
 NULL, NULL, 6);
