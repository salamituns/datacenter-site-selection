-- Release 13 — parcel decisions: recording what a person concluded about
-- a parcel, without letting that conclusion touch the evidence.
--
-- Two invariants carry the design, both from docs/parcel-decisions-brief.md:
--
--   1. A decision is a claim about a parcel AT A POINT IN EVIDENCE. The
--      row stores the run it was made against and a fingerprint over that
--      run's (gate_key, status) pairs. Regions republish; when a gate
--      moves, the decision is not wrong and is not silently refreshed —
--      it is flagged stale, with the moved gates named.
--   2. An override never mutates a gate verdict. The override sits BESIDE
--      the gate, attributed and dated; overall_status, evidence_coverage
--      and every score stay evidence-derived.
--
-- Identity: decided_by references auth.users. Phase 0 turned on the email
-- (magic-link) provider; the public map stays anonymous — every read
-- policy already grants anon AND authenticated, so signing in changes
-- nothing about what a visitor can see, only what they can record.
--
-- Inserts go through record_parcel_decision (SECURITY DEFINER), not a
-- client INSERT: the fingerprint is computed server-side from the run it
-- claims, so a client cannot record a decision "against" evidence that
-- never existed, and the one sanctioned mutation (superseding) happens
-- atomically with the replacement insert. The brief asks for the
-- SECURITY DEFINER exception on supersede; computing the fingerprint
-- server-side is the same reasoning one step earlier.

CREATE TABLE public.parcel_decisions (
    id              UUID PRIMARY KEY DEFAULT extensions.gen_random_uuid(),
    parcel_key      VARCHAR NOT NULL REFERENCES public.land_parcels(parcel_key)
                        ON DELETE CASCADE,
    decision        TEXT NOT NULL
                        CHECK (decision IN ('approve','reject','hold','override')),
    rationale       TEXT NOT NULL CHECK (length(btrim(rationale)) >= 10),
    decided_by      UUID NOT NULL REFERENCES auth.users(id),
    decided_at      TIMESTAMPTZ NOT NULL DEFAULT timezone('utc', now()),

    -- The evidence this decision was made against.
    run_id          UUID NOT NULL REFERENCES public.ingestion_runs(id),
    gate_fingerprint TEXT NOT NULL,

    -- Only meaningful for an override: which gate is being accepted
    -- despite its verdict, and what that verdict was when accepted.
    override_gate   TEXT,
    override_status TEXT,

    superseded_by   UUID REFERENCES public.parcel_decisions(id),
    CONSTRAINT override_names_its_gate CHECK (
        (decision <> 'override') OR (override_gate IS NOT NULL
                                     AND override_status IS NOT NULL)
    ),
    CONSTRAINT override_only_on_failing_verdicts CHECK (
        (decision <> 'override') OR (override_status IN ('FAIL','UNKNOWN'))
    )
);

-- Append-only as a database invariant, not just a policy: the ONLY
-- mutation any role can perform is setting superseded_by from NULL to a
-- value on an otherwise byte-identical row (the supersede write), and
-- even that only via the definer function. No DELETE under any
-- circumstances. Without this, a future policy slip or a service-role
-- script could edit history in place — and the history is the point.
CREATE FUNCTION public.parcel_decisions_append_only() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
    IF TG_OP = 'UPDATE'
       AND OLD.superseded_by IS NULL
       AND NEW.superseded_by IS NOT NULL
       AND ROW(NEW.id, NEW.parcel_key, NEW.decision, NEW.rationale,
               NEW.decided_by, NEW.decided_at, NEW.run_id,
               NEW.gate_fingerprint, NEW.override_gate, NEW.override_status)
           IS NOT DISTINCT FROM
           ROW(OLD.id, OLD.parcel_key, OLD.decision, OLD.rationale,
               OLD.decided_by, OLD.decided_at, OLD.run_id,
               OLD.gate_fingerprint, OLD.override_gate, OLD.override_status)
    THEN
        RETURN NEW;
    END IF;
    RAISE EXCEPTION
        'parcel_decisions is append-only: record a new decision to change one';
END;
$$;

CREATE TRIGGER trg_parcel_decisions_append_only
    BEFORE UPDATE OR DELETE ON public.parcel_decisions
    FOR EACH ROW EXECUTE FUNCTION public.parcel_decisions_append_only();

