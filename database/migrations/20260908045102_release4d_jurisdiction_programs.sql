-- Release 4d — statutory programs that move project economics.
--
-- Named "programs", not "incentives", because it deliberately holds both
-- sides. Virginia's data-center sales and use tax exemption is a benefit;
-- the electricity consumption tax enacted for FY2027-28 is a cost, and at
-- 100 MW it is roughly $8.2m a year. A table that recorded only the
-- benefits would produce exactly the one-sided number this project exists
-- to avoid, so `kind` distinguishes exemption from levy and both are
-- ingested together.
--
-- Jurisdiction-scoped rather than parcel-scoped: these terms are identical
-- for every parcel in a jurisdiction, so storing them per parcel would add
-- thousands of duplicate rows that differentiate nothing. They become a
-- differentiator only across jurisdictions — which is where the region
-- selector is already heading.
create table if not exists public.jurisdiction_programs (
  id                    uuid primary key default gen_random_uuid(),
  jurisdiction_code     varchar(40)  not null,
  program_key           varchar(80)  not null,
  program_name          varchar(200) not null,
  kind                  varchar(20)  not null,
  authority             varchar(200) not null,
  summary               text         not null,
  qualifying_conditions jsonb,
  rate_params           jsonb,
  effective_from        date,
  sunset_date           date,
  policy_risk           text,
  source_url            text,
  source_org            varchar(200),
  source_date           date,
  created_at            timestamptz  not null default now(),
  constraint jurisdiction_programs_uniq unique (jurisdiction_code, program_key),
  constraint jurisdiction_programs_kind
    check (kind in ('exemption', 'levy', 'grant', 'abatement', 'credit'))
);

comment on table public.jurisdiction_programs is
  'Statutory programs affecting project economics, both benefits and costs. kind distinguishes an exemption from a levy so neither can be presented without the other.';
comment on column public.jurisdiction_programs.policy_risk is
  'Known scheduled review, sunset or repeal exposure — the timing risk in relying on the program.';

alter table public.jurisdiction_programs enable row level security;
create policy "Allow public read access to jurisdiction programs"
  on public.jurisdiction_programs for select using (true);
create policy "Allow service role write to jurisdiction programs"
  on public.jurisdiction_programs for all
  using (auth.role() = 'service_role') with check (auth.role() = 'service_role');

INSERT INTO public.jurisdiction_programs
  (jurisdiction_code, program_key, program_name, kind, authority, summary,
   qualifying_conditions, rate_params, effective_from, sunset_date, policy_risk,
   source_url, source_org, source_date)
VALUES
('VA', 'data_center_sales_use_exemption',
 'Data Center Retail Sales and Use Tax Exemption', 'exemption',
 'Code of Virginia 58.1-609.3(18) and (19)',
 'Exempts computer equipment, enabling software and related infrastructure — including chillers and backup generators — plus qualifying upgrades, supplements and replacements, from Virginia retail sales and use tax. Requires a memorandum of understanding with the Virginia Economic Development Partnership Authority.',
 '{"capital_investment_usd": 150000000,
   "new_jobs": 50,
   "wage_multiple_of_prevailing_average": 1.5,
   "mou_required_with": "Virginia Economic Development Partnership Authority",
   "note": "Distressed localities qualify at lower thresholds; Loudoun County does not."}'::jsonb,
 NULL,
 NULL,
 '2035-06-30',
 'Sunsets 30 June 2035, with extensions to 2040 and 2050 only for operators meeting substantially higher investment and employment thresholds. A legislative study of the exemption is underway with recommendations due 15 December 2026, so the terms may change inside a typical development timeline.',
 'https://law.lis.virginia.gov/vacode/title58.1/chapter6/section58.1-609.3/',
 'Code of Virginia; Virginia Economic Development Partnership',
 '2026-08-01'),

('VA', 'data_center_electricity_consumption_tax',
 'Data Center Electricity Consumption Tax', 'levy',
 '2026 Virginia budget (HB30); no Code section assigned as yet',
 'A per-kilowatt-hour tax on electricity consumed by data center operators. Utilities generally collect it; operators using self-supplied generation must report consumption and remit directly. Statewide collections are capped at $600m a year.',
 '{"applies_to": "data center operators in Virginia",
   "self_supplied_generation": "operator reports and remits directly"}'::jsonb,
 '{"usd_per_kwh": 0.011,
   "annual_statewide_collection_cap_usd": 600000000,
   "worked_example": "A 100 MW load at 85% utilisation consumes about 744.6m kWh a year, roughly $8.19m at this rate."}'::jsonb,
 '2026-07-01',
 '2028-06-30',
 'Enacted for the 2026-2028 biennium only. Whether it lapses, is extended or is raised at expiry is unresolved, so a project underwritten across that boundary carries an open operating-cost assumption.',
 'https://www.hklaw.com/en/insights/publications/2026/08/virginia-preserves-data-center-tax-incentive',
 'Commonwealth of Virginia 2026 budget (HB30)',
 '2026-08-01');
