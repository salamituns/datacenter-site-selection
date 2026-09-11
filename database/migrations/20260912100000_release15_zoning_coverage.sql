-- Release 15 — zoning coverage: the 14 unmapped districts, the Jersey
-- overlay read, and the Taylor no-county-zoning rule.
--
-- Four things ship here, all data (the engine's gate code reads whatever
-- the rows state):
--   1. A TIGER Places source + incorporated_place metric — the
--      municipal-limits test the Texas rule is gated on.
--   2. New zoning_dc_use rule versions for Licking, Prince William and
--      Loudoun, each cited to the ordinance text that decided it.
--   3. A first zoning_dc_use row for Taylor County, TX — not a use table
--      but the no-county-zoning finding itself (TX Local Government Code
--      ch. 231), applied only to parcels the Places layer confirms are
--      outside incorporated limits.
--   4. Nothing is deleted: constraint_rules is append-only by version.
--      Prior rows stay exactly where the gate rows that cite them
--      (rule_id) can find them; loaders read the newest version per
--      gate_key, so a new row governs from the next run.

-- ── The Places source and metric ─────────────────────────────────────
INSERT INTO public.data_sources (source_key, organization, dataset, endpoint_url, description) VALUES
    ('census_tiger_places', 'U.S. Census Bureau', 'TIGER/Line Places (incorporated)',
     'https://tigerweb.geo.census.gov/arcgis/rest/services/TIGERweb/Places_CouSub_ConCity_SubMCD/MapServer',
     'Incorporated-place polygons (MTFCC G4110; census designated places excluded — a CDP is unincorporated and has no zoning authority): the municipal-limits test behind the no-county-zoning rule and the incorporated-town coverage. State-cached clip like the roads layer, with the TIGER/Line state PLACE shapefile as fallback.')
ON CONFLICT (source_key) DO NOTHING;

INSERT INTO public.metric_definitions (metric_key, label, gate_key, unit, description) VALUES
    ('incorporated_place', 'Incorporated place', 'zoning_dc_use', NULL,
     'The incorporated place whose limits cover the parcel''s majority area (TIGER/Line Places); absent means no municipal limits cover it. Municipal zoning applies inside city limits.')
ON CONFLICT (metric_key) DO NOTHING;

