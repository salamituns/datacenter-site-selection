# Data Center Site Selection Engine

An end-to-end geospatial platform for siting **100+ MW hyperscale data centers**, built on a strict evidence discipline: every value in the decision layer is traceable to a named source, and **what is not known is shown as UNKNOWN — never invented**.

Two tiers run on the same map:

1. **Regional screening** — 10 km² fishnet cells scored on power, water, risk, and climate factors, clustered into Prime Development Zones (HIFLD / USGS / FEMA / NOAA live data).
2. **Parcel qualification** (Loudoun pilot) — cadastral parcels ≥20 acres run through **hard gates** (zoning use, floodway, wetlands, acreage, slope, protected land, road access) that return `PASS / CONDITIONAL / FAIL / UNKNOWN` with the rule, the affected-area percentage, and the source lineage behind every verdict.

```
 OPEN DATA                    INGESTION WORKER                  POSTGRES / SUPABASE              CLIENT
 ───────────                  ────────────────                  ────────────────────              ──────
 HIFLD grid      ─┐          screening cells ─┐                grid_parcels        ─┐
 USGS NWIS/PGA    ├─(fallback→┤ + scores       │  versioned,    map features         │ anon,
 NOAA ACIS       ─┘  marked)  └────────────────┤  staged runs   ─────────────────────┤ read-only
                                                  │                │
 Loudoun parcels  ─┐                            │  promote RPC   land_parcels        │ views
 Loudoun zoning    │          parcel metrics    ├─ (atomic, ──►  parcel_metrics     │
 county FEMAFlood  │          + gate verdicts   │  transaction) parcel_gates       │
 NWI wetlands      ├─(fail→    with evidence    │                source_snapshots   │
 PAD-US 4.0        │  UNKNOWN, ├────────────────┘                ingestion_runs     │
 3DEP DEM          │  never a  └─────────────────────────────────────────────────────┘
 TIGER roads      ─┘  default)                                          │
                                                                      ▼
                                                    Next.js dashboard — verdict-shaded
                                                    parcels, gate ledgers, evidence
                                                    classes, diligence checklists
```

---

## The Decision Model

**Four criterion kinds** govern a parcel:

| Kind | Examples | Output |
| :--- | :--- | :--- |
| Hard gate | zoning DC-use, floodway, wetlands, contiguous acreage, slope, protected land, road access | `PASS` / `CONDITIONAL` / `FAIL` / `UNKNOWN` |
| Scored factor | transmission/substation/road distances | metric values (never gates) |
| Verification-required | slope, protected land, road access, wetlands | `UNKNOWN` until the evidence layer lands — no favorable default |
| Informational | ordinance vintage, assembly potential | context metrics |

**Four states.** A parcel's overall status is `FAIL` if any gate fails, `UNKNOWN` if any gate is unknown, `CONDITIONAL` if any is conditional, `PASS` only when every gate passes. (During the current USFWS outage, no parcel can be overall `PASS` — wetlands gates are honestly `UNKNOWN`.)

**Evidence classes** tag every metric row: `observed` (fetched as-is), `derived` (computed from observations — overlaps, slopes, distances), `manual` (reviewed mapping such as the zoning use-table), `estimated` / `fallback` (regional screening models only — never allowed in the decision layer).

**Atomic, versioned ingestion.** Each run stages every layer, records a **source snapshot** per layer (endpoint, record count, evidence class, fetched-at), and publishes in a single transaction via `promote_ingestion_run()` — cells/features are replaced region-scoped, parcels are upserted, and the previous run is superseded. A failed run is recorded as `failed` and publishes nothing.

**Zoning rules are data, not code.** The Loudoun mapping (2023 ordinance + March 2025 ZOAM) lives in `constraint_rules`: by-right `PDGI/PDIP/GI/IP/MRHI`, special-exception `CLI/PDRDP/PDCH`, prohibited residential/commercial districts, `TOWNS` = town jurisdiction → `UNKNOWN`.

---

## Monorepo Structure

- **[`client/`](./client/)** — Next.js 14 + TypeScript + Tailwind + Leaflet. Regional screening dashboard **and** the parcel qualification view: verdict-shaded cadastral parcels, gate ledgers with rationales and affected areas, metrics with evidence class + source organization, unresolved-diligence checklists. Vitest suite (`npm test`).
- **[`worker/`](./worker/)** — Python geospatial pipeline (geopandas, scikit-learn, turf-equivalent browser parity). `pipeline.py` runs the full staged→promote lifecycle; `loudoun_api.py` fetches county cadastral/regulatory layers; `overlay_layers.py` fetches the verification layers (TIGER roads, PAD-US, 3DEP slopes); `parcel_gates.py` computes metrics and gate verdicts.
- **[`database/`](./database/)** — Supabase migrations + `tests/rls_tests.sql`, a repeatable allow/deny suite executed live as `anon` / `authenticated`.

---

## Data Sources

**Regional screening** layers degrade to a deterministic regional model when unreachable — the fallback is marked `fallback` in provenance and the UI shows the demo/PostGIS chip.

