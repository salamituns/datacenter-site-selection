-- ============================================================================
-- Migration: release17_jurisdiction_restrictions
-- Description: Adopted, pending and checked-clear restrictions on data-centre
--              land use, as the evidence layer for a moratorium gate.
--
--   Political risk is the second-largest stated constraint on US siting in
--   2026 and at least six public trackers aggregate it. Every one is a list
--   of jurisdictions; none is a parcel-level verdict with a citation.
--
--   Three design points, each learned elsewhere in this engine:
--
--   1. An ordinance is evidence; a tracker is a search result. A verdict
--      citing a tracker would disqualify real land on somebody's blog post,
--      so a jurisdiction whose instrument cannot be located is recorded
--      UNVERIFIED — never as restricted, and never as clear.
--
--   2. "No row" must not mean "no restriction". Without a checked-clear
--      record, PASS is indistinguishable from nobody having looked — the
--      absence-versus-zero error this project keeps meeting. status
--      'none_found' is a positive statement carrying its date and the
--      sources consulted.
--
--   3. The verdict is a function of the calendar. Moratoria are time-boxed;
--      v_jurisdiction_restrictions derives in_force_today so a lapsed pause
--      re-opens the gate with no human action, while the row survives —
--      a county that paused data centres stays worth knowing about.
--
--   The first population proved the first rule immediately. A secondary
--   source reports a 12-month Licking County moratorium adopted 2026-04-20;
--   it could not be traced to the county's own record, and the same period
--   saw Ohio end a state-level data-centre sales-tax exemption, which is a
--   different instrument and a plausible conflation. Licking is therefore
--   'unverified': the engine will not disqualify 1,990 parcels on an untraced
--   claim, and will not clear them either while the claim stands.
--
--   Applied to production 2026-09-12 with six jurisdiction rows.
-- ============================================================================

CREATE TABLE IF NOT EXISTS public.jurisdiction_restrictions (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    state_code      VARCHAR(2) NOT NULL,
    county_name     TEXT,
    place_name      TEXT,
    status          TEXT NOT NULL
                    CHECK (status IN ('adopted', 'pending', 'none_found', 'unverified')),
    instrument      TEXT,
    adopting_body   TEXT,
    adopted_date    DATE,
    effective_date  DATE,
    expires_date    DATE,
    scope           TEXT,
    source_url      TEXT,
    basis           TEXT NOT NULL,
    reviewed_at     DATE NOT NULL,
    sources_checked TEXT NOT NULL,
    evidence_class  TEXT NOT NULL DEFAULT 'manual'
                    CHECK (evidence_class IN ('observed','derived','estimated','manual','fallback')),
    created_at      TIMESTAMPTZ NOT NULL DEFAULT TIMEZONE('utc', NOW()),
    CONSTRAINT restriction_names_its_instrument CHECK (
        (status NOT IN ('adopted','pending')) OR (instrument IS NOT NULL
                                                  AND adopting_body IS NOT NULL)
    ),
    CONSTRAINT one_jurisdiction_level CHECK (
        county_name IS NOT NULL OR place_name IS NOT NULL
    )
);

ALTER TABLE public.jurisdiction_restrictions ENABLE ROW LEVEL SECURITY;
CREATE POLICY "restrictions are public" ON public.jurisdiction_restrictions
    FOR SELECT TO anon, authenticated USING (true);

CREATE INDEX IF NOT EXISTS idx_restrictions_county
    ON public.jurisdiction_restrictions (state_code, county_name);
CREATE INDEX IF NOT EXISTS idx_restrictions_place
    ON public.jurisdiction_restrictions (state_code, place_name);

CREATE OR REPLACE VIEW public.v_jurisdiction_restrictions AS
SELECT r.*,
       CASE
           WHEN r.status <> 'adopted' THEN NULL
           WHEN r.effective_date IS NOT NULL AND r.effective_date > CURRENT_DATE THEN FALSE
           WHEN r.expires_date IS NOT NULL AND r.expires_date <= CURRENT_DATE THEN FALSE
           ELSE TRUE
       END AS in_force_today,
       (CURRENT_DATE - r.reviewed_at) AS days_since_review
FROM public.jurisdiction_restrictions r;
ALTER VIEW public.v_jurisdiction_restrictions SET (security_invoker = true);
GRANT SELECT ON public.v_jurisdiction_restrictions TO anon, authenticated;
