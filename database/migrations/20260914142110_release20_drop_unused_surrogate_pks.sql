-- ============================================================================
-- Migration: release20_drop_unused_surrogate_pks
-- Description: Drop the surrogate primary keys on the two evidence tables.
--
--   parcel_metric_values_pkey held 133 MB and had been scanned twice in the
--   life of the database; parcel_gate_results_pkey held 34 MB and had never
--   been scanned at all. Both tables are always reached by their natural key
--   -- (parcel_id, run_id, metric_key) and (parcel_id, run_id, gate_key) --
--   whose unique indexes carry 3.0M and 0.67M scans respectively. Indexes on
--   the two tables came to 810 MB against an 812 MB heap.
--
--   This was found while measuring whether to partition these tables. The
--   partitioning was not done: 501k live rows and zero dead tuples is not a
--   table under pressure, and the national tier writes its measurements to
--   grid_parcels.metadata rather than here, so nationwide coverage does not
--   grow them at all. They grow only with diligenced counties. Partitioning
--   becomes right when a parcel licence takes diligence national; until then
--   it would mean adding a region_key column these tables do not have,
--   backfilling it, and rewriting promote -- a migration in search of a
--   problem.
--
--   Checked before dropping, because a primary key is load-bearing in four
--   ways that do not announce themselves:
--     1. No foreign key anywhere references either table.
--     2. Neither table belongs to a publication, so no logical replication
--        or Realtime subscriber depends on the PK for replica identity.
--     3. promote_ingestion_run moves rows with DELETE ... WHERE run_id then
--        INSERT ... SELECT. No ON CONFLICT on either table, so no arbiter
--        index is needed.
--     4. Nothing in the client or worker reads either table directly; the
--        client goes through v_parcel_metrics / v_parcel_gates and the
--        worker writes to the stg_ tables.
--
--   The id COLUMN stays. Dropping a constraint drops its index, not the
--   column, so v_parcel_gates continues to select it.
--
--   Replica identity is repointed at the natural-key index rather than left
--   as "default" with no PK to resolve to. Nothing replicates these tables
--   today, but the default would make a future publication fail on its first
--   UPDATE, and the natural key is unique, NOT NULL and non-partial, which
--   is everything a replica identity needs.
--
--   Applied 2026-09-14. parcel_metric_values 1622 -> 1489 MB,
--   parcel_gate_results 349 -> 316 MB; 167 MB reclaimed. Every dependent
--   view re-checked afterwards, and the one recorded decision reads
--   identically (FAIL, is_stale true, one gate moved).
-- ============================================================================

ALTER TABLE public.parcel_metric_values DROP CONSTRAINT parcel_metric_values_pkey;
ALTER TABLE public.parcel_metric_values
    REPLICA IDENTITY USING INDEX parcel_metric_values_parcel_id_run_id_metric_key_key;

ALTER TABLE public.parcel_gate_results DROP CONSTRAINT parcel_gate_results_pkey;
ALTER TABLE public.parcel_gate_results
    REPLICA IDENTITY USING INDEX parcel_gate_results_parcel_id_run_id_gate_key_key;
