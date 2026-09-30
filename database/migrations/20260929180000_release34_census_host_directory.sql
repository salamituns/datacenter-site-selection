-- ============================================================================
-- Migration: release34_census_host_directory
-- Description: a discovery path for layers found in a server's own service
--              directory, for the census's targeted pass.
--
--   Outline coverage (release32/33) found 77 regions whose "verified"
--   layers cover under a quarter of the county or are not parcel-sized.
--   Two, looked at by hand, had a good layer recorded wrongly: Kenton's
--   was hidden behind the per-region candidate cap, and Lexington's web
--   maps pointed at parcels/MapServer, which the server had since renamed
--   property/MapServer. The targeted pass (cadastre_census.py --targeted)
--   lifts the cap and reads the /rest/services directory of every
--   self-hosted server already tied to a region — the server's own current
--   word on what it publishes. Layers found that way are recorded as
--   'host_directory', and verified and outline-measured like the rest.
--
--   It also adds VGIN's REST service for Virginia's statewide parcels
--   (vginmaps.vdem.virginia.gov; the gismaps host the index still names no
--   longer resolves) as a statewide program — 'state_program', no change
--   here — which the first pass could only record as a download candidate.

ALTER TABLE public.cadastre_sources
    DROP CONSTRAINT cadastre_sources_via_check;
ALTER TABLE public.cadastre_sources
    ADD CONSTRAINT cadastre_sources_via_check
    CHECK (discovered_via IN ('county_search', 'state_program', 'web_map',
                              'host_directory'));

-- A layer on a county server's directory is a county service.
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
                                                          'host_directory'))
                                                                        AS best_county_count,
    max(s.record_count) FILTER (WHERE s.evidence_class = 'verified'
                                 AND s.discovered_via = 'state_program') AS best_state_count,
    max(s.outline_coverage) FILTER (WHERE s.evidence_class = 'verified'
                                     AND s.record_count >= 1000)        AS best_outline_coverage
FROM public.cadastre_sources s
GROUP BY s.region_key, s.state_code, s.county_name;
