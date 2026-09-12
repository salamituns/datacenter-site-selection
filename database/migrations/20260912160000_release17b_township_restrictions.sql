-- ============================================================================
-- Migration: release17b_township_restrictions
-- Description: Add the township level, and correct the Licking record.
--
--   The first population recorded Licking County as 'unverified' on a
--   secondary report of a 12-month county moratorium. The county has no
--   moratorium: Microsoft restarted 869 MW of campuses across Heath, Hebron
--   and New Albany during 2026, which is not the behaviour of a paused
--   county. What exists is a TOWNSHIP ban — St. Albans, adopted unanimously
--   2026-03-10 and permanent.
--
--   That is a level the table could not express. county_name and place_name
--   cover counties and TIGER incorporated places; an Ohio township is
--   neither. It is a minor civil division, and in Ohio it is the zoning
--   authority for unincorporated land — which is exactly why the Licking use
--   table is township-keyed. A restriction table that cannot name the body
--   which actually restricts is the wrong shape, and recording one township's
--   ban against its county would have failed 1,990 parcels for a rule binding
--   on a township of 2,600 people.
--
--   The St. Albans instrument also clarifies where the two gates divide. It
--   is a zoning TEXT AMENDMENT striking data processing services from the
--   conditionally permitted uses — not a pause. A moratorium suspends
--   processing while the use table still allows the use; this removed the
--   use. Its enforcement mechanism is therefore the zoning gate, and the
--   township rule must reflect it if the survey ever reaches St. Albans.
--   Today it binds no surveyed parcel: none of the 22 township ordinances
--   covering the corridor's 1,885 zoned parcels is St. Albans.
--
--   Applied to production 2026-09-12.
-- ============================================================================

ALTER TABLE public.jurisdiction_restrictions
    ADD COLUMN IF NOT EXISTS subdivision_name TEXT;

COMMENT ON COLUMN public.jurisdiction_restrictions.subdivision_name IS
    'Minor civil division — an Ohio township or equivalent, as TIGER county subdivisions name it. Neither a county nor an incorporated place, and in Ohio the zoning authority for unincorporated land.';

ALTER TABLE public.jurisdiction_restrictions
    DROP CONSTRAINT IF EXISTS one_jurisdiction_level;
ALTER TABLE public.jurisdiction_restrictions
    ADD CONSTRAINT one_jurisdiction_level CHECK (
        county_name IS NOT NULL OR place_name IS NOT NULL
        OR subdivision_name IS NOT NULL
    );

CREATE INDEX IF NOT EXISTS idx_restrictions_subdivision
    ON public.jurisdiction_restrictions (state_code, subdivision_name);

-- The Licking correction and the St. Albans row are data, applied with this
-- migration in production; see the release17b statements there.
