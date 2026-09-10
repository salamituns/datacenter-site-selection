# Geospatial Data Ingestion & ML Worker 🐍⚙️

Python geospatial processing engine and unsupervised machine learning clustering pipeline for 100+ MW hyperscale data center site selection.

## Modules

- **[`water_api.py`](./water_api.py)**: Pulls groundwater levels (parameter `72019`) and streamflow observations directly from USGS National Water Information System via the `dataretrieval` package.
- **[`grid_parser.py`](./grid_parser.py)**: Generates 10-square-kilometer parcel fishnets (`shapely` + `geopandas`), intersects HIFLD 115kV+ transmission lines & substations, FEMA flood/hurricane risk, USGS seismic hazard (PGA), and NOAA Cooling Degree Days (CDD). Computes multi-factor weighted suitability scores.
- **[`clustering_model.py`](./clustering_model.py)**: Uses `scikit-learn` unsupervised clustering (DBSCAN / K-Means) to detect contiguous high-suitability parcels and group them into named **Prime Development Zones**.
- **[`pipeline.py`](./pipeline.py)**: CLI entrypoint orchestrating data ingestion, scoring, clustering, and PostGIS batch synchronization into Supabase.

## Getting Started

```bash
# 1. Create and activate virtual environment
python3 -m venv .venv
source .venv/bin/activate

# 2. Install dependencies
pip install -r requirements.txt

# 3. Configure environment variables
cp .env.example .env

# 4. Run pipeline
# Dry run mode (outputs local GeoJSON, no DB sync):
python pipeline.py --dry-run --region VA-LOUDOUN

# Live mode (syncs directly to Supabase PostGIS):
python pipeline.py --region VA-LOUDOUN
```
