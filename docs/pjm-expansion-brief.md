# PJM expansion — implementation brief

Companion to [`pjm-sourcing-decision.md`](./pjm-sourcing-decision.md), which
settles *where* and *why*. This is *how*, in order, with the traps the first
three adapters found the hard way.

**Read this first: the first county is not the first task.** The engine
currently models one region per **state**, and both Tier 1 candidates sit in
states that already have a live county. Adding either one before Phase 0
lands will delete the county it is joining.

---

## Outcome — first county (Licking) launched 2026-09-10

All five phases are done. Phase 0 re-keyed regions to county slugs and the
sibling promote test proved Franklin survives a Licking publish; the live
acceptance after launch shows both Ohio regions side by side — Franklin
982 parcels / 306 cells / 0.777 coverage, Licking 1,990 parcels / 110
cells / 0.881 coverage, with Loudoun, Taylor and Morrow untouched. The
published run is `1f81e412-728e-46ce-9a1d-aeb26288c425`.

Two traps the plan did not name, both caught by the dry-run and fixed
before publishing:

- The Ohio NWI clip carries a single wetland complex of over a million
  vertices spanning most of the corridor, and the overlap index paid for
  all of them on every parcel under its envelope (~16 s per gate call,
  days for the corridor). `_OverlapIndex.fraction` now intersects each
  candidate with the parcel before any union work (identical answer —
  intersection distributes over union) and explodes multiparts at index
  build; ~150× faster, held against the verbatim reference
  implementation.
- The NWI state cache was the one clip cache without a bbox coverage
  check, so the Licking run served the Franklin-bbox clip and would have
  passed the wetlands gate on unexamined ground east of Franklin. Caught
  from one log line — "cached clip: 13200 polygons", exactly Franklin's
  count, on a bbox the clip does not cover. It now uses the same
  containment-checked cache contract as NFHL, PAD-US and TIGER.

Evidence coverage landed at **0.881**, above the 0.78 the brief expected:
township zoning is published (94.7% of parcels carry a district), and the
power gate decided for every parcel on PJM RTEP area evidence (CONDITIONAL,
4 Board-approved upgrades active in the county area). The dry-run read
0.777 because it runs without database credentials, so the curated
evidence layers read as missing — dry-run coverage is a floor, not a
forecast. Water availability stays UNKNOWN. The follow-up probe found:

- Licking County's own ArcGIS server publishes **no water layer**. The
  `Utilities` folder is ArcGIS plumbing (GeometryServer, printing,
  packaging); `Engineer` holds addresses and tax maps; `Hosted` holds
  surveys and contours.
- The City of **Pataskala** — inside the corridor — publishes public
  utility layers at
  `services7.arcgis.com/koWQgqubB6fcogq8/.../Utility_Layers_Public/FeatureServer`,
  including *Water Service Areas* (layer 18) and *Wastewater Service
  Areas* (layer 40), SR 3729, anonymously queryable; 7 water polygons
  intersect the corridor. It is city-scale, so wiring it would decide
  Pataskala-served parcels and leave the rural townships UNKNOWN —
  honest but partial, and worth doing alongside a county-scale source.
- **Columbus Public Utilities**, which serves the New Albany/Etna edge,
  publishes no service-area boundary on its open-data portal that the
  probe could find.

Also pending: curating the legislative applications record once
data-center cases exist in the county.

---

## Phase 0 — re-key the region model from state to county

### Why this blocks everything

`ingestion_runs.region_code` holds a state code (`OH`, `VA`, `TX`, `OR`), and
`promote_ingestion_run` scopes its swap by state:

```sql
DELETE FROM public.grid_parcels WHERE state_code = v_state;
...
UPDATE public.land_parcels lp SET is_active = FALSE
WHERE lp.state_code = v_state AND lp.is_active AND NOT EXISTS (...stg...);
```

Publishing Licking County, OH would therefore **delete every Franklin County
screening cell and deactivate all 982 Franklin parcels** — atomically, in a
run that reports success. The promote is transactional, so nothing would look
broken; the region would simply be gone, and the only recovery is a Franklin
republish.

This is not a corner case. Both Tier 1 counties collide:

| new county | collides with |
| --- | --- |
| Licking County, OH | Franklin County, OH (982 parcels, 306 cells) |
| Prince William County, VA | Loudoun County, VA (2,478 parcels, 306 cells) |

### What changes

A stable region key — recommend `region_code` becoming a slug such as
`OH-FRANKLIN`, `OH-LICKING`, `VA-LOUDOUN`. `grid_parcels` already carries
`county_name`, so the data is present; only the scoping is wrong.

