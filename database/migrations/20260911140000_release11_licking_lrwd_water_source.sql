-- ============================================================================
-- Migration: release11_licking_lrwd_water_source
-- Description: Register the Licking County water source the gate now reads.
--
--   The Southwest Licking Community Water & Sewer District — renamed the
--   Licking Regional Water District in 2024 — publishes a JOINT service
--   boundary for itself and the Pataskala Utility Department, dated June
--   2021, on the district's ArcGIS hub: a water layer and a wastewater
--   layer, each keyed by a single Name field that records which utility
--   operates each polygon (SWLCWSD / Pataskala Utility Department /
--   Joint). Neither layer exposes an edit timestamp or a service-type
--   column, so the pipeline records the 2021-06 vintage as a dated fact
--   (provider is attributed row-level from Name, never by region).
--
--   The boundary is 2021-vintage county-scale evidence: the gate treats
--   absence from it as UNKNOWN, not as non-service.
-- ============================================================================

INSERT INTO data_sources (source_key, organization, dataset, endpoint_url, license, description)
VALUES
    ('licking_lrwd_water_service',
     'Licking Regional Water District (formerly Southwest Licking Community Water & Sewer District)',
     'Joint water / wastewater service-area boundary (district + Pataskala Utility Department, June 2021)',
     'https://services3.arcgis.com/iHpkStKZmEoDkIuv/arcgis/rest/services/Water_Service_2021_view/FeatureServer/0',
     'Public ArcGIS Hub feature service (no stated license)',
     'The district''s own published service-area polygons: a water layer (Water_Service_2021_view) and a wastewater layer (Waste_Water_Service_2021), each with a single Name field recording the operating utility (SWLCWSD, Pataskala Utility Department, or Joint). No edit timestamp is exposed; the June 2021 vintage comes from the layer''s own name and is recorded as such. Absence from the boundary is never treated as evidence of non-service.')
ON CONFLICT (source_key) DO NOTHING;
