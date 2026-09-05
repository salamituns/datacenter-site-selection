-- ============================================================================
-- Migration: release21b_evidence_expansion
-- Description: Second LandMARC evidence pass for matched parcels.
--
--   All 11 remaining cases attached to matched parcels were harvested and
--   text-scanned (staff reports, conditions, proffers). Two carry dated,
--   parcel-specific utility statements that meet the PASS standard:
--
--     ZCPA-2023-0005 (Zebra East, parcel 089309997000, 26.6 ac, 100%
--       covered): the Board-approved proffer statement commits the property
--       to data-center and utility-substation development.
--
--     ZMAP-2017-0004 (Quarry Commerce Center, parcel 097398776000, 43.4 ac,
--       100% covered): the BOSPH staff record documents the provision of
--       underground electrical service to the site, and the approved plan
--       carries the proffered note "All new utility distribution lines
--       shall be placed underground."
--
--   The other nine cases were reviewed and intentionally NOT curated:
--   their records contain no utility-service statements (lighting policy,
--   procedural zoning notes, or nothing). Notably, the proposed Tuscarora
--   Crossing substation (CMPT-2024-0009) had only its comprehensive-plan
--   commission permit upheld (Board, 2025-07-09); the special exception to
--   build it was deferred indefinitely in October 2025 — not approved
--   utility service, so no evidence row is seeded for those parcels.
-- ============================================================================

-- ── 1. Supporting documents (public LandMARC file) ───────────────────────

INSERT INTO public.power_documents (doc_key, title, publisher, doc_type, published_date, url, summary) VALUES
    ('loudoun_zcpa_2023_0005_proffer_2023', 'ZCPA-2023-0005 Zebra East — Approved Proffer Statement', 'Loudoun County, VA', 'county_proffer', '2023-07-10',
     'https://loudouncountyvaeg.tylerhost.net/prod/selfservice/LoudounCountyVAProd#/plan/F09D6295-70A7-4A80-8284-BFC19002B750',
     'Proffer statement approved with the Zebra East zoning concept plan amendment (amending ZMAP-1998-0003 to allow data center uses): "The Property shall be developed with Data Centers, utility substations, and related uses." Board approved the ZCPA on March 18, 2025; signed proffers filed April 15, 2025.'),
    ('loudoun_zmap_2017_0004_bosph_2018', 'ZMAP-2017-0004 Quarry Commerce Center — Board of Supervisors Public Hearing Staff Report', 'Loudoun County, VA', 'county_staff_report', '2018-01-10',
     'https://loudouncountyvaeg.tylerhost.net/prod/selfservice/LoudounCountyVAProd#/plan/5770BC31-8A16-40A7-9C7D-A20DD7D0F26F',
     'Staff analysis for the Quarry Commerce Center rezoning (CLI and MR-HI to PD-GI for data centers, John Mosby Highway/Route 50): documents the provision of underground electrical service to the site and the proffered plan note "All new utility distribution lines shall be placed underground." Board approved February 6, 2019.')
ON CONFLICT (doc_key) DO NOTHING;

-- ── 2. Seeded evidence — quotes verbatim from the public record ──────────

INSERT INTO public.power_parcel_evidence (
    parcel_key, application_number, application_type, approval_date, utility,
    utility_statement, capacity_mw, document_name, document_date, source_url,
    notes
) VALUES
    (
     'VA-LOUDOUN-089309997000', 'ZCPA-2023-0005', 'ZCPA', '2025-03-18', NULL,
     'Approved proffer statement (Permitted Uses): "The Property shall be developed with Data Centers, utility substations, and related uses."',
     NULL,
     'PROFFER STATEMENT (CLEAN) 7-10-2023.pdf', '2023-07-10',
     'https://loudouncountyvaeg.tylerhost.net/prod/selfservice/LoudounCountyVAProd#/plan/F09D6295-70A7-4A80-8284-BFC19002B750',
     'Zebra East (22130 [parkway], Ashburn): ZCPA amending the ZMAP-1998-0003 proffer statement to allow data center uses and adjust FAR; Board approved 2025-03-18, signed proffers filed 2025-04-15. The proffer also states uses requiring a Special Exception are permitted only after such approval. No MW figure is asserted — the record commits the parcel to utility-substation development, not a capacity number.'
    ),
    (
     'VA-LOUDOUN-097398776000', 'ZMAP-2017-0004', 'ZMAP', '2019-02-06', NULL,
     'Staff report: at the Commission Public Hearing the application was forwarded with a recommendation of approval after discussing "the environmental measures included in the proposal and the provision of underground electrical service to the site," and the approved plan carries the proffered note "All new utility distribution lines shall be placed underground."',
     NULL,
     'BOSPH STAFF REPORT 01-10-18.pdf', '2018-01-10',
     'https://loudouncountyvaeg.tylerhost.net/prod/selfservice/LoudounCountyVAProd#/plan/5770BC31-8A16-40A7-9C7D-A20DD7D0F26F',
     'Quarry Commerce Center (John Mosby Highway/Route 50): ZMAP from CLI and MR-HI to PD-GI for data centers; Board approved 2019-02-06. No MW figure is asserted — the record documents underground electrical service and distribution to the site, not a capacity number.'
    )
ON CONFLICT (parcel_key, application_number) DO NOTHING;
