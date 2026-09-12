# Moratorium gate — implementation brief

**Why this one next.** Political risk is the second-largest stated constraint
on US data-centre siting in 2026: 300+ bills across 30+ states, 140+ local
groups, ~$60B+ in delayed or blocked investment, and at least 100 adopted
moratoria. At least six public trackers exist — dcmap.us, Programs.com, savrn,
datacenterbans.com, Interconnected Capital, Axis Intelligence.

Every one of them is a **list of jurisdictions**. None is a parcel-level gate
with a citation. That is the gap, and it is the shape this engine already
builds in: jurisdiction-scoped, versioned, dated, and refusing to guess.

It is also the cheapest edge available. Unlike water — which is published by
whoever happens to run the pipes — moratorium data is public, national, and
already aggregated by other people.

---

## The rule that governs the whole feature

**An ordinance is evidence. A tracker is a search result.**

A gate that says "blocked, because axis-intelligence.com lists this county"
would break the premise the engine is built on. Trackers are how you *find*
a jurisdiction worth checking; what gets stored is what the jurisdiction
itself adopted:

| field | example |
| --- | --- |
| adopting body | Snohomish County Council |
| instrument | Emergency Ordinance 26-026 |
| adopted | 2026-06-24 |
| effective | 2026-06-24 |
| expires | 2026-12-24 (nullable — some are indefinite) |
| scope | new or expanded data centres, unincorporated areas |
| source_url | the county's own record, not the tracker |

If the ordinance cannot be located and cited, the jurisdiction is **not**
recorded as restricted. An unverified restriction is worse than none: it would
disqualify real land on somebody's blog post.

Evidence class is `manual` — a human read the ordinance — the same class the
Loudoun zoning use-table already carries. Not `observed`; nothing fetched it.

---

## The part that makes this gate unlike the others

**Its verdict is a function of the calendar.** Every other gate is static given
its evidence: a wetland does not stop being a wetland on a date. A moratorium
does — Snohomish's lapses on 2026-12-24, Clay County's ran exactly a year.

Two consequences:

1. **Evaluate against the run's own date and record it.** The verdict must be
   reproducible: "what did we know, and what was in force, on the day this run
   published." Store the evaluation date in the gate's `details` so a verdict
   can be re-derived rather than merely re-run.
2. **A lapsed moratorium re-opens the gate by itself.** No human action, no
   re-entry. The row stays — expired, with its dates — because "this county
   paused data centres for six months in 2026" remains a fact worth knowing
   about a jurisdiction even after it lapses. It informs political risk
   whether or not it is currently binding.

Suggested verdicts:

| situation | verdict |
| --- | --- |
| active moratorium covering this parcel | `FAIL` |
| adopted, not yet effective, or expiring within the horizon | `CONDITIONAL` |
| expired, or restrictive zoning short of a ban (setbacks, noise, water disclosure) | `CONDITIONAL` |
| jurisdiction checked, nothing found | `PASS` |
| jurisdiction not yet checked | `UNKNOWN` |

That last row matters. A county nobody has reviewed is `UNKNOWN`, never `PASS`.
Absence of a recorded moratorium is not evidence of absence, and this gate
would be the easiest place in the engine to accidentally assume otherwise.

---

## The matching problem, and its solution

Parcels carry `county_name` and `state_code`. County-level moratoria match
directly. **Municipal ones do not** — a parcel knows its county, not its city,
and many pauses are adopted by towns and cities.

The fix is a layer already in use: **Census TIGER/Line Places**, the same
federal source behind the roads fallback in `overlay_layers.py`. Clip places to
the survey bbox, join parcels by point-in-polygon, and a parcel gains the
incorporated place containing it — or none, meaning unincorporated, which is
itself the scope clause of ordinances like Snohomish's.

That join is reusable well beyond this gate: it is also what would let the
zoning gate stop conceding `UNKNOWN` for incorporated towns, which is exactly
why Loudoun holds 50 parcels at `UNKNOWN` today.

