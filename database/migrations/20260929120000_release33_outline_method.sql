-- ============================================================================
-- Migration: release33_outline_method
-- Description: record how each outline_coverage was measured.
--
--   Outline coverage (release32) laid its sample grid over the whole inset
--   county outline, water included. A point in a sound or bay has no
--   parcel under it, so water counties read as partly covered when their
--   layer was whole: the first-pass statewide run put NC's sound counties
--   at 0.292 (Dare) to 0.667 (Pamlico) and NJ-OCEAN at 0.708.
--
--   The worker now subtracts the county's TIGER/Line area water (buffered
--   100 m, to keep points off the shoreline) before laying the grid. That
--   is a different measurement, so each row records which one it holds:
--   'grid24-inset800m-water-excluded' now; NULL for rows measured before
--   this migration. The next --outline run re-measures every row whose
--   method is not current, so the column converges on one method and a
--   half-finished run never leaves two readings indistinguishable.

ALTER TABLE public.cadastre_sources
    ADD COLUMN outline_method varchar;

COMMENT ON COLUMN public.cadastre_sources.outline_method IS
    'How outline_coverage was measured. NULL = measured before release33 (water not excluded).';
