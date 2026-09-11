# Prince William County cadastre probe (Phase 1)

Answers to the five questions in [`pjm-expansion-brief.md`](./pjm-expansion-brief.md),
from live queries against the county's ArcGIS Server on 2026-09-11.
**Verdict: four of five pass. The fifth — assessment — has no bulk
publication anywhere in the county's GIS or open data; the roll is
per-parcel on the Assessor's web portal. Gates are unaffected (the
roll-back exposure is a metric, not a gate), but PW's assessed-value
metrics will record UNKNOWN rather than a number.** Every number below is
from the services themselves, not from documentation.

Cadastre endpoint (nightly Real Estate Assessments CAMA join on the parcel
polygons — "Parcel CAMA Public" / AGOL "Parcel Ownership Table"):

```
https://gisweb.pwcva.gov/arcgis/rest/services/GTS/CAMA_Parcels/MapServer/4
```

ArcGIS Server 10.91, geometry `esriGeometryPolygon`, SR **2283** (Virginia
State Plane North, US feet — every query must pass `outSR=4326`),
`OBJECTID` + `GlobalID`, `maxRecordCount: 2000`, `supportsPagination: true`,
158,482 features.

---

## 1. Geometry + identity — PASS

- **`GPIN` (string, 15, e.g. `7302-03-9126`) is the parcel id.** 155,770
  distinct values across 158,482 features, and **the only duplicated value
  is the placeholder `9999-99-9999`** — 2,712 right-of-way slivers that
  identify themselves (`TaxMapNumber = 'ROW'`, no acreage, no use code, no
  owner). Filter `GPIN <> '9999-99-9999'` and every remaining GPIN is
  unique. This is Franklin's VNP-WATER trap in a milder form, and it
  self-labels.
- **`TaxMapNumber` is not a pin** (70,778 duplicates — condominium units
  share their parent map number); `CAMA_MAPBLOLOT` is the same story.
- `ParcelRecordationStatus` ('Active'), `ParcelType`, `DataSource` are
  present; `CAMA_USECODE` carries real three-digit REA property classes
  (105 codes county-wide; among ≥20-acre parcels: `971`×204, `092`×107,
  `911`×90, `011`×87, `813`×72 …).

## 2. Acreage — PASS (inline — Franklin's shape, better than the brief expected)

The brief expected deed acreage in a **separate table** (Loudoun's join
shape). In fact the nightly join puts every acreage figure **inline on the
parcel feature**: `CAMA_DeedAcre` (deed), `CAMA_TaxAcreage1`/`2` (tax
roll), and `Acreage`. On 21,777 rows where both exceed 1 acre, `Acreage`
and `CAMA_DeedAcre` agree within 2% for all but 321 (1.5%). No second
fetch, no join, no square-feet contamination (ratios would sit near
43,560; none do).

- ≥20-acre parcels: **962** county-wide (by `Acreage`, envelope
  `(-77.75, 38.49, -77.20, 38.96)`).

## 3. Assessment — NO BULK PUBLICATION (measured, not assumed)