---

## Scope

Start with the five live regions and their states — Loudoun and Prince William
VA, Franklin and Licking OH, Taylor TX. That is a real answer for real parcels
and a week of ordinance reading, not a national dataset.

National coverage is a research pipeline, not an engineering one, and should
follow the same rule the cadastre expansion follows: one jurisdiction at a
time, verified, or `UNKNOWN`.

## Order of work

| # | task | gate |
| --- | --- | --- |
| 0 | TIGER/Line Places layer + parcel-to-place join | every parcel resolves to a place or explicit unincorporated |
| 1 | `jurisdiction_restrictions` table, versioned and dated, citation required | no row without a locatable ordinance |
| 2 | `moratorium_status` gate, evaluated against the run date | unchecked jurisdiction reads UNKNOWN, not PASS |
| 3 | dossier surfacing with the ordinance cited and its expiry | verdict states the instrument, not the tracker |
| 4 | comparison panel row | mixed-jurisdiction shortlists already render |

## Not doing

- **No scraping the trackers as a source.** They are discovery. Cite ordinances.
- **No sentiment or opposition scoring.** "140 local groups" is a real risk and
  an unfalsifiable number; this gate records adopted instruments, not mood.
- **No predicting moratoria.** A county that might pause is not a county that
  has, and the engine does not forecast.

---

## Status and next step (2026-09-12)

**Phase 0 is done.** The TIGER Places join shipped with the Texas no-zoning
rule; every parcel already resolves to its incorporated place, persisted as
the `incorporated_place` metric (778 parcels across 18 municipalities).

**The evidence layer is built and populated.** `jurisdiction_restrictions`
(release 17/17b) holds four statuses rather than a boolean — `adopted`,
`pending`, `none_found`, `unverified` — with `basis`, `reviewed_at` and
`sources_checked` required on every row, and `v_jurisdiction_restrictions`
deriving `in_force_today` from the dates.

Two things were learned populating it, and both change the gate.

### Townships are the level that acts

Licking County has no moratorium — Microsoft restarted 869 MW across Heath,
Hebron and New Albany during 2026. **St. Albans Township** banned data centres
outright on 2026-03-10. Other central-Ohio townships (Jackson, Jerome,
Washington) have adopted temporary pauses.

So the gate matches at three levels, and the table now has a column for each:
county, incorporated place, and **minor civil division**. In Ohio the township
is the zoning authority for unincorporated land, which is why the Licking use
table is township-keyed already.

The engine currently infers township from the `zoning_ordinance_vintage`
string (`"Bennington Township Zoning Resolution"`). That works and is fragile —
it depends on how the county labels its own layer. **Persist township properly
from TIGER county subdivisions**: the same
`Places_CouSub_ConCity_SubMCD` service already used for places, a different
layer, cached per state like the rest. Emit it as a metric beside
`incorporated_place`.

### A ban is not a pause, and they belong to different gates

St. Albans did not adopt a moratorium. It struck "Data Processing Services"
from its **conditionally permitted uses** — a zoning text amendment. A
moratorium suspends processing while the use table still permits the use; this
removed the use. `expires_date` is NULL because a use-table amendment does not
lapse.

Its enforcement mechanism is therefore the **zoning gate**: if the survey ever
reaches St. Albans, that township's `constraint_rules` row must carry the
removal, and the moratorium gate should not be the thing that catches it. The
temporary township pauses are this gate's actual business.

### Gate logic

Collect every applicable row — the county, plus whichever of place or
subdivision contains the parcel — and take the most restrictive:

| condition | verdict |
| --- | --- |
| any `adopted` with `in_force_today` | `FAIL` |
| any `unverified` | `UNKNOWN` |
| any `adopted` that has lapsed, or any `pending` | `CONDITIONAL` |
| all applicable rows `none_found` | `PASS` |
| **no row for the jurisdiction at all** | `UNKNOWN` |

