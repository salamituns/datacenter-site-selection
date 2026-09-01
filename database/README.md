# Database & PostGIS Setup 🗺️🐘

This directory contains the PostGIS SQL schema and migrations for the **AI Data Center Site Selection Engine**.

## Schema Overview

- **`grid_parcels`**: Stores 10-square-kilometer parcel polygons (`geom`) and centroids (`centroid`) with evaluated constraints:
  - **Power Grid Proximity**: Distance to 115kV+ transmission lines, nearest substation voltage, grid operator.
  - **Water Availability**: Groundwater well depth, surface water proximity, normalized availability index.
  - **Geological & Climate Risk**: Peak Ground Acceleration (PGA) seismic hazard, FEMA flood & hurricane risk.
  - **Ambient Temperature**: Annual Cooling Degree Days (CDD), economizer free-cooling hours.
  - **Scoring & ML Clustering**: Sub-scores (Power, Water, Risk, Climate), Composite Score (0–100), DBSCAN/K-Means cluster IDs, and Prime Zone flags.

## Spatial Functions

- `get_parcels_in_bbox(...)`: Retrieves parcel polygons within a dynamic map viewport bounding box as GeoJSON.
- `get_prime_cluster_polygons()`: Aggregates contiguous parcel polygons (`ST_UnaryUnion`) to render unified Prime Zone boundaries on the frontend map.

## Applying Migrations to Supabase

### Option A: Using Supabase CLI (Recommended)
```bash
# Link project
supabase link --project-ref <your-project-id>

# Apply migrations
supabase db push
```

### Option B: Using Supabase Dashboard SQL Editor
1. Open your project on [database.new](https://database.new) or [supabase.com/dashboard](https://supabase.com/dashboard).
2. Navigate to **SQL Editor** -> **New query**.
3. Copy and paste the contents of [`migrations/20260831000000_init_postgis_parcels.sql`](./migrations/20260831000000_init_postgis_parcels.sql).
4. Run the query.
