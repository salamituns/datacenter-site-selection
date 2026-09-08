-- Release 7 — interconnection reaches every region.
--
-- The PeeringDB layer landed on the parcel tier, which only Virginia and
-- Ohio have, so Texas and Oregon saw none of it. The data is national and
-- the screening grid covers all four regions, so it belongs there too.
--
-- Real columns rather than a metadata blob: every other screening factor
-- — power distance, groundwater depth, cooling degree days — is a column,
-- and these need to be sortable and filterable in exactly the same way.
ALTER TABLE public.grid_parcels
  ADD COLUMN IF NOT EXISTS ixp_nearest_facility          VARCHAR(200),
  ADD COLUMN IF NOT EXISTS ixp_nearest_distance_miles    NUMERIC(8,3),
  ADD COLUMN IF NOT EXISTS ixp_latency_floor_ms          NUMERIC(8,4),
  ADD COLUMN IF NOT EXISTS ixp_networks_at_nearest       INTEGER,
  ADD COLUMN IF NOT EXISTS ixp_facilities_within_25mi    INTEGER,
  ADD COLUMN IF NOT EXISTS ixp_networks_within_25mi      INTEGER,
  ADD COLUMN IF NOT EXISTS ixp_best_networks_within_25mi INTEGER;

ALTER TABLE public.stg_grid_parcels
  ADD COLUMN IF NOT EXISTS ixp_nearest_facility          VARCHAR(200),
  ADD COLUMN IF NOT EXISTS ixp_nearest_distance_miles    NUMERIC(8,3),
  ADD COLUMN IF NOT EXISTS ixp_latency_floor_ms          NUMERIC(8,4),
  ADD COLUMN IF NOT EXISTS ixp_networks_at_nearest       INTEGER,
  ADD COLUMN IF NOT EXISTS ixp_facilities_within_25mi    INTEGER,
  ADD COLUMN IF NOT EXISTS ixp_networks_within_25mi      INTEGER,
  ADD COLUMN IF NOT EXISTS ixp_best_networks_within_25mi INTEGER;

COMMENT ON COLUMN public.grid_parcels.ixp_latency_floor_ms IS
  'Round trip light needs through fibre over the straight-line distance to the nearest interconnection facility. A floor no route can beat, not a forecast.';
COMMENT ON COLUMN public.grid_parcels.ixp_best_networks_within_25mi IS
  'Networks at the largest facility within a metro radius. Usually decides whether real peering is available: the nearest facility is often not the significant one.';

-- Sorting a region by what it can actually reach is the common query.
CREATE INDEX IF NOT EXISTS grid_parcels_ixp_best_idx
  ON public.grid_parcels (state_code, ixp_best_networks_within_25mi DESC);
