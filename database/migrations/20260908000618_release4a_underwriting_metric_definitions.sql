-- Release 4a — commercial metrics from the RTEP record already ingested.
--
-- Labels keep the existing convention of naming the scope out loud: these
-- describe the serving transmission area, and must never read as a cost or
-- a date belonging to one parcel.
insert into public.metric_definitions (metric_key, label, gate_key, unit, description)
values
  ('rtep_area_upgrade_cost_musd',
   'Transmission upgrade cost (area)',
   'power_capacity',
   'USD millions',
   'Sum of PJM Board-approved project cost estimates for active upgrades in the county transmission area. PJM''s own estimates, not actual spend, and not attributable to a single parcel.'),

  ('rtep_area_schedule_slip_median_days',
   'Median schedule slip (area)',
   'power_capacity',
   'days',
   'Median difference between actual and projected in-service dates for upgrades that have already energised. Negative means delivered early. A track record, not a forecast.'),

  ('rtep_area_schedule_slip_p90_days',
   '90th percentile schedule slip (area)',
   'power_capacity',
   'days',
   'Ninth decile of the same slip distribution — the tail a schedule should be underwritten against rather than the median.'),

  ('rtep_area_on_time_pct',
   'Upgrades delivered on time (area)',
   'power_capacity',
   'percent',
   'Share of completed upgrades that energised on or before their projected in-service date.')
on conflict (metric_key) do update
  set label = excluded.label,
      gate_key = excluded.gate_key,
      unit = excluded.unit,
      description = excluded.description;
