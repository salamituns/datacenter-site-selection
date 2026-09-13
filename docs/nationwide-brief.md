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

## Blocker 4 — the region model is hand-maintained — **SOLVED 2026-09-13**

`REGION_PRESETS` carried a hand-written bbox per county and `COUNTY_FIPS` a
hand-written FIPS. Six entries is fine; 3,143 is not a list anyone maintains.

Both are now derived from the Census cartographic boundary file (900 KB, all
3,222 county-equivalents) in `worker/region_registry.py`. `SURVEY_REGIONS` is
reduced to a list of six names; everything geometric comes from the county's
own polygon. Any county in the country runs with `--region`.

**The hand-typed boxes were wrong, and not in one direction.** Measured
against the real county geometry:

| region | county area | outside the typed box | |
| --- | --- | --- | --- |
| VA-LOUDOUN | 519.5 mi² | 66.4 mi² | 12.8% |
| TX-TAYLOR | 919.0 mi² | 291.1 mi² | 31.7% |
| OH-FRANKLIN | 553.0 mi² | 168.3 mi² | 30.4% |
| OR-MORROW | 2,059.0 mi² | 1,475.7 mi² | 71.7% |
| VA-PRINCEWILLIAM | 334.2 mi² | 0.0 mi² | 0.0% |
| OH-LICKING | 690.0 mi² | 307.6 mi² | deliberate corridor |

Four of six claimed a whole county and surveyed part of one. Loudoun's
published parcels stop at -77.8547 and 39.2614 — hugging the typed box's
edges — while the county runs to -77.96 and 39.32. A parcel in that strip
never read UNKNOWN; it was absent, and absence is invisible in a dossier.

Loudoun's box was also too *large* on the east, running to -77.25 where the
county ends at -77.32. Harmless in practice only because the cadastral API is
county-authoritative and refused to serve the neighbours' parcels — the
screening grid had no such protection. Being wrong in both directions at once
is what a typed constant does and a derived one cannot.

Two further defects the derivation exposed:

* **Six region keys collided.** Virginia's independent cities are
  county-equivalents sharing a name with the county beside them — Fairfax,
  Franklin, Richmond, Roanoke, plus Baltimore and St. Louis. Since `promote`
  swaps on `region_key`, two counties sharing one would have overwritten each
  other's parcels with no error raised. Independent cities (Census LSAD 25)
  now carry a `CITY` suffix, and building the cache fails if any key is not
  unique.
* **`grid_operator` defaulted to `"PJM Interconnection"`.** Harmless across
  six hand-listed regions, five of which really are PJM. Across 3,222 it
  would have labelled every unmapped county in the country as PJM. RTO
  footprints do not follow state lines, so the operator is now `None` unless
  explicitly mapped.

The weekly cron reads its region list out of `SURVEY_REGIONS`, so the refresh
still carries with it, and a region outside that list is a `--region` away.

**Not yet republished.** The corrected boxes only take effect on the next run
for each region, which will pull in the previously-missed strips.

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
| 2 | metric retention policy | **done 2026-09-13** |
| 3 | region model from Census counties | **done 2026-09-13** |
| 4 | partition `parcel_metric_values` / `parcel_gate_results` by region or run | 2 |
| 5 | national parcel adapter | a licence |
| 6 | progressive rollout, PJM footprint first | 1–5 |

Items 1–4 are prerequisites regardless of vendor and can start immediately.
Item 5 is a purchase.

---

## Tile-first slope: measured, and it is not a drop-in

Attempted 2026-09-13. The plan above assumed tile-first slope was an
optimisation. It is not — it is a **method change**, and the measurements
below are why.

### What was tried

| approach | result |
| --- | --- |
| Windowed reads from the S3 COG via `/vsicurl/` | **6.8 parcels/sec — slower than the 9.4/sec API.** Cost is per-read HTTP overhead, not block misses; ordering the reads by 512px block made it worse (4.7/sec), so the block-reuse premise was simply wrong. |
| Download the whole 1°×1° tile (489 MB) | Viable only on fast links. 1.37 MB/s measured locally = 6 min/tile, worse than the API for a county the size of Loudoun. CI bandwidth to S3 is likely far better, but this was not measurable from here. |
| `exportImage` bulk raster, chunked | **Works and is fast.** 4096px fails with HTTP 500; 2048px returns 16.8 MB in 4.4 s. Loudoun needs 9 chunks ≈ 40 s against 265 s today, and the cost is O(area) rather than O(parcels) — a county with 50,000 parcels costs the same 40 s instead of 89 minutes. |

