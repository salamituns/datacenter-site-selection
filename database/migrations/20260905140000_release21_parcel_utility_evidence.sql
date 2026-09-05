-- ============================================================================
-- Migration: release21_parcel_utility_evidence
-- Description: Parcel-specific utility evidence from public county records.
--
--   Loudoun special-exception / rezoning applications for data centers are
--   public records (LandMARC). Their Board-approved staff reports and
--   proffer/condition documents contain dated, parcel-specific utility
--   statements (serving substation capacity, approved on-site substations,
--   distribution connections with MW figures, Dominion-planned service).
--   These are exactly the dated parcel-level sources the power_capacity
--   gate reserved PASS for.
--
--   New curated table power_parcel_evidence carries one row per
--   (parcel, application) with the quoted statement, the document that
--   supports it, and its dates. The gate awards PASS only from these rows;
--   a MW figure is recorded only when the document states one.
-- ============================================================================

-- ── 1. Curated parcel utility evidence (public county records) ───────────

CREATE TABLE public.power_parcel_evidence (
    id UUID PRIMARY KEY DEFAULT extensions.gen_random_uuid(),
    parcel_key VARCHAR(80) NOT NULL,           -- references land_parcels.parcel_key
    application_number VARCHAR(40) NOT NULL,   -- 'ZMAP-2017-0003' (LandMARC case)
    application_type VARCHAR(10),              -- ZMAP / SPEX / ZCPA / ZMOD / SPMI / LEGI
    approval_date DATE NOT NULL,               -- county approval date (dated decision)
    utility VARCHAR(120),                      -- named utility when the record names one
    utility_statement TEXT NOT NULL,           -- quoted statement from the public record
    capacity_mw NUMERIC(8, 1),                 -- only when the record states a figure
    document_name VARCHAR(200) NOT NULL,       -- e.g. 'BOSPH STAFF REPORT 11-15-17.pdf'
    document_date DATE NOT NULL,               -- the dated source document
    source_url TEXT NOT NULL,                  -- LandMARC plan record (public portal)
    evidence_class VARCHAR(20) NOT NULL DEFAULT 'manual',
    notes TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT TIMEZONE('utc', NOW()),
    UNIQUE (parcel_key, application_number)
);

CREATE INDEX idx_power_parcel_evidence_parcel ON public.power_parcel_evidence (parcel_key);

-- ── 2. Client view ────────────────────────────────────────────────────────

CREATE VIEW public.v_power_parcel_evidence AS
SELECT ppe.parcel_key, ppe.application_number, ppe.application_type,
       ppe.approval_date, ppe.utility, ppe.utility_statement, ppe.capacity_mw,
       ppe.document_name, ppe.document_date, ppe.source_url,
       ppe.evidence_class, ppe.notes, ppe.created_at
FROM public.power_parcel_evidence ppe;
ALTER VIEW public.v_power_parcel_evidence SET (security_invoker = true);

-- ── 3. RLS + grants ───────────────────────────────────────────────────────

ALTER TABLE public.power_parcel_evidence ENABLE ROW LEVEL SECURITY;
CREATE POLICY "Allow public read access to parcel utility evidence" ON public.power_parcel_evidence
    FOR SELECT TO anon, authenticated USING (true);
CREATE POLICY "Allow service role write to parcel utility evidence" ON public.power_parcel_evidence
    FOR ALL TO service_role USING (true) WITH CHECK (true);

GRANT SELECT ON public.power_parcel_evidence, public.v_power_parcel_evidence
    TO anon, authenticated;

-- ── 4. Reference data ─────────────────────────────────────────────────────

INSERT INTO public.data_sources (source_key, organization, dataset, endpoint_url, description) VALUES
    ('loudoun_legislative_applications', 'Loudoun County, VA', 'Legislative Applications (data-center cases)',
     'https://logis.loudoun.gov/gis/rest/services/COL/PlanningZoning/MapServer/3',
     'County legislative land-use applications (SPEX/ZMAP/ZCPA) with approval dates and boundaries'),
    ('loudoun_landmarc', 'Loudoun County, VA', 'LandMARC public records portal',
     'https://loudouncountyvaeg.tylerhost.net/prod/selfservice',
     'Public record file for each legislative application: staff reports, conditions, proffers, and applicant statements (dated documents)')
ON CONFLICT (source_key) DO NOTHING;

