-- Release 14 — decision snapshots: make an approval say what it was
-- approved despite, per docs/parcel-decisions-brief.md ("Follow-up").
--
-- The first real decision exposed the gap. A Loudoun parcel failing
-- protected_land, water_availability and zoning_dc_use was recorded as
-- approve with override_gate null — the schema forces an override to
-- name the gate it accepts, and approve walks past that, accepting
-- failing gates without naming one. run_id reconstructs every verdict,
-- but the row was not self-describing, and the join is the thing nobody
-- knows to run six months on.
--
-- verdict_at_decision and gates_not_passing are a denormalised summary
-- for readability, NOT a second source of truth: the fingerprint plus
-- run_id stays authoritative, and if the two ever disagree the summary
-- is the bug. Both are computed inside record_parcel_decision in the
-- SAME statement that takes the fingerprint — a snapshot read
-- separately can disagree with the fingerprint (a concurrent write
-- lands between the reads), and then the row contradicts itself. Never
-- accepted from the client, never derived from "current" gates later.
--
-- Explicitly not done: constraining approve to PASS/CONDITIONAL. A
-- schema that refuses a judgement a person is entitled to make gets
-- worked around, usually by recording something less true that the
-- constraint happens to allow. The UI prompts instead; the schema stays
-- permissive and the record stays honest.

-- 1. The columns ----------------------------------------------------------

ALTER TABLE public.parcel_decisions
    ADD COLUMN verdict_at_decision TEXT,   -- PASS | CONDITIONAL | FAIL | UNKNOWN
    ADD COLUMN gates_not_passing  TEXT[];  -- e.g. {protected_land,water_availability}

-- 2. The append-only guard learns the new columns --------------------------
--
-- The guard's byte-identical test must cover the summary too: without
-- these two entries, an in-place edit of ONLY verdict_at_decision or
-- gates_not_passing would pass the check — history editable through
-- the one column the guard forgot.

CREATE OR REPLACE FUNCTION public.parcel_decisions_append_only()
RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
    IF TG_OP = 'UPDATE'
       AND OLD.superseded_by IS NULL
       AND NEW.superseded_by IS NOT NULL
       AND ROW(NEW.id, NEW.parcel_key, NEW.decision, NEW.rationale,
               NEW.decided_by, NEW.decided_at, NEW.run_id,
               NEW.gate_fingerprint, NEW.override_gate, NEW.override_status,
               NEW.verdict_at_decision, NEW.gates_not_passing)
           IS NOT DISTINCT FROM
           ROW(OLD.id, OLD.parcel_key, OLD.decision, OLD.rationale,
               OLD.decided_by, OLD.decided_at, OLD.run_id,
               OLD.gate_fingerprint, OLD.override_gate, OLD.override_status,
               OLD.verdict_at_decision, OLD.gates_not_passing)
    THEN
        RETURN NEW;
    END IF;
    RAISE EXCEPTION
        'parcel_decisions is append-only: record a new decision to change one';
END;
$$;

-- 3. Recording computes the whole snapshot in one read ---------------------

CREATE OR REPLACE FUNCTION public.record_parcel_decision(
    p_parcel_key   text,
    p_decision     text,
    p_rationale    text,
    p_override_gate text DEFAULT NULL,
    p_supersedes   uuid DEFAULT NULL
) RETURNS uuid
LANGUAGE plpgsql SECURITY DEFINER SET search_path = public AS $$
DECLARE
    v_uid     uuid := auth.uid();
    v_run     uuid;
    v_fp      text;
    v_verdict text;
    v_gates   text[];
    v_status  text;
    v_id      uuid;
