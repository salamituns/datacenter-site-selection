# Ohio township zoning: what is reachable and what is not

Researched 2026-09-15, working through Fairfield County — the best-organised
of the four Ohio counties — to find out what the full job costs.

The answer is not the one expected. **Reading the township resolutions does
not unblock the zoning gate.** The blocker is district geometry, not use
tables, and the two are published by completely different people.

---

## The gate needs two things, and only one of them is in the PDFs

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

## What this means for the other three counties

The expensive part of this research was never the use tables. It was
discovering that they cannot be applied. Repeating it county by county would
cost the same and return the same.

**The reachable work is one question per county, not one per township:**
*which townships have adopted no zoning?* Fairfield's RPC answers it in a
sentence. That is the only part of Ohio township zoning that is solvable
without a zoning map, and it is worth doing for Delaware, Union and Franklin
before anything else.

Everything beyond it needs district geometry, and the honest options are:

1. **Wait for publication.** Some townships will; Licking already has.
2. **Ask the counties.** An RPC that reviews resolutions under ORC 519 often
   holds shapefiles it has not published.
3. **Digitise the maps.** Each resolution carries a zoning map as an image.
   Georeferencing 60-odd township maps is a project in its own right, and one
   whose errors would be invisible — a parcel assigned the wrong district
   gets a confident wrong verdict, which is the failure this engine exists to
   avoid.

Option 3 should not be undertaken casually. Options 1 and 2 cost little and
may simply resolve it.
