# Data Center Site Selection Engine

An end-to-end geospatial intelligence and machine learning platform to evaluate, score, and rank **10-square-kilometer parcel grids** for **100+ Megawatt hyperscale data centers**.

```
                           AI DATA CENTER SITE SELECTION ENGINE
 ┌─────────────────────────────────────────────────────────────────────────────────────────┐
 │                                                                                         │
 │   OPEN DATA SOURCES             DATA INGESTION & ML WORKER            STORAGE & API     │
 │  ┌─────────────────────┐       ┌─────────────────────────────┐       ┌────────────────┐ │
 │  │ HIFLD Transmission  │──────>│ GeoPandas Spatial Fishnet   │──────>│ PostGIS /      │ │
 │  │ & Substations (GIS) │       │ 10 km x 10 km Tessellation  │       │ Supabase       │ │
 │  └─────────────────────┘       └──────────────┬──────────────┘       │ Spatial DB     │ │
 │  ┌─────────────────────┐                      │                      └───────┬────────┘ │
 │  │ USGS NWIS Water     │──────────────────────┤                              │          │
 │  │ (dataretrieval)     │                      │                              │          │
 │  └─────────────────────┘                      ▼                              │          │
 │  ┌─────────────────────┐       ┌─────────────────────────────┐               │          │
 │  │ FEMA NRI Flood /    │──────>│ Multi-Factor Weighted       │               │          │
 │  │ USGS Seismic Maps   │       │ Constraint Scoring Engine   │               │          │
 │  └─────────────────────┘       └──────────────┬──────────────┘               │          │
 │  ┌─────────────────────┐                      │                              │          │
 │  │ NOAA Climate /      │──────────────────────┤                              │          │
 │  │ Cooling Degree Days │                      ▼                              │          │
 │  └─────────────────────┘       ┌─────────────────────────────┐               │          │
 │                                │ Scikit-learn Clustering     │───────────────┘          │
 │                                │ (DBSCAN / K-Means Zones)    │                          │
 │                                └─────────────────────────────┘                          │
 │                                                                                         │
 └───────────────────────────────────────────┬─────────────────────────────────────────────┘
                                             │
                                             ▼
                             ┌───────────────────────────────┐
                             │    NEXT.JS WEB DASHBOARD      │
                             │  - Interactive PostGIS Layers │
                             │  - Multi-Factor Sliders       │
                             │  - Ranked 100+ MW Parcels     │
                             │  - Prime Development Clusters │
                             └───────────────────────────────┘
```

---

## Monorepo Structure

- **[`client/`](./client/)**: Next.js 14+ frontend with TypeScript, Tailwind CSS, Lucide icons, and an interactive geospatial dashboard for rendering PostGIS map layers and constraint weighting controls.
- **[`worker/`](./worker/)**: Python geospatial data pipeline using `geopandas`, `scikit-learn`, `dataretrieval`, and `supabase` to ingest open data, compute multi-criteria suitability scores, and cluster contiguous parcels into Prime Development Zones.
- **[`database/`](./database/)**: Supabase SQL migrations with PostGIS extensions — parcel grids (`grid_parcels`), persisted map features (`transmission_lines`, `substations`, `observation_wells`), spatial indexes (GiST), and client-facing GeoJSON/lon-lat views.

---

## Core Data Sources

Every constraint layer is ingested from a live public API per survey region. When a service is unreachable, the pipeline degrades to a deterministic regional model for that layer only — it never hard-fails.

