-- stg_land_parcels is created LIKE land_parcels, which copies the NOT
-- NULL constraints on first_run_id / latest_run_id. The worker stages
-- parcels without them (it cannot know a parcel's original first run),
-- and promote_ingestion_run() fills both from the promoting run — so
-- the staging copies must be nullable.

ALTER TABLE public.stg_land_parcels ALTER COLUMN first_run_id DROP NOT NULL;
ALTER TABLE public.stg_land_parcels ALTER COLUMN latest_run_id DROP NOT NULL;

-- Remove any staging residue from runs that failed before promotion.
DELETE FROM public.stg_grid_parcels
WHERE run_id IN (SELECT id FROM public.ingestion_runs WHERE status = 'failed');
DELETE FROM public.stg_transmission_lines
WHERE run_id IN (SELECT id FROM public.ingestion_runs WHERE status = 'failed');
DELETE FROM public.stg_substations
WHERE run_id IN (SELECT id FROM public.ingestion_runs WHERE status = 'failed');
DELETE FROM public.stg_observation_wells
WHERE run_id IN (SELECT id FROM public.ingestion_runs WHERE status = 'failed');
DELETE FROM public.stg_land_parcels
WHERE run_id IN (SELECT id FROM public.ingestion_runs WHERE status = 'failed');
DELETE FROM public.stg_parcel_metric_values
WHERE run_id IN (SELECT id FROM public.ingestion_runs WHERE status = 'failed');
DELETE FROM public.stg_parcel_gate_results
WHERE run_id IN (SELECT id FROM public.ingestion_runs WHERE status = 'failed');
