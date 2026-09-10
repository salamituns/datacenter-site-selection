# Licking County cadastre probe (Phase 1)

Answers to the five questions in [`pjm-expansion-brief.md`](./pjm-expansion-brief.md),
from live queries against the county's ArcGIS Server on 2026-09-10.
**Verdict: all five pass. Licking is buildable.** Every number below is
from the service itself, not from documentation.

Endpoint (Auditor CAMA-joined parcel layer):

```
https://gis.lickingcounty.gov/server/rest/services/Auditor/Parcels/FeatureServer/0
```

ArcGIS Server 11.4, geometry `esriGeometryPolygon`, SR **3735** (Ohio State
Plane North, US feet — every query must pass `outSR=4326`), `OBJECTID` +
`GlobalID`, `maxRecordCount: 2000`, 83,805 features.

---

## 1. Geometry + identity — PASS

- **`Parcel` (string, 18) is the parcel id.** 82,625 distinct non-null
  values across 83,805 features — exactly the 82,625 rows where it is
  non-null, i.e. **every non-null Parcel is unique**. No `PROP_ID = 0`
  collapse (Taylor) and no shared placeholder ids (Franklin).
- **1,180 rows have `Parcel`/`PID` null — and *everything* else null**
  (OwnerName, Landuse, Class, TaxAcres, LegalDescription; GISAcres mostly
  under 0.1). These are non-parcel slivers, and they identify themselves:
  the adapter filters `Parcel IS NOT NULL` and they are gone. Franklin's
  VNP-WATER trap does not recur — nothing scores a river as land here.
- Land-use codes are real property classes (DTE-style `110 CAUV Vacant`,
  `511 Single Family`, `499 Other Commercial`); `Class` ∈
  {Residential, Agricultural, Exempt, Commercial, Public Real Commercial,
  Industrial}.

## 2. Acreage — PASS

- **Three fields, all in acres:** `TaxAcres` (legal, the auditor's roll
  figure), `GISAcres` (measured from the polygon), `CAUVAcres`
  (CAUV-enrolled acres; 6,276 parcels county-wide carry it).
- Per-row check on a 2,000-parcel sample: median `TaxAcres/GISAcres` =
  **1.0011**, 1,856/2,000 within 0.9–1.1, only 10/2,000 outside 0.5–2.0 —
  and every one of those is a sub-acre parcel where `TaxAcres` is a rounded
  legal figure (e.g. 0.02 vs 0.046). **No square-feet contamination**
  (Franklin's failure mode would show ratios near 43,560; none exist).
  `_reconcile_legal_acreage` will still run per row — small-parcel rounding
  is a reason to reconcile, not to trust one field.
- ≥20-acre parcels: 5,271 county-wide (5,207 by GISAcres — the two fields
  agree to ~1%).

## 3. Assessment — PASS (inline, Franklin's shape)

CAMA is **joined into the parcel feature itself**: `MarketLandValue`,
`MarketImpValue`, `MarketTotalValue`, `NetTotalValue`, `ExemptLandValue`,
`AbatedImpValue`, `TIF` (string), `CAUVLandValue`, plus three transfer
records (T1–T3 with dates, instruments, sale amounts, valid-sale flags),
`YearBuilt`, `LivingAreaSqFt`. No separate roll to fetch — the underwriting
metrics are one query.

## 4. Paging — PASS

- Pages at **2,000** (server-enforced: a request for 5,000 returned 2,000,
  `exceededTransferLimit: true`), `resultOffset` honored — verified at
  offset 82,000 (final page: 625 rows = 82,625 − 82,000 exactly).
  `supportsPagination: true`. The Franklin per-page retry pattern applies
  unchanged; ~42 pages county-wide, fewer in a scoped bbox.
- `f=geojson` works, `inSR=4326` envelopes work, statistics
  (`outStatistics`) work. `returnDistinctValues` **errors 400** on this
  service — the adapter must tally distinct values client-side, never via
  the server.

## 5. Zoning — PUBLISHED (better than expected)

`Planning/Zoning` FeatureServer: **25 per-township polygon layers** with
`ZoningClass`, `ZoningDescription`, `ZoningOverlay`, township, resolution
and URL. Classes are real districts (Bennington: B-1, M-1 Light
Manufacturing, C-1 Conservation, PUD…; Etna: AG, GB1, M-1, M-2, PMUD…).
Six townships carry a single blanket `UZ`/`Unzoned` polygon (Eden,
Fallsbury, Hanover, Hopewell, Mary Ann, Perry) — a real finding, not a gap.

Two caveats the adapter must encode:

- **Per-township layers, not one county layer.** The adapter queries each
  township layer the survey bbox touches and concatenates. Districts are
  township-resolution; a parcel straddling layers gets its dominant
  district, same rule as Loudoun/Franklin zoning overlays.
- **Municipal zoning is absent.** This is township zoning only — Newark,
  Granville, Pataskala and Johnstown administer their own. Parcels inside
  municipalities come back with no district: **UNKNOWN**, never a guessed
  class. (Pataskala straddles the Franklin/Licking line and its corporate
  area reaches into the survey corridor, so this will be a live case.)

---

## Extra facts worth recording

- **County envelope (4326):** −82.782 … −82.183 lon, 39.913 … 40.277 lat.
  Candidate survey bboxes (≥20-acre parcels by `TaxAcres`):
  - full county `(-82.79, 39.91, -82.18, 40.28)` → **5,271 parcels**
  - west-Licking corridor (I-70 / Pataskala / Jersey / Etna, the New Albany
    edge) `(-82.75, 39.95, -82.35, 40.25)` → **3,281 parcels**
  Franklin published 982; a full-county Licking run is 5× that compute.
- The audit trail for the rollback gate is stronger than Franklin's:
  `CAUVAcres` + `CAUVLandValue` are explicit per-parcel columns, and
  CAUV land-use codes (110/111/122/190) tag enrollment directly — ORC
  5713.34's three-year roll-back can be evidenced per row, not inferred
  from class alone.
- TIF is an inline string field (Franklin needed a separate TIF layer);
  abatements have their own value column (`AbatedImpValue`).

## Consequences for Phase 2

- Copy `franklin_api.py` (FeatureServer + inline CAMA), not `loudoun_api.py`.
- Filter `Parcel IS NOT NULL` at query time; `pin = Parcel`.
- Legal acreage from `TaxAcres`, reconciled against geometry per row;
  `CAUVAcres > 0` or a CAUV land-use code drives the rollback-gate
  evidence.
- Page at 2,000 with `resultOffset`, per-page retries, `outSR=4326`,
  `f=geojson`; no `returnDistinctValues`.
- Zoning adapter queries `Planning/Zoning/{township_layer}` for the
  townships in bbox, concatenates, and leaves municipal parcels UNKNOWN.