| Constraint | Live source | Stored metrics |
| :--- | :--- | :--- |
| Power proximity | HIFLD ArcGIS FeatureServers (lines ≥100 kV, named substations) | Interconnect / substation distances (mi), operator |
| Water availability | USGS NWIS (parameter 72019) | Water table depth, availability index |
| Seismic hazard | USGS ASCE 7-16 design service | Uniform-hazard PGA (g) |
| Flood/hurricane context | FEMA National Risk Index (counties) | County risk scores (context only) |
| Ambient cooling | NOAA ACIS GridData (PRISM normals) | CDD, mean temp, free-cooling hours |

**Parcel qualification** layers (Loudoun pilot) have **no fallback**: an unreachable layer yields `UNKNOWN` gates with an explicit rationale.

| Gate | Source | Notes |
| :--- | :--- | :--- |
| Zoning DC-use | Loudoun County GIS — Zoning Ordinance districts | Dominant district per parcel overlay; rules from `constraint_rules` |
| Contiguous acreage | Loudoun County GIS — Land Records parcels | County PIN + legal acreage; GIS acreage from planar geometry |
| Floodway / floodplain | Loudoun County GIS — FEMAFlood (FEMA DFIRM 51107C mirror) | County mirror used because the federal NFHL endpoint throttles county-sized envelope queries; identical `FLD_ZONE`/`ZONE_SUBTY`/`SFHA_TF` attributes |
| Wetlands | USFWS National Wetlands Inventory | Screening only; field delineation remains a diligence item |
| Protected land | USGS PAD-US 4.0 — official Virginia geodatabase (ScienceBase) | Downloaded once, clipped, cached in `worker/cache/`; hosted national ArcGIS layers are partial subsets |
| Slope | USGS 3DEP bare-earth DEM (`getSamples`) | Per-parcel elevation lattice → gradient-derived max/median slope % |
| Road access | Census TIGERweb — Transportation (S1100 primary, S1200 secondary) | Nearest suitable-road distance (mi) |

---

## Security Model (Release 0)

- **Anonymous API roles are read-only.** All write policies and write grants were revoked from `anon`/`authenticated`; ingestion requires the service role. Verified by `database/tests/rls_tests.sql` (all passing live).
- **`security_invoker` views throughout** — client views execute with the caller's RLS, so nothing is accidentally exposed through a view.
- **Staging tables are invisible to API roles** (401 over REST).
- The worker exits with an error if `SUPABASE_SERVICE_ROLE_KEY` is absent for a publishing run (dry-runs work without it).

---

## Survey Regions

| Region | County / Area | Grid operator | CLI |
| :--- | :--- | :--- | :--- |
| **Virginia (Loudoun)** — Data Center Alley *(parcel pilot)* | Loudoun County | PJM | `python pipeline.py --state VA` |
| **Texas (Abilene)** | Taylor County | ERCOT | `python pipeline.py --state TX` |
| **Ohio (New Albany)** | Franklin County | PJM | `python pipeline.py --state OH` |
| **Oregon (Boardman)** | Morrow County | BPA | `python pipeline.py --state OR` |

Ad-hoc surveys: `--bbox min_lon,min_lat,max_lon,max_lat --county <label>`. Parcel qualification currently runs for VA; other regions get screening only until their county layers land.

---

## Quick Start

### 1. Database (Supabase / PostGIS)

```bash
supabase db push        # applies database/migrations/ in order
psql "$DB_URL" -f database/tests/rls_tests.sql   # optional: run the RLS suite
```

Key migrations: provenance schema (`data_sources`, `ingestion_runs`, `source_snapshots`), parcel tables (`land_parcels`, `parcel_metric_values`, `parcel_gate_results`), staging + `promote_ingestion_run()` RPC, client views (`v_land_parcels_map`, `v_parcel_gates`, `v_parcel_metrics`), and the security lockdown.

### 2. Worker

```bash
cd worker && python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env    # set SUPABASE_URL + SUPABASE_SERVICE_ROLE_KEY

python pipeline.py --state VA --dry-run   # fetch + compute, publish nothing
python pipeline.py --state VA             # staged, atomically promoted
```

Publishing requires `SUPABASE_SERVICE_ROLE_KEY` (the anon key can no longer write, by design).

### 3. Client

```bash
cd client && npm install
npm test        # vitest: null-safety + prime-zone semantics
npm run dev     # http://localhost:3000
```

Environment: `NEXT_PUBLIC_SUPABASE_URL`, `NEXT_PUBLIC_SUPABASE_ANON_KEY` (in `.env.local` locally, per-environment on Vercel).

---

## CI/CD

- **Client** — Node 22 workflow: typecheck, vitest, production build on every push/PR touching `client/`.
- **Worker** — weekly scheduled ingestion (Sundays 00:00 UTC) plus manual dispatch with state/county/dry-run inputs; needs `SUPABASE_URL` + `SUPABASE_SERVICE_ROLE_KEY` secrets.
- **Production** — every push to `main` deploys to [grid.salamituns.com](https://grid.salamituns.com).