So the throughput problem is solved. The correctness problem is not.

### The values do not match, and that is the blocker

Seven Loudoun parcels, comparing stored `getSamples` figures against the
export at native resolution:

| parcel | stored max | tiled max | stored median | tiled median |
| --- | --- | --- | --- | --- |
| 151107395000 | 97.1 | 220.9 | 29.3 | 16.3 |
| 152491104000 | 81.5 | 220.9 | 14.2 | 10.6 |
| 150405648000 | 63.8 | 184.9 | 5.5 | 7.4 |

Reproducing the 32×32 lattice geometry from the raster did not close it
(170.9 against 97.1). Neither did asking the service for a 32×32 export over
exactly the same envelope (152.9 against 97.1) — the same service, the same
extent, the same grid, a different answer.

`getSamples` resolves each sample through a mosaic rule and
`returnFirstValueOnly`, and that behaviour is not reproducible from
`exportImage`. Five experiments failed to match it.

### Why this matters more than the speed

`slope.max_fail_pct = 25` was calibrated against the `getSamples` figure.
Switching method would move every slope value upward — natively-resolved
maxima catch ditches, road cuts and stream banks that a lattice over a large
envelope smooths away — and would fail parcels the engine currently passes,
silently, across all five regions.

That is the change this project refuses to make quietly.

It also raises a question about the **existing** values rather than the new
ones. If `getSamples` is resolving through a coarser overview than the
1/3-arcsecond product, today's slope figures are systematically low, and the
threshold was calibrated against a smoothed measurement without that being
recorded anywhere. Worth establishing before either method is trusted at
national scale.

### Options

1. **Treat it as a method change.** New slope method, thresholds recalibrated
   against it, recorded as a new `constraint_rules` version with its basis,
   all regions republished. Honest and substantial, and it should settle the
   overview question first.
2. **Split by tier.** Keep `getSamples` for diligenced counties and use the
   export-based method for national screening coverage, under its own metric
   key and threshold. This fits the tiering model the engine already has —
   national coverage is explicitly a different, coarser product — and avoids
   changing any verdict already published.
3. **Leave slope out of the national six.** Nationwide becomes five free
   gates with slope UNKNOWN until a county is diligenced. Costs nothing, loses
   a genuinely useful screening signal.

Recommended: **2**, with the overview question answered as its own task. It
gets national coverage moving without touching a published verdict, and the
difference between the two measurements becomes a documented property of the
tiers rather than an unexplained discrepancy.

### Calibration: the thresholds cannot be translated

Attempted on 30 Loudoun parcels with both measurements — the `getSamples`
figures already published, and an `exportImage` raster over the same area:

| statistic | correlation | ratio (DEM ÷ stored) | p10 → p90 |
| --- | --- | --- | --- |
| **max** | 0.731 | 2.32× | **1.28 → 5.67** |
| **median** | 0.907 | 1.24× | 1.02 → 1.83 |

`max` is not convertible. A 4.4-fold spread in the ratio means no constant
carries `max_fail_pct = 25` across to the DEM method, and `max` is precisely
what the FAIL threshold reads. Fitting one anyway would be inventing a
threshold and calling it a translation.

The reason is physical rather than statistical. At 10 m resolution the maximum
over a parcel is decided by its single steepest pixel — a road cut, a stream
bank, a quarry face — so it measures the worst artefact in the parcel rather
than its buildability. The 32×32 lattice smooths those away by construction,
which is why it has served as a screening statistic.

**Median survives the change; max does not.** Correlation 0.907 and a 1.02–1.83
ratio still is not a conversion factor, but median is a robust statistic at
native resolution in a way max is not.

### Revised recommendation

A national screening slope gate should:

* use the **export raster**, which is fast and scales with area;
* decide on **median** slope, not max — at native resolution max measures the
  worst pixel, and screening wants the typical grade;
* carry its **own threshold, set on its own terms**, not derived from 25.
  Note that `slope.max_fail_pct = 25` is itself recorded as project judgement
  with no external authority, so calibrating a new judgement against it
  through a noisy ratio would compound rather than ground it;
* emit under **distinct metric keys** so a screening-tier slope is never
  compared with a parcel-tier one as though they were the same measurement.

This is not a code change waiting to be written. It is a threshold that needs
deciding — what median grade makes a 100+ MW pad uneconomic — and that is the
same kind of judgement call the acreage and road-access thresholds already
are, to be recorded with its basis like them.

**Not shipped.** The engineering is solved and the measurement is understood;
what remains is a number nobody has justified yet, and guessing it would put
an unfounded threshold underneath national coverage.
