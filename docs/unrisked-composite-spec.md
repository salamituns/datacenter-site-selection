# Unrisked composite storage

**Decision:** `grid_parcels` stores the *measurement* and lets the database
derive the *risked* figure, rather than storing a product the measurement
cannot be recovered from. `composite_score_unrisked` becomes the screening
model's own output; `composite_score` becomes a generated column equal to
`round(unrisked × coverage_factor, 1)`. The worker stops multiplying.

## Why

Release 9 stores only the risked composite: for a parcel-tier region,
`composite_score` is the screening score already multiplied by
`evidence_coverage`. The unrisked value is not stored anywhere and is not
recoverable from what is.

That is a deviation from every framework this engine otherwise follows.
SPE-PRMS is the one standard that sanctions multiplying an estimate by a
chance factor at all — and it requires the unrisked figure be disclosed
alongside the risked one. JORC goes further: categories "must not be reported
in a combined form unless details for the individual categories are also
provided". AACE 18R-97, which this project already uses for site-work costs,
classifies by definition maturity and never discounts one class into another.

The failure mode is not hypothetical here. Multiplying Morrow County's 330
composites by a coverage of 0.0 destroyed them irreversibly: they could not be
reconstructed afterwards, only re-derived by re-running the pipeline. A
40/25/20/15 recomputation reproduced every region's prime-cell count exactly
(210/274/276/301) and still matched only ~75% of rows, so a SQL backfill from
it would have written numbers the worker never produced.

Ohio and Texas are in the same position today, just less visibly: their stored
composites are risked figures at 0.772 and 0.664, and the measurements behind
them are gone.

## Design

| column | meaning | written by |
| --- | --- | --- |
| `composite_score_unrisked` | the screening model's output — power/water/risk/climate under the ingestion weights. A measurement. | worker |
| `evidence_coverage` | share of the region's parcel gates the diligence can decide. A confidence factor. | worker |
| `evidence_tier` | which survey the region gets: `parcel` \| `screening`. | worker |
| `composite_score` | `round(unrisked × factor, 1)`, where factor is `evidence_coverage` inside the parcel tier and `1` outside it. A derived decision figure. | **the database** |

```sql
composite_score NUMERIC(6,2) GENERATED ALWAYS AS (
    round(composite_score_unrisked *
          (CASE WHEN evidence_tier = 'parcel' THEN evidence_coverage ELSE 1 END),
          1)
) STORED
```

Validated against the live column types (`composite_score` NUMERIC(6,2),
`evidence_coverage` NUMERIC(4,3)): the expression is immutable, so Postgres
accepts it as `STORED`, and it reproduces the current figures exactly —
64.80 × 0.664 → 43.00, 79.50 × 0.994 → 79.00, and a screening-tier 78.10 → 78.10.

Three properties follow, and they are the point of the change:

1. **The annihilator becomes structurally impossible.** The worker never writes
   a product, so no multiplication can overwrite a measurement. The 0.0 case
   is handled once, in one expression, in the schema.
2. **The two figures cannot drift.** A derived value that is stored by hand is
   a second source of truth; a generated column is not.
3. **It stays orderable and indexable.** `STORED` means the client's
   `.order("composite_score")` and a btree index keep working unchanged.

### What ranks on which

Making this explicit, because today it is accidental rather than decided:

- **Zones form on unrisked score.** A cluster of contiguous high-scoring cells
  is a physical finding about the land, and diligence coverage is not a
  property of the land. This is already what happens — clustering runs before
  the scaling — which is why Morrow County has a zone at all.
- **Sites rank on risked score, within tier.** Ranking is a decision aid, and
  the decision should be penalised by what is not yet known.

Both become deliberate rather than a side effect of statement order.

### Disclosure

PRMS requires the unrisked figure be shown, not merely stored. The dossier
should read as three facts, not one number:

```
Composite      64.8   screening measurement
Coverage       66.4%  4 of 9 parcel gates undecidable
Risked         43.0   comparable figure
```

## Rollout

The inversion cannot be backfilled. Dividing a stored risked value by its
coverage factor reconstructs a number the worker never produced — the same
error the Oregon episode already demonstrated. Each region must be republished.

There is also no zero-window ordering: adding the generated column while
`composite_score` still holds risked values would double-risk it, and shipping
the worker change first would drop the penalty until the republish lands. So
the new column is introduced additively and the swap happens last, behind a
verification gate.

