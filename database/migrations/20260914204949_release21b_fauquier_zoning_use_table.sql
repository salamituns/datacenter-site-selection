-- ============================================================================
-- Migration: release21b_fauquier_zoning_use_table
-- Description: Fauquier's data-centre use table, read from the ordinance.
--
--   The placeholder from release21 is superseded, not edited.
--
--   The ordinance was retrievable after all. fauquiercounty.gov answers 403
--   to a plain fetcher because Akamai keys on the request's header set; a
--   complete browser header set plus the session cookies from the page visit
--   returns 200. Articles 1-15 came down as 25 published documents.
--
--   WHAT THE ORDINANCE SAYS (downloaded 2026-09-14):
--
--     Art. 4 Sec. 4-603 (PCID, Principal Uses Permitted) lists
--       "Data Center using recycled water for cooling and with all new power
--        lines, including transmission or substation feed lines, placed
--        underground"
--     as permitted, subject to designation in an approved Development Plan
--     and to the use limitations in 4-605 and 4-606.
--
--     Art. 4 Sec. 4-605 (PCID, Special Exception Uses) requires Board
--     approval under Article V for (b) any new structure or group of
--     structures serving the same enterprise with an aggregate footprint
--     exceeding 50,000 square feet, and (c) a Data Center NOT using recycled
--     water for cooling with all new power lines placed underground.
--
--     Art. 3 Sec. 3-400(25) (Use Regulations): "A data center use shall only
--     be located in a Service District when proposed in the Business Park
--     District."
--
--     Art. 3 Part 3 use chart: NO Data Center row, in any column.
--     Art. 15 Definitions: NO definition of Data Center.
--
--   THE TWO QUESTIONS THE REPORTING COULD NOT ANSWER:
--
--     1. The 50,000 sq ft threshold is COUNTY-WIDE across PCID, not specific
--        to Vint Hill. Sec. 4-605 sits in Article 4 Part 6, the general PCID
--        district; "Vint Hill" appears exactly once in all 130 pages of
--        Article 4, as an exception to an access standard in 4-606(a). Every
--        news account framed a county-wide rule by its Vint Hill impact.
--
--     2. Business Park is genuinely unresolved, which is a finding rather
--        than a gap. Sec. 3-400(25) is a binding use regulation presupposing
--        that a data centre may be proposed in BP, yet no use chart row
--        assigns the use a permission type there or anywhere. BP is left
--        unmapped and reads UNKNOWN: inferring by-right or special-exception
--        from silence is the borrowed, unverified reasoning this engine
--        refuses. It is the one question left for Community Development.
--
--   MAPPING:
--     PCID -> special_exception. The by-right path exists but turns on
--     cooling and transmission design a parcel survey cannot observe, and is
--     overridden by 4-605(b) for any building group above 50,000 sq ft,
--     which every credible data centre exceeds. by_right stays empty.
--
--     The sixteen other Article 3 base districts -> prohibited, on the use
--     chart's own key ("BLANK - Use not allowed as listed in the zoning
--     district represented by that column") together with Sec. 3-332, the
--     separate route for a use not otherwise allowed. BP is excluded because
--     3-400(25) singles it out.
--
--     M-G, M-R, M-T, MU-BLTN and PRD appear in the GIS layer but their use
--     regulations were not read. Unmapped, so UNKNOWN.
--
--   Measured against all 4,062 qualifying parcels after applying: 4,044 FAIL,
--   4 CONDITIONAL (PCID), 14 UNKNOWN (no zoning overlap — boundary slivers).
--   99.7% decided, against 0% under the placeholder and an 80% entry bar.
--   Every row carries a rationale.
-- ============================================================================

WITH replacement AS (
  INSERT INTO public.constraint_rules
      (gate_key, jurisdiction, rule_version, params, description, basis,
       reviewed_at, reviewed_against, review_due_months)
  VALUES (
    'zoning_dc_use', 'Fauquier County, VA', '2026-ord-reviewed',
    '{
       "by_right": [],
       "special_exception": ["PCID"],
       "prohibited": ["RC","RA","RR-2","V","R-1","R-2","R-3","R-4","TH","GA",
                      "MDP","C-1","C-2","C-3","CV","I-1","I-2"]
     }'::jsonb,
    'Data-centre use status by zoning district, from the Fauquier County Zoning Ordinance.',
    'Read from the ordinance text, not from reporting. PCID: Sec. 4-603 lists "Data Center using recycled water for cooling and with all new power lines, including transmission or substation feed lines, placed underground" among the Principal Uses Permitted, subject to an approved Development Plan and the limitations of 4-605 and 4-606; Sec. 4-605 makes a Data Center not meeting those conditions a Special Exception (c), and independently makes any structure or group serving one enterprise above 50,000 square feet a Special Exception (b). Because every credible data centre exceeds 50,000 square feet, and because the by-right path turns on cooling and transmission design that a parcel survey cannot observe, PCID is recorded as special exception and by_right is left empty. That 50,000 sq ft threshold is county-wide across PCID and not specific to Vint Hill: Sec. 4-605 sits in Article 4 Part 6, the general PCID district, and Vint Hill appears once in the whole of Article 4, as an exception to an access standard in 4-606(a). BUSINESS PARK IS DELIBERATELY UNMAPPED. Art. 3 Sec. 3-400(25) is a binding use regulation reading "A data center use shall only be located in a Service District when proposed in the Business Park District", which presupposes the use may be proposed there, yet the Article 3 Part 3 use chart carries no Data Center row in the BP column or any other, and Article 15 defines no such use. The ordinance contemplates a data centre in BP without stating its permission type, so BP reads UNKNOWN rather than being inferred. The sixteen other Article 3 base districts are prohibited on the chart''s own key, which states that a blank means the use is not allowed in that district, together with Sec. 3-332 providing the separate route for a use not otherwise allowed. M-G, M-R, M-T, MU-BLTN and PRD appear in the GIS layer but their regulations were not read and are left UNKNOWN. Sources: Article 3 (Districts and Use Regulations), Article 4 Part 6 (PCID, Secs. 4-601 to 4-616) and Article 15 (Definitions), downloaded from fauquiercounty.gov on 2026-09-14, together with the county''s adopted text-amendment logs through 2026-07-09, none of which record a data-centre amendment after the Article 3 and 4 text relied on here.',
    '2026-09-14',
    'Fauquier County Zoning Ordinance, Art. 3 Secs. 3-100/3-332/3-400(25), Art. 4 Part 6 Secs. 4-601 to 4-606, Art. 15; zoning text amendment logs adopted 2025-03-13 through 2026-07-09',
    12)
  RETURNING id
)
UPDATE public.constraint_rules c
   SET superseded_by = (SELECT id FROM replacement)
 WHERE c.gate_key = 'zoning_dc_use'
   AND c.jurisdiction = 'Fauquier County, VA'
   AND c.rule_version = '2026-districts-only'
   AND c.superseded_by IS NULL;
