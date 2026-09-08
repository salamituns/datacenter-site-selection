-- Release 5 — interconnection evidence.
--
-- Power decides whether a data centre can be built; interconnection
-- decides whether it is worth building. Loudoun is Data Center Alley
-- because Equinix Ashburn sits inside it carrying over five hundred
-- networks, not because the land is unusually good — and until now the
-- engine had no way to see that.
INSERT INTO public.data_sources (source_key, organization, dataset, endpoint_url, description) VALUES
  ('peeringdb_facilities', 'PeeringDB',
   'Interconnection facility register',
   'https://www.peeringdb.com/api/fac',
   'The industry''s own public register of carrier hotels and colocation facilities: coordinates, and for each site how many networks, carriers and internet exchanges are actually present. Operators maintain their own entries, so the counts record who is there rather than estimating who might be.')
ON CONFLICT (source_key) DO NOTHING;

INSERT INTO public.metric_definitions (metric_key, label, gate_key, unit, description)
VALUES
  ('ixp_nearest_facility', 'Nearest interconnection facility', NULL, NULL,
   'Closest registered carrier hotel or colocation facility, with its operator. Read with the network count: the nearest site can be a single-tenant room while a major carrier hotel sits a mile further out.'),
  ('ixp_nearest_distance_miles', 'Distance to nearest facility', NULL, 'miles',
   'Straight-line distance from the parcel to that facility.'),
  ('ixp_latency_floor_ms', 'Latency floor to nearest facility', NULL, 'ms',
   'Round trip that light itself needs over the straight-line distance through fibre, using c divided by the refractive index of standard single-mode fibre (1.4682). A floor, not a forecast: no route can be shorter than the straight line, so no carrier, contract or equipment can beat this figure. Real paths run roughly 1.3 to 1.5 times longer before any switching is added.'),
  ('ixp_networks_at_nearest', 'Networks at nearest facility', NULL, 'count',
   'How many networks are present at the closest facility, per its PeeringDB record.'),
  ('ixp_facilities_within_25mi', 'Facilities within 25 miles', NULL, 'count',
   'Interconnection facilities reachable within a metro radius, without long-haul transport.'),
  ('ixp_networks_within_25mi', 'Networks within 25 miles', NULL, 'count',
   'Total network presences across those facilities — the breadth of interconnection a site can reach locally.'),
  ('ixp_best_facility_networks_within_25mi', 'Networks at best facility within 25 miles', NULL, 'count',
   'Network count at the largest facility in reach. Usually the figure that decides whether real peering is available, since the nearest facility is often not the significant one.')
ON CONFLICT (metric_key) DO UPDATE
  SET label = excluded.label, gate_key = excluded.gate_key,
      unit = excluded.unit, description = excluded.description;
