INSERT INTO public.data_sources (source_key, organization, dataset, endpoint_url, description) VALUES
  ('franklin_incentives', 'Franklin County Auditor, Ohio',
   'Recorded tax abatements and TIF districts',
   'https://gis.franklincountyohio.gov/hosting/rest/services/RealEstate/Abatements/FeatureServer/0',
   'Abatements recorded against a parcel id — Community Reinvestment Area and other cases, with start year, end year and term — and Tax Increment Financing districts as polygons with their first and last years. Parcel-level incentives, which Virginia has no public equivalent of: there the data-centre benefit is statutory and identical statewide.')
ON CONFLICT (source_key) DO NOTHING;

INSERT INTO public.metric_definitions (metric_key, label, gate_key, unit, description)
VALUES
  ('tax_abatement', 'Recorded tax abatement', NULL, NULL,
   'An abatement recorded against this parcel, by case type. Unlike a statewide exemption this differentiates neighbouring sites, and it is granted rather than automatic.'),
  ('tax_abatement_end_year', 'Abatement ends', NULL, NULL,
   'Final year of the recorded abatement. The benefit is a term, not a permanent condition of the land, and value beyond this year should not be underwritten.'),
  ('tif_district', 'TIF district', NULL, NULL,
   'Tax Increment Financing district containing the parcel. Affects how increased assessed value is applied, and typically directs it to district infrastructure rather than to general revenue.'),
  ('tif_end_year', 'TIF district ends', NULL, NULL,
   'Final year of the TIF district.')
ON CONFLICT (metric_key) DO UPDATE
  SET label = excluded.label, unit = excluded.unit, description = excluded.description;
