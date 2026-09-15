-- ============================================================================
-- Migration: release26_delaware_genoa_use_table
-- Description: Delaware County, OH — the one township whose resolution both
--   names data centres AND uses district codes the published layer carries.
--
--   Sixteen resolutions were read. 36 of 2,760 parcels became decidable —
--   1.3%. The small yield is the finding, not a shortfall in the reading.
--
--   GENOA — decidable. Article 5's principal-use matrix, effective
--   2026-05-14, gives a Data Center row against ten districts:
--
--       RR  SR  PRD(w/o)  PRD(with)  HOD  CB  PCD  LI  PID  PCF
--        N   N      N         N       N   N    N   C    S    N
--
--   Conditional in LI (Light Industrial), Special in PID (Planned Industrial
--   District), not permitted in the other eight. Article 17 Section 1732
--   carries the standards. Both C and S require Board approval and both map
--   to special_exception; the distinction is recorded rather than flattened
--   silently. RIVER, ROAD and WESTERVILLE in the layer are cartographic
--   features or a municipality, not districts, and stay unmapped.
--
--   THE OTHER FIFTEEN, and the three ways a resolution fails to answer:
--
--     Silence — brown, concord, kingston, liberty, oxford, scioto and the
--     county code shared by Radnor, Thompson and Marlboro name no
--     data-centre use at all. 1,528 parcels, 497 of them on the county code.
--     Ohio zoning is permissive, so an unlisted use needs a similar-use
--     determination a zoning inspector makes case by case.
--
--     Overlay-bound — Harlem names the use as "Data Center C*" in Table 35.1,
--     the County Road Overlay's CLR-A/B/C subareas, and a Mixed-Use Overlay
--     separately prohibits data centres. Harlem's published layer carries
--     AR-1, C-2, FR-1, HCVR-1, PCD, PID, PRCD, PRD and R-2 — no CLR or MU
--     codes. The provisions have nothing to attach to. 174 parcels.
--
--     Definitionally ambiguous — Berlin zones by NAICS and lists 518210,
--     "Computing Infrastructure Providers, Data Processing, Web Hosting, and
--     Related Services", among office and information uses. That covers a
--     payroll processor and a hyperscale campus alike. 105 parcels.
--
--   Scoped per township in district_classes, as release25 required: LI and
--   PID appear in several Delaware townships under their own resolutions, and
--   a flat entry would decide all of them from Genoa's.
--
--   Applied 2026-09-15. Supersedes the 2026-districts-only placeholder.
-- ============================================================================

WITH replacement AS (
  INSERT INTO public.constraint_rules
      (gate_key, jurisdiction, rule_version, params, description, basis,
       reviewed_at, reviewed_against, review_due_months)
  VALUES (
    'zoning_dc_use', 'Delaware County, OH', '2026-genoa-reviewed',
    '{
       "by_right": [],
       "special_exception": [],
       "prohibited": [],
       "district_classes": {
         "LI|Genoa township":  "special_exception",
         "PID|Genoa township": "special_exception",
         "RR|Genoa township":  "prohibited",
         "SR|Genoa township":  "prohibited",
         "PRD|Genoa township": "prohibited",
         "CB|Genoa township":  "prohibited",
         "PCD|Genoa township": "prohibited",
         "PCF|Genoa township": "prohibited"
       }
     }'::jsonb,
    'Genoa township''s data-centre use table. The other fifteen Delaware townships remain unmapped, for reasons recorded in the basis.',
    'GENOA IS THE ONLY DELAWARE TOWNSHIP WHOSE RESOLUTION BOTH NAMES DATA CENTRES AND USES DISTRICT CODES THE PUBLISHED LAYER CARRIES. Its Article 5 principal-use matrix, effective 2026-05-14, gives a Data Center row against ten districts — RR, SR, PRD without conservation, PRD with conservation, HOD, CB, PCD, LI, PID, PCF — reading N N N N N N N C S N. So: Conditional in LI (Light Industrial), Special in PID (Planned Industrial District), and not permitted in the other eight. Article 17 Section 1732 carries the standards that attach to the use. Both C and S require Board approval and both therefore map to special_exception; the difference between a Conditional and a Special use is recorded here rather than flattened without saying so. The layer''s RIVER, ROAD and WESTERVILLE values are cartographic features or a municipality rather than districts, and are left unmapped. THE OTHER FIFTEEN: brown, concord, kingston, liberty, oxford, scioto and the county code shared by Radnor, Thompson and Marlboro name no data-centre use at all — 1,528 parcels, of which the county code alone covers 497 — and Ohio zoning being permissive, an unlisted use needs a similar-use determination that a zoning inspector makes case by case and the engine cannot make from text. Harlem names the use but in overlays the GIS does not publish: "Data Center C*" sits in Table 35.1, the County Road Overlay''s CLR-A/B/C subareas, and a Mixed-Use Overlay separately prohibits data centres, while Harlem''s published layer carries only AR-1, C-2, FR-1, HCVR-1, PCD, PID, PRCD, PRD and R-2 — so the provisions have nothing to attach to. Berlin zones by NAICS code and lists 518210, "Computing Infrastructure Providers, Data Processing, Web Hosting, and Related Services", among its office and information uses; that code covers a payroll processor and a hyperscale campus alike, and whether Berlin reads a 100 MW campus into it is a judgement rather than a text, the same shape as Fairfield''s "Data processing/computer services" proving to be a bookkeeping office listed beside barber shops. All mappings are scoped per township because LI and PID appear in several Delaware townships under their own resolutions, and a flat entry would decide all of them from Genoa''s.',
    '2026-09-15',
    'Genoa Township Zoning Resolution effective 2026-05-14, Article 5 principal-use matrix and Article 17 Section 1732; fifteen further Delaware township resolutions read and found silent, overlay-bound or NAICS-ambiguous, all published by the Delaware County Regional Planning Commission',
    12)
  RETURNING id
)
UPDATE public.constraint_rules c
   SET superseded_by = (SELECT id FROM replacement)
 WHERE c.gate_key = 'zoning_dc_use'
   AND c.jurisdiction = 'Delaware County, OH'
   AND c.rule_version = '2026-districts-only'
   AND c.superseded_by IS NULL;
