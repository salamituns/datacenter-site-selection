-- Release 4c — the estimated metrics. Each description states what the
-- figure excludes, because an underwriter needs the boundary of a number
-- as much as the number.
INSERT INTO public.metric_definitions (metric_key, label, gate_key, unit, description)
VALUES
  ('land_use_rollback_tax_usd', 'Roll-back tax exposure', NULL, 'USD',
   'Estimated roll-back tax triggered by converting a land-use deferred parcel to a more intensive use, under Code of Virginia 58.1-3237: five years of deferred tax at the county''s adopted rate. Applies the current year''s deferred value to all five years and excludes statutory simple interest and the 50% rezoning penalty, so it is an order-of-magnitude liability rather than a settlement figure. Zero is a real finding: the parcel is assessed at full fair market value and carries no roll-back exposure.'),
  ('site_prep_cost_low_usd', 'Site preparation cost (low)', NULL, 'USD',
   'Low bound for clearing and rough grading over the contiguous developable acreage. The unit cost is a placeholder from non-authoritative pricing guides, not a published schedule. Excludes stormwater management, utility trenching, access roads, structural fill, rock excavation and environmental mitigation.'),
  ('site_prep_cost_high_usd', 'Site preparation cost (high)', NULL, 'USD',
   'High bound for the same scope. Published as a range with no midpoint deliberately: the underlying unit cost cannot support a point estimate, and a single figure would read as a precision the source does not have.')
ON CONFLICT (metric_key) DO UPDATE
  SET label = excluded.label, gate_key = excluded.gate_key,
      unit = excluded.unit, description = excluded.description;
