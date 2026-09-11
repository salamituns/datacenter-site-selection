# Parcel decisions — implementation brief

The engine qualifies 9,651 parcels across five counties and offers no way to
record what anyone decided about one. This closes that, without letting
opinion contaminate evidence.

**Read this first: there is no identity yet.** `auth.users` is empty and all
34 RLS policies grant read-only access to `anon`. A decision needs an author,
and there is currently nobody who can be one. Phase 0 is that, not the table.

---

## Phase 0 — identity

A decision record without an attributable author is not a record; it is a
note. Three options, and only one is defensible:

| option | verdict |
| --- | --- |
| Supabase Auth (email magic link) | **do this** — real author, real RLS, survives devices, shareable across a team |
| Browser-local decisions | already what the shortlist does; does not survive a device change, cannot be reviewed by anyone else, and is not an audit trail |
| Server rows with a self-declared name and no auth | **do not** — an unverifiable author on a durable record is worse than no record, and this engine refuses exactly that shape everywhere else |

Magic-link auth is a modest lift: enable the provider, add a sign-in route,
and gate only the decision surfaces. **The public map stays anonymous and
read-only.** Nothing about screening, qualification or comparison should
require an account — signing in buys the ability to record a decision, not
the ability to see evidence.

---

## The schema

Decisions key on `parcel_key`, not `parcel_id`. Parcels are upserted on
`parcel_key` and keep it across runs; `id` is stable today but the key is the
identifier the engine treats as the parcel's name.

```sql
CREATE TABLE public.parcel_decisions (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    parcel_key      VARCHAR NOT NULL REFERENCES public.land_parcels(parcel_key)
                        ON DELETE CASCADE,
    decision        TEXT NOT NULL
                        CHECK (decision IN ('approve','reject','hold','override')),
    rationale       TEXT NOT NULL CHECK (length(btrim(rationale)) >= 10),
    decided_by      UUID NOT NULL REFERENCES auth.users(id),
    decided_at      TIMESTAMPTZ NOT NULL DEFAULT TIMEZONE('utc', NOW()),

    -- The evidence this decision was made against.
    run_id          UUID NOT NULL REFERENCES public.ingestion_runs(id),
    gate_fingerprint TEXT NOT NULL,

    -- Only meaningful for an override: which gate is being accepted despite
    -- its verdict, and what that verdict was at the time.
    override_gate   TEXT,
    override_status TEXT,

    superseded_by   UUID REFERENCES public.parcel_decisions(id),
    CONSTRAINT override_names_its_gate CHECK (
        (decision <> 'override') OR (override_gate IS NOT NULL
                                     AND override_status IS NOT NULL)
    )
);
```

`rationale` is `NOT NULL` with a length floor on purpose. A decision with no
stated reason cannot be reviewed later, and this project already refuses
unexplained values everywhere else.

Decisions are **append-only**. Changing your mind writes a new row and sets
`superseded_by` on the old one; nothing is updated in place and nothing is
deleted. The history is the point.

---

## The two rules that make this the engine's feature rather than a CRUD table

### 1. A decision is a claim about a parcel *at a point in evidence*

Regions republish. A parcel approved last week may have had its wetlands gate
flip to FAIL on Tuesday's run. The decision is not wrong — it was correct
against what was known — but it is **stale**, and the product must say so
rather than keep displaying "Approved" beside contradicting evidence.

`gate_fingerprint` is a hash over the parcel's `(gate_key, status)` pairs for
the run the decision was made against, ordered by `gate_key`. On read,
recompute it from the current latest run and compare:

- identical → the decision still stands on the evidence it was made on;
- different → surface it as **"evidence changed since this decision"**, and
  show which gates moved.

Do not auto-void a stale decision, and do not silently refresh the
fingerprint. Both destroy the record. Flag it and let a person decide.

A view is the right home for this — `v_parcel_decisions` joining the current
fingerprint alongside the stored one, so the client never recomputes a hash.

### 2. An override never mutates a gate verdict

`override` means a human accepting a FAIL or UNKNOWN with their eyes open.
The gate stays exactly as the evidence left it. The override sits beside it,
attributed and dated, and the parcel's `overall_status` is **not** recalculated
to suit it.

If an override could change a verdict, the evidence layer would start carrying
opinion, and every downstream figure — coverage, ranking, comparison — would
quietly inherit it. That is the single thing this engine must never do. The
UI may show "FAIL · overridden by [author]"; the data must still say FAIL.

`evidence_coverage` must also ignore decisions entirely. Coverage measures
what the diligence can decide, not what a person concluded.

---

## RLS

- `anon`: **no access.** Decisions are not public.
- `authenticated`: `SELECT` all rows (a team sees each other's decisions),
  `INSERT` where `decided_by = auth.uid()`, no `UPDATE`, no `DELETE`.
- The `superseded_by` write is the one exception and should go through a
  `SECURITY DEFINER` function that sets it as part of inserting the
  replacement, so append-only cannot be worked around from the client.

Add the allow/deny cases to `database/tests/rls_tests.sql` alongside the
existing suite — an anon read that must fail, an authenticated insert
claiming another user's id that must fail, and an update attempt that must
fail.

---

## Client

- Decision control in the qualification dossier, beside the verdict. Buttons
  are inert and explain why when signed out — never hidden, since hiding it
  makes the product look like it lacks the feature.
- Rationale is required in the UI, not merely by the constraint. A form that
  submits and fails on a CHECK is a worse experience than one that asks.
- A stale decision renders with its warning and the gates that moved.
- The shortlist and comparison surface decision state; `ParcelComparisonPanel`
  gains a decision row. It already handles mixed jurisdictions, so mixed
  decision authorship is the same shape.

## Tests

Worker suite has no reach here, so these are client and SQL:

- `rls_tests.sql`: the four cases above.
- A fingerprint test: same gates in a different row order hash identically;
  one changed status hashes differently. Order-independence matters because
  the gate rows have no guaranteed order.
- A staleness test: a decision against run A, gates changed in run B, view
  reports stale.

## What not to build

- **No approval workflow.** One person recording one judgement. Multi-step
  review is a different product and would be guessed, not required.
- **No decision-weighted scoring.** Composite score stays evidence-derived.
  The moment a decision moves a score, ranking stops being reproducible.
- **No delete.** Superseding is the only way to change a decision.

## Order of work

| # | task | gate |
| --- | --- | --- |
| 0 | magic-link auth; public map stays anonymous | sign-in works, anon still reads the map |
| 1 | table, view, RLS, `rls_tests.sql` cases | anon denied, cross-user insert denied |
| 2 | fingerprint + staleness view | order-independent hash test passes |
| 3 | dossier control, rationale required | signed-out state explains itself |
| 4 | comparison + shortlist surfacing | mixed authorship renders |

Phase 0 is the only one that changes the product's posture — from a public
read-only dashboard to one with accounts. Worth a deliberate decision before
it starts.
