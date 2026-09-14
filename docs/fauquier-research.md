# Fauquier: the two research items

The shortlist left two things to settle before Fauquier could enter qualified
rather than land at screening and need a second pass: the zoning use table,
and a water-service layer. Researched 2026-09-14.

One came back negative and one is blocked on a primary source. Both answers
are useful, and neither is "it will probably be fine".

---

## 1. Zoning use table — blocked on the ordinance text

### What is verified

The zoning layer is genuinely official. Fauquier's own metadata on
`Zoning_Districts_DL`:

> "The zoning layer constitutes the official zoning map for Fauquier County
> and is a component of the official zoning ordinance. The zoning data is
> owned by Fauquier County, Virginia Department of Community Development and
> maintained by Fauquier County GIS Department."

434 district polygons, `ZONECLASS` + `ZONEDESC`, 23 distinct classes:

```
BP  C-1  C-2  C-3  CV  GA  I-1  I-2  M-G  M-R  M-T  MDP
MU-BLTN  PCID  PRD  R-1  R-2  R-4  RA  RC  RR-2  TH  V
```

That is the same shape as Loudoun's and Prince William's layers, so the
dominant-district spatial join carries over unchanged.

### What is reported but NOT verified

Three independent secondary sources agree on the substance:

* Data centres are permitted in **two districts only — PCID (Planned
  Commercial Industrial Development) and BP (Business Park)**.
* A **March 2024** Board of Supervisors amendment to the **Vint Hill** PCID
  requires a **special exception for buildings, or assemblages of buildings
  serving one enterprise, over 50,000 sq ft**; existing projects grandfathered.
* Buildings **under 10,000 sq ft remain by right**.
* **Part 13** of the ordinance covers the PDMU, PRD and PCID districts.

### Why that is not enough to write a rule row

Every one of those is journalism or a law-firm note. This project has been
bitten three times by a rule version named for an amendment it does not
encode — Loudoun's `2023-ord+2025-zoam` listing districts ZOAM-2024-0001 had
just removed, and Harrison Township's `reviewed3` citing minutes without
changing the mapping. A `constraint_rules` row asserts what an instrument
says; secondary reporting is not that instrument.

Two specific questions the secondary sources cannot answer, and both change
the gate:

1. **Is the 50,000 sq ft special exception county-wide across PCID, or only
   the Vint Hill PCID?** Every source says "Vint Hill". If it is
   site-specific, a county-wide PCID rule would be wrong wherever else PCID
   is mapped — the Harrison Township failure exactly.
2. **What does BP permit?** Every source names BP as a data-centre district
   and then says nothing further about it. By right? Special exception? The
   2024 amendment appears not to touch it.

### Why it could not be retrieved from here

| source | result |
| --- | --- |
| `fauquiercounty.gov` zoning ordinance page | HTTP 403, with and without a browser user-agent |
| Municode library | HTTP 200 but a JavaScript shell; its API rejects the client name |
| `fauquiernow.com`, `pecva.org` | HTTP 403 |
| `princewilliamtimes.com` | HTTP 429 |
| the one ordinance PDF that surfaced in search | retrieved and read — it amends Articles 3, 5 and 15 on **nonagricultural fill material**, nothing to do with data centres |

### What is needed

The adopted text of the March 2024 amendment and the PCID and BP use tables.
Any of: a PDF of the zoning ordinance downloaded from the county site in a
browser; the adopted resolution from the Board of Supervisors' agenda packet;
or a request to Community Development.

Until then Fauquier can be **ingested** — its parcels, acreage and zoning
districts are all retrievable — but `zoning_dc_use` must read UNKNOWN rather
than be mapped from a newspaper.

---

## 2. Water — settled, and the answer is that there is no layer

**Fauquier publishes no water or sewer service-area boundary as data.**

* The Fauquier County Water and Sanitation Authority publishes one facilities
  map, a static PDF dated **2017**. No ArcGIS service, no shapefile, no
  GeoJSON.
* FCWSA confirms whether a given property is served **by telephone**,
  (540) 349-2092. That is a per-parcel human lookup, not a dataset.
* Nothing in the county's ArcGIS organisation carries a service area: of 60
  published items, the only water-named ones are `Waterlines_DL`,
  `Waterbodies_DL` and a raster image of the FCWSA map.

### The trap in that list

**`Waterlines_DL` is not a utility layer.** Its fields are `HYDROID`,
`REACHCODE`, `GNISID`, `FLOWDIR`, `NEXTDOWNID` — National Hydrography Dataset
attributes. It is 6,524 **streams**, not water mains.

An adapter matching on the layer name would have wired watercourses into the
water-availability gate and produced confident, wrong "served" verdicts for
every parcel near a creek. This is the second such trap in Fauquier alone,
after `District_D` turning out to be the magisterial district rather than
zoning. Both were found by reading fields rather than names.

### The options

1. **Water UNKNOWN for every parcel.** Honest, and it satisfies the entry
   test's criterion 4, which asks that water be classified rather than known.
2. **`Service_Districts_DL` as a proxy.** Fauquier policy concentrates public
   water and sewer in designated Service Districts — Bealeton, Catlett,
   Warrenton, Midland, New Baltimore, Remington. The layer exists and is
   clean. But it is a *comprehensive-plan land-use* layer, not the utility's
   own boundary, and using it would assert service the authority has not
   claimed. It belongs as context on the dossier, not as the gate's evidence.
3. **Ask FCWSA for the boundary.** The only route to a decided water gate.

Recommended: **1 now, 3 in parallel.** 2 is the tempting one and should be
resisted for the reason the whole engine exists — a plausible proxy recorded
as evidence is worse than a recorded UNKNOWN.

---

## An admission about the entry test

Criterion 4 as written — "every parcel carries served / not-served /
UNKNOWN" — is satisfied structurally, because the engine emits a
`water_availability` row for every parcel whether or not anything was found.
Franklin and Taylor both pass it at 0% decided. It is a check that the
plumbing works, not that any research happened, and it should be read that
way rather than as evidence a county has water diligence.

## Where this leaves Fauquier

| criterion | status |
| --- | --- |
| 1 cadastre answers acreage | ready — after string coercion and the 3.6% blanks |
| 2 zoning ≥ 80% | layer ready; **verdicts blocked on the ordinance** |
| 2b zoning rule cites an instrument | **blocked** |
| 3 power adapter for its RTO | ready, PJM |
| 4 water classified | ready as UNKNOWN; no layer exists to do better |
| 5 ≥ 19 source snapshots | expected |
| 6 no verdict without rationale | structural |

Fauquier can be ingested now and will sit one criterion short of qualified.
The missing piece is a document, not an engineering task.
