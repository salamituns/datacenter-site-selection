# The county-entry test

When may a county leave screening and enter parcel qualification?

The bar is set from the five counties already published, not from a wish.
A standard our own best county fails is not a standard, and a standard every
county passes is not a test. Everything below was measured on 2026-09-14.

---

## What the five counties actually look like

Share of active parcels whose current run decided the gate — anything not
decided is an honest UNKNOWN.

| gate | Loudoun | Pr. William | Licking | Taylor | Franklin |
| --- | --- | --- | --- | --- | --- |
| contiguous_acreage | 100 | 100 | 100 | 100 | 100 |
| floodway | 100 | 100 | 100 | 100 | 100 |
| wetlands | 100 | 100 | 100 | 100 | 100 |
| protected_land | 100 | 100 | 100 | 100 | 100 |
| road_access | 100 | 100 | 100 | 100 | 100 |
| slope | 100 | 100 | 94.4 | 99.9 | 100 |
| **zoning_dc_use** | 97.9 | 98.2 | 94.2 | 82.7 | **0** |
| **moratorium_status** | 97.9 | 99.4 | 93.1 | 82.7 | **24.7** |
| **power_capacity** | 100 | 100 | 100 | **0** | 100 |
| **water_availability** | 98.0 | 49.8 | 15.6 | **0** | **0** |

| | Loudoun | Pr. William | Licking | Taylor | Franklin |
| --- | --- | --- | --- | --- | --- |
| parcels | 2,478 | 961 | 1,990 | 3,240 | 982 |
| live rules | 9 | 9 | 9 | 7 | 7 |
| source snapshots | 22 | 21 | 21 | 19 | 19 |
| screening coverage | 0.994 | 0.947 | 0.897 | 0.765 | 0.725 |
| adapter (lines) | 275 | 443 | 370 | 240 | 369 |

Three things fall straight out of this table.

**The six free gates really are free.** Acreage, floodway, wetlands, protected
land, road access and slope sit at 94–100% in every county including the
weakest. They are federal layers plus a cadastre, they need no local research,
and they are therefore the floor rather than a test.

**Zoning is what separates counties.** Four counties clear 82%; Franklin is at
zero, because it publishes no township zoning layer. That is the single
largest difference between a county that can be qualified and one that cannot.

**Water is weak nearly everywhere.** Only Loudoun is strong. The median across
five diligenced counties is 15.6%. A test demanding decided water would
disqualify four of our own five, which tells us water belongs in the deepening
programme, not the entry gate.

---

## The test

### Tier 0 — Screening. Every county, automatically.

No entry test. Federal layers measured over screening cells, reported as
measurements with no verdicts, acreage absent. Nothing here claims diligence,
and lexicographic tiering keeps it below every qualified parcel.

### Tier 1 — Parcel qualification. The entry test proper.

All six must hold.

| # | criterion | measure | bar | why this number |
| --- | --- | --- | --- | --- |
| 1 | Cadastral parcels | acreage gate decided | **≥ 99%** | All five sit at 100. A cadastre that cannot answer its own acreage is not a cadastre. |
| 2 | Zoning traceable | zoning gate decided | **≥ 80%** | Four counties clear it (82.7–98.2); Franklin's 0% does not. Set at the weakest passing county, not the best. |
| 2b | Zoning rule recorded | live `constraint_rules` row for `zoning_dc_use`, with `reviewed_at` and `reviewed_against` | **required** | A decided gate with no cited instrument is a guess with a percentage attached. |
| 3 | Power framework | the county's market has an evidence adapter | **required for its RTO** | Taylor is at 0% not from missing research but because ERCOT has no adapter. A county may enter with power UNKNOWN only if no county in its market can do better. |
| 4 | Water classified | every parcel carries served / not-served / UNKNOWN | **100% classified**, no minimum decided | Only Loudoun decides water well. What must hold is that the answer is stated, not that it is known. |
| 5 | Repeatable retrieval | source snapshots on the latest run | **≥ 19** | The observed floor. Fewer means a layer was fetched without being recorded, and an unrecorded fetch cannot be re-run. |
| 6 | UNKNOWN discipline | no gate row with a PASS/FAIL and no rationale; no gate defaulting to another jurisdiction's rule | **zero violations** | This is the whole product. A wrong UNKNOWN is recoverable; a confident wrong verdict is not. |

### Tier 2 — Diligence-grade.

Tier 1, plus water decided ≥ 90%, power decided ≥ 90%, all rules reviewed
within 12 months, and at least one utility or interconnection document
attached. **Only Loudoun meets this today.**

---

## Scoring the five against it

| county | T1 | fails on |
| --- | --- | --- |
| Loudoun | pass | — (also Tier 2) |
| Prince William | pass | — |
| Licking | pass | — |
| Taylor | pass | power UNKNOWN, permitted: ERCOT has no adapter (criterion 3) |
| **Franklin** | **fail** | **zoning 0% against an 80% bar** |

Franklin is published at parcel tier today and would not pass this test. That
is the test doing its job rather than an argument against it — and the fix is
named: Franklin needs the township use-table treatment Harrison and Licking
already have, or it should sit at Tier 0 until it does.

The recommendation is not to withdraw Franklin. Its gates are honest — the
zoning gate reads UNKNOWN on 982 parcels rather than guessing — so it is
mislabelled rather than wrong. It should carry a visible "screening-grade
zoning" marker until the use table exists.

---

## Running the test

`database/tests/county_entry_test.sql` scores any published county against
criteria 1, 2, 4, 5 and 6, which are all decidable from the database. Criteria
2b and 3 are read from `constraint_rules` and the adapter list and are checked
by eye — they are judgements about provenance, not counts.

The test is advisory. It says whether a county has the evidence to be
qualified, never whether a site is good.
