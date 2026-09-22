# The cadastre census — inventory before diligence

Companion to [`nationwide-brief.md`](./nationwide-brief.md) and
[`licking-cadastre-probe.md`](./licking-cadastre-probe.md). The probe
answers five questions about one county. The census answers one question
about all of them: **does public cadastral parcel data exist here, where,
and can it be counted?**

## Why

The parcel tier is nine regions of 554. The other 545 are screening
cells — ranked leads with no diligence underneath, because nobody has
inventoried which of those counties publish parcel data at all. Ohio
expansion happened because Licking was probed by hand; that path does
not scale to 545 counties. The census is the machine that replaces it:
the queue that says which counties a deep probe (the five-question
format) is worth an afternoon on, before anyone spends the afternoon.

## Method: two discovery paths, one verification rule

**County search.** ArcGIS Online's public sharing index — the same
index that surfaces every county service the nine adapters use. Hits
are filtered and scored: service types only, "parcel" in title or tags,
and the county's identity in the title or the publishing account. The
floor matters more than the ranking: a hit with no county token
anywhere is rejected, so `Regrid USA Nationwide Parcel Boundaries` and
the neighbouring county's service can never score for a county they do
not cover.

**State programs.** Six statewide services, each verified by hand on
2026-09-22 before the census first ran:

| State | Service | Owner |
|---|---|---|
| NC | North Carolina Parcels (Polygons) | nconemap |
| IN | Parcel Boundaries of Indiana Current | IndianaMap |
| NJ | Parcels and MOD-IV Composite of New Jersey | NJOGIS |
| OH | Ohio Statewide Parcels Public View | ogrip_agol |
| MD | Maryland Parcel Boundaries | mdimapdatacatalog |
| TN | Tennessee Property Boundaries Public Use | tnmap_oir |

Virginia is the seventh, differently: VGIN publishes a statewide parcel
**file geodatabase** — downloadable, not REST-queryable — so it is
recorded as a *candidate* on every VA region, with the reason in the
note. DE is covered by FirstMap's per-county services, which the county
search finds on its own. MI, WV, KY, IL and PA have no authoritative
statewide service the census could verify; their coverage comes from
the county search. Commercial aggregators (Regrid, First American) are
deliberately absent: the census records what a government publishes
itself.

**Verification.** Every candidate is checked against the region's own
bounding box: the layer must describe itself as polygons, and a count
query with the bbox as the envelope must answer. A count is presence
proven, not presence assumed — the same rule as every layer in this
engine. Allen County, Indiana verified at 169,325 parcels in its bbox
from the statewide service; that number came from the service, not from
a claim on a website.

## Evidence classes

- **verified** — the service answered, the layer is polygons, a count
  was taken against the region bbox. A verified service with *zero*
  features in the bbox is still verified, with its zero recorded.
- **candidate** — found but uncheckable today (endpoint down, no
  polygon layer, count refused). Different from nothing.
- **none_found** — the sentinel row. Searches ran and nothing relevant
  surfaced, so the county is censused and a re-run will not repeat it.
  The claim is exactly what was searched: **the ArcGIS Online index.**

## The blind spot, named

The county search sees ArcGIS Online, not the internet. Counties that
self-host ArcGIS Server without publishing to ArcGIS Online are
invisible to it — and two of the nine live adapters are exactly that
(Loudoun at `logis.loudoun.gov`, Licking at
`gis.lickingcounty.gov`; both would read `none_found` to this search).
So a `none_found` row means "not in the index", never "does not exist".
The six state programs carry their states entirely; the states where
the blind spot bites are MI, WV, KY, IL and PA. The follow-up, when
their queue positions matter, is a second pass that reads county web
maps in the index and extracts the self-hosted service URLs they
reference — a technique, not a rewrite.

## The queue

`v_cadastre_queue` is one row per censused region: verified and
candidate source counts, and the best bbox feature count from a county
service (`best_county_count`) and from a statewide program
(`best_state_count`). County services outrank statewide programs at
equal counts — a county CAMA join is usually richer than a statewide
standardized layer. The census does not decide buildability: a verified
source means the five-question probe starts with data on the table, not
that it passes.

## Running it

```
worker/.venv/bin/python cadastre_census.py --state IN --limit 22   # one state
worker/.venv/bin/python cadastre_census.py --list                 # progress
```

Progress is the table, not a file: a county is censused when it has a
row (including its sentinel), so re-runs skip finished counties and a
crash loses nothing. `--redo` re-censuses, `--dry-run` verifies without
writing. Writes go through the service role to `cadastre_sources`
(release30 migration); RLS mirrors `parcel_decisions` — authenticated
reads, no anon rows, no write policies of any kind.

## Results (full run, 2026-09-22)

544 regions censused, 0 failed. **277 of 544 (51%) have at least one
verified public parcel source** — data on the table for a five-question
probe, today. 100 more are candidate-only, and 167 carry only the
sentinel: nothing in the ArcGIS Online index. Per state:

| State | Regions | Verified | Read |
|---|---|---|---|
| IN | 22 | **22** | IndianaMap carries every county |
| MD | 24 | **24** | mdimapdatacatalog carries every county |
| NJ | 21 | **21** | NJ OGIS MOD-IV carries every county |
| OH | 83 | 74 | OGRIP carries 74; 9 counties score only as candidates |
| NC | 24 | 24 | OneMap plus county CAMA services |
| DE | 3 | 3 | FirstMap per-county services |
| TN | 3 | 3 | TNMap |
| VA | 127 | 77 | 77 via county services; VGIN gdb is a candidate on all |
| PA | 67 | 15 | PASDA county layers where published; 14 nothing in index |
| IL | 25 | 7 | Self-hosted blind spot bites hardest here among the searched states |
| MI | 6 | 2 | |
| KY | 83 | 2 | 80 nothing in the index — the blind-spot state |
| WV | 55 | 3 | 52 nothing in the index |

The "Verified" column counts regions, not source rows (one region can
verify several services; Ohio has 157 verified rows). The none_found
states are exactly the predicted ones — no statewide program and
county GIS that self-hosts. The counts say the same thing from the
other side: the largest verified county sources are IL-Cook (1.42M),
PA-Montgomery (1.05M), MD-Baltimore (674K), PA-Allegheny (587K),
OH-Cuyahoga (565K), NJ-Bergen (536K) — every one a state program or a
publishing county.

What the census buys: the screening tier is no longer undifferentiated
leads. `v_cadastre_queue` ranks all 544 by what is actually there, and
the second pass (county web maps → self-hosted service URLs) has a
named target list: KY 80, WV 52, IL 16, PA 14, MI 4, DC 1.