**Phase 1 — additive, no behaviour change. _Done._**
Add `composite_score_unrisked NUMERIC(6,2)` (nullable). The worker writes both:
the pure composite into the new column and, as today, the risked value into
`composite_score`. Nothing reads the new column. Safe to ship alone.

> `CREATE OR REPLACE VIEW` may only **append** columns — inserting one mid-list
> fails with `cannot change name of view column`, because replacing a view
> matches columns by position, not by name. `v_grid_parcels` therefore carries
> `composite_score_unrisked` last, out of logical order. Phase 3 drops and
> recreates the view anyway, which is the only point at which the ordering can
> be tidied.

**Phase 2 — republish and verify. _Done._**
Publish VA, OH, TX, OR. Every row then carries both figures, and the gate is a
data-integrity check that the worker and the future generated expression agree:

```sql
select count(*) filter (
  where abs(composite_score
        - round(composite_score_unrisked *
                (case when evidence_tier='parcel' then evidence_coverage else 1 end), 1)
        ) > 0.05
) as disagreements
from grid_parcels;
```

Phase 3 proceeds only at `disagreements = 0` and `composite_score_unrisked IS
NOT NULL` for every row.

**Phase 3 — make the derived value derived. _Done._**
A column cannot be made generated in place, so `composite_score` is dropped and
re-added as the generated column. That drops `idx_grid_parcels_composite_score`
and the dependent view, both of which this project's migrations already
recreate wholesale. `promote_ingestion_run` stops inserting `composite_score`
(a generated column cannot be inserted into) and inserts
`composite_score_unrisked` instead, which stays a plain column on
`stg_grid_parcels` so staging remains a straight dict insert.

`stg_grid_parcels.composite_score` is **dropped**, not merely left unwritten.
It was `NOT NULL DEFAULT 0.0`, so a worker that simply stopped sending it would
have staged 0.0 from the default without erroring, and the promote would have
copied that 0.0 into every cell of the region. That is the Morrow County
annihilator arriving through a column default instead of a multiplication — a
loud failure turned quiet. Dropping the column makes the mistake impossible and
forces the worker and the schema to ship together.

**Phase 4 — client. _Done._**
Surface all three figures in the dossier per the disclosure block above.
`coverageFactor()` stays: the live slider path re-weights from raw component
scores in the browser and must still apply the factor itself. Its contract
becomes "apply the same factor the database applies", which is exactly what it
already does — the tests in `evidenceRanking.test.ts` pin it.

## Not doing

- **Storing a risked value per weighting.** Sliders re-weight in the browser;
  persisting a figure per slider position would be a cache of a pure function.
- **Risking the component scores.** Power, water, risk and climate stay pure,
  as they are today. Coverage describes parcel-gate diligence, not the quality
  of the HIFLD or USGS measurement behind a component.
- **A confidence interval.** AACE Class 5 is −50%/+100% and the site-work
  estimate already carries that. A coverage fraction is not a distribution and
  must not be dressed up as one.

## Outcome

Phases 1-3 are live. All four regions were republished and the gate query ran
over 1,338 rows: no NULL measurements, and exactly 2 disagreements — Loudoun
cells `0104` and `0263`, both at 70.00 x 0.995 = 69.65, where numpy's
half-to-even wrote 69.6 and SQL's half-away-from-zero writes 69.7. Both moved
to 69.7 when the generated column took over, deliberately, onto the convention
`worker/parcel_gates.py::_round_half_away` already established.

The divergence is now unreachable rather than corrected: with the worker's
multiplication deleted there is only one implementation of the risking, and it
is the schema's.

Phase 4 is done. The dossier's composite card carries the risked headline
figure, its tier band, and a disclosure line reading `64.8 measured · 66% of
gates decided` (or `screening tier · no parcel survey`). Both figures are
recomputed together from the live slider weights so their ratio is exactly the
coverage factor — pairing a re-weighted score against the *stored* measurement
would compare two different weightings and read as a bug.

Phase 4 also repaired a divergence it exposed. `zoneScoredParcels` was judging
Prime Zone candidacy on the risked figure while the worker clusters on the
unrisked one, and since the browser's zones override the stored ones, Franklin
County's 274 prime cells (unrisked max 81.0) were being re-derived from a
risked max of 62.9 against a threshold of 60 and rendered as almost nothing.
The browser now judges candidacy on the measurement, matching the worker. The
`primeZones` module docstring had claimed this parity all along; it stopped
being true when risking was introduced and nothing caught it, because both
sides still produced plausible output.
