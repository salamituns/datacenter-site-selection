-- ============================================================================
-- Migration: release14_dc_use_authorisation
-- Description: Record which curated approvals actually authorise a data-centre
--              use, so the zoning gate can stop contradicting them.
--
--   Loudoun's ZOAM-2024-0001 (adopted 2025-03-18) ended by-right data-centre
--   development in the IP, GI and MR-HI districts, and the engine correctly
--   moved those parcels to CONDITIONAL — "data centers require a Special
--   Exception". That verdict is now being shown on seven parcels whose
--   Special Exception the Board has already granted, one of which
--   (SPEX-2019-0028) is literally an approved Special Exception sitting in
--   this very table.
--
--   A parcel-specific approval is stronger zoning evidence than a district
--   classification: the first is the governing body permitting this use on
--   this land, the second is a rule about a category the land belongs to.
--   The gate should read it and say PASS.
--
--   The flag is explicit rather than inferred from the application type or
--   the statement text. power_parcel_evidence is curated for the POWER gate,
--   and a future row could be a utility filing with no land-use authorisation
--   at all — a substation interconnection study, say. Inferring "ZMAP implies
--   data centres are permitted" would eventually grant a zoning PASS from a
--   record that never said so. The curator states it; the engine does not
--   guess it.
-- ============================================================================

ALTER TABLE public.power_parcel_evidence
    ADD COLUMN IF NOT EXISTS authorizes_dc_use BOOLEAN NOT NULL DEFAULT FALSE;

COMMENT ON COLUMN public.power_parcel_evidence.authorizes_dc_use IS
    'TRUE when the approved record authorises a data-centre use on this parcel (not merely documenting power). Set by the curator from the record itself; never inferred from application_type. Read by the zoning gate.';

-- Backfill: every curated record to date is a land-use approval whose own
-- text authorises data centres on the parcel. Quoted from `notes` /
-- `utility_statement` as filed:
--   ZMAP-2008-0017  "up to 3.9M sq ft of data center and office uses"
--   ZMAP-2017-0003  "750,000 sq ft of data center uses"
--   ZMAP-2017-0004  "ZMAP from CLI and MR-HI to PD-GI for data centers"
--   SPEX-2019-0028  "developed as an AWS data center"
--   ZCPA-2023-0005  "The Property shall be developed with Data Centers"
--   SPEX-2025-0031  "expansion of a data center building footprint"
UPDATE public.power_parcel_evidence
SET authorizes_dc_use = TRUE
WHERE application_number IN (
    'ZMAP-2008-0017', 'ZMAP-2017-0003', 'ZMAP-2017-0004',
    'SPEX-2019-0028', 'ZCPA-2023-0005', 'SPEX-2025-0031'
);

CREATE OR REPLACE VIEW public.v_power_parcel_evidence AS
SELECT parcel_key,
    application_number,
    application_type,
    approval_date,
    utility,
    utility_statement,
    capacity_mw,
    document_name,
    document_date,
    source_url,
    evidence_class,
    notes,
    created_at,
    authorizes_dc_use
FROM public.power_parcel_evidence ppe;
