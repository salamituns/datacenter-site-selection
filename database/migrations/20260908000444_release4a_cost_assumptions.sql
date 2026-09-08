-- Release 4a — the assumption ledger.
--
-- Underwriting numbers are modelled, and this project's claim is that no
-- displayed value is invented. constraint_rules already plays this role
-- for gate verdicts: the versioned, cited object behind a PASS or FAIL.
-- cost_assumptions is its counterpart for money and time.
--
-- Every estimated metric names the assumption that produced it, so a cost
-- is always storable and displayable as `observed input x named assumption`
-- rather than as a bare number. Revising a unit price is then a new row,
-- not a code change, and old runs keep pointing at the version they used.
create table if not exists public.cost_assumptions (
  id                 uuid primary key default gen_random_uuid(),
  assumption_key     varchar(80)  not null,
  jurisdiction       varchar(120),            -- null = applies everywhere
  assumption_version varchar(40)  not null,
  params             jsonb        not null,
  -- Deliberately NOT NULL: an assumption without a stated basis is the
  -- invented number this schema exists to prevent.
  basis              text         not null,
  source_url         text,
  source_org         varchar(160),
  source_date        date,
  unit               varchar(40),
  valid_from         date         not null default current_date,
  valid_to           date,
  created_at         timestamptz  not null default now(),
  constraint cost_assumptions_key_version_uniq
    unique (assumption_key, assumption_version),
  constraint cost_assumptions_basis_not_blank
    check (length(btrim(basis)) > 0),
  constraint cost_assumptions_valid_range
    check (valid_to is null or valid_to >= valid_from)
);

comment on table public.cost_assumptions is
  'Versioned, cited inputs behind every estimated cost or duration. An estimated metric references assumption_key + assumption_version in its details, so the observed input and the assumption stay separable.';
comment on column public.cost_assumptions.basis is
  'Where the number comes from, in prose, with enough detail to check it. Required.';

create index if not exists cost_assumptions_key_idx
  on public.cost_assumptions (assumption_key, valid_from desc);

alter table public.cost_assumptions enable row level security;

create policy "Allow public read access to cost assumptions"
  on public.cost_assumptions for select using (true);

create policy "Allow service role write to cost assumptions"
  on public.cost_assumptions for all
  using (auth.role() = 'service_role')
  with check (auth.role() = 'service_role');
