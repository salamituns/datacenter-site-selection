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

## The second pass — web maps, and two statewide services nobody had indexed

Run 2026-09-28 over the 267 regions the first pass left unverified
(`cadastre_census.py --web-maps`, release31).

**Method.** ArcGIS Online's index holds a county's *web maps* even when
the county's server is self-hosted, and a web map is a JSON document
listing the layer URLs it draws. The pass searches up to 40 web maps per
county, walks their operational layers (group layers included), and
keeps a layer only when it is

- **self-hosted** — any host but `*.arcgis.com`. Hosted services were the
  first pass's whole search space; what web maps add there is re-uploads.
  Probing Licking showed exactly that: its hits were student coursework
  copies (`services8.arcgis.com`, `*_virginiatech` owners), while
  Loudoun's maps led straight to `logis.loudoun.gov`.
- **a parcel layer** — "parcel", "taxmap" or "cadastre" in the title or
  the URL path, and not a PLSS survey grid, district, label or point
  layer (`is_parcel_layer`). BLM's PLSS service, in the `Cadastral`
  folder, was the false positive the probe actually hit.

Each surviving URL is verified by the first pass's rule — polygon layer,
bbox count answers — and recorded as `discovered_via = 'web_map'`. The
publisher recorded is the URL's **host**, not the map's author: a
student's map pointing at a county server still found the county's
server. Every second-passed region gets a web-map sentinel
(`(none: web maps)`) when its maps found nothing, so re-runs skip it and
the claim stays exact: *no indexed web map references a self-hosted
parcel layer*.

**Self-hosted statewide programs.** Probing for the pass found two
statewide services outside the index, now queried directly:

| State | Service | Note |
|---|---|---|
| WV | WV GIS Technical Center `Planning_Cadastre/WV_Parcels` | compiled from county assessors + WV Property Tax Division |
| PA | PA DEP `Parcels/PA_Parcels` | self-described **partial** dataset: a count proves presence, not county-complete coverage |

Kentucky's state server (`kygisserver.ky.gov`) hosts one county PVA
service (Webster), not a program.

**A security fix on the way.** `v_cadastre_queue` had been created without
`security_invoker`, so it ran as `postgres`, bypassed `cadastre_sources`'
RLS, and Supabase's default privileges had granted `anon` every privilege
on it — the census was anonymously readable over REST. release31b sets
`security_invoker = true` and leaves `authenticated` with SELECT only;
anon now gets 401 on the view and no rows from the table (verified live).

### Results (full run, 2026-09-28)

267 regions second-passed, 0 failed. **115 gained a verified source with
1,000+ parcels in the bbox** (a count of 0, or a few hundred at a county
edge, is recorded but not counted as a gain here):

| State | Gap before | Gained | How |
|---|---|---|---|
| WV | 52 | **52** | WVGISTC statewide (50), county/state layers in web maps (Jefferson's own `gisarcweb.jeffersoncountywv.org`, plus Grant, Hardy, Logan on WVGISTC) |
| PA | 52 | **49** | PA DEP partial statewide (49); McKean's own server via web maps |
| VA | 50 | 9 | Bedford, Harrisonburg, James City, Staunton on their own servers; five on a neighbour's (below) |
| KY | 81 | 4 | Kenton (LINK-GIS), Scott (Georgetown-Scott planning); Campbell and Pendleton on Kenton's server |
| OH | 9 | 1 | Richland (`maps.richlandcountyoh.us`) |
| IL | 18 | 0 | Boone and Kane servers found but refused counts — recorded as candidates |
| MI | 4 | 0 | |
| DC | 1 | 0 | DC calls parcels "owner polygons"/"lots"; the filter's vocabulary misses it |

**Seven gains looked like a neighbour's service**, because the check is a
bbox and adjacent bboxes overlap. The outline-coverage check (below)
settled them the same day, and mostly the other way: six are real.

### Outline coverage — settling the bbox ambiguity (release32)

`cadastre_census.py --outline` asks each verified layer, at 24 points on a
grid inside the county's own Census outline (inset 800 m past the 1:20m
generalisation), whether a parcel is there. `outline_coverage` is the
share that hit. A county's own layer covers most of its land — the misses
are roads and water; controls measured 0.75 (Harrisonburg, a city) to
1.00. A neighbour's layer covers almost none.

