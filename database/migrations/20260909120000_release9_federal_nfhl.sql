-- ============================================================================
-- Migration: release9_federal_nfhl
-- Description: Register the federal FEMA NFHL ArcGIS REST service as a
--   data source. One federal adapter decides the floodway gate in any US
--   county: counties that mirror NFHL locally (Loudoun's FEMAFlood) keep
--   their mirror, and this service is the fallback for every other
--   county — previously 4,222 UNKNOWN parcels (all of Franklin OH and
--   Taylor TX) existed only because nothing queried it.
-- ============================================================================

INSERT INTO public.data_sources (source_key, organization, dataset, endpoint_url, description) VALUES
    ('fema_nfhl', 'FEMA', 'National Flood Hazard Layer (NFHL) — Flood Hazard Zones (S_Fld_Haz_Ar)',
     'https://hazards.fema.gov/arcgis/rest/services/public/NFHL/MapServer/28/query',
     'The federal flood hazard zone service: FLD_ZONE / ZONE_SUBTY polygons including the regulatory floodway, for any US county. Queried per survey bbox with paging and retry (the service throttles); clips cached per state.')
ON CONFLICT (source_key) DO NOTHING;
