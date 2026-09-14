-- ============================================================================
-- County-entry test — scores every published county against the Tier 1 bar
-- in docs/county-entry-test.md. Read-only; safe to run against production.
--
-- The bars are calibrated from the five counties already published, not
-- chosen: a standard our best county fails is not a standard, and one every
-- county passes is not a test. See the doc for where each number comes from.
--
-- Five of the six criteria are decidable here. Criterion 2b (the zoning rule
-- cites a dated instrument) and criterion 3 (the county's RTO has a power
-- adapter) are judgements about provenance rather than counts, and are
-- checked by eye against constraint_rules and pipeline.PARCEL_ADAPTERS.
--
-- Result on 2026-09-14: Loudoun, Prince William, Licking and Taylor PASS;
-- Franklin FAILS on zoning (0% decided against an 80% bar) because it
-- publishes no township zoning layer. Franklin is qualified today, so the
-- test is telling us something we had not written down.
-- ============================================================================

WITH cur AS (
  -- Only the current run of each active parcel. Superseded generations are
  -- history, not evidence about whether the county is ready.
  SELECT p.region_key, p.id AS parcel_id, p.latest_run_id
    FROM public.land_parcels p WHERE p.is_active
), g AS (
  SELECT c.region_key, gr.gate_key, gr.status, gr.rationale, gr.details
    FROM cur c
    JOIN public.parcel_gate_results gr
      ON gr.parcel_id = c.parcel_id AND gr.run_id = c.latest_run_id
), scored AS (
  SELECT region_key,
    -- 1. the cadastre can answer its own acreage
    round(100.0 * count(*) FILTER (WHERE gate_key='contiguous_acreage' AND status<>'UNKNOWN')
          / NULLIF(count(*) FILTER (WHERE gate_key='contiguous_acreage'),0), 1) AS acreage_pct,
    -- 2. zoning is traceable for most of the county
    round(100.0 * count(*) FILTER (WHERE gate_key='zoning_dc_use' AND status<>'UNKNOWN')
          / NULLIF(count(*) FILTER (WHERE gate_key='zoning_dc_use'),0), 1) AS zoning_pct,
    -- 4. water is CLASSIFIED for every parcel. Not decided -- only Loudoun
    --    decides water well, and a bar four of our own five counties fail
    --    would be a wish. What must hold is that the answer is stated.
    count(*) FILTER (WHERE gate_key='water_availability') AS water_rows,
    -- 6. UNKNOWN discipline: a verdict with no rationale is the failure this
    --    whole product exists to avoid -- a confident answer with nothing
    --    behind it. A wrong UNKNOWN is recoverable; this is not.
    count(*) FILTER (WHERE status<>'UNKNOWN'
                       AND (rationale IS NULL OR btrim(rationale)='')) AS verdicts_without_rationale,
    -- Screening-grade zoning: the jurisdiction publishes no zoning layer at
    -- all, so no parcel in it can be decided. Distinct from a parcel falling
    -- in a gap of a published map, and the distinction is the difference
    -- between a county that is mislabelled and one that is merely incomplete.
    bool_or(gate_key='zoning_dc_use' AND details->>'zoning_grade'='screening')
      AS zoning_is_screening_grade
  FROM g GROUP BY region_key
), parcels AS (
  SELECT region_key, count(*) AS n, (array_agg(DISTINCT latest_run_id))[1] AS run_id
    FROM cur GROUP BY region_key
)
SELECT
  s.region_key,
  p.n                                                   AS parcels,
  s.acreage_pct                                         AS "1_acreage_pct",
  s.zoning_pct                                          AS "2_zoning_pct",
  (s.water_rows = p.n)                                  AS "4_water_classified",
  (SELECT count(*) FROM public.source_snapshots ss
    WHERE ss.run_id = p.run_id)                         AS "5_snapshots",
  s.verdicts_without_rationale                          AS "6_verdicts_no_rationale",
  coalesce(s.zoning_is_screening_grade, false)          AS zoning_screening_grade,
  CASE WHEN s.acreage_pct >= 99
        AND s.zoning_pct  >= 80
        AND s.water_rows = p.n
        AND (SELECT count(*) FROM public.source_snapshots ss WHERE ss.run_id = p.run_id) >= 19
        AND s.verdicts_without_rationale = 0
       THEN 'PASS' ELSE 'FAIL' END                      AS tier1,
  concat_ws(', ',
    CASE WHEN s.acreage_pct < 99 THEN 'cadastre incomplete' END,
    CASE WHEN s.zoning_pct  < 80 THEN 'zoning below 80%' END,
    CASE WHEN s.water_rows <> p.n THEN 'water unclassified on some parcels' END,
    CASE WHEN (SELECT count(*) FROM public.source_snapshots ss WHERE ss.run_id = p.run_id) < 19
         THEN 'fewer than 19 source snapshots' END,
    CASE WHEN s.verdicts_without_rationale > 0 THEN 'verdicts without rationale' END,
    CASE WHEN s.zoning_is_screening_grade THEN 'no zoning layer published (screening-grade zoning)' END
  )                                                     AS fails_on
FROM scored s JOIN parcels p USING (region_key)
ORDER BY tier1 DESC, s.region_key;
