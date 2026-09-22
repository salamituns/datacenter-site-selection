-- ============================================================================
-- Migration: release30_cadastre_census
-- Description: a table for the cadastre census — the discovery tier that
--              answers, per county, "does public cadastral parcel data
--              exist, where, and can it be counted?"
--
--   The parcel tier is nine regions of 554. The other 545 are screening
--   cells: ranked leads with no diligence underneath, because nobody has
--   inventoried which of those counties publish parcels at all. Ohio
--   expansion happened because Licking was probed by hand; that path
--   cannot scale to 545 counties, and the census is the machine that
--   replaces it: search ArcGIS Online per county (plus the six verified
--   statewide programs: NC OneMap, IndianaMap, NJ OGIS MOD-IV, OGRIP
--   Ohio, MD iMap, TNMap), then VERIFY every candidate against the
--   region's own bounding box — a feature count that intersects the
--   county is presence proven, not presence assumed. The same rule as
--   every layer in this engine: no synthetic fallback, no guessed rows.
--
--   The census does not decide buildability. A verified source means a
--   deep probe (the five-question format in licking-cadastre-probe.md)
--   is worth a human's time; it does not mean the five questions pass.
--   Evidence classes carry that distinction:
--     verified    — the service answered, the layer is polygons, and a
--                   count was taken against the region bbox
--     candidate   — a search hit that could not be verified (endpoint
--                   down, wrong geometry, count query refused); still
--                   recorded, because "found but uncheckable today" is
--                   different from "nothing found"
--     none_found  — the sentinel: searches ran and nothing relevant
--                   surfaced. A row, not an absence, so progress lives
--                   in this table like it lives in grid_parcels — a
--                   county is censused when it has a row, and re-running
--                   never repeats finished counties.
--
--   RLS mirrors parcel_decisions: operational intel, not client-facing
--   data. anon has no policy and therefore no rows; authenticated reads
--   all. There is deliberately no write policy of any kind — the worker
--   writes with the service role, and nothing else writes ever.

CREATE TABLE public.cadastre_sources (
    id              uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    region_key      varchar  NOT NULL,
    state_code      varchar  NOT NULL,
    county_name     varchar  NOT NULL,
    -- 'county_search' (per-county ArcGIS Online search) or
    -- 'state_program' (a statewide service, verified per region bbox)
    discovered_via  varchar  NOT NULL,
    title           text     NOT NULL,
    -- the ArcGIS Online owner account — an organisation identity signal,
    -- not a person; "FirstMap@De" or "nconemap" says who publishes
    owner           varchar  NOT NULL,
    item_id         varchar,
    service_url     text     NOT NULL,
    layer_id        integer  NOT NULL,
    geometry_type   varchar,
    -- features intersecting the region bbox; NULL until verified
    record_count    bigint,
    -- the layer's own paging limit, the Licking probe's first question
    max_record_count integer,
    evidence_class  varchar  NOT NULL,
    notes           text,
    checked_at      timestamptz NOT NULL DEFAULT now(),
    UNIQUE (region_key, service_url, layer_id)
);

ALTER TABLE public.cadastre_sources
    ADD CONSTRAINT cadastre_sources_evidence_class_check
    CHECK (evidence_class IN ('verified', 'candidate', 'none_found'));
ALTER TABLE public.cadastre_sources
    ADD CONSTRAINT cadastre_sources_via_check
    CHECK (discovered_via IN ('county_search', 'state_program'));

COMMENT ON TABLE public.cadastre_sources IS
    'The cadastre census: per-county public parcel sources, search-discovered and bbox-verified. The queue that decides which of the 545 screening-only counties deserve a deep cadastral probe.';

-- The queue view: one row per censused region, its verified sources and
-- the best coverage found. County services outrank statewide programs at
-- equal counts (a county CAMA join is usually richer than a statewide
-- standardised layer), and record_count 0 is kept visible rather than
-- coalesced away — a verified service with zero parcels in the bbox is a
-- fact a deep probe would want to know about before it starts.
CREATE VIEW public.v_cadastre_queue AS
SELECT
    s.region_key,
    s.state_code,
    s.county_name,
    count(*) FILTER (WHERE s.evidence_class = 'verified')               AS verified_sources,
    count(*) FILTER (WHERE s.evidence_class = 'candidate')              AS candidate_sources,
    bool_or(s.evidence_class = 'none_found')                            AS searched_nothing_found,
    max(s.record_count) FILTER (WHERE s.evidence_class = 'verified'
                                 AND s.discovered_via = 'county_search') AS best_county_count,
    max(s.record_count) FILTER (WHERE s.evidence_class = 'verified'
                                 AND s.discovered_via = 'state_program') AS best_state_count
FROM public.cadastre_sources s
GROUP BY s.region_key, s.state_code, s.county_name;

COMMENT ON VIEW public.v_cadastre_queue IS
    'One row per censused region: how many verified/candidate parcel sources it has, and the best bbox feature count from a county service and from a statewide program.';

ALTER TABLE public.cadastre_sources ENABLE ROW LEVEL SECURITY;
CREATE POLICY "team reads the cadastre census"
    ON public.cadastre_sources FOR SELECT
    TO authenticated
    USING (true);

GRANT SELECT ON public.v_cadastre_queue TO authenticated;
