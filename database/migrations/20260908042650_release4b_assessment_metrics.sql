-- Release 4b — the county assessment roll as observed underwriting inputs.

INSERT INTO public.data_sources (source_key, organization, dataset, endpoint_url, description) VALUES
  ('loudoun_assessment_roll',
   'Loudoun County Office of the Commissioner of the Revenue',
   'Annual Assessed Values (Countywide)',
   'https://www.loudoun.gov/649/Public-Real-Estate-Reports',
   'Parcel-level fair market land, building and total value, the land-use assessment (use value and deferred value) under Code of Virginia 58.1-3230 et seq., the taxable base, and the county''s estimated annual levy. Published annually as a countywide extract keyed by parcel id.')
ON CONFLICT (source_key) DO NOTHING;

INSERT INTO public.metric_definitions (metric_key, label, gate_key, unit, description)
VALUES
  ('assessed_land_value_usd', 'Assessed land value', NULL, 'USD',
   'Assessor''s fair market value of the land alone, excluding improvements.'),
  ('assessed_building_value_usd', 'Assessed improvement value', NULL, 'USD',
   'Assessor''s fair market value of improvements. Relevant to underwriting as demolition scope, not as value acquired.'),
  ('assessed_total_value_usd', 'Assessed total value', NULL, 'USD',
   'Assessor''s fair market value of land plus improvements. An assessment, not a sale price or an appraisal.'),
  ('assessed_taxable_value_usd', 'Taxable value', NULL, 'USD',
   'The value actually taxed. Lower than fair market total wherever land-use deferral or an exemption applies.'),
  ('assessed_land_value_per_acre_usd', 'Assessed land value per acre', NULL, 'USD/acre',
   'Fair market land value divided by GIS acreage — the first comparable between candidate sites.'),
  ('annual_property_tax_usd', 'Estimated annual property tax', NULL, 'USD',
   'The county''s own estimated annual levy for the parcel, carried verbatim rather than recomputed from a rate.'),
  ('assessment_class', 'Assessment class', NULL, NULL,
   'The assessor''s land-use classification (acreage band, commercial, residential, exempt).'),
  ('land_use_deferred_value_usd', 'Land-use deferred value', NULL, 'USD',
   'Value untaxed because the parcel is assessed on use value under Virginia''s land-use program rather than at fair market value. A change to a more intensive use triggers roll-back taxes under Code of Virginia 58.1-3237 — the five most recent complete tax years of deferred tax plus simple interest — so this is a conversion liability, not a saving.'),
  ('in_land_use_deferral', 'In land-use deferral', NULL, NULL,
   'Whether the parcel is currently taxed on use value. Recorded for every parcel on the roll, including "no": assessed at full fair market value is itself a finding.')
ON CONFLICT (metric_key) DO UPDATE
  SET label = excluded.label, gate_key = excluded.gate_key,
      unit = excluded.unit, description = excluded.description;
