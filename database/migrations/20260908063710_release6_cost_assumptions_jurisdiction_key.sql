-- The uniqueness of an assumption was keyed on (key, version) alone, which
-- was only ever right while a single jurisdiction existed. Virginia and
-- Ohio both have a land_use_rollback v1 — same concept, different statute,
-- different numbers — and the old constraint made the second one
-- impossible to insert.
--
-- Jurisdiction is part of an assumption's identity, so it belongs in the
-- key. Surfaced by adding the second jurisdiction, which is what a second
-- jurisdiction is for.
ALTER TABLE public.cost_assumptions
  DROP CONSTRAINT IF EXISTS cost_assumptions_key_version_uniq;

ALTER TABLE public.cost_assumptions
  ADD CONSTRAINT cost_assumptions_key_version_uniq
  UNIQUE (assumption_key, jurisdiction, assumption_version);
