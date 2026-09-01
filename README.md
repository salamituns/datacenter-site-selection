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
- **[`database/`](./database/)**: Supabase SQL migrations with PostGIS extensions, spatial tables (`grid_parcels`), spatial indexes (GiST), and spatial bounding-box RPC functions.

---

## Core Data Sources

| Constraint | Source | Purpose | Metric |
| :--- | :--- | :--- | :--- |
| **Power Proximity** | [HIFLD](https://hifld-geoplatform.opendata.arcgis.com/) (Homeland Infrastructure Foundation-Level Data) | Electric transmission lines (115kV+) & substations | Interconnect distance (miles), voltage capacity (kV) |
| **Water Availability** | [USGS NWIS](https://waterdata.usgs.gov/nwis) (`dataretrieval` Python SDK) | Groundwater depth & surface streamflow gauges | Aquifer depth (ft), surface water yield index |
| **Geological & Climate Risk** | [FEMA NRI](https://hazards.fema.gov/nri/) & [USGS Seismic Hazard](https://www.usgs.gov/programs/earthquake-hazards/hazards) | Flood, hurricane, and earthquake risk | Peak Ground Acceleration (PGA), FEMA flood recurrence |
| **Ambient Temperature** | [NOAA NCEI](https://www.ncei.noaa.gov/) | Historical temperature and climate normals | Cooling Degree Days (CDD), free cooling potential |

---

## Quick Start

### 1. Database Setup (Supabase / PostGIS)
Apply the migration in [`database/migrations/20260831000000_init_postgis_parcels.sql`](./database/migrations/20260831000000_init_postgis_parcels.sql) to your Supabase project:
```bash
# Using Supabase CLI
supabase db push
```

### 2. Python Worker (Data Ingestion & ML Pipeline)
```bash
cd worker
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env

# Run full ingestion, scoring, and clustering pipeline
python pipeline.py
```

### 3. Next.js Dashboard Client
```bash
cd client
npm install
npm run dev
```
Open [http://localhost:3000](http://localhost:3000) to access the interactive site selection dashboard.
