# PJM expansion — implementation brief

Companion to [`pjm-sourcing-decision.md`](./pjm-sourcing-decision.md), which
settles *where* and *why*. This is *how*, in order, with the traps the first
three adapters found the hard way.

**Read this first: the first county is not the first task.** The engine
currently models one region per **state**, and both Tier 1 candidates sit in
states that already have a live county. Adding either one before Phase 0
lands will delete the county it is joining.

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
