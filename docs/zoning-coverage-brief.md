# Zoning coverage — finishing the use tables, and one decision

`zoning_dc_use` is UNKNOWN on 4,490 parcels. That is one gate key with three
unrelated causes, and conflating them has been hiding the cheap fix:

| cause | parcels | fix |
| --- | --- | --- |
| A. No zoning layer covers the parcel (Taylor 3,240, Franklin 982, Licking 105) | 4,327 | **a decision, below** — and a zoning layer for Franklin |
| B. Inside an incorporated town (Loudoun 52, Prince William 6) | 58 | TIGER/Line Places, then each town's ordinance |
| C. District not in the reviewed use table | 105 | **read the ordinance — no new data, no new code** |

Category C is the whole of this brief's first task. It needs no layer, no
adapter and no migration beyond `constraint_rules` rows.

---

## Task 1 — classify 14 districts

| county | district | parcels | acres |
| --- | --- | --- | --- |
| Prince William | `FED` | 32 | **41,121** |
| Prince William | `PMD` (Planned Mixed Use) | 11 | 507 |
| Prince William | `SR-1C` | 10 | 423 |
| Prince William | `A-1C` | 7 | 482 |
| Prince William | `R-4C` | 7 | 175 |
| Licking | `C-1` | 20 | 1,037 |
| Licking | `HMU-NWIOD` | 4 | 143 |
| Licking | `MUDOD` | 3 | 109 |
| Licking | `MU-NEOD`, `MCOB`, `CPO-W`, `MCOA` | 1 each | 126 |
| Loudoun | `PDSA` (Planned Development–Special Activity) | 3 | 722 |
| Loudoun | `PDMUB` (Planned Development–Mixed Use Business) | 2 | 231 |

Three of these are not simple lookups.

### `FED` — 41,121 acres, and already correctly disqualified

Federal land; Quantico sits in Prince William. PAD-US already returns
**FAIL on `protected_land` for all 32**, so the overall verdict is right and
this is not a wrong answer being shown to anyone.

It is still worth fixing, for one reason: those 32 UNKNOWN gates drag Prince
William's evidence coverage down for a district the county's own ordinance
defines. The land is federal, the ordinance says so, and "we don't know" is
the one thing that is not true about it.

Map it to `prohibited`. The rationale should name the ordinance district, not
PAD-US — two independent sources agreeing is the point, not a duplication to
be collapsed.

### `A-1C`, `R-4C`, `SR-1C` — proffered conditional districts

Standard Virginia practice: the `C` suffix marks a district rezoned with
proffers. The base use permissions are those of `A-1`, `R-4`, `SR-1`, all of
which are **already mapped**. Confirm that reading against the ordinance and
then classify each `-C` variant as its base district.

Do not pattern-match the suffix in code. Add explicit rows, so a future
district ending in C that means something else cannot be swept in by a rule
nobody wrote down.

### Licking's overlays — the one that is a data problem, not a mapping problem

`HMU-NWIOD`, `MUDOD`, `MU-NEOD`, `MCOA`, `MCOB`, `CPO-W` are all **overlay**
districts — their own names say so. An overlay does not replace a base
district; it modifies it. If the adapter is emitting the overlay code in the
`zone` field, **the base district is being lost**, and classifying the overlay
would be answering a different question from the one the gate asks.

Check the source layer first. If base and overlay are separate attributes, the
gate should read the base and carry the overlay as context. If the county
genuinely publishes only the overlay for these parcels, then the honest
verdict stays UNKNOWN and the reason is worth recording as such.

### Licking `C-1` — one code, two districts

`C-1` appears with two different names: "Conservation District" and "Local
Commercial District". Those are opposite answers for a data centre. Whichever
way the 20 parcels split, a single `C-1` row in the use table would be wrong
for some of them. Disambiguate before classifying — most likely these are
different townships' ordinances sharing a code, which is exactly the collision
the Prince William brief warned about between counties, appearing one level
further down.

