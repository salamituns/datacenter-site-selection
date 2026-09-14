# Ohio expansion: which county next

Probed 2026-09-14, before any adapter was written, the same way Virginia was.
The answer is shaped differently from Virginia's, and the difference is the
finding.

Nine counties touch Franklin or Licking: Muskingum, Coshocton, Knox,
Fairfield, Pickaway, Madison, Delaware, Union, Perry.

## Cadastre: solved regionally, not per county

The City of Columbus publishes **Central Ohio Parcels** — one layer covering
**Delaware, Fairfield, Franklin, Licking, Madison, Pickaway and Union**,
848,070 parcels, 120 fields, with a `COUNTY` column.

`maps.columbus.gov/arcgis/rest/services/CityServices/KeyLayers/MapServer/3`

That is the opposite of Virginia, where three counties needed three adapters.
One adapter would serve five counties here.

**But acreage is not populated everywhere**, and acreage is what the gate
reads:

| county | ≥ 20 acres | from |
| --- | --- | --- |
| Licking | 5,232 | `ACRES` — already ingested |
| Fairfield | 3,541 | `ACRES` |
| Union | 3,337 | `STATEDAREA` |
| Delaware | 3,050 | `STATEDAREA` |
| Franklin | 2,196 | `ACRES` — already ingested |
| **Madison** | **—** | neither field populated |
| **Pickaway** | **—** | neither field populated |

`STATEDAREA` is in acres: checked against `ACRES` on Licking rows where both
are present, and they agree 1:1 (151.56/150.0, 94.42/95.0, 96.04/95.9). It is
a usable substitute, not a different unit.

Madison and Pickaway carry parcels with no acreage in either field. They are
out until a county source is found, regardless of anything else.

**The trap in this layer**, found the same way as Fauquier's: `CLASSCD`,
`CLASSDSCRP`, `USECD` and `PCLASS` are Ohio **auditor property-class codes**,
not zoning districts. A field-name match on "class" or "use" picks them up and
would map an auditor's tax classification into the zoning gate.

## Zoning: the Ohio problem, and it is structural

**None of the three viable candidates publishes zoning.**

| county | what exists |
| --- | --- |
| Delaware | one township — "Delaware Township Zoning", not the county's ~19 |
| Union | nothing county-wide |
| Fairfield | nothing. `LancasterGIS` is the **city** of Lancaster, not the county; the county's own server publishes `CALU`, which is *Current Agricultural Land Use* |

Nor does the regional service (four layers: addresses, roads, corporate
boundary, parcels), nor MORPC.

This is not an oversight in the probe. `franklin_api.py` already says it:

> ZONING IS NOT AVAILABLE. Ohio zones by municipality and township, not by
> county, so there is no county-wide ordinance layer to read.

Licking is the Ohio exception rather than the Ohio norm — it publishes a
township zoning layer carrying `ZoningClass`, `ZoningDescription`, `Township`
and `Resolution`, which is why it reaches 94.2% where Franklin sits at 0%.

## What this means for repeatability

The Virginia and Ohio results answer the repeatability question differently,
and both answers are real:

* **Virginia** — cadastre is per-county and costs an adapter each; zoning is
  county-wide and published, so a county can reach Tier 1. Fauquier did:
  one adapter, four data traps, one ordinance read, 99.7% zoning decided.
* **Ohio** — cadastre is regional and nearly free; zoning is township-level
  and mostly unpublished, so a county reaches the cadastre and stops.

**Repeatability is a property of the state, not of the engine.** That is worth
knowing before committing to a PJM-wide rollout plan that assumes a uniform
per-county cost.

## Recommendation

Adding Fairfield, Union and Delaware on the regional layer is cheap — one
adapter for three counties, roughly 10,000 new qualifying parcels, six of ten
gates decided from federal layers.

It would also put three more counties exactly where Franklin already is:
published at parcel tier with zoning at 0%, which the county-entry test says
is **mislabelled rather than wrong**. Doing that three more times without
fixing the label is how a known gap becomes an unnoticed one.

So the honest sequence is:

1. **Ship the screening-grade zoning marker first.** It is small, it fixes
   Franklin, which is mislabelled today, and it makes the Ohio counties
   honest on arrival rather than retroactively.
2. **Then build the one regional adapter** for Fairfield, Union and Delaware.
3. **Township zoning is research, per township**, and can follow per county —
   Fairfield has 13 townships, Delaware 19, Union 14. Licking proves it is
   obtainable; it is not obtainable from GIS alone.

Madison and Pickaway are excluded on acreage until a county source exists.
Muskingum, Coshocton, Knox and Perry were not probed: they are outside the
regional layer, so each would cost its own adapter for less inventory.