That last line is the one to get right. A jurisdiction nobody has reviewed
must read UNKNOWN, never PASS — `none_found` is a positive statement with a
date and sources behind it, and the absence of a row is not that statement.
This is the same refusal the zoning gate already makes for a region with no
use table.

A lapsed moratorium reads CONDITIONAL rather than PASS: the pause is over, but
a jurisdiction that paused once is a live political-risk signal, and the row
survives precisely so that stays visible.

### Verdicts must cite the instrument, not the tracker

`{adopting_body} {instrument}, adopted {adopted_date}` — and for `pending`,
say what is pending and when it is decided. Record `reviewed_at` in the
verdict details so a reader can see how fresh the check is, the same way the
slope cache carries its retrieval date.

### Order

| # | task | gate |
| --- | --- | --- |
| 1 | persist township from TIGER CouSub | every unincorporated parcel resolves to a township |
| 2 | wire `moratorium_status` against the three levels | an unreviewed jurisdiction reads UNKNOWN, not PASS |
| 3 | dossier surfacing with the instrument cited | verdict names the body and date, never a tracker |
| 4 | republish all five regions | St. Albans still binds nothing; Pataskala reads CONDITIONAL |

---

## Shipped — the township layer and the gate (2026-09-12, release18)

**The township layer.** `fetch_subdivisions` (TIGERweb
Places_CouSub_ConCity_SubMCD layer 1, MTFCC G4040; TIGER/Line state
COUSUB shapefile fallback; state clip cache like the rest) resolves every
parcel to the minor civil division holding its majority, persisted as the
`county_subdivision` metric beside `incorporated_place`. Measured: 1,872
of 1,990 Licking parcels resolve to a township; Loudoun's 37 MCDs are all
election districts and resolve zero — which is correct, not a gap.

**The gate.** `moratorium_status` collects the rows for the jurisdictions
that govern each parcel — its county, its incorporated place (if the
majority lies inside one), its township — and takes the most restrictive:
`adopted` and in force on the run date → FAIL; any level with no row, or
any `unverified` row → UNKNOWN; `pending`, or `adopted` but lapsed or not
yet effective → CONDITIONAL; every level `none_found` → PASS. The verdict
is evaluated against the run's own date (recorded in the details, so a
verdict can be re-derived), and a lapsed moratorium re-opens the gate by
itself while the row survives as a political-risk signal. Rationales cite
`{adopting_body}, {instrument}, adopted {date}` — never a tracker — and
carry `reviewed_at`, `source_url` and per-level statuses in the details.

Four semantics the implementation had to decide, each settled by the
evidence rows' own text:

1. **A county `none_found` row speaks only for the county.** Taylor's row
   says it outright: "incorporated places within the county are recorded
   separately as they are reviewed", and Licking's separates the St.
   Albans township ban from the county. So a parcel inside Abilene or an
   unreviewed township reads UNKNOWN even where the county is checked
   clear — the same refusal the zoning gate makes for TWN parcels.
2. **Only governing MCDs match at the township level.** An MCD is only
   sometimes a government: an Ohio township (FIPS class 44, functioning)
   zones unincorporated land; a Virginia election district (27/28) or a
   Texas CCD (22) is a statistical artefact nobody adopts ordinances
   through. The class test lives beside the matching logic
   (`TOWNSHIP_MCD_CLASSES`), extended per state as the survey grows.
3. **An unavailable subdivision layer holds unincorporated parcels at
   UNKNOWN**, the same present/None contract as the places layer —
   silence is never "no township", which is not a thing in a tiled
   county. Parcels inside a place are unaffected: township zoning does
   not reach municipal limits.
4. **A parcel-specific land-use approval outranks the district, not the
   moratorium** — the approvals override already shipped in the zoning
   gate is untouched; a moratorium in force fails the parcel regardless
   of what the use table permits, because a pause suspends processing
   itself.

