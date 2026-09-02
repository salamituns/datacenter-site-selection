"""
Data Ingestion & Machine Learning Pipeline Runner
-------------------------------------------------
Orchestrates:
1. Geospatial fishnet generation (10 km² parcel tessellation).
2. Live API ingestion:
   - USGS National Water Information System (`dataretrieval` / NWIS REST)
   - NOAA NCEI / ACIS Climate Normals & Cooling Degree Days (CDD)
   - HIFLD 115kV+ Transmission lines & Substations
   - FEMA NRI Flood / Hurricane & USGS Seismic Hazard PGA
3. Multi-factor constraint suitability scoring.
4. Scikit-learn unsupervised spatial clustering (DBSCAN / K-Means) for Prime Development Zones.
5. PostGIS batch synchronization to Supabase.
"""

import os
import sys
import argparse
import logging
from typing import Dict, Any, List, Optional, Tuple
from dotenv import load_dotenv
import pandas as pd
import geopandas as gpd

from water_api import USGSWaterAPI
from climate_api import NOAAClimateAPI
from grid_parser import GridParser
from clustering_model import SiteClusteringModel
from hifld_api import HIFLDPowerAPI
from hazard_api import HazardAPI

load_dotenv()

# Survey region presets — bbox (min_lon, min_lat, max_lon, max_lat), county
# label, and the regional grid operator attached to ingested parcels.
# Targets are real hyperscale corridors: Abilene (Stargate/CTLV, ERCOT),
# the New Albany/Columbus corridor (PJM), and Boardman/Umatilla (BPA).
REGION_PRESETS: Dict[str, Dict[str, Any]] = {
    "VA": {
        "bbox": (-77.85, 38.75, -77.25, 39.25),
        "county": "Loudoun",
        "grid_operator": "PJM Interconnection",
    },
    "TX": {
        "bbox": (-100.05, 32.15, -99.45, 32.75),
        "county": "Taylor",
        "grid_operator": "ERCOT",
    },
    "OH": {
        "bbox": (-83.15, 39.85, -82.55, 40.35),
        "county": "Franklin",
        "grid_operator": "PJM Interconnection",
    },
    "OR": {
        "bbox": (-120.05, 45.55, -119.45, 46.15),
        "county": "Morrow",
        "grid_operator": "Bonneville Power Administration",
    },
}

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s"
)
logger = logging.getLogger("pipeline")


