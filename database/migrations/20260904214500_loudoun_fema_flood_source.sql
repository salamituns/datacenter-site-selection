-- Register the Loudoun County FEMAFlood service as a distinct data source.
--
-- The federal NFHL endpoint (hazards.fema.gov) throttles county-sized
-- envelope queries: pages of >=500 records return ArcGIS 500s or reset
-- the connection, making a full-county fetch infeasible during the
-- pilot. Loudoun County's own FEMAFlood service mirrors the FEMA DFIRM
-- flood hazard areas (S_Fld_Haz_Ar, DFIRM_ID 51107C) for the county with
-- identical FLD_ZONE / ZONE_SUBTY / SFHA_TF attributes, including the
-- regulatory floodway, and serves them without throttling. The flood
-- gates therefore run on the county mirror with its own provenance row;
-- the federal NFHL source remains registered for later national rollout.

INSERT INTO public.data_sources (source_key, organization, dataset, endpoint_url, description) VALUES
    ('loudoun_fema_flood', 'Loudoun County GIS', 'FEMAFlood — FEMA Flood Hazard (DFIRM 51107C)',
     'https://logis.loudoun.gov/gis/rest/services/COL/FEMAFlood/MapServer/4',
     'County-hosted mirror of FEMA DFIRM flood hazard zones incl. regulatory floodway (ZONE_SUBTY); FLD_ZONE/SFHA_TF attributes match the federal NFHL S_Fld_Haz_Ar layer')
ON CONFLICT (source_key) DO NOTHING;
