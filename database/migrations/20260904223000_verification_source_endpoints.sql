-- Accurate endpoints for the three verification layers, now that the
-- fetchers are implemented (TIGERweb Transportation, the official
-- PAD-US 4.0 state geodatabase, 3DEP getSamples).

UPDATE public.data_sources
SET endpoint_url = 'https://tigerweb.geo.census.gov/arcgis/rest/services/TIGERweb/Transportation/MapServer',
    description = 'TIGERweb Transportation: primary (S1100) and secondary (S1200) road segments for access screening'
WHERE source_key = 'census_tiger_roads';

UPDATE public.data_sources
SET endpoint_url = 'https://www.sciencebase.gov/catalog/item/652d4f80d34e44db0e2ee45c',
    description = 'Official PAD-US 4.0 state geodatabase (Virginia); combined fee/designation/easement inventory, clipped per survey'
WHERE source_key = 'padus';

UPDATE public.data_sources
SET description = '3DEP bare-earth DEM: per-parcel getSamples elevation lattices (32x32 cap) from which slope statistics are derived'
WHERE source_key = 'usgs_3dep';
