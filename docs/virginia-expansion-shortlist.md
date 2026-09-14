# Virginia expansion: which county next

Probed 2026-09-14, before any adapter was written. The point of probing first
is that three of the four candidates would have been discovered unsuitable
somewhere in the middle of building for them.

Adjacency computed from the Census county geometry against Loudoun and Prince
William: six touch them. **Manassas city** (10 mi²) and **Manassas Park city**
(3 mi²) are independent cities, fully built out, and carry no plausible
20-acre inventory — excluded on size, not on data.

That leaves four.

## What was measured

| | Fauquier | Stafford | Clarke | Fairfax |
| --- | --- | --- | --- | --- |
| area | 660 mi² | 286 mi² | 171 mi² | 402 mi² |
| parcel layer | yes | yes | **none found** | not located |
| parcels | 36,205 | 62,948 | — | — |
| **parcels ≥ 20 acres** | **4,202** | 982 | — | — |
| parcels ≥ 100 acres | 1,007 | — | — | — |
| legal acreage field | `ACREAGE` | **none** — computed area only | — | — |
| zoning layer | 434 district polygons, `ZONECLASS` + `ZONEDESC` | parcel-level `ZONE1/2/3`, 63,247 rows | `County Zoning` only | not located |

Sources: Fauquier `services.arcgis.com/oAoeYJ1kqmAwcEC2` (`Tax_Parcels_DL`,
`Zoning_Districts_DL`); Stafford `services1.arcgis.com/qKiA6JuCrE2l72iL`
(`Parcels`, `Zoning`); Clarke `services7.arcgis.com/1uNEgmtBVWGKSY5Q`.

## Recommendation: Fauquier

1. **Four times the qualifying inventory.** 4,202 parcels at 20 acres against
   Stafford's 982 — and more than Loudoun's own 2,478. 1,007 parcels clear 100
   acres, which is hyperscale-capable ground rather than infill.
2. **It has a legal acreage field.** Stafford publishes only computed geometry
   area. The engine records `gis_acreage` and `legal_acreage` separately
   because the deed figure is the authoritative one; a county that publishes
   only the computed figure can never satisfy that distinction.
3. **Its zoning is shaped like the ones we already handle.** 434 district
   polygons carrying `ZONECLASS` and `ZONEDESC` is exactly Loudoun's and
   Prince William's shape, so the spatial-join dominant-district logic carries
   over unchanged. Stafford's parcel-level `ZONE1/ZONE2/ZONE3` is a different
   pattern — split-zoned parcels with up to three codes each — and would need
   new logic before it produced a single district per parcel.
4. PJM, rural, and directly adjacent to Loudoun, so the power evidence,
   restrictions layer and cost assumptions all carry.

## What the probe found that the adapter must handle

Found now rather than mid-build:

* **`ACREAGE` is a String(50), not a number.** Values are `'0.777'`, `'0'`,
  `' '`. Needs coercion, and `'0'` and `' '` must become UNKNOWN rather than
  zero acres — a zero would silently fail the acreage gate instead of
  conceding it.
* **378 parcels have a blank `PARCELID`** (1.0%). The engine refuses
  duplicate ids, and 378 rows sharing `' '` would trip that check. They must
  be dropped with a count logged, not silently de-duplicated.
* **1,300 parcels have a blank `ACREAGE`** (3.6%) — UNKNOWN, not zero.
* **`District_D` is the magisterial district, not zoning** (`LEE`,
  `CENTER-WARRENTON`, `SCOTT`). A field-name match on "district" picks it up
  and would have mapped election districts into the zoning gate. Zoning comes
  only from `Zoning_Districts_DL`.
* The service does support `CAST(ACREAGE AS FLOAT)` server-side, so the
  20-acre floor can be pushed to the query rather than filtered locally.

## Against the county-entry test

Predicted, not yet measured — the test only scores published counties.

| criterion | Fauquier |
| --- | --- |
| 1 cadastre answers acreage | expected pass, after string coercion, minus the 3.6% blank |
| 2 zoning ≥ 80% | expected pass: 434 district polygons over the whole county |
| 2b zoning rule cites an instrument | **to do** — needs the ordinance read and a `constraint_rules` row |
| 3 power adapter for its RTO | pass, PJM |
| 4 water classified | **unknown** — the water source has not been identified |
| 5 ≥ 19 source snapshots | expected pass |
| 6 no verdict without rationale | structural, holds |

Two open items before Fauquier could be qualified rather than merely
ingested: the zoning ordinance's data-centre use table, and a water-service
layer. Both are research, not engineering.

## Not chosen

* **Stafford** — second. Viable, but no legal acreage, a different zoning
  shape, and a quarter of the large-parcel inventory. Worth revisiting once
  Fauquier proves the process is repeatable, which is the point of doing two.
* **Clarke** — no parcel layer found in its ArcGIS org. Smallest of the four
  and the most protective of rural character. Excluded until a cadastre is
  located.
* **Fairfax** — not located, not excluded. It runs its own ArcGIS server whose
  OpenData folder holds no parcel or zoning service; the layers are likely in
  the DPZ or LDS folders and were not chased. Deprioritised on market grounds
  — 402 mi² and heavily built out, so 20-acre greenfield inventory is scarce
  — but that is a judgement, not a measurement.