---

## Task 2 — a decision, not an implementation

**Taylor County's 3,240 parcels are UNKNOWN on zoning because Texas counties
have no zoning authority.**

Texas counties generally may not adopt comprehensive zoning in unincorporated
areas. Local Government Code ch. 231 grants it only to specific named counties
— Cameron and Willacy, for parts of Padre Island. Taylor is not among them.
County regulatory power over unincorporated land is limited to subdivision
platting, septic, floodplain, nuisance and roads.

So the current verdict is not merely unhelpful, it is **inaccurate**. The gate
asks whether zoning permits a data-centre use. We are answering "unknown" when
the answer is known: *no county zoning applies at all.*

Three ways to read it:

1. **Leave UNKNOWN.** Defensible only if the gate means "has a use table been
   reviewed", which is not what it claims to mean.
2. **PASS, with the statute cited.** "Texas counties have no general zoning
   authority over unincorporated land (Local Government Code ch. 231); no
   county zoning restriction applies." True, and it would move Taylor's
   coverage from 0.666 toward ~0.78.
3. **A distinct not-applicable verdict.** Most precise, and the most
   expensive: it means a fifth gate status, a CHECK constraint change, and
   every consumer of `GateStatus` learning a new case.

**Superseded — see the decision below.** (Originally recommended: 2.) Absence of a prohibition is a
genuine PASS on the question this gate asks. But it must be paired with the
caveat in the rationale — no zoning also means no zoning *protection*, which
is why unzoned counties are where moratoria and targeted ordinances appear.
That is the moratorium gate's job, not this one's, and the two should ship
close together so the map never shows an unqualified green where the real
answer is "nothing stops you yet".

**This is a judgement call about what the product claims, and it moves 3,240
parcels. It needs the owner's decision, not an implementer's.**

---

## Task 3 — the prerequisite for both B and 2

A parcel inside Abilene's city limits **does** have zoning; a parcel in
unincorporated Taylor County does not. The Texas rule cannot be applied
safely without telling those apart, and that is the same TIGER/Line Places
join the moratorium gate needs.

So the order is:

| # | task | blocked by |
| --- | --- | --- |
| 1 | classify the 14 districts (category C) | nothing — do this first |
| 2 | TIGER/Line Places join | nothing |
| 3 | Texas no-zoning-authority rule | 2, and the owner's decision |
| 4 | town ordinances for the 58 (category B) | 2 |
| 5 | moratorium gate | 2 |


---

## DECIDED — Taylor reads CONDITIONAL, not PASS

Owner approved the recommendation on the condition that it be the
best-practice reading. Tested against that, the original recommendation was
wrong in one respect, so it is revised here rather than implemented as given.

**Verdict: `CONDITIONAL`.** Rationale, to carry the citation:

> No county zoning applies: Texas counties have no general zoning authority
> over unincorporated land (Local Government Code ch. 231, which grants it
> only to specific named counties). No zoning restriction prohibits a data
> centre here. Confirm the parcel's extraterritorial-jurisdiction status with
> the nearest municipality — a city's ETJ reaches 0.5 to 5 miles beyond its
> limits depending on population, carries subdivision-platting and permitting
> authority without zoning, and annexation would bring zoning with it.

### Why not PASS

A Loudoun `PDGI` PASS means *an adopted ordinance affirmatively permits this
use*. An unincorporated Taylor "PASS" would mean *no ordinance exists to
prohibit it*. Both would render as the same green badge, and they are not the
same claim: the first is a durable legal permission, the second is an absence
of regulation that an annexation vote can end.

That conflation is the one this engine has refused twice already — screening
tier against parcel tier, and zero against absent. Letting it back in through
the zoning gate, at national scale, for every unzoned county in the country,
would undo the principle in the place it matters most.

### Why CONDITIONAL costs nothing to prefer

* **Coverage is identical.** `evidence_coverage` counts *decided*, not
  *passed* — `decided = status <> 'UNKNOWN'`. Taylor moves 0.666 toward ~0.78
  either way.