-- ── Licking County, OH — the township-reviewed use table ─────────────
-- The county's zoning is 25 per-township resolutions, and the gate now
-- reads them the way the county publishes them: base district as the
-- district, overlays as context. Jersey Township draws overlay districts
-- as separate features ON TOP of a base (ZoningOverlay = 'Y'), and the
-- previous dominant-district read let the overlay code win and lose the
-- base — answering a different question. The overlay articles themselves
-- say the base continues until the owner's Development Plan is approved
-- (WCOD §14.05.B, §14.05.D.07: "upon such approval the Zoning Map shall
-- be changed so that any other zoning district that applied to the Tract
-- ... no longer applies to that Tract").
--
-- C-1 is scoped per township because it is two districts sharing a code:
-- a Conservation/Conservancy district (Granville §801/§903, adopted
-- 12/3/2025; Bennington Art. 305, amended eff. 12/8/2025; Harrison
-- Art. 11, 6/1/98; Hartford Art. 7, 11/21/1999; Newark Art. 11,
-- 10/27/1983; Madison Art. 7 — floodplain conservation, exclusive
-- agriculture/recreation/accessory use lists, "no dumping, filling, or
-- earth moving" in Granville's) and Liberty's "C-1 Local Commercial" GIS
-- label, which matches no findable version of Liberty's own resolution
-- (the 2022 and 2025/2026 resolutions both use LB Local Business, §806,
-- whose exclusive list contains no data-center-like use). Both readings
-- prohibit a data centre; the scoped rows keep them separate so a future
-- township's C-1 can never be decided by another township's ordinance.
INSERT INTO public.constraint_rules (gate_key, jurisdiction, rule_version, params, description) VALUES
    ('zoning_dc_use', 'Licking County, OH', '2026-township-reviewed', $json${"by_right": ["M-1", "M-2", "I", "M&D"], "special_exception": ["PUD", "PMUD"], "prohibited": ["AG", "R", "R-1", "R-2", "R-3", "R-15", "R-45", "R-70", "R-87", "R-E", "RR", "RR-3", "RR-4", "RS", "SER", "ER-NEOD", "MHP", "PRCD", "CCRC", "B-1", "B-2", "GB", "GB1", "GB-1", "GB-2", "LB", "NB", "IB", "BLB", "JB", "AB", "CN"], "unknown_jurisdiction": ["UZ"], "district_classes": {"C-1|Granville": "prohibited", "C-1|Bennington": "prohibited", "C-1|Harrison": "prohibited", "C-1|Hartford": "prohibited", "C-1|Newark": "prohibited", "C-1|Madison": "prohibited", "C-1|Liberty": "prohibited"}, "overlay_classes": {"IE-W": "special_exception", "MCOA": "special_exception", "MCOB": "special_exception", "MU-W": "prohibited", "CPO-W": "prohibited", "MCOC": "prohibited", "MCOD": "prohibited", "HMU-NWIOD": "prohibited", "NMU-NWIOD": "prohibited", "MU-NEOD": "prohibited", "ER-NEOD": "prohibited"}, "jurisdiction_reasons": {"UZ": "the township administers no zoning (the county layer marks it Unzoned); there is no use table to consult"}}$json$,
     'TOWNSHIP-REVIEWED USE TABLE (supersedes 2025-township-screening). Base districts: manufacturing/industrial by right (M-1 §12.01.B + Appendix E NAICS 518210 "Data Processing, Hosting, and Related Services" = P in the M-1 column; M-2, I, M&D); residential/agricultural/business prohibited (Jersey RR §9.00 / RR-3 §9.01 use lists are exclusive and contain no commercial or industrial category). PUD/PMUD stay special_exception because Jersey''s PUDs are ORC 519.021 districts whose permitted uses are set per district by the adopting text (Art. 14.03: "the specific list of Permitted Uses for each PMUD district is subject to approval as part of the text amendment for that PMUD district") — read each PUD''s adopted text at diligence. C-1 is scoped per township (see migration notes): Conservation in Granville/Bennington/Harrison/Hartford/Newark/Madison, and Liberty''s legacy Local Commercial label whose successor LB district (§806, resolution effective 7/9/2025) prohibits data centres by omission — prohibited either way, recorded separately. Jersey overlays, read as combinations over the base: IE-W (WCOD Art. 14.05 IE subarea, effective 11/8/2022, §14.05.F.1 lists "Data Processing Centers" in the IE column; base RR/RR-3 governs until a Development Plan is approved under §14.05.D, after which §14.05.D.07 drops the base), MCOA and MCOB (MCOD §14.06.F.1 Table 1, adopted 11/6/2023: "Data Processing Center" = P in Subareas A and B, same Development-Plan mechanism §14.06.B) are special_exception — the data centre is an expressly permitted use, but only after a township approval; MU-W, CPO-W (not listed in §14.05.F.1; §14.05.E.1 "Uses not specifically authorized ... shall be prohibited"), MCOC and MCOD-as-subarea-D (§14.06.E.1), HMU-NWIOD/NMU-NWIOD (NWIOD §14.11, adopted 7/23/2025) and MU-NEOD/ER-NEOD (NEOD §14.10, adopted 7/23/2025; use tables per the May 2025 adopted drafts) are prohibited — no data-processing use appears in any of their tables and each article prohibits unlisted uses. DELIBERATELY UNMAPPED, recording UNKNOWN rather than guessing: MUDOD and MUOD (MUDOD''s adopted Exhibit A text, Resolution 25-04-07-01 of 4/7/2025, is not published; the predecessor MUOD set uses case-by-case per district via Appendix E), the bare MU code (no such base district exists in Jersey''s resolution), and Liberty''s TC overlay. UZ is the county layer''s Unzoned marker for the six townships that administer no zoning — a real finding, not missing data.');

-- ── Prince William County, VA — the chapter-32-reviewed use table ────
-- FED: no district named FED exists anywhere in Chapter 32 — it is the
-- county's own GIS label ("FED Federal Property", Zoning Districts layer
-- coded-value domain). Classified prohibited through the code's
-- exclusive-use rule, Sec. 32-200.03(a): "only those uses specified
-- shall be permitted in the various zoning districts. If a use is not
-- specified in a zoning district, it shall be prohibited in that
-- district" — and a full-text search for "data center" returns hits only
-- in Parts 509/402/401/403/511 and Sec. 32-201.11, none of which covers
-- federal land. The rationale cites the county's own designation, not
-- PAD-US: two independent sources agreeing is the point (and PAD-US
-- already FAILs protected_land for all 32 of these parcels).
--
-- The -C suffix is CLUSTER, not proffered conditional zoning (correcting
-- the assumption in the zoning-coverage brief): the county's GIS domain
-- reads A-1C "Agricultural Cluster", R-2C/R-4C/SR-1C/SR-3C/SR-5C
-- "Cluster Residential", and the ordinance's cluster provisions (Secs.
-- 32-300.40 rural cluster in A-1, 32-300.50 semi-rural cluster in SR,
-- 32-300.60 suburban cluster in R-2/R-4) govern lot design and density
-- only — they add no uses, so the base district's use list decides, and
-- Parts 301-304 list no data center. Proffers are a separate mechanism
-- (Sec. 32-700.30(4): proffered conditions "shall be in addition to the
-- regulations provided for the zoning district") and the GIS layer tracks
-- them in its own "Proffers?" field, never as a C suffix. Explicit rows
-- for every C variant so a future C-suffixed district that means
-- something else cannot be swept in by a pattern.
--
-- PMD stays deliberately UNMAPPED, now with the mechanism verified:
-- PMD has no fixed use table — Sec. 32-405.03.1 sends permitted uses to
-- the land bay designations of Sec. 32-280.11 (residential LDR/MDR/HDR/
-- UDR/UHDR; nonresidential B-1, B-2, O(L), O(M), O(H), O/F, M-2; OS),
-- and Sec. 32-700.23(5) makes the approved master zoning plan determine
-- "the uses permitted in the land bays." The land bays live in the
-- county's separate Planned Districts GIS layer (Planning/Zoning
-- MapServer/8) as free-text, plan-specific designations (RC1, OC3,
-- ResML, "B-1/B-2/O(L)(M)(H)(F)/M-2", ...), and the 11 candidate PMD
-- parcels each span multiple land bays — resolving one requires that
-- parcel's approved master plan, not a use-table row.
INSERT INTO public.constraint_rules (gate_key, jurisdiction, rule_version, params, description) VALUES
    ('zoning_dc_use', 'Prince William County, VA', '2026-ch32-reviewed', $json${"by_right": ["M-1 (DCOZ)", "M-2 (DCOZ)", "M/T (DCOZ)", "O(L) (DCOZ)", "O(M) (DCOZ)", "O(H) (DCOZ)", "O(F) (DCOZ)"], "special_exception": ["M-1", "M-2", "M/T", "O(L)", "O(M)", "O(H)", "O(F)", "B-1", "MXD-U"], "prohibited": ["A-1", "A-1C", "SR-1", "SR-1C", "SR-3", "SR-3C", "SR-5", "SR-5C", "R-2", "R-2C", "R-4", "R-4C", "R-6", "R-16", "R-30", "RPC", "PMR", "V", "B-2", "B-3", "PBD", "FED"], "unknown_jurisdiction": ["TWN"], "jurisdiction_reasons": {"TWN": "inside an incorporated town (Dumfries, Occoquan, Haymarket, Quantico) whose ordinance the county does not publish"}}$json$,
     'CHAPTER-32-REVIEWED USE TABLE (supersedes 2026-ch32-screening), read from the Code of Prince William County, Ch. 32 (Municode, current through the 2026-07-14 supplement). Unchanged from screening: industrial/office by right only within the Data Center Opportunity Zone (Sec. 32-509, Ord. No. 16-21) — the "(DCOZ)" codes are adapter-tagged where the district polygon''s majority area lies inside the overlay — and by Special Use Permit outside it (M-1 32-403.11, M-2 32-403.21, M/T 32-403.31, O(L) 32-402.11, O(M) 32-402.31, O(H) 32-402.21, O(F) 32-402.41); B-1 by unconditional SUP (Sec. 32-401.13 item 10); MXD-U Small Urban Data Center by SUP (Secs. 32-307.23/.33); agricultural/residential districts, PMR (which excepts data centers from its secondary office uses, Sec. 32-306.11.2), RPC, V, B-2, B-3, PBD prohibited (no data-center use in Parts 301-306, checked part by part). NEW, each cited: FED (32 parcels, ~41,121 acres) prohibited via Sec. 32-200.03(a) exclusive-use rule — no FED district exists in the ordinance text; "FED Federal Property" is the county''s own GIS zoning designation (Planning/Zoning MapServer/5 coded domain), and this row cites the county''s designation, not PAD-US, which independently FAILs these parcels on protected_land. The C-suffixed cluster variants (A-1C, R-2C, R-4C, SR-1C, SR-3C, SR-5C) prohibited as their base districts: the suffix is cluster development (GIS domain "Agricultural Cluster"/"Cluster Residential"; Secs. 32-300.40/.50/.60 — lot design and density only, no added uses), and the base use lists (Parts 301-304) contain no data center, so Sec. 32-200.03(a) prohibits. DELIBERATELY UNMAPPED, recording UNKNOWN: PMD (uses follow the parcel''s land bay under the approved master zoning plan — Secs. 32-405.03/32-280.11/32-700.23(5); land bays are published only in the separate Planned Districts layer, MapServer/8, as plan-specific free-text designations, and the 11 candidate parcels each span multiple bays, so each needs its own approved master plan), TWN (town placeholder — see jurisdiction_reasons), CTY.');

