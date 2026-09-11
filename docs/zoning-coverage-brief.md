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

**Recommended: 2, conditional on Task 3 below.** Absence of a prohibition is a
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
