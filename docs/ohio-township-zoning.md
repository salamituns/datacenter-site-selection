# Ohio township zoning: what is reachable and what is not

Researched 2026-09-15, working through Fairfield County first, then the other
three.

**This document was wrong when first written, and the correction is the most
useful thing in it.** The first pass concluded, from Fairfield, that Ohio
township zoning geometry does not exist and the whole effort was blocked.
That holds for Fairfield. It is false for Delaware and for Franklin, and the
reason it looked true is worth more than the conclusion it produced.

## How the geometry was missed, and how it was found

Searching ArcGIS Online by title finds nothing, because nobody names these
services the way a searcher would guess. Delaware's are `porterzon`,
`harlemzon`, `sciotozon` — one per township, owned by a named individual at
the planning commission rather than by an organisation account. A title
search for "Delaware County Ohio zoning" returns a single township and
invites exactly the wrong conclusion, which is the one this document first
drew.

**Trace the county's zoning WEB MAP instead.** Every one of these counties
publishes an interactive zoning map for the public. That app references a web
map; the web map's `operationalLayers` name every service behind it, group
layers included. Two requests to `arcgis.com/sharing/rest/content/items/...`
turn "nothing published" into a complete inventory.

That is the method. It should be the first thing tried for any county, not
the last.

---

## Where the geometry actually is

| county | zoning geometry | detail |
| --- | --- | --- |
| **Delaware** | **yes — all 18 townships** | 16 feature services, 3,510 polygons. Thompson, Radnor and Marlboro share one service because all three adopted the *county* code under ORC 303. |
| **Franklin** | **yes** | A county zoning districts layer (1,090 polygons) published by the county's own Economic Development & Planning GIS, plus per-township layers: Prairie 6,799, Perry 1,532, Plain 1,009, Washington 367, Blendon 130. |
| **Fairfield** | **no** | Checked the county ArcGIS server, the RPC, AGOL for the county and for Greenfield specifically, and the regional Columbus service. Nothing. |
| **Union** | not found | No zoning web map located yet; worth the same web-map trace before concluding. |

`worker/franklin_api.py` still carries a module note saying "ZONING IS NOT
AVAILABLE... there is no county-wide ordinance layer to read". That note is
wrong, and Franklin has sat at 0% zoning since inception partly because of
it.

Delaware has **no unzoned townships at all** — all 18 have resolutions — so
the unzoned lever that decided 509 Fairfield parcels returns nothing there.
Its 2,760 parcels need the geometry route instead, and the geometry is
available.

## For Fairfield, the gate needs two things and only one is in the PDFs

| requirement | what supplies it | Fairfield |
| --- | --- | --- |
| **use table** — which district permits a data centre | the township's zoning resolution | 11 PDFs, all obtained |
| **district geometry** — which district a given parcel is in | a zoning GIS layer | **does not exist** |

Checked: the county's own ArcGIS server (14 root services, 12 folders — no
zoning), the county RPC, ArcGIS Online for the county and for Greenfield
Township specifically, and the regional Columbus parcels service. Nothing
publishes Fairfield zoning geometry at any level.

So a use table read from a PDF has nothing to attach itself to. Knowing that
Greenfield permits data centres conditionally in its Industrial district does
not tell us which of Greenfield's 219 parcels are Industrial.

**This is why the unzoned-township slice worked and the rest does not.** "This
township has adopted no zoning" is the one zoning answer that needs no
geometry — it applies to every parcel in the township by definition. It is
not a shortcut; it is the only part of the problem that is shaped to be
solvable without a map.

Licking reaches 94.2% because it publishes a township zoning **layer** —
`ZoningClass`, `ZoningDescription`, `Township`, `Resolution` — geometry and
use class together. That is the exception in Ohio, not the model.

---

## What the 11 resolutions actually say

Worth recording even though it cannot be applied yet: when geometry appears,
this is already done.

### Greenfield — names the use, and recently

Version history, Application 26-022, approved **2026-06-10**, effective
**2026-07-10**:

> Section 105.02 Definitions: Add "Data Center"
> Section 355.04 — Industrial — Conditional Use: Add "Data Centers"

with the definition:

> "Data Center — Real and personal property consisting of buildings or
> structures specifically designed or modified to house networked computers
> and data and transaction processing equipment and related infrastructure"

So: **conditional use in the Industrial district**. Three months old. Nothing
else in Fairfield addresses the use at all.

### Amanda, Bloom, Walnut — the trap

All three contain the phrase "Data processing/computer services", and it is
**not a data centre**. It appears in a list of professional office and
personal-service uses, beside:

> antique shop/restoration · barber/beauty shop · craft shop · day-care
> facility · drafting/graphic arts · photography/art studio · insurance,
> financial, investment services

That is a bookkeeping office, not a hyperscale campus. A keyword match on
"data" would have mapped **821 parcels** on a phrase that looks right and
means something else — the same shape as Fauquier's `District_D` turning out
to be the magisterial district, and the Central Ohio layer's `CLASSCD` being
an auditor tax class.

### Berne, Hocking, Liberty, Pleasant, Richland, Rushcreek, Violet

**No data-centre language at all.** 1,909 parcels across seven townships
whose resolutions simply do not name the use — the same silence as Fauquier's
Business Park district and the Columbus zoning code. Ohio zoning is
permissive, so an unlisted use is generally not permitted without a
similar-use determination, and several of these codes carry "substantially
similar uses" provisions that a zoning inspector applies case by case. That
is a judgement the engine cannot make from the text, so it stays UNKNOWN.

---

## Fairfield, settled

| status | townships | parcels | why |
| --- | --- | --- | --- |
| **decided — PASS** | Clearcreek, Madison | **509** | no zoning adopted (ORC 519); needs no geometry |
| blocked on geometry | Greenfield | 219 | use table known, district map does not exist |
| blocked on geometry + silence | the other 9 | 2,736 | resolutions do not name the use |
| municipal | Lancaster city, Columbus city | 83 | city zoning, not township |

**509 of 3,541 — 14.4% — is the reachable ceiling for Fairfield** until
somebody publishes zoning geometry.

---

## What to do next, per county

**Delaware — build it.** 2,760 parcels, geometry for every township, and the
resolutions are all published by the RPC as PDFs alongside. This is the
Licking pattern arriving in a second county: geometry plus use table. The
work is an adapter that reads 16 services and normalises their schemas, which
differ per township (`Scioto_Zoning_ZONING` against `berkshirezon_ZONING` —
each service is a join of polygons to a district table, and the join prefixes
the field names).

**Franklin — check what the county layer covers, then build.** 1,090 county
polygons is small for a county this size, which suggests it covers only the
townships that adopted the county code under ORC 303 rather than all
unincorporated land. Measure the coverage against the 2,178 parcels before
promising anything. Correct the module note either way.

**Union — trace its zoning web map** the way Delaware's was traced, before
concluding anything. The title search that found nothing is the same search
that found nothing for Delaware.

**Fairfield — genuinely blocked**, and the 509 unzoned parcels remain its
ceiling. The options there are to wait for publication, to ask the RPC
directly (a commission that reviews resolutions under ORC 519 often holds
shapefiles it has not published), or to digitise sixty township maps — which
should not be undertaken casually, because a parcel assigned the wrong
district gets a confident wrong verdict, invisibly.