**Expected verdicts, confirmed by the dry runs and the republish:** no
FAIL anywhere (St. Albans binds no surveyed parcel — its corridor has
none); Pataskala's parcels CONDITIONAL on the pending November ballot
measure; every other Licking parcel UNKNOWN (townships unreviewed — the
honest state until each is read); Loudoun CONDITIONAL on the Board's
pending pause motion, except the 52 town parcels which stay UNKNOWN
(their municipalities unreviewed); Prince William PASS outside towns,
UNKNOWN inside them; Taylor PASS outside places, UNKNOWN inside them
(Abilene et al. unreviewed). Evidence coverage dips where the gate is
honestly undecided — Licking 0.900 → 0.811 of a now-ten-gate set — which
is the coverage metric reporting the truth rather than the gate guessing.

**Verification.** Worker suite 241 tests (new: unreviewed-township
UNKNOWN, pending-measure CONDITIONAL with instrument cited, adopted-ban
FAIL, all-levels-checked-clear PASS, unavailable-layer hold,
no-rows-for-state, lapsed → CONDITIONAL, not-yet-effective → CONDITIONAL,
unverified → UNKNOWN, township metric persisted, missing-subdivision-layer
hold). Client gate label added (`moratorium_status: "Moratorium /
restriction"`). One pre-existing parcel decision now flags stale with
"moratorium_status: added" — the fingerprint view doing exactly its job
when the gate set grows.

---

## Shipped — the township reviews (2026-09-12, release19)

**The review.** Every Ohio township governing surveyed parcels — 13 in
Licking, 15 in Franklin — was researched to the layer's own standard:
the township's own record first (minutes, resolutions, notices), reputable
coverage naming the action, date and vote acceptable, tracker claims
never citable. The decoy problem was real and handled row by row: the
"Plain Township moratorium" is Stark County's, the "Liberty Township
votes" are Butler County's, the "Granville Township data-center
ordinance" is Mifflin County, Pennsylvania's, the "Monroe Township
moratorium" is Adams County's, the "Blendon Township moratorium" is
Ottawa County, Michigan's, and the heavily covered "Perry Township"
fight is Stark County's. Twenty-eight rows, each with basis,
sources_checked and reviewed_at.

**What it found.** Six adopted restrictions among the 28:

