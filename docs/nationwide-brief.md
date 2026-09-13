# Nationwide on the six free gates

Six of the engine's ten gates already decide from federal data and need no
local research: **contiguous acreage, wetlands, protected land, floodway,
road access, slope**. The other four — zoning, water, power capacity,
moratorium — need a human to read an ordinance, a utility boundary, an RTO
queue or a township's minutes, and no amount of code removes that.

So the national product is not "everything, everywhere". It is every county in
America decided on six gates, with the other four honestly UNKNOWN, ranked
below anywhere actually diligenced. The machinery for that already exists:
lexicographic evidence tiering means an unreviewed county can never out-rank
Loudoun, `evidence_coverage` prices it down, and `none_found` distinguishes
"checked, clear" from "nobody looked".

What follows is what has to change first. Two of the four blockers were found
by measuring rather than assuming, and both are invisible at six regions.

---

## Blocker 1 — a national parcel source

Five of the six free gates are federal layers. The sixth,
`contiguous_acreage`, needs the cadastre, and the cadastre is the thing this
project has built one county at a time.

Three counties needed three different adapters and a fourth (Morrow, OR) was
impossible at any effort. That is the empirical case for licensing rather than
scraping — settled in `pjm-sourcing-decision.md`, unchanged here. **One
national adapter replaces the per-county adapter problem for this gate
entirely**, which is the single largest simplification available.

It is also a purchase, not an engineering task. Everything below is worth
doing regardless of which vendor is chosen, because none of it depends on the
vendor.

## Blocker 2 — slope does not scale, and this is the hard one

3DEP `getSamples` is **one HTTP request per parcel**. Measured on Loudoun's
2,478-parcel cold run: 265 s on 12 workers, or 9.4 parcels/sec.

| scope | parcels | one full pass |
| --- | --- | --- |
| today, 6 regions | 9,651 | 17 minutes |
| one PJM state | ~400,000 | **12 hours** |
| national, ≥20 acres | ~10,000,000 | **12.4 days** |

The envelope cache makes re-runs nearly free, which is why this has never
hurt — but the first pass over a new county is always cold, and at national
scale the first pass never ends.

**Re-engineer it tile-first.** 3DEP publishes 1/3-arcsecond DEM tiles (roughly
1° × 1°). Download the tiles covering a county once, compute slope for every
parcel in them locally with numpy, and the per-parcel network call disappears.
One download serves thousands of parcels instead of one request serving one.
The existing per-envelope cache stays as the fallback for gaps.

This is the only gate of the six that does not already scale, and it is worth
doing before any vendor decision: it makes even a single-state rollout
practical.

## Blocker 3 — metric history grows without bound

`parcel_metric_values` holds **3,292,581 rows for 9,651 parcels**. Only
**377,698 of them — 11.5% — belong to current runs.** The other 88.5% is
superseded history from 43 runs, and nothing removes it.

`promote_ingestion_run` deletes by `run_id` and re-inserts for that run, so
each republish adds a full generation and removes nothing. That is 1.6 GB
today against roughly 190 MB of live data.

Nobody decided to keep it. It is a side effect of the promote's shape, and it
is genuinely useful — "what did we know on this date" is exactly this
project's discipline — but unbounded is not a retention policy. At 341 metrics
per parcel:

| scope | rows per full run |
| --- | --- |
| today | 3.3 million |
| national, ≥20 acres | **3.4 billion** |

Multiply by weekly runs with no expiry and the arithmetic stops working long
before nationwide.

**Decide a policy.** Options, cheapest first: keep N generations per region;
keep only runs a `parcel_decision` fingerprint references (decisions already
pin the evidence they were made against, so this preserves exactly the history
that is load-bearing); or archive superseded generations out of the hot table.
The middle option is the one that fits what the engine already promises.

## Blocker 4 — the region model is hand-maintained

`REGION_PRESETS` carries a hand-written bbox per county and `COUNTY_FIPS` a
hand-written FIPS. Six entries is fine; 3,143 is not a list anyone maintains.

Derive both from the Census county layer — the same TIGER service already used
for roads, places and county subdivisions. A county becomes a region by FIPS,
its bbox comes from its own geometry, and adding coverage stops being an edit
to a Python dict.

The weekly cron already reads its region list out of `REGION_PRESETS`, so this
change carries the refresh with it.

---

## What does not need to change

Worth stating, because it is most of the system:

* **Region scoping.** `region_key` already isolates publication per county;
  3,143 regions work exactly as 6 do. The re-key that let two Ohio counties
  coexist is the same mechanism.
* **Per-state layer caches.** PAD-US, NWI and TIGER are already
  state-parameterised and shared across counties in a state.
* **The evidence model.** UNKNOWN, coverage weighting, lexicographic tiering
  and rule provenance were built for exactly this: publishing honestly
  incomplete coverage without letting it out-rank real diligence.
* **The gates themselves.** Six of ten need no jurisdiction input at all.

## Expected result

A county with no local research decides 6 of 10 gates — coverage near 0.6
against Loudoun's 0.995 — and ranks below every diligenced county by
construction. That is a real answer, not a placeholder, and it says precisely
what it does not know.

## Order

| # | task | depends on |
| --- | --- | --- |
| 1 | tile-first slope | nothing — do this first, it unblocks any rollout |
| 2 | metric retention policy | nothing |
| 3 | region model from Census counties | nothing |
| 4 | partition `parcel_metric_values` / `parcel_gate_results` by region or run | 2 |
| 5 | national parcel adapter | a licence |
| 6 | progressive rollout, PJM footprint first | 1–5 |

Items 1–4 are prerequisites regardless of vendor and can start immediately.
Item 5 is a purchase.