* **No overall verdict changes.** Taylor parcels also hold `water_availability`
  and `power_capacity` at UNKNOWN, so `overall_status` stays UNKNOWN whichever
  is chosen. The decision is purely about what the gate itself claims.
* **It names a real diligence item.** ETJ status and annexation exposure are
  genuine, checkable, and specific to this situation — which is what
  CONDITIONAL is for, as against PASS's "nothing further to do".

So the choice has no functional cost and one real benefit: the badge means
what it says.

### Precedent

This rule is not about Taylor. Much of rural America is unzoned, and every
future county in an unzoned state will hit it. Fixing the reading now, once,
sets the precedent correctly before it is applied 3,000 times.

Still conditional on Task 3: the rule may only be applied to parcels confirmed
**outside** incorporated limits. A parcel inside Abilene has city zoning, and
sweeping it in with this rationale would be exactly the borrowed-verdict error
the Prince William brief was written to prevent.

---

## Shipped — both tasks, and one stale verdict fixed on the way

Migration `20260912100000_release15_zoning_coverage.sql`; worker changes in
`parcel_gates.py`, `overlay_layers.py`, `pipeline.py`, `runs.py`; rule
versions are new rows (append-only — old gate rows keep the rule ids that
actually decided them; loaders now read the newest version per gate in
`created_at` order instead of trusting return order).

### Task 1 — the 14 districts, each read from its own ordinance

| county | district | verdict | basis |
| --- | --- | --- | --- |
| PW | `FED` (32) | FAIL | No FED district exists in Ch. 32 — it is the county's own GIS label ("FED Federal Property"). Prohibited via the exclusive-use rule, Sec. 32-200.03(a); "data center" appears in no use table covering federal land. Cites the county's designation, not PAD-US, which independently FAILs these parcels on protected_land. |
| PW | `A-1C` (7), `R-4C` (7), `SR-1C` (10) — and `R-2C`, `SR-3C`, `SR-5C` for completeness | FAIL | **Correction: the `-C` suffix is CLUSTER, not proffered conditional zoning.** GIS domain "Agricultural Cluster"/"Cluster Residential"; Secs. 32-300.40/.50/.60 govern lot design and density only, adding no uses; Parts 301–304 list no data center, so 32-200.03(a) prohibits. Explicit rows per variant — no pattern-matching. |
| PW | `PMD` (11) | UNKNOWN, reason sharpened | Verified mechanism: uses follow the land bay under the approved master zoning plan (Secs. 32-405.03/32-280.11/32-700.23(5)). The land bays ARE published — in the county's separate Planned Districts layer (Planning/Zoning MapServer/8) — but as plan-specific free-text designations (`RC1/OC3`, `ResML`, `B-1/B-2/O(L)(M)(H)(F)/M-2`…), and each of the 11 parcels spans multiple bays. Resolving one needs that parcel's approved master plan; a use-table row would be a guess. |
| Licking | `C-1` (20) | FAIL | Scoped per township — Conservation in Granville (§801/§903), Bennington (Art. 305), Harrison (Art. 11), Hartford (Art. 7), Newark (Art. 11), Madison (Art. 7): exclusive floodplain-conservation use lists. Liberty's "C-1 Local Commercial" label matches no findable version of Liberty's resolution (2022 and 2025/26 both use LB, §806) — prohibited by omission there too. Prohibited either way; recorded separately so a future township's C-1 can never be decided by another township's ordinance. |
| Licking | `IE-W` (5), `MCOA`/`MCOB` (1 each) | CONDITIONAL | Overlay read over the base (see below): "Data Processing Centers" is an expressly permitted use in the WCOD IE subarea (§14.05.F.1) and MCOD Subareas A/B (§14.06.F.1 Table 1, "P") — but only after the township approves a Development Plan, which is a CONDITIONAL, not a by-right. |
| Licking | `HMU-NWIOD` (4), `MU-NEOD`, `CPO-W`, (1 each) | FAIL | No data-processing use in NWIOD §14.11 / NEOD §14.10 / WCOD CPO tables; each article prohibits unlisted uses. |
| Licking | `MUDOD` (3) | UNKNOWN, reason recorded | MUDOD's adopted text (Exhibit A of Resolution 25-04-07-01, 4/7/2025) is not published; the predecessor MUOD set uses case-by-case per district. UNKNOWN rather than a guess from the predecessor. |
| Loudoun | `PDSA` (3), `PDMUB` (2) | FAIL | Table 3.02.02-1 (legacy suburban districts) row 101 is blank in both columns; blank = prohibited per the table key. ZOAM-2024-0001 touched only Sec. 3.02.05, not the legacy table. |