-- The fingerprint: a hash over the parcel's (gate_key, status) pairs for
-- one run, ordered by gate_key. Order is fixed by the aggregate so two
-- runs with identical verdicts hash identically no matter what order
-- their gate rows were inserted in or are returned in — gate rows carry
-- no guaranteed order. A run with no gate rows hashes to NULL, which the
-- recording function treats as "no evidence to decide against" rather
-- than storing a hash of nothing.
CREATE FUNCTION public.parcel_gate_fingerprint(p_parcel_key text, p_run_id uuid)
RETURNS text
LANGUAGE sql STABLE AS $$
    SELECT md5(string_agg(g.gate_key || '=' || g.status, ',' ORDER BY g.gate_key))
    FROM public.parcel_gate_results g
    JOIN public.land_parcels lp ON lp.id = g.parcel_id
    WHERE lp.parcel_key = p_parcel_key
      AND g.run_id = p_run_id;
$$;

-- The author's email for a decision row. auth.users is not readable by
-- API roles; a team that sees each other's judgements needs to see WHO
-- decided, so this SECURITY DEFINER helper exposes exactly one field.
--
-- anon gets EXECUTE too — not to read emails, but because
-- v_parcel_decisions (security_invoker) references this function, and
-- Postgres checks EXECUTE at query planning BEFORE row-level security
-- filters anything: without the grant, every anon visit that opens a
-- dossier would take a 42501 on the view instead of the quiet empty set
-- the anonymous map promises. The guard inside is what actually
-- protects the field: the email is returned only when the request
-- carries a JWT (any signed-in caller) or the session is a trusted
-- non-API role (psql/scripts/tests as postgres, service_role). A real
-- anon request — session_user 'anon', no signed-in claim — gets NULL
-- for every uid, so the function is not an email-enumeration oracle
-- even though it is executable.
CREATE FUNCTION public.decision_author(p_uid uuid) RETURNS text
LANGUAGE sql STABLE SECURITY DEFINER SET search_path = auth AS $$
    SELECT u.email
    FROM auth.users u
    WHERE u.id = p_uid
      AND (auth.uid() IS NOT NULL
           OR session_user NOT IN ('anon', 'authenticated'));
$$;
REVOKE ALL ON FUNCTION public.decision_author(uuid) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION public.decision_author(uuid) TO authenticated, anon;

-- Recording a decision. decided_by is taken from auth.uid(), never a
-- parameter, so a caller cannot author as someone else. run_id and
-- gate_fingerprint are computed from the parcel's CURRENT latest run —
-- the only evidence the decision can honestly claim to be made against.
-- An override must name its gate, and the gate's verdict is read from
-- the current run server-side (override_status is not a parameter), and
-- must be FAIL or UNKNOWN: an override means a human accepting a failing
-- verdict with their eyes open, not re-grading a PASS.
-- supersede: only your own, unsuperseded decision, on the same parcel.
-- The superseding UPDATE and the INSERT are one transaction — a failed
-- supersede rolls the new row back too.
CREATE FUNCTION public.record_parcel_decision(
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

    v_fp := public.parcel_gate_fingerprint(p_parcel_key, v_run);
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
         gate_fingerprint, override_gate, override_status)
    VALUES
        (p_parcel_key, p_decision, btrim(p_rationale), v_uid, v_run,
         v_fp, p_override_gate, v_status)
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

-- RLS: decisions are not public. anon has no policy and therefore no
-- rows; authenticated sees all of them (a team reviews each other's
-- judgements) but can write nothing directly — there is deliberately NO
-- insert policy, because every insert must go through
-- record_parcel_decision, where the fingerprint and authorship are
-- computed server-side. No update policy, no delete policy, ever.
ALTER TABLE public.parcel_decisions ENABLE ROW LEVEL SECURITY;

CREATE POLICY "team reads all decisions"
    ON public.parcel_decisions
    FOR SELECT TO authenticated
    USING (true);

-- The read surface: the stored fingerprint beside the current one, so
-- the client never recomputes a hash. security_invoker means the view
-- runs as the CALLER, so the table's RLS applies — without it the view
-- would execute as its owner and leak decisions to anon.
-- gates_moved names every gate whose status differs between the decision's
-- run and the current run (added or removed gates included, with the
-- missing side null).
CREATE VIEW public.v_parcel_decisions
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
       moved.gates AS gates_moved
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
