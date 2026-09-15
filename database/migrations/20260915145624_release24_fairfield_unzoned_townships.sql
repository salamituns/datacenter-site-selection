-- ============================================================================
-- Migration: release24_fairfield_unzoned_townships
-- Description: Fairfield County, OH — the two townships that adopted no zoning.
--
--   Ohio township zoning is permissive: ORC Chapter 519 says a township MAY
--   adopt a zoning resolution, and not every township has. Where none exists,
--   nothing zones the land and no zoning approval is required for the use.
--   That is a decidable answer, and leaving it UNKNOWN throws away a sourced
--   fact about 509 parcels.
--
--   The source is the county's own planning commission, which maintains the
--   township zoning register and reviews proposed resolutions under ORC 519:
--
--     "Eleven of the county's thirteen unincorporated townships have adopted
--      zoning, as well as many cities and villages located within the county.
--      Clear Creek and Madison Township do not have zoning in effect at this
--      time."
--         — Fairfield County Regional Planning Commission
--
--   NAMING: the RPC writes "Clear Creek" as two words; the TIGER county
--   subdivision layer the gate matches against writes "Clearcreek township"
--   as one. The TIGER spelling is what goes in the list, because that is the
--   string the gate compares. A row spelled the RPC's way would silently
--   match nothing and read as though the research had never been done.
--
--   SCOPE: this names townships, never the county. Eleven Fairfield townships
--   DO have zoning and are deliberately absent — they stay screening-grade
--   UNKNOWN until their resolutions are read, and the RPC publishes each as a
--   PDF. Zoned and unzoned sit side by side in one county, which is why the
--   county-wide no_county_zoning mechanism built for Taylor County, TX would
--   assert far too much here.
--
--   The gate scopes the finding as the moratorium gate scopes a township:
--   only a functioning township MCD counts (a Virginia election district is
--   an MCD too), and only outside municipal limits, because "this township
--   adopted no zoning" says nothing about a parcel inside a village that
--   adopted its own. Without the incorporated-places layer it declines to
--   fire at all — PASS is the permissive direction and must not rest on an
--   assumption.
--
--   Expected on Fairfield's next republish: Clearcreek 289 + Madison 220 =
--   509 of 3,541 parcels move from UNKNOWN to PASS. The other 3,032 stay
--   UNKNOWN.
--
--   Applied 2026-09-15.
-- ============================================================================

INSERT INTO public.constraint_rules
    (gate_key, jurisdiction, rule_version, params, description, basis,
     reviewed_at, reviewed_against, review_due_months)
VALUES (
  'zoning_dc_use', 'Fairfield County, OH', '2026-rpc-unzoned',
  '{
     "by_right": [],
     "special_exception": [],
     "prohibited": [],
     "unzoned_townships": ["Clearcreek township", "Madison township"]
   }'::jsonb,
  'Townships that have adopted no zoning resolution. The eleven zoned townships are not yet read.',
  'Ohio township zoning is permissive under ORC Chapter 519 — a township may adopt a zoning resolution, and Clearcreek and Madison have not. The Fairfield County Regional Planning Commission, which maintains the county''s township zoning register and reviews proposed resolutions under ORC 519, states: "Eleven of the county''s thirteen unincorporated townships have adopted zoning... Clear Creek and Madison Township do not have zoning in effect at this time." Where no resolution exists there is no district to read and no zoning approval to obtain, so the gate reads PASS with a rationale saying that this is the absence of a restriction rather than a district permitting the use. The names are spelled as the TIGER county subdivision layer spells them ("Clearcreek township"), not as the RPC does ("Clear Creek"), because the TIGER string is what the gate matches; the RPC spelling would match nothing and look like unfinished research. The eleven townships that DO have zoning are deliberately absent from this list and stay UNKNOWN until their resolutions are read — the RPC publishes each as a PDF. This is a township-level finding, not a county-level one: zoned and unzoned townships sit side by side in Fairfield, so the county-wide no_county_zoning mechanism used for Taylor County, TX would assert far too much here.',
  '2026-09-15',
  'Fairfield County Regional Planning Commission township zoning register (co.fairfield.oh.us/rpc/FC-Township-Zoning-Information.html); Ohio Revised Code Chapter 519',
  12);