INSERT INTO public.metric_definitions (metric_key, label, gate_key, unit, description) VALUES
    ('parcel_utility_evidence', 'Parcel-specific utility evidence', 'power_capacity', NULL,
     'dated_county_record when an approved, dated county application record documents utility service for this parcel (power_parcel_evidence)'),
    ('parcel_utility_evidence_mw', 'Documented capacity (parcel record)', 'power_capacity', 'MW',
     'MW figure only when the dated parcel record states one — never derived'),
    ('dc_application_on_parcel', 'Approved data-center applications on parcel', 'power_capacity', 'count',
     'Approved county legislative applications for data-center use whose boundary overlaps the parcel (county Legislative Applications layer)'),
    ('dc_application_latest_approval', 'Latest data-center application approval', 'power_capacity', NULL,
     'Most recent approval date among approved data-center applications overlapping the parcel')
ON CONFLICT (metric_key) DO NOTHING;

-- power_capacity rule v1 semantics extended: PASS is now awarded from
-- curated parcel evidence rows (rules-as-data note, no param change).
UPDATE public.constraint_rules
SET description = 'Power capacity evidence: PASS when a dated, approved county application record (LandMARC public file) documents utility service for the parcel — a MW figure is recorded only when that record states one; CONDITIONAL when the serving utility is identified AND dated PJM Board-approved area reinforcements exist; UNKNOWN otherwise. No MW figure is displayed without a dated supporting source.'
WHERE gate_key = 'power_capacity' AND jurisdiction = 'Loudoun County, VA' AND rule_version = 'v1';

-- County staff reports that support the seeded evidence rows (dated,
-- public, parcel-specific). Published via the LandMARC public portal.
INSERT INTO public.power_documents (doc_key, title, publisher, doc_type, published_date, url, summary) VALUES
    ('loudoun_zmap_2017_0003_bosph_2017', 'ZMAP-2017-0003 True North Data — Board of Supervisors Public Hearing Staff Report', 'Loudoun County, VA', 'county_staff_report', '2017-11-15',
     'https://loudouncountyvaeg.tylerhost.net/prod/selfservice/LoudounCountyVAProd#/plan/09005944-E4A4-401F-A4BD-6AD895079C01',
     'Staff analysis for the True North Data rezoning (~106 acres): documents the proposed electrical connection over the Dulles Greenway providing approximately 60 MW to the site, the existing 230 kV line on the west boundary, and the approved dedicated/distribution substation location. Board approved January 18, 2018.'),
    ('loudoun_legi_2025_0015_pcph_2026', 'LEGI-2025-0015 SDC Ashburn 1 — Planning Commission Public Hearing Staff Report', 'Loudoun County, VA', 'county_staff_report', '2026-03-24',
     'https://loudouncountyvaeg.tylerhost.net/prod/selfservice/LoudounCountyVAProd#/plan/0cdca2e2-c29e-4a7a-ab35-862bad8566e3',
     'Staff analysis for the SDC Ashburn 1 special exception (SPEX-2025-0031): documents that no above-ground electrical infrastructure or substations are needed because Dominion Energy already planned service to the building from the existing campus infrastructure. Board approved June 16, 2026.'),
    ('loudoun_spex_2019_0028_bosph_2020', 'SPEX-2019-0028 Rollins Property Data Center — Board of Supervisors Public Hearing Staff Report', 'Loudoun County, VA', 'county_staff_report', '2020-07-15',
     'https://loudouncountyvaeg.tylerhost.net/prod/selfservice/LoudounCountyVAProd#/plan/3E0EFB31-7648-4AAA-9B7C-203532531169',
     'Staff analysis for the Rollins Property special exception (~48 acres, CLI district): documents the adjacent Poland Road Dominion Power substation and states it has sufficient capacity to accommodate a data center use of the property. Board approved September 1, 2020.'),
    ('loudoun_zmap_2008_0017_bos_2011', 'ZMAP-2008-0017 Stonewall Secure Business Park — Board of Supervisors Staff Report', 'Loudoun County, VA', 'county_staff_report', '2011-06-13',
     'https://loudouncountyvaeg.tylerhost.net/prod/selfservice/LoudounCountyVAProd#/plan/A5B8456C-29E7-457C-8070-7D33F32A2A54',
     'Staff analysis for the Stonewall Secure Business Park rezoning: documents the applicant''s proposed on-site utility transmission substation under the existing overhead utility lines (north of land bays G and H) to provide a secure, redundant source of electrical power, noting the new 40 MW NOVEC substation in Philip A. Bolen Memorial Park would not be sufficient. Board approved July 12, 2011.')
ON CONFLICT (doc_key) DO NOTHING;

-- ── 5. Seeded evidence — quotes verbatim from the public record ──────────

