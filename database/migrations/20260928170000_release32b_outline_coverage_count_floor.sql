-- ============================================================================
-- Migration: release32b_outline_coverage_count_floor
-- Description: coverage counts only from layers with a parcel-sized count.
--
--   Measured on the first run of outline coverage (2026-09-28): a layer of
--   a few large polygons covers a county completely without being a parcel
--   layer — WV-HARDY's tax districts (17 features) and a Staunton boundary
--   layer (1 feature) both read 1.000. Coverage says a layer reaches every
--   part of the county; the bbox count says it is divided like parcels.
--   Neither alone says "this is the county's parcel layer", together they
--   do, so best_outline_coverage now reads only layers with at least 1,000
--   features in the bbox — the floor the census results already used to
--   call a region gained. The floor is project judgement, not a measured
--   bound: the smallest own-county layer measured so far is Manassas Park
--   (5,935), but a very small independent city could fall under 1,000
--   and would then read NULL here — unmeasured, never a false coverage.

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
                                 AND s.discovered_via IN ('county_search', 'web_map'))
                                                                        AS best_county_count,
    max(s.record_count) FILTER (WHERE s.evidence_class = 'verified'
                                 AND s.discovered_via = 'state_program') AS best_state_count,
    max(s.outline_coverage) FILTER (WHERE s.evidence_class = 'verified'
                                     AND s.record_count >= 1000)        AS best_outline_coverage
FROM public.cadastre_sources s
GROUP BY s.region_key, s.state_code, s.county_name;
