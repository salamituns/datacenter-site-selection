-- ============================================================================
-- Migration: release16b_rule_currency_exposes_basis
-- Description: v_rule_currency reports whether a rule states its basis.
--
--   The view predates constraint_rules.basis. A currency view that cannot
--   report whether a threshold states its origin is only half the check:
--   "reviewed recently" and "says where the number came from" are different
--   questions, and a rule can pass one while failing the other.
-- ============================================================================

DROP VIEW IF EXISTS public.v_rule_currency;

CREATE VIEW public.v_rule_currency AS
SELECT cr.id, cr.jurisdiction, cr.gate_key, cr.rule_version,
       cr.reviewed_at, cr.reviewed_against, cr.basis, cr.review_due_months,
       (CURRENT_DATE - cr.reviewed_at) AS days_since_review,
       CASE
           WHEN cr.reviewed_at IS NULL THEN 'never recorded'
           WHEN cr.reviewed_at < (CURRENT_DATE - (cr.review_due_months || ' months')::interval)
                THEN 'review due'
           ELSE 'current'
       END AS review_status,
       (cr.basis IS NULL) AS basis_missing,
       cr.created_at
FROM public.constraint_rules cr
WHERE cr.superseded_by IS NULL;

ALTER VIEW public.v_rule_currency SET (security_invoker = true);
GRANT SELECT ON public.v_rule_currency TO anon, authenticated;
