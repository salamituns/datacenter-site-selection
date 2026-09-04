-- Map-serving view for the Release 1 parcel qualification layer.
--
-- Full-resolution parcel geometry is 4.7 MB of GeoJSON for Loudoun's
-- 2,478 active parcels; ST_SimplifyPreserveTopology at 5e-5 degrees
-- (~5 m) cuts that to ~1.4 MB with no visible difference at county
-- zoom. Gate status rides along so the client can shade by verdict
-- without a second round-trip.

CREATE VIEW public.v_land_parcels_map AS
SELECT
    lp.parcel_key,
    lp.source_parcel_id AS pin,
    lp.state_code,
    lp.county_name,
    (extensions.ST_AsGeoJSON(
        extensions.ST_SimplifyPreserveTopology(lp.geom, 0.00005)
    ))::jsonb AS geojson_geom,
    extensions.ST_X(extensions.ST_Centroid(lp.geom)) AS lon,
    extensions.ST_Y(extensions.ST_Centroid(lp.geom)) AS lat,
    lp.gis_acreage,
    lp.legal_acreage,
    (SELECT CASE
        WHEN COUNT(*) = 0 THEN NULL
        WHEN BOOL_OR(g.status = 'FAIL') THEN 'FAIL'
        WHEN BOOL_OR(g.status = 'UNKNOWN') THEN 'UNKNOWN'
        WHEN BOOL_OR(g.status = 'CONDITIONAL') THEN 'CONDITIONAL'
        ELSE 'PASS'
    END
    FROM public.parcel_gate_results g
    WHERE g.parcel_id = lp.id AND g.run_id = lp.latest_run_id) AS overall_status
FROM public.land_parcels lp
WHERE lp.is_active;

ALTER VIEW public.v_land_parcels_map SET (security_invoker = true);
GRANT SELECT ON public.v_land_parcels_map TO anon, authenticated;