### The Licking overlay fix (the data problem the brief flagged)

The brief's suspicion was right and worse than stated: Jersey Township
publishes overlays as separate features **on top of** a base district
(`ZoningOverlay='Y'`), and the dominant-district join let the overlay win and
lose the base — all 16 affected parcels sit on RR/RR-3 (one on PUD). The gate
now reads the **base** as the parcel's district, carries township and overlay
codes as context, and the rule row classifies combinations explicitly
(`overlay_classes`), with an unreviewed overlay holding the verdict at UNKNOWN
rather than letting the base's class stand for a combination nobody reviewed.
Every mapped overlay verdict names both districts.

### The regression that first publish exposed — slivers and standards-only overlays

Publishing Licking (run `a6b8d2e9`) and diffing against the previous run
found the overlay read holding 33 decided parcels at UNKNOWN. Measuring each
touch against the county's live layer split them into three findings, each
with its own fix:

* **Boundary slivers.** Liberty's TC corridor overlay clips 19 parcels at
  **0.9–13.9%** of their area; the stale MUOD footprints clip two more at
  1.0–1.4%; MCOB clips one at 1.8%. A touch is not membership. Overlays now
  participate only at **≥5% coverage** — the same meaningful-coverage line
  the legislative-application read draws between an approved footprint and
  boundary noise. Shares are summed per overlay code (a code drawn as
  several features counts once, at its combined footprint) and recorded in
  the verdict's details.