| Region | Layer | Coverage | Verdict |
|---|---|---|---|
| KY-CAMPBELL | LINK-GIS `Parcels_CC` (38,039) | 1.000 | covered — LINK-GIS is regional |
| KY-PENDLETON | LINK-GIS `Parcels_PC` (9,049) | 0.958 | covered |
| VA-ISLEOFWIGHT | HRSD regional parcels (134,500) | 0.958 | covered |
| VA-SOUTHAMPTON | HRSD regional parcels (24,593) | 1.000 | covered |
| VA-MANASSASCITY | Prince William (18,287) | 1.000 | covered |
| VA-MANASSASPARKCITY | Prince William (5,935) | 1.000 | covered |
| VA-WILLIAMSBURGCITY | James City (6,354) | 0.000 | **neighbour — not a source** |

It also caught a false gain the bbox rule had passed: **KY-KENTON's**
recorded rows were LINK-GIS's *subdivisions* service (coverage 0.000) —
the 4-candidate cap had filled before Kenton's parcel layer was reached.
LINK-GIS publishes one layer per county on one service (`Parcels_CC`,
`Parcels_KC_PVA`, `Parcels_PC`); `Parcels_KC_PVA` covers Kenton at 0.917
with 64,580 parcels and is now recorded, noted as found through its
neighbours' web maps.

**Coverage needs the count beside it.** A layer of a few big polygons
covers a county completely: WV-HARDY's tax districts (17 features) and a
Staunton boundary layer (1) both read 1.000. `best_outline_coverage` in
`v_cadastre_queue` therefore reads only layers with 1,000+ features in
the bbox (release32b) — coverage says the layer reaches all of the
county, the count says it is divided like parcels.

### The statewide programs, measured (2026-09-29)

Spillover is worse for a statewide layer than a county one: a county
server reaches into its few neighbours' boxes, a statewide layer into
every uncovered county bordering a covered one.

**WV — WVGISTC holds.** 49 of 50 rows cover their county at 0.833–1.000;
WV-TUCKER reads 0.708, below the line but plainly its own county's
layer. The remaining three (Grant, Hardy, Logan) were already confirmed
on their web-map rows. All 52 West Virginia regions are real sources.

**PA — DEP's "partial" is partial.** 35 counties covered (0.750–1.000),
PA-SOMERSET partly (0.333), and **14 not at all** (0.000–0.042): Armstrong,
Beaver, Bradford, Butler, Cameron, Carbon, Fayette, Luzerne, McKean,
Mercer, Monroe, Montour, Warren, Washington. Their bbox counts were all
neighbours' parcels — PA-WASHINGTON's 385,520 is Allegheny's and
Westmoreland's, and it covers 0.000 of Washington. McKean survives on its
own server (0.958); the other twelve that had passed the 1,000 floor were
false gains.

**Net, second pass:** **102 of 267** regions gained a source that covers
the county itself — WV 52, PA 37 (Somerset partial), VA 8, KY 4, OH 1 —
down from the 115 the bbox count claimed. Every one is outline-measured.

What is left — 165 regions, KY 77 the bulk — is what the index cannot
reach by any route: counties whose assessors publish through vendor
viewers (qPublic, Schneider Beacon, PVA sites) rather than ArcGIS.
Finding those would mean scraping vendor sites, which is a different
project with different terms of use; the census stops here.

**Known limit, for the first pass:** its 277 verified regions are still
bbox-verified only. The second pass showed how far that can mislead —
twelve of PA DEP's 49 were a neighbour's parcels — so the first pass's
statewide programs (IN, MD, NJ, OH, NC, TN) deserve the same
`--outline --via state_program` run before the queue is trusted to pick
the next county to probe.
