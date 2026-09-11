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
