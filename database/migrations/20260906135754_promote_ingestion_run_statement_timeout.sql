-- The weekly ingest stages ~90k rows (2.4k parcels, 66k metrics, 22k gates)
-- and publishes them in one atomic swap via promote_ingestion_run().
--
-- PostgREST connects as `authenticator` (statement_timeout=8s) and then
-- SET ROLE service_role, which carries no config of its own, so the RPC
-- inherited an 8 second budget and was cancelled with 57014 every run.
--
-- Scoped to the function so the protective 8s default still applies to
-- every other query; the override lasts only for this function body.
ALTER FUNCTION public.promote_ingestion_run(uuid)
  SET statement_timeout = '10min';