-- ── Loudoun County, VA — the ordinance-reviewed use table ────────────
-- The screening row claimed "industrial by-right (post-ZOAM)". That is
-- stale: ZOAM-2024-0001 (adopted 3/18/2025, "Data Center Standards and
-- Locations", with CPAM-2024-0001) amended Sec. 3.02.05 so the Data
-- Center row of Table 3.02.05-1 reads "S" in every office and industrial
-- district — OP, IP, GI, MR-HI — with new notes 3-4 (a minor site-plan
-- change may be permitted without SPEX; ZMAPs/ZCPAs/ZRTDs approved on or
-- before 3/18/2025 with detailed data-center proffers or CDPs are deemed
-- to include a SPEX approval). No district in the county permits a data
-- center by right anymore, so by_right is empty — an empty list is a
-- finding, not a gap. OP moves from prohibited to special_exception.
--
-- PD-SA and PD-MUB (legacy districts, Secs. 2.02.05.09/.11) are
-- prohibited: Table 3.02.02-1 row 101 (Data Center) is blank in both
-- columns — the table key: "P = Permitted | S = Special Exception | M =
-- Minor Special Exception | blank cell = Prohibited" — and the ZOAM
-- history shows no amendment touching 3.02.02 or the legacy districts.
--
-- PDGI and PDIP are not current-ordininance districts at all: they are
-- 1972 Zoning Ordinance districts that survive on the map only within
-- the Route 28 Tax District, administered under the 1972 ordinance
-- pursuant to Sec. 1.02.K.1 of the current ordinance. "Data center" is
-- not a listed use in the 1972 text; the nearest categories are
-- "Research, experimental, testing, and development activities"
-- (by-right in both, §722.3.1/§723.3.1) and "Warehousing" /
-- "Commercial office building" (by-right in PD-GI §723.3.1, only
-- Board-permissible in PD-IP §722.3.2), and whatever is actually
-- allowed on a given parcel is fixed by its approved site development
-- plans ("No structure or use other than as indicated in approved site
-- development plans and reports shall be permitted", §700.5.6.2). A
-- county determination under §501.1 is required either way — which is
-- the definition of a CONDITIONAL, so both codes map special_exception
-- and the rationale says why.
INSERT INTO public.constraint_rules (gate_key, jurisdiction, rule_version, params, description) VALUES
    ('zoning_dc_use', 'Loudoun County, VA', '2026-ord-reviewed', $json${"by_right": [], "special_exception": ["OP", "IP", "GI", "MRHI", "PDGI", "PDIP", "CLI", "PDRDP", "PDCH"], "prohibited": ["A10", "A3", "AR1", "AR2", "CR1", "CR2", "CR3", "CR4", "RC", "R1", "R2", "R3", "R4", "R8", "R16", "R24", "SCN8", "SCN16", "SCN24", "PDH3", "PDH4", "PDH6", "PDAAAR", "PDRV", "PDCCRC", "PDSC", "C1", "GB", "CCCC", "CCNC", "CCSC", "PDOP", "TRC", "TC", "TR1LF", "TR1UBF", "TR2", "TR3LBR", "TR3LF", "TR3UBF", "TR10", "PUD-1", "JLMA1", "JLMA2", "JLMA3", "JLMA20", "PDSA", "PDMUB"], "unknown_jurisdiction": ["TOWNS"], "jurisdiction_reasons": {"TOWNS": "inside an incorporated town (the county layer's TOWNS placeholder); the town's own ordinance governs, not the county's"}}$json$,
     'ORDINANCE-REVIEWED USE TABLE (supersedes 2023-ord+2025-zoam), read from the Loudoun County Zoning Ordinance as amended (enCodePlus, current through ZOAM-2024-0003). THE CHANGE FROM SCREENING: ZOAM-2024-0001 (adopted 3/18/2025) amended Sec. 3.02.05 so Table 3.02.05-1 row 101 (Data Center, notes 3-4, use-specific standard 4.06.02) reads S (Special Exception) in OP, IP, GI and MR-HI — by-right data-center development no longer exists anywhere in the county, so by_right is empty and IP/GI/MRHI (57+40+22 candidate parcels previously PASS) and OP (26 parcels previously prohibited, now correctly CONDITIONAL) all read special_exception. PDGI/PDIP (4 parcels) are 1972-Ordinance districts surviving only within the Route 28 Tax District under Sec. 1.02.K.1 of the current ordinance: not a listed use in the 1972 text (nearest categories — R&D by right §722.3.1/§723.3.1; Warehousing and Commercial office building by right in PD-GI §723.3.1 but only Board-permissible in PD-IP §722.3.2 — and actual uses locked to the approved site development plans, §700.5.6.2), so a §501.1 county determination is required: special_exception. CLI and PD-RDP stay special_exception (Table 3.02.02-1 row 101 shows S in the CLI and PD-RDP columns, unchanged by ZOAM-2024-0001, which touched only Sec. 3.02.05); PDCH unchanged. PDSA and PDMUB (legacy districts, Secs. 2.02.05.09/.11) prohibited: Table 3.02.02-1 row 101 is blank in both columns (table key: blank cell = Prohibited). Residential, transition/rural, JLMA and commercial districts prohibited per the 2023 use tables (3.02.01/3.02.03/3.02.04). TOWNS is the incorporated-town placeholder (see jurisdiction_reasons); any other unmapped code stays UNKNOWN.');

-- ── Taylor County, TX — the no-county-zoning rule ────────────────────
-- Not a use table: the finding itself, per the owner's decision recorded
-- in docs/zoning-coverage-brief.md (DECIDED section). CONDITIONAL, not
-- PASS, because an unzoned county's "nothing stops you" is not the same
-- claim as an adopted ordinance's affirmative permission, and the badge
-- must not conflate them. The gate applies this only to parcels the
-- TIGER/Line Places layer confirms are OUTSIDE every incorporated place
-- (a parcel inside Abilene, Merkel, Clyde, Tuscola, Tye, Impact,
-- Buffalo Gap has city zoning); inside a place the gate records UNKNOWN,
-- and if the Places layer is unavailable the rule holds at UNKNOWN
-- rather than assume unincorporated. The rationale text is the row's,
-- quoted verbatim into every verdict, so the citation travels with the
-- decision.
INSERT INTO public.constraint_rules (gate_key, jurisdiction, rule_version, params, description) VALUES
    ('zoning_dc_use', 'Taylor County, TX', '2026-ch231', $json${"by_right": [], "special_exception": [], "prohibited": [], "unknown_jurisdiction": [], "no_county_zoning": {"status": "CONDITIONAL", "rationale": "No county zoning applies: Texas counties have no general zoning authority over unincorporated land (Local Government Code ch. 231, which grants it only to specific named counties). No zoning restriction prohibits a data centre here. Confirm the parcel's extraterritorial-jurisdiction status with the nearest municipality — a city's ETJ reaches 0.5 to 5 miles beyond its limits depending on population, carries subdivision-platting and permitting authority without zoning, and annexation would bring zoning with it."}}$json$,
     'THE NO-COUNTY-ZONING RULE (Taylor County, TX). Texas counties generally may not adopt comprehensive zoning in unincorporated areas: Local Government Code ch. 231 grants it only to specific named counties (Cameron and Willacy, for parts of Padre Island), and Taylor is not among them; county regulatory power over unincorporated land is limited to subdivision platting, septic, floodplain, nuisance and roads. The gate records CONDITIONAL — not PASS — per the owner''s decision (docs/zoning-coverage-brief.md): an adopted ordinance''s affirmative permission and the absence of any ordinance are different claims that must not render as the same badge, and CONDITIONAL names the real diligence item (ETJ status and annexation exposure). PREREQUISITE, enforced by the gate engine: the rule fires only on parcels confirmed outside every incorporated place (TIGER/Line Places, MTFCC G4110); inside a place the verdict stays UNKNOWN with the place named, and an unavailable Places layer holds the rule back entirely. Coverage is unchanged either way (decided, not passed), and no overall verdict moves: Taylor parcels still hold water_availability and power_capacity at UNKNOWN.');
