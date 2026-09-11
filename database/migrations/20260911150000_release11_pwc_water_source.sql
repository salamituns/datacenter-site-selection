-- ============================================================================
-- Migration: release11_pwc_water_source
-- Description: Register the Prince William County water sources the gate
--   now reads (ships with the Prince William region wiring).
--
--   Prince William's potable water is run by two utilities, and the county
--   publishes both as 2040 Comprehensive Plan layers (adopted 2017-10-17,
--   hosted 2018): Prince William Water's (PWCSA) potable pressure zones,
--   Virginia American Water's Dale City service area, and the Service
--   Authority's sewershed. None exposes a per-feature edit timestamp or a
--   NOT-served polygon, so the pipeline records the 2017-10 adoption
--   vintage as a dated fact and treats absence from the boundary as
--   UNKNOWN, never as non-service.
-- ============================================================================

INSERT INTO data_sources (source_key, organization, dataset, endpoint_url, license, description)
VALUES
    ('pwc_water_service_area',
     'Prince William County GIS (Comprehensive Plan) / Prince William Water (PWCSA) / Virginia American Water',
     'Potable water pressure zones, Virginia American Water service area, and PWCSA sewershed (2040 Comprehensive Plan, adopted 2017-10-17)',
     'https://services2.arcgis.com/0Q7l03Ls62VG0fy4/arcgis/rest/services/CP_Potable_Water_PWCSA_Pressure_Zones/FeatureServer/0',
     'Public hosted feature services (county disclaimer: reference data, not a legal description)',
     'The county''s own published water planning polygons: PWCSA potable pressure zones (CAPTION names each zone), the single Virginia American Water Dale City service-area polygon, and the PWCSA sewershed (sewer service areas). Comprehensive Plan layers adopted 2017-10-17 and hosted 2018; no per-feature edit timestamps are exposed, so the vintage is recorded from the plan adoption date. No NOT-served polygon is published: absence from the boundary is never treated as evidence of non-service.')
ON CONFLICT (source_key) DO NOTHING;