| location | change |
| --- | --- |
| `promote_ingestion_run` | scope the `DELETE`, the `is_active` sweep and the count rollup by region key, not `state_code` |
| `grid_parcels` / `stg_grid_parcels` | add `region_key`, backfill from `state_code` + `county_name`, index it |
| `land_parcels` | same; the `is_active` sweep is the dangerous one |
| `ingestion_runs.region_code` | now the slug; the `superseded` update already scopes by it, so it follows automatically |
| `worker/pipeline.py:51` `REGION_PRESETS` | key by slug; bbox and county label move inside |
| `worker/pipeline.py:83` `PARCEL_PILOTS` | key by slug (currently `"OH" → "Franklin County, OH"`) |
| `worker/pipeline.py:463` adapter branch | dispatch on slug, not `state_code == "OH"` |
| `worker/overlay_layers.py:64` `COUNTY_FIPS` | key by slug — it is genuinely per-county (TIGER/Line is a county file) |
| `.github/workflows/data_pipeline.yml` | `--state`/`--county` inputs become one region input, or derive the slug from both |
| `client/src/lib/regions.ts` | `REGIONS` and `HOME_REGION` become slugs |
| `client/src/app/page.tsx` | `selectedState` → `selectedRegion`; `fetchGridParcels(500, code)` filters on the new key |

State-keyed **layer caches** (`_padus_cache`, `_nwi_cache`, `_tiger_cache`)
stay keyed by state — those artefacts really are per-state, and two counties
in one state should share them. Do not re-key those; it would restore the
per-county download cost this project spent a release removing.

### Acceptance

Publish Licking, then confirm Franklin is untouched:

```sql
select region_key, state_code, county_name,
       count(*) filter (where is_active) as parcels
from land_parcels group by 1,2,3 order by 1;
-- expect OH-FRANKLIN 982 and OH-LICKING > 0 side by side
```

Add a worker test that a promote scoped to one region leaves a sibling
region's rows alone. This is the single most expensive regression available
in the codebase and currently nothing guards it.

---

## Phase 1 — the cadastre probe (gating, ~30 minutes)

Do not write an adapter before this passes. All three existing counties
needed a *different* ingestion shape, and Morrow County, OR was blocked
outright, so the probe is what stops a week being spent on an impossible
county.

Endpoint (verified live, this session):

```
https://gis.lickingcounty.gov/server/rest/services/Auditor/Parcels/FeatureServer/0
```

Answer all five in writing before proceeding:

1. **Geometry + identity.** Is there a parcel id that is unique and non-null
   across the bbox? *(Taylor County returned `PROP_ID = 0` on 124 parcels,
   which would have collapsed ~9,500 acres into one row. Franklin returned
   non-parcel features — `VNP-WATER`, railroads — sharing placeholder ids,
   which would have scored rivers as developable land.)*
2. **Acreage.** Which field, and in what unit? *(Franklin's legal-acres field
   carries acres on some rows and square feet on others — 367 of 993. Check
   the ratio of stated to mapped area per row, never in aggregate.)*