* **Standards-only overlays.** The TC slivers were only the symptom; reading
  Liberty's §811 settled the substance: TC (Transportation Corridor) does
  not modify uses at all — its entire use language is *"Any permitted use
  allowed in the underlying zoning district"*, and the rest of the article
  is corridor setbacks, access, screening, signage and Technical Review
  Committee site-plan review. FP (§810, *"The base district shall determine
  uses and minimum requirements"*) is the same. Both are now
  `standards_only_overlays` in the rule row: carried as context with the
  citation, never deciding or holding. The prior row had listed TC as
  deliberately unmapped pending a read — the read happened, and it says
  otherwise.
* **Genuine overlay coverage.** The parcels inside MUDOD (and the stale MUOD
  polygons over the same footprints) measure **~100% covered** — UNKNOWN is
  the honest verdict there until Resolution 25-04-07-01's Exhibit A text
  surfaces, and it stays.
* **A classifier bug the diff exposed.** Where mapped overlays disagree,
  the rule is the most restrictive wins — the code shipped with `min()`
  over the restrictiveness order, i.e. the most *permissive* reading of a
  combination nobody reviewed as a whole. It surfaced as a Jersey parcel
  reading CONDITIONAL off a prohibited CPO-W overlay paired with a
  special_exception IE-W one (the single-overlay cases were unaffected,
  which is why the tests passed). Now `max()`, and `deciding_overlays`
  names only the overlays carrying the winning class.

Rule version `2026-township-reviewed2` (migration
`20260912110000_release15b_overlay_floor.sql`; the `a6b8d2e9` row kept
unchanged — append-only, so its gate rows still cite the rule that actually
decided them). Republished twice: once for the floor and standards-only
read (19 UNKNOWN→FAIL on the TC parcels, one MCOB sliver, 4 sub-5% IE-W
touches correctly tightening CONDITIONAL→FAIL), then once for the
restrictiveness fix (the CPO-W/IE-W parcel, CONDITIONAL→FAIL). Final Licking
zoning split: 54 PASS / 28 CONDITIONAL / 1,793 FAIL / 115 UNKNOWN.

### Task 2/3 — Taylor reads CONDITIONAL, gated on measured municipal limits

`fetch_places` (TIGERweb Places layer 4, MTFCC G4110 — CDPs excluded because
a CDP is unincorporated and has no zoning authority; TIGER/Line state PLACE
shapefile fallback; state clip cache like roads). A present-but-empty layer is
a real answer ("no cities here"), never None — None means unavailable, and an
unavailable layer holds the Texas rule at UNKNOWN rather than assume
unincorporated. Measured on Taylor's 3,240 candidates: **559 parcels lie
majority-inside an incorporated place** (Abilene, Merkel, Clyde, Tuscola, Tye,
Impact, Buffalo Gap) and stay UNKNOWN with the place named; **2,681 read
CONDITIONAL** with the ch. 231 rationale quoted verbatim from the rule row.
Taylor's evidence coverage moved 0.666 → **0.758**, the brief's own
projection; no overall verdict moved (UNKNOWN outranks CONDITIONAL). The
`incorporated_place` metric is recorded for every region, which is also the
prerequisite for category B (the 58 town parcels) and the moratorium gate.

### The stale verdict found on the way — Loudoun's by-right list

The brief's Task 1 scope was UNKNOWNs, but reading Loudoun's ordinance to
classify PDSA/PDMUB found the existing rule row **wrong about parcels already
showing green**: ZOAM-2024-0001 (adopted 3/18/2025) amended Sec. 3.02.05 so
the Data Center row of Table 3.02.05-1 reads **S in OP, IP, GI and MR-HI** —
no district in Loudoun permits a data center by right any more. The screening
row still carried GI/IP/MRHI (and PDGI/PDIP) as by-right. The reviewed row
fixes it: `by_right` is now empty (an empty list is a finding), IP/GI/MRHI
(119 parcels previously PASS) and OP (26 parcels previously FAIL) all read
CONDITIONAL. PDGI/PDIP are not current-ordinance districts at all — they are
1972-Ordinance districts surviving only inside the Route 28 Tax District
(current ordinance Sec. 1.02.K.1), where "data center" is not a listed use
(nearest categories: R&D by right; Warehousing/Commercial office building by
right in PD-GI §723.3.1 but only Board-permissible in PD-IP §722.3.2; actual
uses locked to approved site development plans, §700.5.6.2) — so a §501.1
county determination is required: CONDITIONAL. All citations in the rule
row's description; republished.

### Verification

Worker suite 213 tests (new: base-vs-overlay read, unreviewed-overlay UNKNOWN,
township-scoped C-1, overlay-decides-over-base with most-restrictive-wins
over disagreeing overlays, sliver-overlay non-participation,
standards-only-overlay base decision with citation, standards-only context
on a held verdict, Taylor outside/inside/unavailable-places,
rule-never-fires-with-a-layer). Dry runs of
all four regions, then live republishes. Post-publish queries verified the
verdict flips parcel by parcel: Loudoun IP 57 / GI 40 / MRHI 22 / OP 26 all
CONDITIONAL (by-right list now empty), PDGI 1 + PDIP 3 CONDITIONAL, PDSA 3 +
PDMUB 2 FAIL; Prince William FED 32 FAIL, A-1C 7 / SR-1C 10 / R-4C 7 FAIL,
PMD 11 UNKNOWN with the master-plan reason; Taylor 2,681 CONDITIONAL + 559
UNKNOWN-inside-a-place, coverage 0.666 → 0.758; Licking diffed run over run
(the table above).
