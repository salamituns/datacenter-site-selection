-- Release 4c — the first assumptions. Each states its own evidential
-- strength in `basis`, because they are not equally well founded and the
-- UI has to be able to say so.

INSERT INTO public.cost_assumptions
  (assumption_key, jurisdiction, assumption_version, params, basis, source_url, source_org, source_date, unit)
VALUES

-- Strong: every input is a published statutory or adopted figure.
('land_use_rollback', 'Loudoun County, VA', 'v1',
 '{"tax_rate_per_100_usd": 0.805,
   "rollback_years": 5,
   "interest_included": false,
   "penalty_included": false,
   "deferral_held_constant": true}'::jsonb,
 'Code of Virginia 58.1-3237 sets the roll-back at the deferred tax for the five most recent complete tax years plus simple interest. The rate is Loudoun County''s adopted FY2026 real property rate of $0.805 per $100 of assessed value, independently confirmed against the assessment roll itself, where 135,996 parcels imply exactly that rate. TWO STATED SIMPLIFICATIONS, in opposite directions: the current year''s deferred value is applied to all five years, which overstates the figure where land values rose over the period; and statutory simple interest is excluded, which understates it. The 50% penalty for rezoning to a more intensive use within five years of qualifying is also excluded, as it depends on rezoning history this dataset does not carry. Treat as an order-of-magnitude liability, not a settlement figure.',
 'https://vacode.org/58.1-3237/',
 'Code of Virginia; Loudoun County Board of Supervisors FY2026 adopted budget',
 '2026-01-01',
 'USD'),

-- Weak, and labelled as such: no authoritative public unit cost exists.
('site_prep', 'Loudoun County, VA', 'v1',
 '{"usd_per_acre_low": 1500,
   "usd_per_acre_high": 8000,
   "scope": "clearing and rough grading only",
   "excludes": ["stormwater management", "utility trenching", "access roads",
                "structural fill", "rock excavation", "environmental mitigation"]}'::jsonb,
 'PLACEHOLDER — REPLACE WITH YOUR OWN COST MODEL BEFORE RELYING ON IT. No authoritative public unit-cost dataset exists for data-center site preparation. This range is drawn from Virginia land-clearing contractor pricing guides, which are marketing material rather than a published schedule, and it covers clearing and rough grading only. It excludes stormwater management, utility trenching, access roads, structural fill, rock excavation and environmental mitigation, any one of which can exceed the whole range on a constrained site. It is published as a range precisely so that it cannot be read as a point estimate, and it is the reason site-prep figures carry a low and a high rather than a single number.',
 NULL,
 'Virginia land-clearing contractor pricing guides (non-authoritative)',
 '2026-01-01',
 'USD/acre');
