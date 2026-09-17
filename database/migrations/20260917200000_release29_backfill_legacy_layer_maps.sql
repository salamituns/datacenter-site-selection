-- ============================================================================
-- Migration: release29_backfill_legacy_layer_maps
-- Description: Derive stats.layers for the live generations that predate it.
--
--   The coverage guard (release28) compares a run's stats.layers against the
--   region's live generation. Twelve live generations predate the map, so
--   the guard protects 1 region out of 13 — a republish of Licking with
--   PAD-US unreachable would thin its evidence and record the thinned map as
--   if it were normal, which is the Taylor incident with the guard watching
--   and unable to help.
--
--   This backfill derives each legacy generation's map from the evidence
--   that run itself left, never from what today's network would answer:
--
--   Parcel tier: the run's own source_snapshots rows. A fetch that answered
--     carries record_count; one that failed carries record_count NULL and an
--     "unavailable" note — the provenance layer was recording availability
--     all along; it just never reached the run's stats. Snapshot layer names
--     map onto the stats keys (county_subdivisions -> subdivisions,
--     utility_territories -> utility, rtep_upgrades -> rtep,
--     pjm_queue -> queue, water_service_areas -> water).
--   `restrictions` has no snapshot row (it is a database read, not a
--     fetch), so it is derived from the run's moratorium gates: the
--     unavailable branch's rationale literal is distinctive, so any
--     moratorium gate row reading "Restriction evidence layer unavailable…"
--     marks the layer missing, and its absence marks it present.
--   Screening tier: grid_parcels.metadata.federal_metrics. measure() writes
--     a layer's key whenever that layer answered, whatever the value — so a
--     key present in any cell means present, and a key in no cell of a
--     measured run means missing. (One theoretical edge: a layer that
--     answered with an empty frame writes no key. TIGER roads in a county
--     with no roads would misread; no such county exists.)
--
--   Layers with no evidence either way are omitted, not guessed: an omitted
--   key is simply not guard-protected, exactly as before the backfill.
--
--   Known truths this must reproduce, verified after applying:
--     * TX-TAYLOR: padus missing (the incident that motivated the guard),
--       rtep/queue/county_applications missing (ERCOT has no PJM
--       artifacts), everything else present.
--     * DE-KENT / DE-NEWCASTLE / DE-SUSSEX: all five screening layers
--       present — they published before the ScienceBase challenge.
--     * OH-LICKING: water present (the LRWD boundary decided 310 parcels).
--
--   One-off: only status='succeeded' rows are backfilled (superseded
--   generations are pruned weekly and read by nothing). Runs published
--   after release28 already carry their own map and are skipped.
--
--   Applied 2026-09-17.
-- ============================================================================

DO $$
DECLARE
    r record;
    v_layers jsonb;
    v_gates int;
    v_cells int;
    v_mora int;
    v_mora_unavailable int;
BEGIN
    FOR r IN
        SELECT id, region_code
        FROM public.ingestion_runs
        WHERE status = 'succeeded'
          AND (stats -> 'layers') IS NULL
        ORDER BY region_code
    LOOP
        v_layers := '{}'::jsonb;

        SELECT count(*) INTO v_gates
        FROM public.parcel_gate_results WHERE run_id = r.id;

        IF v_gates > 0 THEN
            -- Parcel tier: derive from the run's own provenance rows.
            SELECT coalesce(jsonb_object_agg(m.key,
                             CASE WHEN s.record_count IS NOT NULL
                                  THEN 'present' ELSE 'missing' END), '{}')
            INTO v_layers
            FROM (VALUES
                ('wetlands', 'wetlands'),
                ('nfhl', 'nfhl'),
                ('padus', 'padus'),
                ('roads', 'roads'),
                ('places', 'places'),
                ('subdivisions', 'county_subdivisions'),
                ('slope', 'slope'),
                ('utility', 'utility_territories'),
                ('rtep', 'rtep_upgrades'),
                ('queue', 'pjm_queue'),
                ('county_applications', 'county_applications'),
                ('water', 'water_service_areas')
            ) AS m(key, snap)
            JOIN public.source_snapshots s
              ON s.run_id = r.id AND s.layer = m.snap;

            -- `restrictions` is a database read with no snapshot row; the
            -- gate's unavailable branch is the only way it fails, and its
            -- rationale literal is distinctive.
            SELECT count(*) INTO v_mora
            FROM public.parcel_gate_results
            WHERE run_id = r.id AND gate_key = 'moratorium_status';
            IF v_mora > 0 THEN
                SELECT count(*) INTO v_mora_unavailable
                FROM public.parcel_gate_results
                WHERE run_id = r.id
                  AND gate_key = 'moratorium_status'
                  AND rationale LIKE 'Restriction evidence layer unavailable%';
                v_layers := v_layers || jsonb_build_object(
                    'restrictions',
                    CASE WHEN v_mora_unavailable > 0
                         THEN 'missing' ELSE 'present' END);
            END IF;
        ELSE
            -- Screening tier: measure() writes a layer's key in every cell
            -- whenever the layer answered.
            SELECT count(*) INTO v_cells
            FROM public.grid_parcels WHERE source_run_id = r.id;
            IF v_cells > 0 THEN
                SELECT jsonb_build_object(
                    'wetlands', CASE WHEN count(*) FILTER (
                        WHERE (gp.metadata -> 'federal_metrics') ? 'wetland_pct') > 0
                        THEN 'present' ELSE 'missing' END,
                    'nfhl', CASE WHEN count(*) FILTER (
                        WHERE (gp.metadata -> 'federal_metrics') ? 'floodway_pct'
                            OR (gp.metadata -> 'federal_metrics') ? 'floodplain_pct') > 0
                        THEN 'present' ELSE 'missing' END,
                    'padus', CASE WHEN count(*) FILTER (
                        WHERE (gp.metadata -> 'federal_metrics') ? 'protected_pct') > 0
                        THEN 'present' ELSE 'missing' END,
                    'roads', CASE WHEN count(*) FILTER (
                        WHERE (gp.metadata -> 'federal_metrics') ? 'nearest_road_km') > 0
                        THEN 'present' ELSE 'missing' END,
                    'slope', CASE WHEN count(*) FILTER (
                        WHERE (gp.metadata -> 'federal_metrics') ? 'slope_max_pct'
                            OR (gp.metadata -> 'federal_metrics') ? 'slope_median_pct') > 0
                        THEN 'present' ELSE 'missing' END)
                INTO v_layers
                FROM public.grid_parcels gp
                WHERE gp.source_run_id = r.id;
            END IF;
        END IF;

        IF v_layers <> '{}'::jsonb THEN
            UPDATE public.ingestion_runs
            SET stats = stats || jsonb_build_object('layers', v_layers)
            WHERE id = r.id;
            RAISE NOTICE 'backfilled % (%)', r.region_code, v_layers::text;
        ELSE
            RAISE NOTICE 'no evidence to derive a map for run % (%)', r.id, r.region_code;
        END IF;
    END LOOP;
END $$;
