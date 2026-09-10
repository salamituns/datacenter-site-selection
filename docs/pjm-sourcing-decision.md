# PJM-footprint sourcing decision

**Decision:** the next parcel tiers come from the PJM footprint only — 13 states
plus DC — until PJM parcel coverage is complete. MISO next, ERCOT after. No new
regions outside the current interconnections in between.

## Why scoped to PJM, not to all 3,143 counties

1. **Power diligence does not port across interconnections.** `power_capacity`
   is UNKNOWN for 3,240/3,240 Taylor County, TX parcels for a structural
   reason: RTEP is a PJM artifact and Taylor County is ERCOT. A nationwide
   parcel table would surface verdicts that aren't comparable to each other —
   which breaks the cross-region comparison the screening map exists to make.
2. **One power-evidence pipeline amortizes over hundreds of counties.** The
   RTEP adapter (2,507 records live for VA, 3,270 for OH) and the PJM queue
   feed already work; every PJM county added after them reuses both unchanged.
3. **Validation cost scales with distinct sources, not parcels.** Three
   bespoke cadastre adapters so far (Loudoun, Franklin, Taylor) each surfaced
   latent defects no amount of Loudoun testing would have found. Staying
   inside one interconnection doesn't remove that cost, but it guarantees the
   *verdicts* it buys are comparable — which is the point of the expansion.

## What every county now gets for free (Release 9)

The federal layers are national, so a new PJM county starts with 6 of 9 gates
decidable before any county adapter is written:

| Gate | Source | Coverage |
| --- | --- | --- |
| floodway | FEMA NFHL federal REST (county mirror first) | every US county — 4,222 UNKNOWNs → 0 |
| protected_land | PAD-US 4.0 state geodatabase (combined inventory) | every state, per-state clip cache |
| wetlands | NWI REST + official state geodatabase fallback | every state |
| slope | 3DEP getSamples | every US county |
| road_access | TIGERweb + TIGER/Line county shapefile fallback | every US county |
| contiguous_acreage | parcel geometry | with the cadastre |

Remaining per-county work: the cadastral adapter, zoning use, a water-utility
boundary (rare — expect `water_availability` UNKNOWN initially), and curated
power evidence.

## Where in PJM, ranked

RTEP upgrade records by state (from the live PJM dataset, this session):

| State | Upgrades | Est. cost | Active |
| --- | --- | --- | --- |
| OH | 3,270 | $21.2B | 1,005 |
| PA | 2,959 | $18.5B | 670 |
| VA | 2,229 | $34.1B | 852 |
| NJ | 1,763 | $29.6B | 288 |
| WV | 981 | $9.1B | 342 |
| IN | 941 | $6.1B | 271 |
| IL | 849 | $9.4B | 126 |
| MD | 757 | $10.3B | 141 |
| KY | 483 | $1.9B | 146 |
| DE | 242 | $1.4B | 22 |
| MI | 183 | $1.2B | 60 |
| NC | 157 | $1.1B | 26 |
| TN | 26 | $0.2B | 2 |

**Tier 1 (next two parcel tiers):**

1. **Licking County, OH.** Cadastre empirically verified this session:
   `gis.lickingcounty.gov/server/rest/services/Auditor/Parcels/FeatureServer/0`
   — parcel boundaries joined with CAMA assessment nightly, the same shape as
   the proven Franklin adapter. New Albany–Intel hyperscale corridor, AEP
   Ohio, in the highest-upgrade state in PJM.
2. **Prince William County, VA.** ArcGIS Hub portal confirmed (Parcels, a
   Parcel Ownership Table with deed acreage, and an "Underdeveloped A1
   Parcels" layer that is practically a screening shortlist by itself). PW
   Digital Gateway thesis; Loudoun-adjacent, so utility/water regimes match
   patterns already handled.

**Tier 2 (probe before committing):**

- A Pennsylvania county — PA is PJM's #2 by upgrades and has a statewide
  parcel boundary layer on PASDA (state-layer leverage). Candidate: Luzerne
  (Berwick corridor). Needs a 30-minute cadastre probe first.
- Eastern WV panhandle (Berkeley/Jefferson) — cheap land, $9.1B of WV RTEP
  work, fibre-adjacent to Ashburn.

**Not now:** NJ/MD/DE (land-constrained), KY/TN/NC (PJM edge zones), MI/IN/IL
(border states, lower thesis priority). Franklin (OH) and Loudoun (VA) are
already live.

## Sequencing rules

- One county at a time, adapter-first (the Franklin pattern: one adapter, one
  contract, missing layer → UNKNOWN).
- The cadastre probe is the gating check: 30 minutes against the county's
  REST endpoint (fields present? acreage? assessment inline? id uniqueness?)
  before any pipeline work.
- Stop-loss after a Morrow-style hard block: if a county publishes nothing
  usable, record it and move to the next candidate — the evidence-coverage
  weighting already prices an undiligenced region honestly (OR now sits at
  0.0 coverage and cannot out-rank a diligenced one).

## Expected evidence coverage at launch

Licking County, day one: ~7 of 9 gates decidable (all federal layers + RTEP +
queue; zoning and water unknown until probed) → coverage ≈ 0.78, comparable to
Franklin's 0.772 today. Prince William: potentially 8 of 9 (zoning is
published) → ≈ 0.89, second only to Loudoun's 0.994.
