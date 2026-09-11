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