3. **Assessment.** Inline on the parcel feature (Franklin) or a separate join
   (Loudoun's XLSX roll)? If separate, is it obtainable at all?
4. **Paging.** Does the service page reliably at 1,000, and does it enforce
   `maxRecordCount`? *(Franklin needed per-page retries — one bad page was
   killing whole runs.)*
5. **Zoning.** Published as a layer, or absent? Absent is acceptable and
   yields `UNKNOWN`; do not invent a mapping.

Record the answers in `docs/`. A "no" on 1 or 2 is a stop-loss: log it and
move to Prince William.

---

## Phase 2 — the adapter

One adapter, one contract. Copy `worker/franklin_api.py`, which is the
closest shape (ArcGIS FeatureServer with assessment inline).

`fetch_all(min_lon, min_lat, max_lon, max_lat, min_acres)` returns exactly:

```python
{"parcels": gdf_or_none, "zoning": None, "wetlands": None, "nfhl": None}
```

`wetlands` and `nfhl` are `None` **by design** — the pipeline fetches the
national layers itself. A county mirror only wins where the county actually
publishes one.

Non-negotiables, each of which is a defect this pipeline has already shipped:

- **A missing layer returns `None`, never an empty frame or a default.** The
  engine records `UNKNOWN`; nothing else is acceptable.
- **Guard duplicate ids before staging.** `ON CONFLICT DO UPDATE cannot
  affect row a second time` is what this looks like in production, and it
  arrives after a complete run.
- **Reconcile acreage against geometry per row**, following
  `franklin_api._reconcile_legal_acreage`. A row agreeing with neither
  reading is left null — GIS acreage is measured from the polygon regardless.
- **No NaN reaches a staged row.** Use `_num` / `_json_safe`. This is the
  most-repeated defect in the project's history: three separate times, each
  killing a publish after a full run.
- **Nothing is keyed on `state_code` inside the adapter.** After Phase 0 that
  is no longer a unique region identifier.

---

## Phase 3 — wiring and configuration

1. `REGION_PRESETS["OH-LICKING"]` — bbox, county label, `grid_operator: "PJM
   Interconnection"`.
2. `PARCEL_PILOTS["OH-LICKING"] = "Licking County, OH"`.
3. Adapter dispatch in `pipeline.py` (~line 463).
4. `COUNTY_FIPS["OH-LICKING"] = "39089"` for the TIGER/Line road fallback.
5. `cost_assumptions` rows for the new jurisdiction. **Both keys**:
   - `site_prep` — copy Franklin's v1 params verbatim; the unit costs are not
     jurisdiction-specific, but the row must exist or site prep prices at
     nothing.
   - `land_use_rollback` — Ohio Revised Code 5713.34, 3 years, $1.50 per
     $100, same as Franklin. **Do not reuse Franklin's row**: the jurisdiction
     column is what keeps Virginia from being described using Ohio's statute,
     and the test suite asserts exactly that.
   - The unique constraint is on `(key, version, jurisdiction)`; a new
     jurisdiction may reuse `v1`.
6. `client/src/components/LayerControls.tsx` — add the parcel-source caption.
   The current `PARCEL_SOURCE` map is keyed by state and will need the same
   re-keying as everything else.

---

## Phase 4 — verification before publishing

Run in this order. The dry-run is free; the publish is not.

```bash
cd worker && python -m pytest -q            # 149 tests, offline
python pipeline.py --region OH-LICKING --dry-run
```

Then read the dry-run's own report rather than assuming:

- `Qualification complete: {...}` — check `zoning_coverage_pct`, every
  `*_layer` key, and `slope_sampled_ok` against parcel count.
- Evidence coverage should land near **0.78** (7 of 9 gates decidable:
  all federal layers plus RTEP and queue; zoning and water unknown until
  probed). Materially lower means a layer silently failed.
- Spot-check three parcels end to end: one expected `PASS`, one `FAIL`, one
  `UNKNOWN`, and confirm each rationale cites a real source.

Only then publish, and immediately re-run the Phase 0 acceptance query to
confirm Franklin survived.

---

## What is already free

Do not build these; they are national and working:

FEMA NFHL (floodway, every US county) · PAD-US 4.0 (protected land, per-state
geodatabase) · NWI (wetlands, per-state) · 3DEP (slope, now cached per
envelope) · TIGER roads (with the TIGER/Line county fallback for when the
Census WAF blocks the runner) · PeeringDB (interconnection) · PJM RTEP and
queue (Licking is PJM, so power diligence carries over unchanged — unlike
Taylor County, which is ERCOT and holds `power_capacity` UNKNOWN on all
3,240 parcels).

## Order of work

| # | task | gate |
| --- | --- | --- |
| 0 | re-key region model, state → county | sibling-region promote test passes |
| 1 | Licking cadastre probe | all five questions answered in writing |
| 2 | adapter | returns the four-key contract; duplicate-id guard present |
| 3 | wiring + `cost_assumptions` rows | dry-run reaches qualification |
| 4 | dry-run review, then publish | Franklin still intact afterwards |

Phase 0 is the only one that touches live data for an existing region. It
deserves its own commit, its own test, and a Franklin republish standing by.

---

## Follow-up — the Licking water gate

**Recommendation: do not wire Pataskala as a standalone task.** The work it
requires — parameterising the water provider — is already on Prince William
County's critical path, since PW has its own Service Authority. Do the
refactor there, where it decides a whole county, and Pataskala becomes a
configuration entry rather than a bespoke job.

### What is already safe

The dangerous failure is prevented by the existing gate. `FAIL` fires only
where a parcel sits at or above the pass threshold inside an explicit
*NOT-served* polygon the utility itself published; every other uncovered
case falls through to `UNKNOWN`. Loudoun's 1,853 water FAILs are Loudoun
Water declaring non-service, not the engine inferring it from absence.

Pataskala publishes no not-served polygon, so wiring it would yield
PASS/CONDITIONAL inside the city and UNKNOWN across the rural townships.
Partial coverage is the established shape, not a new compromise — Loudoun
already ships 50 UNKNOWN parcels where incorporated towns run their own
municipal providers.

**Do not "improve" this later by treating absence from a service layer as
evidence of non-service.** A parcel outside Pataskala's polygons may be
served by Columbus Public Utilities, by a township district, or by a well.
The engine does not know which, and `UNKNOWN` is the only honest answer.

### The actual hazard: the provider is hard-coded

`water_evidence.py` carries a single `WATER_SERVICE_AREA_URL`, and every
rationale in the water gate names Loudoun Water in its text. Wiring a second
utility without parameterising both would give Ohio parcels a rationale
reading "Inside Loudoun Water's published service area" — the same class of
error as describing Virginia with Ohio's statute, which the test suite
guards for `cost_assumptions` and does not currently guard for water.

Required before any second water source:

1. **Provider becomes data, not prose.** Region config supplies the utility
   name and endpoint; the gate interpolates it. No rationale names a
   provider the region does not use.
2. **Normalise to the existing column contract** — `area_name`,
   `service_type` (`W` / `WW` / `Both`), `comment`. Pataskala publishes
   water and wastewater as *separate layers* (18 and 40) where Loudoun uses
   one layer with a type column, so the adapter emits `W` rows from one and
   `WW` rows from the other. It does not need to compute `Both`: the engine
   derives serving and wastewater-serving sets independently.
3. **A missing `comment` field is `None`, never an empty string.** The
   no-new-connections branch reads that text; an empty string would read as
   a utility that said nothing, which is true, but only by accident.
4. **Add the provider-attribution test** alongside the existing statute test
   in `test_underwriting.py`: two regions, two utilities, and neither
   rationale naming the other's.

### Gate the decision on a measurement

Nobody has counted how much this buys. Before any implementation, intersect
Pataskala's 7 corridor polygons against the 1,990 Licking parcels:

- **~40 parcels decided** moves coverage 0.881 → ~0.883. Not worth a
  standalone task; fold it into the Prince William refactor.
- **~400 parcels decided** is a different conversation and may justify doing
  it first.

Report the number before writing the adapter. The same probe should check
whether any Licking township or the Southwest Licking Community Water and
Sewer District publishes a county-scale boundary — a county-scale source
would supersede this question entirely.

### The measurement, taken 2026-09-10

Both questions answered. Overlaps computed exactly as the gate does —
≥50% of parcel area inside a serving polygon, EPSG:3735, against the
1,990 published OH-LICKING parcels.

| source | polygons | parcels decided (≥50%) | any overlap |
| --- | --- | --- | --- |
| Pataskala city, `Utility_Layers_Public` layer 18 | 7 | **31** | 59 |
| **LRWD joint, `Water_Service_2021_view`** | 19 | **308** | 311 |

The county-scale source exists. The Southwest Licking district — renamed
**Licking Regional Water District** in 2024 — publishes
`Water_Service_2021_view` on its own ArcGIS org
(`services3.arcgis.com/iHpkStKZmEoDkIuv`): a joint water service-area
boundary for *SWLCWSD and the Pataskala Utility Department together*,
dated June 2021, with a companion `Waste_Water_Service_2021` sewer layer.
It is the only service-area boundary in the org's 17 items — the
district's live water and wastewater web maps carry mains, hydrants,
plants and tanks but no boundary — so 2021 vintage is what exists. Its
`Name` field carries `SWLCWSD` / `Pataskala Utility Department` /
`Joint`, which maps to `area_name`; `service_type` is a constant `W` from
config and `comment` is genuinely absent, so requirement 3 (None, never
"") is exercised for real on this source.

Reading the numbers against the gate above:

- Pataskala alone lands in the **fold-into-Prince-William** bucket, and
  is subsumed anyway: the joint layer already contains the city, so if
  Licking gets a water source it should be the joint layer, not layer 18.
- The joint layer decides **308 parcels** — 77% of the ~400 threshold,
  from a district+city boundary rather than a city one. It does not
  un-gate the refactor: the rationales still hard-code Loudoun Water,
  `water_evidence.py` still carries a single URL, and the column
  contract still needs the `area_name` / `service_type` / `comment`
  normalisation. But it changes the payoff of the Prince William PR from
  "one county plus a fraction of another" to "one county plus 308 Licking
  parcels decided by one config entry" — enough that Licking's water
  config belongs in that same PR, not queued behind it.
- Coverage would move 0.881 → ~0.898; the corridor's north and east
  townships stay UNKNOWN (the 2021 boundary covers the Etna/Pataskala/
  West-Licking quadrant only). The staleness is a disclosure item for
  the rationale, not a blocker: the boundary is the utility's own most
  recent published statement of what it serves.

### Decision (measured)

Licking's water entry ships **in** the Prince William refactor PR, not behind
it. One seam decides a Virginia county plus 308 Licking parcels; splitting
them writes the same code twice. Coverage 0.881 → 0.899, verified:
1,990 x 9 = 17,910 gates, unknowns 2,126 → 1,818.

Use the LRWD joint boundary, not the Pataskala city layer — the joint layer
contains the city and decides 308 parcels against 31.

Two refinements to the requirements above, both found in the measured data:

**1a. Provider is row-level data here, not just region-level.** Requirement 1
assumed the region names one utility, which is true for Loudoun (provider
fixed, `area_name` a sub-zone) and false for this layer. The LRWD layer's only
attribute is `Name`, holding `SWLCWSD` / `Pataskala Utility Department` /
`Joint` — that is *which utility operates that polygon*, not a zone label.
Mapping `Name` → `area_name` while setting provider to the district would
attribute Pataskala-operated parcels to LRWD. Provider resolves from the row
where the layer encodes it, and falls back to the region's configured utility
where it does not.

**1b. `layer_edited` must never be silently null.** The rationale cites
"utility boundary layer edited {date}", and the vintage is this source's main
caveat, so the date has to appear. If the service exposes no edit timestamp,
record the 2021 vintage from the layer's own name as an explicit dated fact
rather than leaving the clause blank or reading "edited None".

**The vintage is a weaker caveat than it looks, in one direction only.**
Service areas expand rather than contract in a growth corridor, so a parcel
inside the 2021 boundary is almost certainly still served — `PASS` is safe —
while a parcel outside may have been annexed since, which is why `UNKNOWN`
rather than `FAIL` is the correct answer there. The existing gate already
produces exactly this asymmetry; do not tune it away.

---

## Next county — Prince William County, VA

Phase 0 is done, so this is probe → adapter → wiring → verify → publish. The
region key work already lets `VA-PRINCEWILLIAM` sit beside `VA-LOUDOUN`; the
sibling-promote test covers it.

### Read this first: the zoning default is Loudoun's

`constraint_rules` is jurisdiction-scoped and every live county has its own
rows — but the *fallback* is not. `parcel_gates.py` resolves each rule as:

```python
rules.get("zoning_dc_use", {}).get("params", DEFAULT_RULE_PARAMS["zoning_dc_use"])
```

and `DEFAULT_RULE_PARAMS["zoning_dc_use"]` holds **Loudoun's district codes**
— `PDGI`/`PDIP`/`GI`/`IP`/`MRHI` by right, `R1`…`R24`, `C1`, `GB`, `TC`
prohibited. A county that supplies a zoning layer with no `zoning_dc_use` row
of its own does not fail and does not concede UNKNOWN: it silently decides
every parcel against Loudoun's use table.

Two Virginia counties make this concrete rather than theoretical. Prince
William's ordinance uses `A-1`, `R-4`, `M-1`, `M-2`, `PBD`. Hyphenated codes
miss Loudoun's lists and land on the safe UNKNOWN branch — but an unhyphenated
`R4` or `A3` would match, and produce a confident FAIL whose rationale cites
Prince William's ordinance while the verdict came from Loudoun's use table.
The answer might even be right; the reasoning would be borrowed and
unverified, which is the failure this engine exists to refuse.

**Required:** a full `zoning_dc_use` row for `Prince William County, VA`
before the first run that supplies zoning, built from PW's own ordinance use
table. Do not derive it from Loudoun's by pattern-matching district letters.

**Also worth doing:** make the pipeline refuse to qualify a region that
supplies a zoning layer with no matching `zoning_dc_use` rule, instead of
falling back. The fallback is only safe for a county like Franklin whose
adapter returns `zoning: None` by construction.

### Adapter

Portal confirmed: Parcels, a Parcel Ownership Table carrying deed acreage,
and an "Underdeveloped A1 Parcels" layer. Run the five probe questions
unchanged — they have caught something in all four counties so far.

Two PW specifics:

- **Deed acreage lives in a separate table**, so this is the Loudoun shape
  (join) rather than the Franklin shape (inline). Reconcile against geometry
  per row as everywhere else; a row agreeing with neither reading is null.
- **The "Underdeveloped A1 Parcels" layer is a shortlist, not evidence.**
  It is somebody's selection, and the engine's job is to derive that from
  primary data. Use it to sanity-check the run's own output — if the engine
  disagrees wholesale, something is wrong — never as an input to a verdict.

### Wiring

1. `REGION_PRESETS["VA-PRINCEWILLIAM"]` — bbox, county label, `grid_operator:
   "PJM Interconnection"`.
2. `PARCEL_PILOTS["VA-PRINCEWILLIAM"] = "Prince William County, VA"`.
3. `COUNTY_FIPS["VA-PRINCEWILLIAM"] = "51153"` — **verify the FIPS**, do not
   trust it from this brief.
4. `constraint_rules` — the `zoning_dc_use` row above, plus the standard
   eight. Nine rules total, matching Loudoun.
5. `cost_assumptions` — **both keys, and neither copied from Loudoun.**
   - `land_use_rollback`: the statute is statewide (Code of Virginia
     58.1-3237, 5 years) but **the rate is the county's own adopted real
     estate rate**, which is not Loudoun's $0.805. Find PW's adopted rate and
     record it with its source. Copying Loudoun's would price a Prince
     William parcel with Loudoun's tax bill.
   - `site_prep`: unit costs are not jurisdiction-specific; copy the params,
     but the row must exist under PW's own jurisdiction or site prep prices
     at nothing.

### Water — the refactor lands here

Prince William County Service Authority is its own utility, and this PR
carries the Licking entry too (see the decision above). Requirements 1, 1a,
1b, 2, 3 and 4 from the previous section all apply. One seam, two counties:
PWCSA decides Prince William, the LRWD joint boundary decides 308 Licking
parcels, and `water_availability` stops being the gate that never generalises.

### What is free

VA already carries 2,507 RTEP records and Prince William is PJM, so power
diligence, the queue feed and PeeringDB carry over unchanged — unlike Taylor
County, which is ERCOT and holds `power_capacity` UNKNOWN on all 3,240
parcels. All federal layers apply as usual.

### Expected coverage

With zoning published and water wired, Prince William should reach 9 of 9
gates decidable — coverage approaching Loudoun's 0.995 and the highest of any
county at launch. If the dry-run reads materially below ~0.95, a layer failed
silently; read the `Qualification complete` line before publishing, not after.

### Acceptance

Publish, then confirm every sibling survived — Loudoun especially, since it is
the one this county shares a state with:

```sql
select region_key, count(*) filter (where is_active) as parcels
from land_parcels group by 1 order by 1;
-- expect VA-LOUDOUN 2478 unchanged, VA-PRINCEWILLIAM > 0,
-- OH-FRANKLIN 982, OH-LICKING 1990, TX-TAYLOR 3240
```

## Outcome — Prince William launched 2026-09-11

Published as run `cd6e66bd-9be4-4d78-b600-bb0416927f0f`: 961 active parcels,
272 screening cells, 8,649 gate rows, evidence coverage **0.936**. Every
sibling survived exactly as the acceptance table expects — Loudoun 2478
unchanged, Franklin 982, Licking 1990, Taylor 3240.

**The zoning rule held.** District verdicts match the section-by-section
ordinance reading to the parcel: 24 M-1 (DCOZ) and 27 other overlay-tagged
districts PASS by right (51 total by-right, as measured beforehand), the
plain M-1 (6), M-2 (10) and their office/B-1/MXD-U kin read CONDITIONAL
(special exception, 36 total), A-1 FAILs 537, and the deliberately
unmapped codes stayed UNKNOWN rather than guessed — PMD 11 (land-bay
designations the layer does not carry), the C-variants and FED/CTY
placeholders 67, TWN 6 (towns administer their own ordinances). The
rationale cites the county's own ordinance and says "in this district";
no verdict borrowed Loudoun's use table, whose fallback this release also
refused.

**The honest UNKNOWNs are the rest of the coverage gap.** 487 parcels sit
outside the published water boundary (Prince William Water + Virginia
American comprehensive-plan layers, dated 2017-10, disclosed in every
rationale) — no NOT-served polygon exists, so absence is never
non-service. There is no bulk assessment roll to publish, so value
metrics and the rollback record UNKNOWN by design; the FY2027 $0.865 rate
row exists but cannot fire until deferral values are ever sourced.

**Licking republished at 0.899** (from 0.881) in the same release: the
LRWD joint boundary now decides 307 PASS + 3 CONDITIONAL water verdicts,
attributed row-level with the 2021-06 vintage stated.

### Two incidents the launch surfaced

1. **`runs.py` class split.** `load_rules_readonly` and `_rows_to_rules`
   had been inserted as module-level functions into the middle of the
   `IngestionRun` class body. Python parses that happily (the class's
   trailing methods become nested locals of the module function), and the
   suite stayed green because nothing tested the class surface. The first
   publish to run since (the Licking republish) failed at Step 6c before
   staging anything — atomic promotion meant no partial data reached the
   published tables. Fixed by moving the helpers below the class, plus
   `tests/test_runs_layout.py` pinning the class surface, the helpers'
   module level, and contiguity of the class body.
2. **One NFHL feature can sink a county.** FEMA's service 500s
   deterministically on any GeoJSON query returning one Prince William
   flood-hazard feature with pathological coordinate precision — at any
   paging depth, with or without outSR, in both formats (an Ohio control
   query with identical parameters returns 200). The tiler subdivides on
   failure, but no subdivision can exclude a feature that lies inside it,
   so at max depth the whole layer conceded UNKNOWN and the floodway gate
   went dark county-wide. `geometryPrecision=6` (~0.1 m; it rounds the
   serialized output, not the source geometries) returns 200 on the same
   query; it is now pinned onto every page of the NFHL fetch by
   `tests/test_nfhl_query.py`.

Also worth recording: sciencebase.gov (PAD-US manifest) had a full outage
on launch day and recovered; the NWI REST service stayed down and the
official state-geodatabase fallback carried the wetlands gate (21,702
polygons) — the fallback exists for exactly this, and the first download
attempt died at 84 MB before a retry completed it.

---

## Sweep readiness — shipped 2026-09-17

Five changes the 552-county sweep needs before it starts, all landed as
one release. The motivating incident: Taylor County was republished to fix
a wetlands bug, PAD-US was unreachable that afternoon, and the pipeline
degraded honestly — layers missing, protected-land verdicts UNKNOWN — and
promoted anyway, replacing 91 decided verdicts with 4,356 UNKNOWNs. Honest
degradation that cannot be *undone* is only half a design; this is the
other half.

### 1 — promote refuses a coverage regression

Every run now records `stats.layers` — `{layer: "present"|"missing"}` — on
its `ingestion_runs` row before promote. Both tiers, one shape: the parcel
tier takes it from `qualify_parcels`' existing `*_layer` stats keys, the
screening tier from `national_metrics.measure`, which now returns the map
alongside the cell measurements and uses the parcel tier's layer names
(`wetlands`, `slope` — not `nwi`, `3dep`) so a county that gains a
cadastral adapter never reads as losing its screening layers to a rename.

`promote_ingestion_run(p_run_id, p_allow_coverage_regression DEFAULT
false)` (migration `release28_promote_coverage_guard`) compares the map
against the region's live succeeded generation **before the first DELETE**:
a layer that was present and is now missing fails the publish, naming the
lost layers. Verified live against fabricated fixtures (region `ZZ-GUARD`,
created and deleted around the test): the blocked swap leaves the live row
untouched and the run `running`; the override promotes; a first publish
proceeds; adding a layer proceeds; a mapless run against a mapped
generation is refused as missing everything. A legacy generation with no
map is not comparable, so the first publish after this change always
proceeds — which is what lets the map start landing. `--allow-coverage-
regression` on `pipeline.py` is the operator override, never passed by any
scheduled path.

Deliberately narrow: layer **availability** is compared, never gate counts
— counts are not comparable across a rule change, and a difference there
is a correction, not a regression. Carrying the previous generation's
evidence forward was rejected too: it would make the published map a mix of
two runs' answers with no record of which was which.

**Known blind spot, accepted:** a legacy live generation (no map) cannot
protect itself, so a republish of, say, OH-LICKING while PAD-US is
unreachable would degrade its protected-land evidence *and record the map
as if that were normal*. That is exactly why the parcel-region recovery
republishes (Licking, Delaware's three, Taylor) stay **blocked until
ScienceBase answers** — see the PAD-US note below — and why the sweep's
first guarded generation matters more than any single republish.

### 2 — `pjm_screening.py --incomplete`

Recovery, derived from published data like progress itself: selects
counties whose live succeeded run has any layer marked missing in
`stats.layers`, instead of counties with no cells. No retry file to drift
or forget; `--list` shows the batch; `--redo` is ignored in this mode —
recovery is for the degraded, not the bored. A run from before the map
existed is *not* incomplete (it predates the record); the coverage guard,
not recovery, handles those at promote time. Reads with whatever key is
available, ordered paging, at most one succeeded run per region so "the
live one" is well-defined.

### 3 — `.github/workflows/pjm_screening.yml`

`workflow_dispatch` per state (`state`, `limit`, `dry_run`), mirroring
`data_pipeline.yml`'s conventions: one `PUBLISHING` env both sides derive
from, the service key withheld on a dry run, the anon key always present,
worker unit tests before any network fetch, Census **and PJM footprint**
caches warmed before batch selection, and a per-state concurrency group
(the same state never races itself; different states may overlap).
Deliberately **no `actions/cache` for the geospatial archives**: the state
geodatabases run to hundreds of MB each and ~400 GB across the footprint,
far past the cache service's limits — the on-disk per-state geodatabase
cache in `worker/cache/gdb` already gives the reuse that matters, one
download per state per run. The runner exits non-zero only when every
county in the batch failed, which is its systemic-problem signal; one
county's outage just leaves it for the next batch.

### 4 — PAD-US URLs resolved once per state, ever

The ScienceBase release manifest now answers datacenter IPs with a
Cloudflare 403. PAD-US 4.0's download URLs are stable for the life of the
release, so `_padus_state_url` consults a JSON cache beside the geodatabase
cache (`worker/cache/gdb/padus_urls.json`) and persists every URL it
resolves; the manifest is never re-asked for a state it has answered. The
failure path is unchanged and nothing attempts to defeat the bot check — a
workaround is the kind of thing that gets an IP range blocked for humans
too. A state whose URL was never resolved and whose manifest read fails
still reads as a missing layer, the gate stays UNKNOWN, and the coverage
guard keeps that from silently replacing decided evidence. **Re-check
ScienceBase reachability before the sweep** (backlog): the sweep's
screening counties degrade honestly without PAD-US, but every degraded
publish lands on the `--incomplete` list for recovery the moment it exists.

### 5 — surveyed vs screened in the region selector

After the sweep the region list stops being a list: `filterRegions`
(`client/src/lib/regions.ts`) owns one rule shared by both surfaces —
surveyed counties (`active_parcels > 0`) by default, in region-key order;
everything else behind the selector's search box, surveyed matches ranked
first; screening-only entries badged `screening` so a measurement never
masquerades as a survey. The native `<select>` in both the desktop header
and the mobile pill became one `RegionSelect` component (search,
keyboard/arrows, outside-press close, the home region never stranded) — a
552-option dropdown buries the ten counties that were actually diligenced,
which was the same defect as the old hand-kept region list wearing a
bigger hat.

### Verified live

Morrow OR (screening tier) republished as run
`OR-MORROW-20260917T010420Z-b665`: 748 cells, `stats.layers` landed as
`{wetlands, nfhl, roads, slope: present, padus: missing}` — the manifest
read failed from this network exactly as designed, the run published
(first guarded generation, nothing to compare against), and the map is
live. Two notes worth keeping:

- The promote RPC's HTTP read timed out client-side while the server
  completed it; `fail()` had already marked the run `failed`, and the
  promote's own final `UPDATE` overwrote that to `succeeded`. The end
  state is accurate (it did publish), but the client saw an exception and
  the log said PIPELINE FAILED for a run that went live. A longer
  client timeout on the promote RPC is the obvious fix if it recurs.
- NWI's REST service 500'd for the Morrow bbox and the state-geodatabase
  fallback carried the wetlands gate — the second time that fallback has
  saved a real run, which is the argument for keeping it despite the
  download cost.

### The backfill — maps for the generations that predate them

Migration `release29_backfill_legacy_layer_maps` derived `stats.layers`
for the twelve live generations that predate release28, from the evidence
each run itself left — never from what today's network would answer.
Parcel-tier maps came from the run's own `source_snapshots` rows (the
provenance layer was recording availability all along: a fetch that
answered carries a record_count, one that failed carries NULL and an
"unavailable" note; only the names needed mapping —
`county_subdivisions`→subdivisions, `utility_territories`→utility,
`rtep_upgrades`→rtep, `pjm_queue`→queue, `water_service_areas`→water).
`restrictions`, a database read with no snapshot row, was derived from the
moratorium gates' distinctive unavailable-rationale literal. Screening-tier
maps came from the cells' `federal_metrics` keys, since `measure()` writes
a layer's key whenever it answered. Layers with no evidence either way are
omitted, not guessed.

Every known truth reproduced: Taylor `padus: missing` (the incident) plus
the three ERCOT-structural misses; the Delaware three fully present (they
published before the ScienceBase challenge); Licking's water present; the
curated applications record present only where it is actually curated
(Loudoun, Prince William). The guard protects 13 of 13 live generations
now, not 1 of 13.

### The loop closed, on real counties

Recovery pass, 2026-09-17, both degraded regions restored through
`--incomplete --state`:

- **OR-MORROW, 6.9 minutes.** All five layers present, `padus: missing` →
  `present`; all 748 cells now carry `protected_pct` (and all nonzero — a
  county of refuges and tribal lands), where the degraded generation
  carried none.
- **TX-TAYLOR, 15.9 minutes.** `protected_land` decided again on every
  active parcel: 4,317 PASS + 39 FAIL, from 4,356 UNKNOWN. PAD-US resolved
  through the direct file route and the TX geodatabase is cached for the
  state.

Morrow's first guarded run had taken ~3 hours, and the question was
whether that was the real per-county cost. It was the cold start: the OR
NWI geodatabase and the OR PAD-US geodatabase, each downloaded once and
now cached. The restore — warm NWI, warm slopes, one new PAD-US archive —
ran in minutes. Hours is a cold-cache western-county property, not a
per-county property.

### The recovery list is a fact, not a queue

After the restores, `--incomplete` still lists seven regions — and every
one of them is a **structural** absence, not a degraded one: ERCOT has no
RTEP or queue artifacts (Taylor), no water source is wired for Taylor, and
no legislative-applications record has been curated for the Ohio counties
or Fauquier. Re-running them would publish identical state and put them
straight back on the list. The list says "these published with a layer
missing" — which is true, and stays true, and is exactly why it is scoped
by the operator with `--state` rather than treated as work to drain. A
future refinement, if the list's noise ever costs more than its honesty:
record why a layer is missing (outage vs. absent-by-structure) beside the
mark, and let recovery select only the outage kind. Not done now — the
sweep's screening counties carry only the five federal layers, so their
recovery list stays clean without it.


