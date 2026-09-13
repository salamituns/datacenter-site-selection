-- ============================================================================
-- Migration: release19_evidence_retention
-- Description: Bound the growth of superseded evidence generations.
--
--   promote_ingestion_run deletes by run_id and re-inserts for that run, so
--   every republish adds a full generation of metrics and gates and removes
--   none. Measured before this ran: 3,292,581 metric rows for 9,651 parcels,
--   of which 377,698 belonged to current runs — 1.6 GB carrying roughly
--   190 MB of live data, and 88.5% superseded history nobody chose to keep.
--
--   Two things must survive, and the second is the one that is easy to miss:
--
--     1. The current run for every active parcel — what is published.
--     2. Every run a parcel_decision was made against. v_parcel_decisions
--        computes gates_moved by joining parcel_gate_results at
--        g.run_id = d.run_id, so deleting those rows would not error. It
--        would return an empty array, reading as "nothing moved" rather than
--        "the history is gone". The engine's one real decision was already
--        in exactly that position — made against run 033379dc, since
--        superseded, its nine surviving gate rows being what make is_stale
--        true and gates_moved = 1. Verified identical before and after.
--
--   Dry run by default: an operation that removes 85% of two tables should
--   not be one keystroke from running by accident.
--
--   Deliberately NOT called from promote. Automatic pruning on every publish
--   would let a defect in the keep-set logic destroy history on a schedule.
--   The weekly workflow calls it once, after every region has published, so
--   it runs against a consistent set rather than mid-refresh.
--
--   Applied 2026-09-13: 2,792,632 metric rows and 695,088 gate rows removed,
--   6 runs retained. Postgres reuses the freed pages rather than returning
--   them to the OS, so table size is unchanged until the space is refilled.
-- ============================================================================

CREATE OR REPLACE FUNCTION public.prune_superseded_evidence(
    p_execute BOOLEAN DEFAULT FALSE
)
RETURNS JSONB
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path TO 'public'
SET statement_timeout TO '20min'
AS $function$
DECLARE
    v_metrics_total BIGINT; v_gates_total BIGINT;
    v_metrics_keep  BIGINT; v_gates_keep  BIGINT;
    v_metrics_del   BIGINT := 0; v_gates_del BIGINT := 0;
    v_keep_runs     BIGINT;
BEGIN
    CREATE TEMP TABLE _keep_runs ON COMMIT DROP AS
        SELECT DISTINCT latest_run_id AS run_id
        FROM public.land_parcels WHERE is_active AND latest_run_id IS NOT NULL
        UNION
        SELECT DISTINCT run_id FROM public.parcel_decisions WHERE run_id IS NOT NULL;

    SELECT count(*) INTO v_keep_runs FROM _keep_runs;
    IF v_keep_runs = 0 THEN
        RAISE EXCEPTION 'refusing to prune: the keep set is empty, which would delete every generation';
    END IF;

    SELECT count(*) INTO v_metrics_total FROM public.parcel_metric_values;
    SELECT count(*) INTO v_gates_total   FROM public.parcel_gate_results;
    SELECT count(*) INTO v_metrics_keep  FROM public.parcel_metric_values m
        WHERE m.run_id IN (SELECT run_id FROM _keep_runs);
    SELECT count(*) INTO v_gates_keep    FROM public.parcel_gate_results g
        WHERE g.run_id IN (SELECT run_id FROM _keep_runs);

    IF p_execute THEN
        DELETE FROM public.parcel_metric_values m
         WHERE m.run_id NOT IN (SELECT run_id FROM _keep_runs);
        GET DIAGNOSTICS v_metrics_del = ROW_COUNT;
        DELETE FROM public.parcel_gate_results g
         WHERE g.run_id NOT IN (SELECT run_id FROM _keep_runs);
        GET DIAGNOSTICS v_gates_del = ROW_COUNT;
    END IF;

    RETURN jsonb_build_object(
        'executed', p_execute,
        'runs_retained', v_keep_runs,
        'metrics', jsonb_build_object('total', v_metrics_total,
            'retained', v_metrics_keep, 'deletable', v_metrics_total - v_metrics_keep,
            'deleted', v_metrics_del),
        'gates', jsonb_build_object('total', v_gates_total,
            'retained', v_gates_keep, 'deletable', v_gates_total - v_gates_keep,
            'deleted', v_gates_del));
END;
$function$;

COMMENT ON FUNCTION public.prune_superseded_evidence(BOOLEAN) IS
    'Removes metric and gate rows for runs that are neither current for an active parcel nor referenced by a parcel_decision. Dry run unless p_execute is true. Deleted space is reused by Postgres rather than returned to the OS.';

REVOKE ALL ON FUNCTION public.prune_superseded_evidence(BOOLEAN) FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION public.prune_superseded_evidence(BOOLEAN) TO service_role;