| Constraint | Live Source | What Is Fetched | Stored Metric |
| :--- | :--- | :--- | :--- |
| **Power Proximity** | [HIFLD](https://hifld-geoplatform.opendata.arcgis.com/) ArcGIS FeatureServers — `Electric_Power_Transmission_Lines` & `Electric_Substations` | In-service AC lines (≥100 kV, voltage-normalized) and named transmission substations, bounded to the survey bbox | Interconnect distance (mi), substation name / voltage (kV), grid operator |
| **Water Availability** | [USGS NWIS](https://waterdata.usgs.gov/nwis) (`dataretrieval` SDK + REST) | Groundwater level observations (parameter 72019) per survey bbox | Water table depth (ft), availability index; well sites are persisted for the map |
| **Seismic Hazard** | [USGS ASCE 7-16 Design Web Service](https://earthquake.usgs.gov/ws/design/) (`/ws/building-codes/asce7-16/calculate`) | Uniform-hazard Peak Ground Acceleration (2% probability of exceedance in 50 years, site class BC, risk category III) per grid centroid, cached at ~11 km precision | PGA (g) |
| **Flood & Hurricane Risk** | [FEMA National Risk Index](https://hazards.fema.gov/nri/) — `National_Risk_Index_Counties` layer | County-level riverine + coastal flood and hurricane risk percentiles (0–100); flood = max of the two modes, hurricane nulls preserved as 0 | FEMA flood / hurricane risk scores |
| **Ambient Cooling** | [NOAA ACIS](https://www.rcc-acis.org/) `GridData` (PRISM) | 30-year climate normals at each parcel centroid | Cooling Degree Days (base 65°F), mean ambient temp, free-cooling hours |

The worker also persists the raw HIFLD line/substation geometries and NWIS well sites per region, so the dashboard draws the real transmission corridors, substation markers, and observation wells on the map — no demo overlays.

---

## Survey Regions

The region selector in the dashboard maps to pipeline presets (bbox, county label, and regional grid operator):

| Region | County / Area | Grid Operator | CLI |
| :--- | :--- | :--- | :--- |
| **Virginia (Loudoun)** — Data Center Alley | Loudoun County | PJM Interconnection | `python pipeline.py --state VA` |
| **Texas (Abilene)** — Stargate / CTLV corridor | Taylor County | ERCOT | `python pipeline.py --state TX` |
| **Ohio (New Albany / Columbus)** | Franklin County | PJM Interconnection | `python pipeline.py --state OH` |
| **Oregon (Boardman / Umatilla)** | Morrow County | Bonneville Power Administration | `python pipeline.py --state OR` |

Ad-hoc surveys are supported with `--bbox min_lon,min_lat,max_lon,max_lat --county <label>`. Re-ingesting a region replaces its parcels and map features in place.

---

## Quick Start

### 1. Database Setup (Supabase / PostGIS)
Apply the migrations in [`database/migrations/`](./database/migrations/) to your Supabase project, in order:
```bash
# Using Supabase CLI
supabase db push
```
- `20260831000000_init_postgis_parcels.sql` — PostGIS extension, `grid_parcels`, spatial indexes, bbox RPCs
- `20260902000000_map_features.sql` — `transmission_lines`, `substations`, `observation_wells` + client views

### 2. Python Worker (Data Ingestion & ML Pipeline)
```bash
cd worker
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env

# Ingest a region (defaults to Loudoun VA); re-runs replace that region in place
python pipeline.py --state TX
```
The worker reads `SUPABASE_URL` plus `SUPABASE_SERVICE_ROLE_KEY` (preferred) or `SUPABASE_KEY` (the anon key also works under the default RLS policies) from `worker/.env`.

### 3. Next.js Dashboard Client
```bash
cd client
npm install
npm run dev
```
Open [http://localhost:3000](http://localhost:3000) to access the interactive site selection dashboard.

## Deployment (CI/CD)

The dashboard deploys to Vercel automatically from this repository:

- **Production**: every push to `main` deploys to [datacenter-site-selection-salamituns-projects.vercel.app](https://datacenter-site-selection-salamituns-projects.vercel.app)
- **Previews**: every pull request gets a SSO-protected preview URL

The Next.js app lives in `client/`, which is configured as the Vercel root directory. The build requires two environment variables (set per-environment in Vercel, never in source):

| Variable | Purpose |
| :--- | :--- |
| `NEXT_PUBLIC_SUPABASE_URL` | Supabase project URL (PostGIS) |
| `NEXT_PUBLIC_SUPABASE_ANON_KEY` | Public client key (protected by row-level security) |

Local development reads the same variables from `client/.env.local`.
