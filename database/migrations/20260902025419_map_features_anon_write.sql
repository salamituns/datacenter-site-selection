-- ============================================================================
-- Migration: 20260902025419_map_features_anon_write.sql
-- Description: Reconstructed record of the applied-but-untracked migration
--              that granted anonymous write access to grid_parcels and the
--              map feature tables (later revoked by release0_security).
--              Guarded so a fresh replay converges to the known DB state.
-- ============================================================================

-- These policies existed in production until Release 0 removed them.
DROP POLICY IF EXISTS "Allow anon and service role write access" ON public.grid_parcels;
CREATE POLICY "Allow anon and service role write access"
    ON public.grid_parcels FOR ALL
    TO anon, authenticated, service_role USING (true) WITH CHECK (true);

DROP POLICY IF EXISTS "Allow anon and service role write access" ON public.transmission_lines;
CREATE POLICY "Allow anon and service role write access"
    ON public.transmission_lines FOR ALL
    TO anon, authenticated, service_role USING (true) WITH CHECK (true);

DROP POLICY IF EXISTS "Allow anon and service role write access" ON public.substations;
CREATE POLICY "Allow anon and service role write access"
    ON public.substations FOR ALL
    TO anon, authenticated, service_role USING (true) WITH CHECK (true);

DROP POLICY IF EXISTS "Allow anon and service role write access" ON public.observation_wells;
CREATE POLICY "Allow anon and service role write access"
    ON public.observation_wells FOR ALL
    TO anon, authenticated, service_role USING (true) WITH CHECK (true);