- **Harrison Township (Licking), 2026-07-06** — trustees struck the
  Zoning Commission's proposed M-1 conditional use "Data Centers" and
  the proposed DATA CENTER / DATA CENTER CAMPUS definitions (3-0 roll
  call, their own minutes): no data-centre authorization exists anywhere
  in the resolution. A township-wide exclusion, recorded like St.
  Albans — its 184 unincorporated parcels FAIL the moratorium gate (six
  more, inside Kirkersville village, read UNKNOWN on the village's own
  unreviewed row), and the zoning gate now
  carries the removal where it belongs: a scoped `"M-1|Harrison":
  "prohibited"` district class in `2026-township-reviewed3`, because the
  flat M-1 by_right entry (true of other townships' resolutions) must
  not speak for Harrison's. Its PUD parcels remain special_exception —
  the amendment does not address planned developments.
- **Etna Township (Licking), August 2026** — a text amendment removing
  data centres from General Business districts only; the ordinance
  continues to allow them in industrial and overlay districts. NOT
  recorded as a township restriction: a district-level use-table fact,
  which the county mapping already carries (GB1 prohibited), so Etna
  reads none_found with the amendment documented in its basis. Failing
  Etna's industrial parcels on a GB-district amendment would be the
  wrong jurisdiction claiming the wrong land.
- **Jackson Township (Franklin), 2026-05-12** — one-year moratorium on
  new data-centre development in the unincorporated portions (the
  township's own community letter, corroborated by the Dispatch, 10TV,
  ABC6). expires_date 2027-05-12 is derived from the stated one-year
  term, so the gate re-opens by itself if no extension is recorded.
- **Pleasant Township (Franklin), 2026-02-24** — Resolution 11, "to put
  a moratorium on any building of data centers in Pleasant Township"
  (the township's own meeting highlights; vote reported 2-1). No
  duration appears anywhere in the record, so expires_date stays NULL
  rather than inferred: the moratorium stands until the township says
  otherwise.
- **Washington Township (Franklin), 2025-12-09** — 90-day moratorium,
  extended six months to 2026-09-05 (both in the township's own
  minutes). The Sept 8, 2026 agenda lists a further extension, but its
  minutes were not yet posted, so the extension is unrecorded and the
  verified record reads lapsed as of the run date: CONDITIONAL, the row
  surviving as the political-risk signal it is, to be re-dated when the
  minutes post.
- **Prairie Township (Franklin), 2026-04-15** — Resolution 18-26, a
  six-month suspension of every zoning-permit application for a data
  centre, expiring 2026-10-15 (the trustees' own signed resolution);
  permanent text amendments were still in process at review time.

The other 22 townships checked clear — none_found with their sources
listed, not unverified; nothing traceable was left dangling. Two
residual gaps are recorded in the rows themselves: Monroe's trustee
minutes sit behind a SharePoint link (its public-notices page, which
would legally have to advertise any zoning hearing, was checked
directly), and Sharon's Aug 11, 2026 hearing notice on unspecified
zoning changes 404'd before it could be read.

**Licking republished** (`2baaddac`, then `28fba0ec` with the
municipal-limits fix below): moratorium verdicts 1,645 PASS /
24 CONDITIONAL (Pataskala's pending ballot) / 184 FAIL (Harrison,
unincorporated) / 137 UNKNOWN — the UNKNOWNs being parcels inside
incorporated places (Newark, Heath, Granville village, Johnstown,
Kirkersville), whose municipal reviews are the follow-on batch.
Harrison's M-1 parcels read prohibited on the zoning gate under the
township's own resolution. Evidence coverage 0.811 → 0.903 of the
ten-gate set.

**Franklin republished** (`cbb1f32f`, then `3feeab22` with the fix):
180 PASS / 2 CONDITIONAL (Washington's lapsed pause, unincorporated) /
61 FAIL (Jackson 19 unincorporated, Pleasant 37, Prairie 5) / 739
UNKNOWN — every UNKNOWN sitting inside an incorporated city or village
(Columbus, Dublin, Grove City, Groveport, Gahanna, Hilliard, Obetz,
Worthington, Reynoldsburg, Whitehall, Westerville, Upper Arlington,
Bexley, Grandview Heights, Canal Winchester, Urbancrest), the
place-level follow-on batch. The county GIS endpoint went unreachable
mid-release and the pipeline refused to publish on screening cells
alone — the deactivation guard doing exactly its job — until it
returned.

**A fifth settled semantic, found on the first Franklin republish.**
The gate was applying a township's row to parcels inside municipal
limits — 34 Grove City and Urbancrest parcels inside Jackson township
read FAIL on a moratorium whose own letter says it covers "the
unincorporated portions" and that township limits "do not control land
once it is annexed into the city." A township's instruments stop at
municipal limits, the same scoping the unavailable-layer branch already
stated and the zoning gate practices: the township level is now carried
only by unincorporated parcels, so a parcel inside a place reads on its
county and place rows, never the township whose MCD contains it. Both
regions republished; six Kirkersville village parcels inside Harrison
township's MCD flipped from FAIL to UNKNOWN for the same reason, and
the regression test (`test_a_township_row_does_not_reach_inside_
municipal_limits`) pins the Grove City-in-Jackson shape. Worker suite
242.

**Dossier surfacing (task 3).** The client now fetches `details` with
each gate row and the moratorium gate renders its record under the
rationale: the adopting body and instrument, the adopted / effective /
expires dates (an instrument with no expiry says "no expiry recorded" —
a finding, not a blank), the scope, a link to the jurisdiction's own
record, reviewed and evaluation dates, and a per-level ledger showing
what the county, place and township reviews each found — so an UNKNOWN
verdict names exactly which level is unreviewed. Six new client tests
(43 passing); worker suite 242 with the municipal-limits regression.
