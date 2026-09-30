-- ============================================================================
-- Migration: release35_census_catalog
-- Description: a discovery path for endpoints found through a catalog of
--              county parcel services, for Kentucky and beyond.
--
--   Kentucky's 77 unsourced regions were invisible to every earlier path.
--   Two reasons, measured 2026-09-30: its services say "Ky PVA Hardin
--   Parcels", not "Kentucky", so the first pass's query (which required
--   the state's full name) never saw them; and its county data lives on
--   county, PVA and regional-development-district servers the index does
--   not list.
--
--   An ArcGIS Online account, GDITAdmin, keeps items titled
--   "Parcels - <ST> - <County> County" — 1,079 nationwide, 20 in Kentucky —
--   each pointing at the publisher's own endpoint. The account carries no
--   description, so the census uses it as an INDEX only: the recorded
--   owner is the endpoint's host, and every layer passes the same polygon,
--   count and outline-coverage checks as anything else. Rows found that
--   way are 'catalog'. The targeted pass also gained an abbreviated-state
--   search (recorded 'county_search', as the first pass's) and a state-wide
--   pool of known servers whose directories are read for services named
--   for the county (recorded 'host_directory').

ALTER TABLE public.cadastre_sources
    DROP CONSTRAINT cadastre_sources_via_check;
ALTER TABLE public.cadastre_sources
    ADD CONSTRAINT cadastre_sources_via_check
    CHECK (discovered_via IN ('county_search', 'state_program', 'web_map',
                              'host_directory', 'catalog'));

CREATE OR REPLACE VIEW public.v_cadastre_queue
WITH (security_invoker = true) AS
SELECT
    s.region_key,
    s.state_code,
    s.county_name,
    count(*) FILTER (WHERE s.evidence_class = 'verified')               AS verified_sources,
    count(*) FILTER (WHERE s.evidence_class = 'candidate')              AS candidate_sources,
    bool_or(s.evidence_class = 'none_found')                            AS searched_nothing_found,
    max(s.record_count) FILTER (WHERE s.evidence_class = 'verified'
                                 AND s.discovered_via IN ('county_search', 'web_map',
                                                          'host_directory', 'catalog'))
                                                                        AS best_county_count,
    max(s.record_count) FILTER (WHERE s.evidence_class = 'verified'
                                 AND s.discovered_via = 'state_program') AS best_state_count,
    max(s.outline_coverage) FILTER (WHERE s.evidence_class = 'verified'
                                     AND s.record_count >= 1000)        AS best_outline_coverage
FROM public.cadastre_sources s
GROUP BY s.region_key, s.state_code, s.county_name;
