-- ============================================================================
-- Migration: release32_cadastre_outline_coverage
-- Description: measure whether a verified parcel layer covers the county
--              itself, not just the county's bounding box.
--
--   Both census passes verify by a bbox count, and adjacent counties'
--   bboxes overlap: the second pass recorded seven regions whose only
--   source was probably a NEIGHBOUR's layer reaching into the box
--   (KY-CAMPBELL and KY-PENDLETON on Kenton's LINK-GIS, VA-ISLEOFWIGHT
--   and VA-SOUTHAMPTON on HRSD, VA-WILLIAMSBURGCITY on James City's
--   server, VA-MANASSASCITY and VA-MANASSASPARKCITY on Prince William's).
--
--   outline_coverage is the share of sample points, spread on a grid
--   inside the county's own Census outline (inset 800 m so the 1:20m
--   generalisation cannot put a point across the line), at which the
--   layer has a parcel. A county's own layer covers most of its land —
--   the misses are roads and water — and a neighbour's covers almost
--   none of it. NULL means not measured, or fewer than half the points
--   answered: an unanswered question is not a zero.
--
--   record_count keeps its meaning (features in the bbox); coverage sits
--   beside it rather than replacing it.

ALTER TABLE public.cadastre_sources
    ADD COLUMN outline_coverage   numeric(4,3)
        CHECK (outline_coverage IS NULL OR outline_coverage BETWEEN 0 AND 1),
    ADD COLUMN outline_points     integer,
    ADD COLUMN outline_checked_at timestamptz;

COMMENT ON COLUMN public.cadastre_sources.outline_coverage IS
    'Share of sample points inside the county''s own outline (inset 800 m) where the layer has a parcel. NULL = not measured or too few answers.';

-- New columns go at the end (CREATE OR REPLACE VIEW may only append).
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
    max(s.outline_coverage) FILTER (WHERE s.evidence_class = 'verified') AS best_outline_coverage
FROM public.cadastre_sources s
GROUP BY s.region_key, s.state_code, s.county_name;
