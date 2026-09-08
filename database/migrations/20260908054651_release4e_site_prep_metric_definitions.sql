INSERT INTO public.metric_definitions (metric_key, label, gate_key, unit, description)
VALUES
  ('site_prep_cost_low_usd', 'Site preparation (Class 5 low)', NULL, 'USD',
   'Low bound of an AACE International 18R-97 Class 5 screening estimate for clearing and mass earthwork. Quantities come from the parcel''s own developable acreage and its median slope sampled from the USGS 3DEP elevation model, so two equal-sized sites on different terrain price differently. The -50% band is the standard''s published accuracy for this level of project definition, not an invented range. Excludes stormwater, erosion control, utilities, access roads, structural fill, rock excavation, mitigation, retaining structures and proffers.'),
  ('site_prep_cost_high_usd', 'Site preparation (Class 5 high)', NULL, 'USD',
   'High bound of the same estimate, at the standard''s +100%. Shown as a band with no midpoint: a Class 5 estimate supports a go/no-go comparison between sites, not a budget figure for one.')
ON CONFLICT (metric_key) DO UPDATE
  SET label = excluded.label, unit = excluded.unit, description = excluded.description;