def run_pipeline(
    min_lon: float = -77.85,
    min_lat: float = 38.75,
    max_lon: float = -77.25,
    max_lat: float = 39.25,
    state_code: str = "VA",
    county_name: str = "Loudoun",
    grid_operator: str = "PJM Interconnection",
    dry_run: bool = False,
    output_geojson: Optional[str] = None
) -> Tuple[gpd.GeoDataFrame, Dict[int, Dict[str, Any]]]:
    """Executes the complete site selection data ingestion, ML clustering, and PostGIS sync."""
    logger.info("=" * 75)
    logger.info("⚡ STARTING AI DATA CENTER SITE SELECTION ENGINE PIPELINE ⚡")
    logger.info(f"Target Region: {county_name} County, {state_code} [{min_lon}, {min_lat}, {max_lon}, {max_lat}]")
    logger.info("=" * 75)

    # 1. Initialize API Clients & Parsers
    water_api = USGSWaterAPI()
    climate_api = NOAAClimateAPI()
    hifld_api = HIFLDPowerAPI()
    hazard_api = HazardAPI()
    grid_parser = GridParser(water_api=water_api, climate_api=climate_api)
    clustering_model = SiteClusteringModel(min_composite_score=60.0, eps_km=8.5, min_samples=2)

    # 2. Step 1: Generate 10-sq-km Parcel Tessellation
    logger.info("Step 1/5: Generating 10 km² Parcel Tessellation Grid...")
    grid_gdf = grid_parser.generate_10km_grid(
        min_lon=min_lon,
        min_lat=min_lat,
        max_lon=max_lon,
        max_lat=max_lat,
        state_code=state_code,
        county_name=county_name
    )

    # 3. Step 2: Intersect real HIFLD transmission lines & substations
    logger.info("Step 2/5: Ingesting & Intersecting HIFLD Power Grid Corridors...")
    lines_gdf, subs_gdf = hifld_api.fetch_power_by_bbox(
        min_lon=min_lon, min_lat=min_lat, max_lon=max_lon, max_lat=max_lat
    )
    if lines_gdf is not None and subs_gdf is not None:
        logger.info(
            f"Using LIVE HIFLD grid: {len(lines_gdf)} transmission lines, {len(subs_gdf)} substations."
        )
        grid_gdf = grid_parser.intersect_hifld_power_grid(
            grid_gdf, transmission_lines_gdf=lines_gdf, substations_gdf=subs_gdf
        )
    else:
        logger.warning(
            "HIFLD services unavailable — falling back to synthetic corridor template."
        )
        grid_gdf = grid_parser.intersect_hifld_power_grid(grid_gdf)

    # 2b. Stamp the region's real grid operator (the HIFLD template step
    #     defaults to PJM, which is wrong for ERCOT / BPA territories).
    grid_gdf["grid_operator"] = grid_operator

    # 4. Step 3: Ingest USGS NWIS Groundwater & NOAA Climate Degree Days
    logger.info("Step 3/5: Querying USGS NWIS Hydrological Data & NOAA Climate Normals...")
    grid_gdf = grid_parser.intersect_water_and_climate(grid_gdf)

    # 5. Step 4: Intersect FEMA Flood & USGS Seismic Hazard Risk
    logger.info("Step 4/5: Intersecting FEMA NRI & USGS Seismic Hazard Risk...")
    county_risk = hazard_api.fetch_county_risk(state_code, county_name)
    pga_lookup = hazard_api.fetch_pga_for_grid(grid_gdf) if county_risk is not None else None
    if county_risk is None:
        logger.warning("FEMA NRI unavailable — synthetic hazard model in effect.")
    grid_gdf = grid_parser.intersect_hazard_risk(
        grid_gdf, pga_lookup=pga_lookup, county_risk=county_risk
    )

    # 6. Step 5: Multi-Factor Weighted Suitability Scoring
    logger.info("Step 5/5: Computing Weighted Constraint Suitability Composite Scores...")
    scored_gdf = grid_parser.calculate_composite_scores(grid_gdf)

    # 7. Step 6: Scikit-learn Unsupervised Clustering for Prime Development Zones
    logger.info("Step 6/6: Training Scikit-Learn Unsupervised DBSCAN Prime Zone Clusters...")
    clustered_gdf, cluster_summaries = clustering_model.fit_prime_zones_dbscan(scored_gdf)

    # Log Execution Summary
    prime_parcels = clustered_gdf[clustered_gdf["is_prime_zone"] == True]
    logger.info("=" * 75)
    logger.info(f"PIPELINE COMPLETED: {len(clustered_gdf)} total 10 km² parcels evaluated.")
    logger.info(f"Discovered {len(prime_parcels)} Prime Parcels across {len(cluster_summaries)} Contiguous Clusters.")
    logger.info("=" * 75)

    for cid, s in cluster_summaries.items():
        logger.info(
            f"★ {s['label']}: {s['parcel_count']} parcels ({s['total_area_sq_km']} km²) | "
            f"Avg Score: {s['avg_composite_score']}/100 | Feasible Capacity: {s['total_mw_capacity']} MW"
        )

    # Export to GeoJSON
    if output_geojson:
        logger.info(f"Saving GeoJSON results to: {output_geojson}")
        clustered_gdf.to_file(output_geojson, driver="GeoJSON")

    # Sync to Supabase PostGIS
    if not dry_run:
        sync_to_supabase(clustered_gdf)
    else:
        logger.info("Dry-run mode active. Skipped remote Supabase synchronization.")

    return clustered_gdf, cluster_summaries