INSERT INTO public.power_parcel_evidence (
    parcel_key, application_number, application_type, approval_date, utility,
    utility_statement, capacity_mw, document_name, document_date, source_url,
    notes
) VALUES
    (
     'VA-LOUDOUN-194103673000', 'ZMAP-2017-0003', 'ZMAP', '2018-01-18', NULL,
     'Staff report (Electricity): "The applicant proposes to bring electric power over the Dulles Greenway. A new power pole of approximately 25 feet in height will be necessary on each side of the road; this connection would provide approximately 60 megawatts of power to the site." The application also received County approval for a dedicated and/or distribution substation location shown on the CDP.',
     60.0,
     'BOSPH STAFF REPORT 11-15-17.pdf', '2017-11-15',
     'https://loudouncountyvaeg.tylerhost.net/prod/selfservice/LoudounCountyVAProd#/plan/09005944-E4A4-401F-A4BD-6AD895079C01',
     'True North Data (~106-acre rezoning, TR-10 to PD-OP, 750,000 sq ft of data center uses). Board approved 2018-01-18 with companion ZMOD-2017-0011 and SPMI-2017-0020; amended by ZCPA-2020-0003 (2022-05-17).'
    ),
    (
     'VA-LOUDOUN-062159785000', 'SPEX-2025-0031', 'SPEX', '2026-06-16',
     'Dominion Energy Virginia',
     'Staff report (3rd review): "no above ground electrical infrastructure or substations are needed to support this data center as Dominion Energy already planned service to this building from the existing campus infrastructure, as it has been planned and was originally included in an approved site plan."',
     NULL,
     'PCPH STAFF REPORT 03-24-2026.pdf', '2026-03-24',
     'https://loudouncountyvaeg.tylerhost.net/prod/selfservice/LoudounCountyVAProd#/plan/0cdca2e2-c29e-4a7a-ab35-862bad8566e3',
     'SDC Ashburn 1 (44254 Import Plz, Ashburn): expansion of a data center building footprint from 14,386 to 20,000 sq ft. Filed under parent Legislative Land Development Application LEGI-2025-0015. Board approved 2026-06-16.'
    ),
    (
     'VA-LOUDOUN-097354183000', 'SPEX-2019-0028', 'SPEX', '2020-09-01',
     'Dominion Energy Virginia',
     'Staff report: "land to the west of the Property has been developed with data centers and the Poland Road substation, which has sufficient capacity to accommodate a data center use of the Property" — the Poland Road Dominion Power substation (CMPT-2016-0004, SPMI-2016-0012) was ratified and approved by the Board on May 10, 2017 to provide service to existing and future uses.',
     NULL,
     'BOSPH STAFF REPORT 07-15-2020.pdf', '2020-07-15',
     'https://loudouncountyvaeg.tylerhost.net/prod/selfservice/LoudounCountyVAProd#/plan/3E0EFB31-7648-4AAA-9B7C-203532531169',
     'Rollins Property (~48 acres, CLI district, 43743 John Mosby Hwy) — developed as an AWS data center; equipment-yard expansion approved under SPEX-2021-0041 (2023-01-11).'
    ),
    (
     'VA-LOUDOUN-193186982000', 'ZMAP-2008-0017', 'ZMAP', '2011-07-12',
     'NOVEC',
     'Staff report (Utility Substation, Transmission): "The Applicant proposes an on-site utility transmission substation to provide a secure, redundant source of electrical power… The substation would be located under the existing overhead utility lines, north of land bays G and H, adjacent to the Hybrid Energy Park property." The report notes the new 40 MW NOVEC substation in Philip A. Bolen Memorial Park would not be sufficient for the business park''s needs.',
     NULL,
     'BOS STAFF REPORT 06-13-11.pdf', '2011-06-13',
     'https://loudouncountyvaeg.tylerhost.net/prod/selfservice/LoudounCountyVAProd#/plan/A5B8456C-29E7-457C-8070-7D33F32A2A54',
     'Stonewall Secure Business Park (up to 3.9M sq ft of data center and office uses). No MW figure is asserted — the record documents the approved on-site transmission substation, not a capacity number.'
    ),
    (
     'VA-LOUDOUN-194498227000', 'ZMAP-2008-0017', 'ZMAP', '2011-07-12',
     'NOVEC',
     'Staff report (Utility Substation, Transmission): "The Applicant proposes an on-site utility transmission substation to provide a secure, redundant source of electrical power… The substation would be located under the existing overhead utility lines, north of land bays G and H, adjacent to the Hybrid Energy Park property." The report notes the new 40 MW NOVEC substation in Philip A. Bolen Memorial Park would not be sufficient for the business park''s needs.',
     NULL,
     'BOS STAFF REPORT 06-13-11.pdf', '2011-06-13',
     'https://loudouncountyvaeg.tylerhost.net/prod/selfservice/LoudounCountyVAProd#/plan/A5B8456C-29E7-457C-8070-7D33F32A2A54',
     'Stonewall Secure Business Park (up to 3.9M sq ft of data center and office uses). No MW figure is asserted — the record documents the approved on-site transmission substation, not a capacity number.'
    )
ON CONFLICT (parcel_key, application_number) DO NOTHING;
