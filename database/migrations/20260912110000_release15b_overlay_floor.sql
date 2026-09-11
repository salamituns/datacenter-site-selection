-- Release 15b — the overlay coverage floor and the Liberty TC/FP read.
--
-- Follows 20260912100000_release15_zoning_coverage.sql. The published
-- Licking run (a6b8d2e9) exposed a regression in the overlay read: a
-- parcel only TOUCHING an overlay feature was held at UNKNOWN even when
-- the overlay covered a boundary sliver of it. Measured against the
-- county's live layer, Liberty's TC corridor clips 19 decided parcels at
-- 0.9-13.9% of their area, and the stale MUOD polygons clip two Jersey
-- parcels at 1.0-1.4% — while the parcels genuinely inside MUDOD (and
-- the same stale MUOD footprints) are covered ~100%, where UNKNOWN is
-- the honest verdict and stays.
--
-- Two fixes ship together, one in the engine and one here:
--   * Engine (worker/parcel_gates.py): an overlay participates in a
--     parcel's classification only at >= 5% coverage — the same
--     meaningful-coverage line the legislative-application read draws
--     between a project footprint and boundary noise.
--   * Data (this migration): Liberty's TC and FP overlays are read, and
--     they do not modify the base district's use permissions — so they
--     are standards_only_overlays, carried as context, never deciding
--     or holding a verdict. The prior row listed TC as deliberately
--     unmapped; the article has now been read and says otherwise.
--
-- Nothing is deleted: the 2026-township-reviewed row stays exactly
-- where the published run's gate rows (rule_id) cite it; loaders read
-- the newest version per gate_key, so this row governs from the next
-- Licking run.

INSERT INTO public.constraint_rules (gate_key, jurisdiction, rule_version, params, description) VALUES
    ('zoning_dc_use', 'Licking County, OH', '2026-township-reviewed2', $json${"by_right": ["M-1", "M-2", "I", "M&D"], "special_exception": ["PUD", "PMUD"], "prohibited": ["AG", "R", "R-1", "R-2", "R-3", "R-15", "R-45", "R-70", "R-87", "R-E", "RR", "RR-3", "RR-4", "RS", "SER", "ER-NEOD", "MHP", "PRCD", "CCRC", "B-1", "B-2", "GB", "GB1", "GB-1", "GB-2", "LB", "NB", "IB", "BLB", "JB", "AB", "CN"], "unknown_jurisdiction": ["UZ"], "district_classes": {"C-1|Granville": "prohibited", "C-1|Bennington": "prohibited", "C-1|Harrison": "prohibited", "C-1|Hartford": "prohibited", "C-1|Newark": "prohibited", "C-1|Madison": "prohibited", "C-1|Liberty": "prohibited"}, "overlay_classes": {"IE-W": "special_exception", "MCOA": "special_exception", "MCOB": "special_exception", "MU-W": "prohibited", "CPO-W": "prohibited", "MCOC": "prohibited", "MCOD": "prohibited", "HMU-NWIOD": "prohibited", "NMU-NWIOD": "prohibited", "MU-NEOD": "prohibited", "ER-NEOD": "prohibited"}, "standards_only_overlays": ["TC", "FP"], "standards_only_reasons": {"TC": "Liberty Twp. Zoning Resolution §811 (Transportation Corridor Overlay, amended eff. 12/18/2024): permitted uses are \"Any permitted use allowed in the underlying zoning district\" — corridor setback/access/screening/signage standards only", "FP": "Liberty Twp. Zoning Resolution §810 (Flood Plain Overlay): \"The base district shall determine uses and minimum requirements\" — floodplain development constraints, not a use table"}, "jurisdiction_reasons": {"UZ": "the township administers no zoning (the county layer marks it Unzoned); there is no use table to consult"}}$json$,
     'TOWNSHIP-REVIEWED USE TABLE, second revision (supersedes 2026-township-reviewed, which decided the published a6b8d2e9 run). Base districts, C-1 scoping, Jersey overlay classes and UZ are unchanged from that row — read its migration notes for those citations. THE CHANGE: Liberty''s TC overlay was listed there as deliberately unmapped pending a read of the article; it has now been read (Liberty Township Zoning Resolution, adopted 6/29/2026, effective 7/29/2026, county-hosted copy; §811 last amended eff. 12/18/2024 and unchanged since — the 2026 amendments touched only §§301, 302, 515, 609, 1213). §811''s entire use language is: "Permitted Uses - TC District: Any permitted use allowed in the underlying zoning district, except that, where the requirements of this section are in conflict with the permitted uses or regulations of the underlying zoning district, the regulations set forth in this section shall control" — and those regulations are development standards (115-ft corridor setback, loading/storage location, underground utilities, multi-use paths, landscaping/buffers, signage, Technical Review Committee site-plan review). No use table, no conditional uses, no data-center language anywhere in the article. TC therefore does not modify the base district''s use permissions and is carried as standards-only context; the base district decides. The same is true of FP (§810: "The base district shall determine uses and minimum requirements", the overlay adds floodplain development constraints), listed alongside. Also in this revision, engine-side (worker/parcel_gates.py, not this row): an overlay now participates in a parcel''s classification only at >= 5% coverage of the parcel (the same meaningful-coverage line the legislative-application read draws), so boundary slivers — Liberty TC touches measured at 0.9-13.9% of the affected parcels, stale MUOD footprints at 1.0-1.4% — cannot hold a decided parcel at UNKNOWN. Still deliberately unmapped, recording UNKNOWN: MUDOD and MUOD (MUDOD''s adopted Exhibit A text, Resolution 25-04-07-01 of 4/7/2025, is not published; the predecessor MUOD set uses case-by-case per district via Appendix E; measured coverage of the affected parcels is ~100%, so UNKNOWN is the honest verdict, not a sliver) and the bare MU code (no such base district exists in Jersey''s resolution).');