def sync_to_supabase(gdf: gpd.GeoDataFrame):
    """Upserts evaluated 10 km² parcels into the Supabase PostGIS `grid_parcels` table."""
    supabase_url = os.getenv("SUPABASE_URL")
    supabase_key = os.getenv("SUPABASE_SERVICE_ROLE_KEY") or os.getenv("SUPABASE_KEY")

    if not supabase_url or not supabase_key:
        logger.warning("SUPABASE_URL or SUPABASE_KEY not found in environment. Skipping database upload.")
        return

    try:
        from supabase import create_client, Client
        supabase: Client = create_client(supabase_url, supabase_key)

        records: List[Dict[str, Any]] = []
        for _, row in gdf.iterrows():
            geom_wkt = row["geometry"].wkt
            centroid_wkt = row["centroid"].wkt

            record = {
                "grid_id": str(row["grid_id"]),
                "geom": f"SRID=4326;{geom_wkt}",
                "centroid": f"SRID=4326;{centroid_wkt}",
                "area_sq_km": float(row["area_sq_km"]),
                "state_code": str(row["state_code"]),
                "county_name": str(row["county_name"]),
                "power_distance_miles": float(row["power_distance_miles"]),
                "substation_distance_miles": float(row["substation_distance_miles"]),
                "substation_voltage_kv": float(row["substation_voltage_kv"]),
                "substation_name": str(row.get("substation_name", "Substation")),
                "grid_operator": str(row.get("grid_operator", "PJM")),
                "groundwater_depth_ft": float(row["groundwater_depth_ft"]),
                "water_availability_index": float(row["water_availability_index"]),
                "seismic_hazard_pga": float(row["seismic_hazard_pga"]),
                "flood_risk_score": float(row["flood_risk_score"]),
                "hurricane_risk_score": float(row["hurricane_risk_score"]),
                "cooling_degree_days": float(row["cooling_degree_days"]),
                "ambient_avg_temp_f": float(row["ambient_avg_temp_f"]),
                "free_cooling_potential_hours": int(row.get("free_cooling_potential_hours", 4500)),
                "power_score": float(row["power_score"]),
                "water_score": float(row["water_score"]),
                "risk_score": float(row["risk_score"]),
                "climate_score": float(row["climate_score"]),
                "composite_score": float(row["composite_score"]),
                "cluster_zone_id": int(row["cluster_zone_id"]),
                "cluster_label": str(row["cluster_label"]),
                "is_prime_zone": bool(row["is_prime_zone"]),
                "megawatt_capacity_estimate": int(row["megawatt_capacity_estimate"]),
                "metadata": {
                    "ingestion_version": "2.0.0",
                    "ml_model": "Scikit-Learn Spatial DBSCAN",
                    "sources": ["HIFLD", "USGS NWIS", "NOAA ACIS", "FEMA NRI"]
                }
            }
            records.append(record)

        logger.info(f"Upserting {len(records)} evaluated parcel records into Supabase `grid_parcels`...")
        # Batch in chunks of 50
        chunk_size = 50
        for i in range(0, len(records), chunk_size):
            chunk = records[i:i + chunk_size]
            response = supabase.table("grid_parcels").upsert(chunk, on_conflict="grid_id").execute()

        logger.info("Successfully pushed all ranked parcel records into Supabase PostGIS!")

    except Exception as e:
        logger.error(f"Error during Supabase upsert: {e}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="AI Data Center Site Selection Pipeline")
    parser.add_argument("--dry-run", action="store_true", help="Run locally without uploading to Supabase")
    parser.add_argument("--state", default="VA", help="State code (e.g. VA, TX, OH, OR) — selects the bbox preset")
    parser.add_argument("--county", default=None, help="Override the preset county/region name")
    parser.add_argument("--bbox", default=None, help="Override the preset bbox: min_lon,min_lat,max_lon,max_lat")
    parser.add_argument("--geojson", default=None, help="Output GeoJSON filepath")
    
    args = parser.parse_args()
    state = args.state.upper()
    preset = REGION_PRESETS.get(state)

    if args.bbox:
        try:
            min_lon, min_lat, max_lon, max_lat = [float(x) for x in args.bbox.split(",")]
        except ValueError:
            raise SystemExit("--bbox must be four comma-separated numbers: min_lon,min_lat,max_lon,max_lat")
    elif preset:
        min_lon, min_lat, max_lon, max_lat = preset["bbox"]
    else:
        raise SystemExit(f"No bbox preset for state '{state}'. Pass --bbox min_lon,min_lat,max_lon,max_lat.")

    county = args.county or (preset or {}).get("county", "Regional")
    operator = (preset or {}).get("grid_operator", "PJM Interconnection")

    run_pipeline(
        min_lon=min_lon,
        min_lat=min_lat,
        max_lon=max_lon,
        max_lat=max_lat,
        state_code=state,
        county_name=county,
        grid_operator=operator,
        dry_run=args.dry_run,
        output_geojson=args.geojson
    )