BEGIN
    IF v_uid IS NULL THEN
        RAISE EXCEPTION 'sign in to record a decision';
    END IF;
    IF p_decision NOT IN ('approve','reject','hold','override') THEN
        RAISE EXCEPTION 'decision must be approve, reject, hold or override';
    END IF;
    IF length(btrim(coalesce(p_rationale, ''))) < 10 THEN
        RAISE EXCEPTION 'a rationale of at least 10 characters is required — a decision nobody can review later is not a record';
    END IF;

    SELECT lp.latest_run_id INTO v_run
    FROM public.land_parcels lp
    WHERE lp.parcel_key = p_parcel_key;
    IF v_run IS NULL THEN
        RAISE EXCEPTION 'no such parcel: %', p_parcel_key;
    END IF;

    -- THE SNAPSHOT READ: fingerprint, overall verdict and non-passing
    -- gates from ONE pass over this run's gate rows. Reading the
    -- summary separately — a second query, or a helper called on its
    -- own — lets a concurrent write land between the reads, and then
    -- the row contradicts itself: a fingerprint that says one thing
    -- and a summary that says another. One statement cannot disagree
    -- with itself. The verdict keeps v_land_parcels' precedence
    -- (FAIL > UNKNOWN > CONDITIONAL > PASS) so the summary always says
    -- exactly what the map said at decision time, and the fingerprint
    -- formula stays byte-identical to parcel_gate_fingerprint, which
    -- the view still uses to compare against the current run.
    SELECT md5(string_agg(g.gate_key || '=' || g.status, ',' ORDER BY g.gate_key)),
           CASE
               WHEN BOOL_OR(g.status = 'FAIL')         THEN 'FAIL'
               WHEN BOOL_OR(g.status = 'UNKNOWN')     THEN 'UNKNOWN'
               WHEN BOOL_OR(g.status = 'CONDITIONAL') THEN 'CONDITIONAL'
               ELSE 'PASS'
           END,
           coalesce(
               array_agg(g.gate_key ORDER BY g.gate_key)
                   FILTER (WHERE g.status <> 'PASS'),
               '{}'::text[])::text[]
    INTO v_fp, v_verdict, v_gates
    FROM public.parcel_gate_results g
    JOIN public.land_parcels lp ON lp.id = g.parcel_id
    WHERE lp.parcel_key = p_parcel_key
      AND g.run_id = v_run;

    IF v_fp IS NULL THEN
        RAISE EXCEPTION 'parcel % has no gate rows for its current run — nothing to decide against', p_parcel_key;
    END IF;

    IF p_decision = 'override' THEN
        IF p_override_gate IS NULL THEN
            RAISE EXCEPTION 'an override must name the gate it accepts';
        END IF;
        SELECT g.status INTO v_status
        FROM public.v_parcel_gates g
        WHERE g.parcel_key = p_parcel_key
          AND g.gate_key = p_override_gate;
        IF v_status IS NULL THEN
            RAISE EXCEPTION 'parcel % has no gate named %', p_parcel_key, p_override_gate;
        END IF;
        IF v_status NOT IN ('FAIL','UNKNOWN') THEN
            RAISE EXCEPTION 'an override accepts a FAIL or UNKNOWN verdict; gate % currently reads %', p_override_gate, v_status;
        END IF;
    END IF;

    INSERT INTO public.parcel_decisions
        (parcel_key, decision, rationale, decided_by, run_id,
         gate_fingerprint, override_gate, override_status,
         verdict_at_decision, gates_not_passing)
    VALUES
        (p_parcel_key, p_decision, btrim(p_rationale), v_uid, v_run,
         v_fp, p_override_gate, v_status, v_verdict, v_gates)
    RETURNING id INTO v_id;

    IF p_supersedes IS NOT NULL THEN
        UPDATE public.parcel_decisions d
        SET superseded_by = v_id
        WHERE d.id = p_supersedes
          AND d.parcel_key = p_parcel_key
          AND d.decided_by = v_uid
          AND d.superseded_by IS NULL;
        IF NOT FOUND THEN
            RAISE EXCEPTION 'cannot supersede that decision — it is not yours, not on this parcel, or already superseded';
        END IF;
    END IF;

    RETURN v_id;
