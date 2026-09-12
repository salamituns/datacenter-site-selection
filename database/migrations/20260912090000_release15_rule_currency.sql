-- ============================================================================
-- Migration: release15_rule_currency
-- Description: Give constraint_rules the provenance every other evidence
--              layer already carries, and make supersession structural.
--
--   Loudoun's use table was named "2023-ord+2025-zoam" and listed IP, GI and
--   MR-HI as by-right. ZOAM-2024-0001 had removed exactly that in March 2025.
--   The rule claimed to account for an amendment it did not reflect, and it
--   decided 119 parcels for months before anyone noticed.
--
--   A version-drift check would not have caught it: the rule and the
--   republish landed together, so nothing was ever out of step with itself.
--   What was missing is older than that — constraint_rules is the only
--   evidence in this engine with no retrieved-at. Every metric row records
--   when its source was read; the rules deciding those metrics record only
--   when the row was inserted, which is not the same claim at all.
--
--   Nothing here detects a changed ordinance. No system can, without watching
--   the ordinance. What it can do is state how old its knowledge is, and say
--   plainly when it has never been checked.
--
--   Two mechanisms, deliberately separate:
--     * superseded_by  — structural supersession, replacing the convention of
--                        writing "(supersedes X)" into the description and
--                        inferring the rest from created_at order.
--     * reviewed_at / reviewed_against — when a human last verified this rule
--                        against a named instrument, and which one.
-- ============================================================================

ALTER TABLE public.constraint_rules
    ADD COLUMN IF NOT EXISTS superseded_by UUID REFERENCES public.constraint_rules(id),
    ADD COLUMN IF NOT EXISTS reviewed_at DATE,
    ADD COLUMN IF NOT EXISTS reviewed_against TEXT,
    ADD COLUMN IF NOT EXISTS review_due_months INT NOT NULL DEFAULT 12;

COMMENT ON COLUMN public.constraint_rules.superseded_by IS
    'The rule version that replaced this one. NULL means current. Structural, so "which rule governs" is a query rather than a created_at convention.';
COMMENT ON COLUMN public.constraint_rules.reviewed_at IS
    'When a human last verified this rule against its source instrument. NULL means never recorded — which is a finding, not a default.';
COMMENT ON COLUMN public.constraint_rules.reviewed_against IS
    'The instrument verified against, named and dated (e.g. "Loudoun County Zoning Ordinance as amended by ZOAM-2024-0001, adopted 2025-03-18").';

-- Backfill supersession from the newest-wins contract the worker already
-- applies: within a jurisdiction and gate, each row is superseded by the next
-- one created. This records what the code was already doing, rather than
-- changing which rule governs anything.
WITH ordered AS (
    SELECT id,
           LEAD(id) OVER (PARTITION BY jurisdiction, gate_key ORDER BY created_at) AS next_id
    FROM public.constraint_rules
)
UPDATE public.constraint_rules cr
SET superseded_by = o.next_id
FROM ordered o
WHERE o.id = cr.id AND o.next_id IS NOT NULL;

-- reviewed_at is deliberately NOT backfilled. created_at is when the row was
-- written, which is not evidence that anyone checked it against an ordinance
-- — and the Loudoun rule proves the two can differ by a year. Every existing
-- rule therefore reports "never recorded as reviewed", which is true.

-- Current rule per jurisdiction and gate, with the age of its review.
CREATE OR REPLACE VIEW public.v_rule_currency AS
SELECT cr.id,
       cr.jurisdiction,
       cr.gate_key,
       cr.rule_version,
       cr.reviewed_at,
       cr.reviewed_against,
       cr.review_due_months,
       (CURRENT_DATE - cr.reviewed_at) AS days_since_review,
       CASE
           WHEN cr.reviewed_at IS NULL THEN 'never recorded'
           WHEN cr.reviewed_at
                < (CURRENT_DATE - (cr.review_due_months || ' months')::interval)
                THEN 'review due'
           ELSE 'current'
       END AS review_status,
       cr.created_at
FROM public.constraint_rules cr
WHERE cr.superseded_by IS NULL;
ALTER VIEW public.v_rule_currency SET (security_invoker = true);

-- Do any published verdicts cite a rule that has since been superseded?
-- This is the mechanical half: it fires when a rule changes and the region is
-- not republished, which is the failure the ZOAM episode did NOT have and the
-- next one may.
CREATE OR REPLACE VIEW public.v_region_rule_drift AS
SELECT lp.region_key,
       lp.county_name || ' County, ' || lp.state_code AS jurisdiction,
       pgr.gate_key,
       decided.rule_version AS decided_under,
       current_rule.rule_version AS current_version,
       count(*) AS parcels
FROM public.parcel_gate_results pgr
JOIN public.land_parcels lp
     ON lp.id = pgr.parcel_id AND lp.latest_run_id = pgr.run_id
JOIN public.constraint_rules decided ON decided.id = pgr.rule_id
JOIN public.constraint_rules current_rule
     ON current_rule.jurisdiction = decided.jurisdiction
    AND current_rule.gate_key = decided.gate_key
    AND current_rule.superseded_by IS NULL
WHERE decided.id <> current_rule.id
GROUP BY lp.region_key, lp.county_name, lp.state_code, pgr.gate_key,
         decided.rule_version, current_rule.rule_version;
ALTER VIEW public.v_region_rule_drift SET (security_invoker = true);

GRANT SELECT ON public.v_rule_currency TO anon, authenticated;
GRANT SELECT ON public.v_region_rule_drift TO anon, authenticated;
