-- ============================================================================
-- Migration: release10_region_key_function_fix
-- Description: Reconciles the ledger, and asserts the region scoping landed.
--
--   This version was applied to production during the Release 10 re-key but
--   had no file in the repository, leaving 40 rows in
--   supabase_migrations.schema_migrations against 39 migrations on disk.
--   That gap matters less for what it did than for what it breaks: the
--   file-count-equals-applied-count check is how drift between the repo and
--   the database gets noticed at all, and a ledger that is already off by one
--   cannot report the next discrepancy.
--
--   The corrective SQL itself is not repeated here. It was folded back into
--   20260911000000_release10_region_key.sql, whose promote_ingestion_run is
--   byte-equivalent to the live function (verified: 18 region_key references,
--   one deliberate state_code reference, matching count rollup). Re-applying
--   it would be a second definition of the same object and a new opportunity
--   for the two to diverge.
--
--   So this file asserts instead of mutating. A replay on a fresh database
--   reaches this point having already created the function from its
--   predecessor, and the checks below fail loudly if that function is the
--   state-scoped version — the one whose publish of a second county in a
--   state silently deletes the first.
-- ============================================================================

DO $$
DECLARE
    v_def TEXT;
BEGIN
    SELECT pg_get_functiondef(p.oid) INTO v_def
    FROM pg_proc p
    JOIN pg_namespace n ON n.oid = p.pronamespace
    WHERE n.nspname = 'public' AND p.proname = 'promote_ingestion_run';

    IF v_def IS NULL THEN
        RAISE EXCEPTION
            'promote_ingestion_run is missing — run the release10_region_key migration first';
    END IF;

    -- The swap that would otherwise take a sibling county's cells with it.
    IF v_def NOT LIKE '%DELETE FROM public.grid_parcels WHERE region_key = v_region;%' THEN
        RAISE EXCEPTION
            'promote_ingestion_run still deletes grid_parcels by state — a second county in a state would erase the first';
    END IF;

    -- The deactivation sweep, which is the more dangerous of the two: it
    -- retires parcels rather than replacing them, so the loss is quiet.
    IF v_def NOT LIKE '%WHERE lp.region_key = v_region%' THEN
        RAISE EXCEPTION
            'promote_ingestion_run still retires land_parcels by state — a sibling county would be deactivated wholesale';
    END IF;
END $$;

-- Structural guard for the same invariant, kept close to the data rather
-- than only in the function body: every region-scoped table must carry the
-- key the promote scopes by.
DO $$
DECLARE
    t TEXT;
BEGIN
    FOREACH t IN ARRAY ARRAY['grid_parcels', 'land_parcels', 'transmission_lines',
                             'substations', 'observation_wells']
    LOOP
        IF NOT EXISTS (
            SELECT 1 FROM information_schema.columns
            WHERE table_schema = 'public' AND table_name = t
              AND column_name = 'region_key'
        ) THEN
            RAISE EXCEPTION '% has no region_key column — the re-key is incomplete', t;
        END IF;
    END LOOP;
END $$;

-- power_rtep_upgrades is deliberately excluded from the list above and stays
-- scoped by state_code. RTEP is a state-level PJM artefact: both Ohio
-- counties draw on the same 3,270 records, and re-keying it per county would
-- make each publish discard the other's copy of identical data.