END;
$$;
REVOKE ALL ON FUNCTION public.record_parcel_decision(text, text, text, text, uuid)
    FROM PUBLIC, anon;
GRANT EXECUTE ON FUNCTION public.record_parcel_decision(text, text, text, text, uuid)
    TO authenticated;

-- 4. Backfill the existing rows from their own recorded history ------------
--
-- THE APPEND-ONLY TRIGGER IS LIFTED DELIBERATELY, FOR THIS ONE UPDATE.
-- trg_parcel_decisions_append_only fires on UPDATE, so the guard that
-- makes the table trustworthy also refuses the migration that fills
-- the new columns on existing rows. A schema migration adding a
-- derived column and filling it from each row's own stored run history
-- is the ONLY legitimate reason to disable it — this comment exists so
-- the next person does not read the DISABLE below as a general escape
-- hatch. Unlike the unrisked composite, this backfill is recoverable:
-- run_id is stored on every row, so the verdicts at decision time are
-- still in parcel_gate_results and this reads real history, not a
-- plausible reconstruction. The trigger is re-enabled in the same
-- transaction, and any failure rolls the whole migration back with the
-- table untouched.
--
-- The summary comes from the same single pass over each row's run that
-- the recording function uses — same aggregates, same precedence — so
-- a backfilled row and a freshly recorded row are indistinguishable.

ALTER TABLE public.parcel_decisions DISABLE TRIGGER trg_parcel_decisions_append_only;

UPDATE public.parcel_decisions d
SET verdict_at_decision = s.verdict,
    gates_not_passing  = s.gates::text[]
FROM (
    SELECT g.parcel_id,
           g.run_id,
           CASE
               WHEN BOOL_OR(g.status = 'FAIL')         THEN 'FAIL'
               WHEN BOOL_OR(g.status = 'UNKNOWN')     THEN 'UNKNOWN'
               WHEN BOOL_OR(g.status = 'CONDITIONAL') THEN 'CONDITIONAL'
               ELSE 'PASS'
           END AS verdict,
           coalesce(
               array_agg(g.gate_key ORDER BY g.gate_key)
                   FILTER (WHERE g.status <> 'PASS'),
               '{}'::text[]) AS gates
    FROM public.parcel_gate_results g
    GROUP BY g.parcel_id, g.run_id
) s
JOIN public.land_parcels lp ON lp.id = s.parcel_id
WHERE lp.parcel_key = d.parcel_key
  AND d.run_id = s.run_id;

ALTER TABLE public.parcel_decisions ENABLE TRIGGER trg_parcel_decisions_append_only;

-- 5. Verify, then tighten ---------------------------------------------------
--
-- The backfill must be complete and must agree with a recomputation
-- from each row's own run_id — the fingerprint plus run_id is
-- authoritative, and a disagreement here means the summary (or the
-- function) wrote something the evidence does not support. Only after
-- that proof do the columns go NOT NULL.

DO $verify$
DECLARE
    v_unbackfilled int;
    v_disagreeing  int;
