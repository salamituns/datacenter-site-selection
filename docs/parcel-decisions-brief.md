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

---

## Shipped (2026-09-11)

All five phases, released as `release13_parcel_decisions`. Authorship,
fingerprint and supersede are computed server-side in one
`SECURITY DEFINER` function (`record_parcel_decision`); there is no INSERT
policy on the table at all, and the append-only trigger makes even the
owner's in-place edit or delete raise. Both SQL suites
(`rls_tests.sql` §5, `decision_tests.sql`) pass against the live database.

One finding worth keeping: `v_parcel_decisions` is `security_invoker` and
references `decision_author`, and Postgres checks EXECUTE on view functions
at planning time — before RLS returns the anon its empty set. With EXECUTE
granted to authenticated only, every anonymous dossier open took a 42501
instead of the quiet nothing the map promises. The fix grants EXECUTE to
anon and puts the protection inside the function: the email is returned only
when the request carries a JWT or the session is a non-API role, so a real
anon call gets `null` for every uid (verified against PostgREST: anon view
GET → 200 `[]`, anon `/rpc/decision_author` → `null`). A `SET ROLE` test
cannot see this — `session_user` stays `postgres` — so the suite pins the
grant and the comment records the probe.

Outstanding, outside the repo (Site URL resolved 2026-09-11: the
dashboard was still `http://localhost:3000` at ship time, so production
magic links redirected wrong until it was set to
`https://grid.salamituns.com` with the redirect allowlist). The built-in
emailer also rate-limits at roughly two sends an hour, which is fine for
a first user and worth replacing with real SMTP if the team grows.

---

## Follow-up — make an approval self-describing

The first real decision exposed this. A Loudoun parcel failing `protected_land`,
`water_availability` and `zoning_dc_use` was recorded as `approve` with
`override_gate` null. The schema forces an `override` to name the gate it
accepts; `approve` walks past that requirement and accepts three failing gates
without naming one.

Nothing is lost — `run_id` reconstructs every verdict at decision time — but
the row is not self-describing. "Approved a clean site" and "approved despite
three FAILs" are the same row shape, and only a join tells them apart. Six
months on, the join is the thing nobody knows to run.

**Do 1 and 2 below. Not 3.**

### 1. Store the verdict the decision was made against

```sql
ALTER TABLE public.parcel_decisions
    ADD COLUMN verdict_at_decision TEXT,          -- PASS | CONDITIONAL | FAIL | UNKNOWN
    ADD COLUMN gates_not_passing  TEXT[];         -- e.g. {protected_land,water_availability}
```

Both are **computed inside `record_parcel_decision`**, in the same statement
that takes the fingerprint, from the same `run_id`. Never accepted from the
client, and never derived later from "current" gates — a snapshot taken from a
different read than the fingerprint can disagree with it, and then the row
contradicts itself.

This is a denormalised summary for readability, not a second source of truth.
The fingerprint plus `run_id` stays authoritative; if the two ever disagree,
the fingerprint wins and the summary is the bug.

Backfill the existing row. Unlike the unrisked-composite case, this one **is**
recoverable: `run_id` is stored, so the verdicts at decision time are still
in `parcel_gate_results` and the backfill reads real history rather than
reconstructing a plausible one. Set `NOT NULL` after backfilling.

> **The append-only trigger will block its own backfill.**
> `trg_parcel_decisions_append_only` fires on UPDATE, so a migration that fills
> these columns on the existing row is refused by the guard that makes the
> table trustworthy. Disable and re-enable it inside the migration
> transaction, with a comment saying why — a schema migration adding a derived
> column is the only legitimate reason to lift it, and writing that down is
> what stops the next person treating it as a general escape hatch.

### 2. Route by verdict in the UI

When the parcel's current verdict is not `PASS` and the author picks
**Approved**, prompt before recording — naming the actual gates:

> This parcel fails **protected land**, **water availability** and **zoning**.
> Record as *Overridden* and name what you're accepting, or continue with
> *Approved*?

Prompt, do not block. The point is to make the better record the easy one,
not to take the judgement away. An author who means "I approve this for
acquisition and the gates are someone else's problem" is making a real call
and must still be able to make it — the record simply has to show what they
knew.

### 3. Not doing: constrain `approve` to PASS or CONDITIONAL

Tempting, and wrong. It would block the legitimate call above, and a schema
that refuses a judgement a person is entitled to make gets worked around —
usually by recording something less true that the constraint happens to allow.

---

## Follow-up shipped (2026-09-11, release14_decision_snapshot)

Both flagged traps handled. `record_parcel_decision` takes the
fingerprint, the overall verdict and the non-passing gates in **one
statement** over the run's gate rows (the verdict keeps
`v_land_parcels`' precedence, FAIL > UNKNOWN > CONDITIONAL > PASS), so
the stored summary cannot disagree with the stored fingerprint — one
read cannot contradict itself. The backfill lifted
`trg_parcel_decisions_append_only` inside the migration transaction
with a comment stating that a schema migration adding a derived column
and filling it from each row's own stored run history is the only
legitimate reason to do so, and re-enabled it before the migration
verified every row against its own `run_id` and then set the columns
NOT NULL. The guard's byte-identical test also learned the two new
columns — without that, an in-place edit of only the summary would
have passed it.

The real Loudoun approval now reads `verdict_at_decision = FAIL` and
`gates_not_passing = {power_capacity, protected_land,
water_availability, wetlands, zoning_dc_use}` — five gates, not the
three FAILs the brief's opening guessed at: "not passing" includes the
UNKNOWNs, which is the truthful reading of what the approval accepted.
Both SQL suites pass against the live database, including a new
whole-table assertion that every stored row agrees with a
recomputation from its own `run_id`.

The UI prompts, never blocks: approving a parcel whose current gates
are not all PASS gets one warning naming each gate and its status,
with *Record as Overridden* (offered only when a FAIL or UNKNOWN gate
exists to accept) beside *Continue with Approved*. Recorded approvals
carry the summary on the card — "Approved despite … — FAIL at decision
time" — read from the stored row, never from gates that may since have
moved.

One verification note: the prompt was exercised in a real browser via
a temporary preview route with an intercepted decisions fetch (the
built-in emailer's rate limit still blocks a genuine local sign-in,
and Supabase's hosted auth refuses password login for users inserted
directly into `auth.users`). The preview route was deleted before the
commit. One ops item from release13 remains: the built-in emailer's
rate limit (the Site URL was set to `https://grid.salamituns.com` on
2026-09-11, so production magic links now redirect correctly).
