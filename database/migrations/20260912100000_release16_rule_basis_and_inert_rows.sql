-- ============================================================================
-- Migration: release16_rule_basis_and_inert_rows
-- Description: Every threshold states its origin, and no rule row claims to
--              govern something it does not.
--
--   cost_assumptions has carried `basis NOT NULL` since Release 4: no cost
--   input without a stated origin. constraint_rules had no equivalent, so the
--   thresholds deciding PASS and FAIL were the least-documented numbers in
--   the engine while the costs derived from them were the best-documented.
--
--   Recording the basis immediately exposed nine rows whose params use a
--   vocabulary parcel_gates never reads. They decide nothing — the gate finds
--   no key, falls through to DEFAULT_RULE_PARAMS, and returns a perfectly
--   reasonable verdict under a threshold nobody wrote down:
--
--     contiguous_acreage  min_acres 20          gate reads min_pass_acres
--     floodway            fail_pct 25           gate reads floodway_fail_pct
--     road_access         max_distance_miles 1  gate reads fail_miles
--
--   The rows are corrected to the read vocabulary carrying the values that
--   were ALREADY governing, so no verdict changes: the gate resolved
--   `rule.get(key, DEFAULT)` to DEFAULT when the key was absent, and now
--   resolves it to a stored value equal to DEFAULT. The rows stop being false
--   rather than starting to be obeyed.
--
--   The reverse fix would have been a live regression. Making the code read
--   fail_pct would move the floodway threshold from 0.5% to 25%, so a parcel
--   sitting a quarter inside a regulatory floodway would stop failing — where
--   FEMA's no-rise requirement (44 CFR 60.3(d)(3)) makes encroachment
--   effectively prohibited. The values happened to be the safer ones, which
--   is why this survived: the verdicts were right and the reasons were
--   fiction.
--
--   Applied to production 2026-09-12. Recorded here for replay.
-- ============================================================================

ALTER TABLE public.constraint_rules
    ADD COLUMN IF NOT EXISTS basis TEXT;

COMMENT ON COLUMN public.constraint_rules.basis IS
    'Where this threshold comes from — a named standard or regulation where one exists, and an explicit statement of project judgement where none does. Mirrors cost_assumptions.basis. "We chose it" is an acceptable basis; silence is not.';

UPDATE public.constraint_rules
SET params = '{"min_pass_acres": 100, "min_conditional_acres": 25, "source_acreage_floor": 20}'::jsonb
WHERE gate_key = 'contiguous_acreage' AND superseded_by IS NULL
  AND NOT (params ? 'min_pass_acres');

UPDATE public.constraint_rules
SET params = '{"floodway_fail_pct": 0.5, "floodplain_conditional": true}'::jsonb
WHERE gate_key = 'floodway' AND superseded_by IS NULL
  AND NOT (params ? 'floodway_fail_pct');

UPDATE public.constraint_rules
SET params = '{"conditional_miles": 2, "fail_miles": 5}'::jsonb
WHERE gate_key = 'road_access' AND superseded_by IS NULL
  AND NOT (params ? 'fail_miles');

-- Basis and review for every current rule. Where no external authority
-- exists the basis says so, rather than implying one by silence. The full
-- texts are in the release16 production migration; they are reproduced by
-- the same statements there.
