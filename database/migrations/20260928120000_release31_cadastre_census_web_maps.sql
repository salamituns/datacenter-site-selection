-- ============================================================================
-- Migration: release31_cadastre_census_web_maps
-- Description: the census second pass — find the self-hosted county GIS
--              the ArcGIS Online search cannot see.
--
--   The first pass searched the ArcGIS Online index for parcel services.
--   Counties that run their own ArcGIS Server without registering it in
--   that index were invisible to it — Loudoun (logis.loudoun.gov) and
--   Licking (gis.lickingcounty.gov), both live adapters, would have read
--   none_found. 267 of 544 censused regions ended the first pass with no
--   verified source: KY 81, WV 52, PA 52, VA 50, IL 18, OH 9, MI 4, DC 1.
--
--   The second pass reads what the index DOES hold for those counties:
--   their web maps. A web map is a JSON document listing the layer URLs it
--   draws, and a county's own maps point at its own server. URLs on a
--   self-hosted host (anything but *.arcgis.com) that name parcels are
--   verified by the same rule as the first pass — polygon layer, a bbox
--   count that answers. Hosted copies (servicesN.arcgis.com) are skipped
--   on purpose: the first pass already searched every hosted service, and
--   what the second pass would add there is student coursework and
--   re-uploads, not a government's own publication.
--
--   'web_map' is the new discovery path. Self-hosted STATEWIDE programs
--   found while probing for this pass (WV GIS Technical Center's
--   WV_Parcels, PA DEP's partial PA_Parcels) are still 'state_program'.
--
--   The second pass writes its own none_found sentinel under
--   service_url '(none: web maps)', distinct from the first pass's
--   '(none)', so both claims stay on record: "not in the service index"
--   and "not referenced by any indexed web map" are different searches.

ALTER TABLE public.cadastre_sources
    DROP CONSTRAINT cadastre_sources_via_check;
ALTER TABLE public.cadastre_sources
    ADD CONSTRAINT cadastre_sources_via_check
    CHECK (discovered_via IN ('county_search', 'state_program', 'web_map'));

-- A service found through a county's own web map is a county service:
-- it counts toward best_county_count, not the statewide column.
CREATE OR REPLACE VIEW public.v_cadastre_queue AS
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
                                 AND s.discovered_via = 'state_program') AS best_state_count
FROM public.cadastre_sources s
GROUP BY s.region_key, s.state_code, s.county_name;