BEGIN
    SELECT count(*) INTO v_unbackfilled
    FROM public.parcel_decisions
    WHERE verdict_at_decision IS NULL
       OR gates_not_passing IS NULL;
    IF v_unbackfilled > 0 THEN
        RAISE EXCEPTION '% decision row(s) could not be backfilled — the run they claim has no gate rows', v_unbackfilled;
    END IF;

    SELECT count(*) INTO v_disagreeing
    FROM public.parcel_decisions d
    JOIN LATERAL (
        SELECT md5(string_agg(g.gate_key || '=' || g.status, ',' ORDER BY g.gate_key)) AS fp,
               CASE
                   WHEN BOOL_OR(g.status = 'FAIL')         THEN 'FAIL'
                   WHEN BOOL_OR(g.status = 'UNKNOWN')     THEN 'UNKNOWN'
                   WHEN BOOL_OR(g.status = 'CONDITIONAL') THEN 'CONDITIONAL'
                   ELSE 'PASS'
               END AS verdict,
               coalesce(
                   array_agg(g.gate_key ORDER BY g.gate_key)
                       FILTER (WHERE g.status <> 'PASS'),
                   '{}'::text[]) AS gates
        FROM public.parcel_gate_results g
        JOIN public.land_parcels lp ON lp.id = g.parcel_id
        WHERE lp.parcel_key = d.parcel_key
          AND g.run_id = d.run_id
    ) s ON true
    WHERE d.gate_fingerprint   IS DISTINCT FROM s.fp
       OR d.verdict_at_decision IS DISTINCT FROM s.verdict
       -- explicit cast: the aggregate returns varchar[] (gate_key is
       -- varchar) and the column is text[] — the array types are not
       -- implicitly comparable, only assignment-castable.
       OR d.gates_not_passing  IS DISTINCT FROM s.gates::text[];
    IF v_disagreeing > 0 THEN
        RAISE EXCEPTION '% decision row(s) disagree with the run they claim', v_disagreeing;
    END IF;
END
$verify$;

ALTER TABLE public.parcel_decisions
    ALTER COLUMN verdict_at_decision SET NOT NULL,
    ADD CONSTRAINT decision_verdict_domain
        CHECK (verdict_at_decision IN ('PASS','CONDITIONAL','FAIL','UNKNOWN')),
    ALTER COLUMN gates_not_passing SET NOT NULL;

-- 6. The view carries the summary to the client -----------------------------
--
-- New columns are appended (CREATE OR REPLACE requires the existing
-- prefix unchanged); security_invoker and the anon/authenticated
-- grants carry over, and are re-issued anyway to be explicit.

CREATE OR REPLACE VIEW public.v_parcel_decisions
WITH (security_invoker = true) AS
SELECT d.id,
       d.parcel_key,
       d.decision,
       d.rationale,
       d.decided_by,
       public.decision_author(d.decided_by) AS decided_by_email,
       d.decided_at,
       d.run_id,
       d.gate_fingerprint,
       d.override_gate,
       d.override_status,
       d.superseded_by,
       d.superseded_by IS NULL AS is_current,
       lp.latest_run_id AS current_run_id,
       cur.fp AS current_gate_fingerprint,
       (d.gate_fingerprint IS DISTINCT FROM cur.fp) AS is_stale,
       moved.gates AS gates_moved,
       d.verdict_at_decision,
       d.gates_not_passing
FROM public.parcel_decisions d
JOIN public.land_parcels lp ON lp.parcel_key = d.parcel_key
CROSS JOIN LATERAL (
    SELECT public.parcel_gate_fingerprint(d.parcel_key, lp.latest_run_id) AS fp
) cur
CROSS JOIN LATERAL (
    SELECT coalesce(
        jsonb_agg(jsonb_build_object('gate_key', m.gate_key, 'was', m.was, 'now', m.now)
                  ORDER BY m.gate_key),
        '[]'::jsonb) AS gates
    FROM (
        SELECT coalesce(a.gate_key, b.gate_key) AS gate_key,
               a.status AS was, b.status AS now
        FROM (
            SELECT g.gate_key, g.status
            FROM public.parcel_gate_results g
            JOIN public.land_parcels lp2 ON lp2.id = g.parcel_id
            WHERE lp2.parcel_key = d.parcel_key
              AND g.run_id = d.run_id
        ) a
        FULL JOIN (
            SELECT g.gate_key, g.status
            FROM public.parcel_gate_results g
            JOIN public.land_parcels lp3 ON lp3.id = g.parcel_id
            WHERE lp3.parcel_key = d.parcel_key
              AND g.run_id = lp.latest_run_id
        ) b ON b.gate_key = a.gate_key
        WHERE a.status IS DISTINCT FROM b.status
    ) m
) moved;

GRANT SELECT ON public.v_parcel_decisions TO authenticated, anon;