- No GIS layer, hosted service, or open-data extract carries assessed
  values. The CAMA join publishes owner, deed acreage, use code and
  living area — **deliberately not values** (the county sells the full
  roll: "Parcel ownership and recordation information … can be purchased
  separately from the Office of Real Estate Assessments").
- The roll as published to the public is **per-parcel** at
  `pwc.publicaccessnow.com` — an Aumentum portal (Quick / Address / GPIN /
  Sales search) whose pages are ASP.NET postbacks. A per-GPIN adapter
  (~962 postbacks with `__VIEWSTATE` round-trips) is feasible later but
  fragile, and is **not** in this PR.
- Land-use (use-value) deferral enrollment is also not distinguishable
  from the CAMA layer — no deferral flag, no use-value column.
- **Consequence:** PW parcels carry no assessed-value metrics and no
  `land_use_rollback_tax_usd` estimate (the model refuses to price from
  nothing). This does not touch gate coverage: the roll-back is an
  estimated *metric* in the underwriting block, gated behind
  `assessed is not None`. Unknown stays unknown; nothing is borrowed.

## 4. Paging — PASS

- Pages at **2,000**, `resultOffset` honored, `supportsPagination: true`.
  The ≥20-acre set is one page (962; a request at offset 2,000 returns
  empty). `f=geojson` works; an `inSR=4326` envelope against the 2283
  layer with `outSR=4326` works.
- `exceededTransferLimit` is **not set** on partial pages — the adapter's
  existing break condition (`len(feats) < page_size`) is the one that
  fires; the Franklin retry pattern applies unchanged.

## 5. Zoning — PUBLISHED, one county-wide layer, measured 100% coverage

`Planning/Zoning/MapServer/5` "Zoning Districts": **2,230 polygons**, a
single county-wide layer with `ZoningDistrict` (the code),
`ZoningCaseName` / `ZoningCaseNumber`, `PROFFERS`, and a per-feature
`last_edited_date` (2025 edits present — current, unlike the 2017
comprehensive-plan water layers).

- **31 distinct codes** (polygon counts): B-1 459, R-4 367, A-1 207,
  SR-1 138, M-1 136, PMR 123, R-16 99, M-2 98, R-6 92, RPC 65, O(L) 61,
  PBD 57, M/T 50, SR-5 44, PMD 43, R-4C 41, R-2 32, O(M) 20, B-2 20,
  SR-1C 15, FED 12, O(H) 11, R-2C 10, R-30 8, O(F) 6, **TWN 4**, A-1C 4,
  V 3, B-3 2, CTY 2, MXD-U 1.
- **Measured against the candidates: 962/962 ≥20-acre parcels' representative
  points fall inside a zoning polygon — 1.000 coverage**, better than the
  brief's ~0.95 expectation.
- Two caveats the wiring must encode:
  - **Towns are mapped as `TWN`, not as their own districts** (Dumfries,
    Occoquan, Haymarket, Quantico). Municipal parcels must read UNKNOWN —
    `TWN` belongs in the `unknown_jurisdiction` list, never a guessed
    class. Same for `V`, `FED`, `CTY` if they carry no use-table entry.
  - The layer has **no district-name field** (the name field holds the
    rezoning *case* name). `zone_name` must come from the wiring's own
    code→name map built from PW's ordinance — the same document the
    `zoning_dc_use` row comes from. Never `ZoningCaseName`.
- Context, not gate inputs: `Planning/Zoning/7` "Overlay District Data
  Center Opportunity Zone" and `/2` "Overlay District Technology
  Subdistricts" exist and are worth citing in the region brief, but the
  gate reads the base districts. **"Underdeveloped A1 Parcels"
  (`Planning/Build_Out_Analysis/2`) stays a sanity-check shortlist only,
  per the brief — never an input.**

---

## Extra facts worth recording

- **FIPS verified: 51153** — from the Census 2020 ANSI county reference
  (`VA|51|153|Prince William County`), matching the brief's value.
- County envelope (from the parcel layer): −77.757 … −77.204 lon,
  38.495 … 38.950 lat. Candidate survey bbox:
  `(-77.76, 38.49, -77.20, 38.96)` → **962 parcels ≥20 acres**.
- The plain boundary layer `GTS/Cadastral/2` (159,727 features) is the
  same geometry without CAMA; use the CAMA layer — one query.
- The CAMA join is nightly ("current as close of business the previous
  day"); `RecordedDate` / `LastEditDate` are per-feature columns.
- Water service areas for the same county are already wired
  (`water_evidence.WATER_PROVIDERS["VA-PRINCEWILLIAM"]`, commit 91ed1ff):
  44 polygons, two utilities, dated 2017-10 by the comprehensive-plan
  adoption — every water PASS rationale discloses the planning-map
  provenance.
- The pipeline currently fetches Loudoun's assessment XLSX unconditionally
  (it feeds `assessment_of`, which simply finds no PW pins and returns
  None). Harmless today, but the PW wiring should key the assessment
  fetch by region so a PW run does not record Loudoun's roll as its
  source snapshot.

## Consequences for Phase 2

- Copy `franklin_api.py` (FeatureServer + inline CAMA), not
  `loudoun_api.py`. One layer answers parcels, acreage and use class.
- `pin = GPIN`; query-side filters `GPIN <> '9999-99-9999'` and
  `Acreage >= 20`.
- Legal acreage from `CAMA_DeedAcre`, reconciled against geometry per row
  (`_reconcile_legal_acreage` unchanged).
- Zoning from `Planning/Zoning/MapServer/5`: `zone = ZoningDistrict`,
  `zone_name` from the wiring's ordinance map; `TWN` →
  `unknown_jurisdiction`.
- Assessment stays None for PW — value metrics honestly absent; no
  portal scraping in this PR.
- Page at 2,000 with `resultOffset`, `outSR=4326`, `f=geojson`; break on
  short pages (no `exceededTransferLimit`).
