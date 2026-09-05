"""
Data Ingestion & Machine Learning Pipeline Runner (v3 — evidence model)
-----------------------------------------------------------------------
Regional screening stays: 10 km² grid cells compare regions consistently.
Underneath, the Loudoun pilot qualifies real cadastral parcels against
hard gates (zoning use, floodway, wetlands, contiguous acreage) with
explicit UNKNOWN for unverified layers.

Ingestion is versioned and atomic:
  * every run is recorded in `ingestion_runs` with per-layer source
    snapshots and evidence classes,
  * all computed data is staged, then published by promote_ingestion_run()
    in a single database transaction,
  * any failure fails the run and re-raises, so scheduled jobs fail
    loudly instead of publishing partial data.

Exit codes: 0 success, 1 failure (run recorded as `failed`).
"""

import os
import sys
import argparse
import logging
import traceback
from datetime import datetime, timezone
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
from loudoun_api import LoudounParcelAPI
from parcel_gates import qualify_parcels, JURISDICTION, RULE_VERSIONS
from runs import IngestionRun
import overlay_layers

load_dotenv()

PIPELINE_VERSION = "3.0.0"

# Survey region presets — bbox (min_lon, min_lat, max_lon, max_lat), county
# label, and the regional grid operator attached to ingested parcels.
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

# Regions with a cadastral parcel pilot (jurisdiction adapters).
PARCEL_PILOTS: Dict[str, str] = {"VA": "Loudoun County, VA"}

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s"
)
logger = logging.getLogger("pipeline")


def _get_supabase_client() -> Optional[Any]:
    """
    Returns a SERVICE-ROLE client for staged writes and publication.
    The anon key was removed from ingestion in Release 0 — anonymous
    clients cannot write ingestion data, by design.
    """
    supabase_url = os.getenv("SUPABASE_URL")
    service_key = os.getenv("SUPABASE_SERVICE_ROLE_KEY")
    if not supabase_url or not service_key:
        raise SystemExit(
            "SUPABASE_SERVICE_ROLE_KEY is required to publish ingestion runs "
            "(anonymous write access was removed in Release 0). Add it to "
            "worker/.env or run with --dry-run."
        )
    from supabase import create_client
    return create_client(supabase_url, service_key)


def _grid_records(gdf: gpd.GeoDataFrame) -> List[Dict[str, Any]]:
    """Builds staged screening-cell records from the scored grid."""
    records: List[Dict[str, Any]] = []
    for _, row in gdf.iterrows():
        records.append({
            "grid_id": str(row["grid_id"]),
            "geom": f"SRID=4326;{row['geometry'].wkt}",
            "centroid": f"SRID=4326;{row['centroid'].wkt}",
            "area_sq_km": float(row["area_sq_km"]),
            "state_code": str(row["state_code"]),
            "county_name": str(row["county_name"]),
            "region": str(row.get("grid_operator", "")),
            "power_distance_miles": float(row["power_distance_miles"]),
            "substation_distance_miles": float(row["substation_distance_miles"]),
            "substation_voltage_kv": float(row["substation_voltage_kv"]),
            "substation_name": str(row.get("substation_name", "Substation")),
            "grid_operator": str(row.get("grid_operator", "")),
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
                "ingestion_version": PIPELINE_VERSION,
                "capacity_note": "area-derived placeholder, capacity unverified",
                "sources": ["HIFLD", "USGS NWIS", "NOAA ACIS", "FEMA NRI", "USGS seismic"],
            },
        })
    return records


def _line_records(lines_gdf: gpd.GeoDataFrame, state_code: str) -> List[Dict[str, Any]]:
    from shapely.geometry import MultiLineString
    records: List[Dict[str, Any]] = []
    for _, row in lines_gdf.iterrows():
        geom = row.geometry
        parts = list(geom.geoms) if isinstance(geom, MultiLineString) else [geom]
        for i, part in enumerate(parts):
            feature_id = str(row["feature_id"]) if len(parts) == 1 else f"{row['feature_id']}-{i + 1}"
            records.append({
                "feature_id": feature_id,
                "state_code": state_code,
                "owner": str(row.get("owner") or "Unknown Owner"),
                "voltage_kv": float(row["voltage_kv"]),
                "volt_class": str(row.get("volt_class") or ""),
                "line_name": str(row.get("line_name") or "Transmission Line"),
                "geom": f"SRID=4326;{part.wkt}",
            })
    return records


def _sub_records(subs_gdf: gpd.GeoDataFrame, state_code: str) -> List[Dict[str, Any]]:
    return [{
        "feature_id": str(row["feature_id"]),
        "state_code": state_code,
        "substation_name": str(row["substation_name"]),
        "voltage_kv": float(row["voltage_kv"]),
        "geom": f"SRID=4326;POINT({row.geometry.x} {row.geometry.y})",
    } for _, row in subs_gdf.iterrows()]


def _well_records(wells_df: pd.DataFrame, state_code: str) -> List[Dict[str, Any]]:
    records: List[Dict[str, Any]] = []
    seen = set()
    for _, row in wells_df.iterrows():
        site_no = str(row["site_no"])
        if site_no in seen:
            continue
        lat, lon = float(row["lat"]), float(row["lon"])
        if pd.isna(lat) or pd.isna(lon):
            continue
        seen.add(site_no)
        records.append({
            "site_no": site_no,
            "state_code": state_code,
            "water_depth_ft": None if pd.isna(row["water_depth_ft"]) else float(row["water_depth_ft"]),
            "geom": f"SRID=4326;POINT({lon} {lat})",
        })
    return records


def run_pipeline(
    min_lon: float = -77.85,
    min_lat: float = 38.75,
    max_lon: float = -77.25,
    max_lat: float = 39.25,
    state_code: str = "VA",
    county_name: str = "Loudoun",
    grid_operator: str = "PJM Interconnection",
    dry_run: bool = False,
    output_geojson: Optional[str] = None,
    trigger: str = "manual",
    qualify_parcels_flag: bool = True,
) -> Tuple[gpd.GeoDataFrame, Dict[int, Dict[str, Any]]]:
    """
    Executes the screening pipeline (+ Loudoun parcel qualification) and
    publishes the complete run atomically. Raises on failure.
    """
    logger.info("=" * 75)
    logger.info("DATA CENTER SITE SELECTION PIPELINE v%s", PIPELINE_VERSION)
    logger.info("Target Region: %s County, %s [%s, %s, %s, %s]",
                county_name, state_code, min_lon, min_lat, max_lon, max_lat)
    logger.info("=" * 75)

    client = None if dry_run else _get_supabase_client()
    run = None
    if client is not None:
        run = IngestionRun(
            client, region_code=state_code, pipeline_version=PIPELINE_VERSION,
            trigger=trigger,
            config={
                "bbox": [min_lon, min_lat, max_lon, max_lat],
                "county": county_name,
                "grid_operator": grid_operator,
                "parcels": qualify_parcels_flag and state_code in PARCEL_PILOTS,
            },
        )
        run.start()

    try:
        water_api = USGSWaterAPI()
        climate_api = NOAAClimateAPI()
        hifld_api = HIFLDPowerAPI()
        hazard_api = HazardAPI()
        grid_parser = GridParser(water_api=water_api, climate_api=climate_api)
        clustering_model = SiteClusteringModel(min_composite_score=60.0, eps_km=8.5, min_samples=2)

        snapshots: Dict[str, Optional[str]] = {}
        retrieve_time = datetime.now(timezone.utc).isoformat()

        # ── Screening: 10 km² tessellation ─────────────────────────────
        logger.info("Step 1: Generating 10 km² screening grid…")
        grid_gdf = grid_parser.generate_10km_grid(
            min_lon=min_lon, min_lat=min_lat, max_lon=max_lon, max_lat=max_lat,
            state_code=state_code, county_name=county_name
        )

        # ── HIFLD power grid ───────────────────────────────────────────
        logger.info("Step 2: Ingesting HIFLD power grid…")
        lines_gdf, subs_gdf = hifld_api.fetch_power_by_bbox(
            min_lon=min_lon, min_lat=min_lat, max_lon=max_lon, max_lat=max_lat
        )
        power_live = lines_gdf is not None and subs_gdf is not None
        if power_live:
            logger.info("Using LIVE HIFLD grid: %d lines, %d substations.",
                        len(lines_gdf), len(subs_gdf))
            grid_gdf = grid_parser.intersect_hifld_power_grid(
                grid_gdf, transmission_lines_gdf=lines_gdf, substations_gdf=subs_gdf
            )
        else:
            logger.warning("HIFLD services unavailable — synthetic corridor template "
                           "in effect for screening only (evidence: fallback).")
            grid_gdf = grid_parser.intersect_hifld_power_grid(grid_gdf)
        grid_gdf["grid_operator"] = grid_operator
        if run is not None:
            evidence = "observed" if power_live else "fallback"
            n_lines = len(lines_gdf) if power_live else None
            n_subs = len(subs_gdf) if power_live else None
            snapshots["power_lines"] = run.snapshot(
                layer="power_lines", source_key="hifld_lines",
                endpoint_url=hifld_api.TRANSMISSION_URL,
                record_count=n_lines, evidence_class=evidence,
                notes=None if power_live else "HIFLD unreachable; synthetic template used for screening"
            )
            snapshots["substations"] = run.snapshot(
                layer="substations", source_key="hifld_substations",
                endpoint_url=hifld_api.SUBSTATIONS_URL,
                record_count=n_subs, evidence_class=evidence
            )

        # ── NWIS groundwater + NOAA climate ────────────────────────────
        logger.info("Step 3: Querying USGS NWIS hydrology & NOAA climate…")
        grid_gdf = grid_parser.intersect_water_and_climate(grid_gdf)
        wells_df = water_api.fetch_groundwater_levels_by_bbox(
            min_lon=min_lon, min_lat=min_lat, max_lon=max_lon, max_lat=max_lat
        )
        if run is not None:
            snapshots["wells"] = run.snapshot(
                layer="wells", source_key="usgs_nwis",
                endpoint_url="https://waterservices.usgs.gov/nwis/iv",
                record_count=None if wells_df is None else len(wells_df),
                evidence_class="observed" if wells_df is not None and not wells_df.empty else "fallback"
            )
            snapshots["climate"] = run.snapshot(
                layer="climate", source_key="noaa_acis",
                endpoint_url="https://data.rcc-acis.org/GridData",
                record_count=len(grid_gdf),
                evidence_class="observed",
                notes="PRISM normals via ACIS GridData; per-metric fallback handled in grid_parser"
            )

        # ── FEMA NRI + USGS seismic ────────────────────────────────────
        logger.info("Step 4: Intersecting FEMA NRI & USGS seismic hazard…")
        county_risk = hazard_api.fetch_county_risk(state_code, county_name)
        pga_lookup = hazard_api.fetch_pga_for_grid(grid_gdf) if county_risk is not None else None
        if county_risk is None:
            logger.warning("FEMA NRI unavailable — synthetic hazard model (evidence: fallback).")
        grid_gdf = grid_parser.intersect_hazard_risk(
            grid_gdf, pga_lookup=pga_lookup, county_risk=county_risk
        )
        if run is not None:
            snapshots["nri"] = run.snapshot(
                layer="county_risk", source_key="fema_nri",
                endpoint_url=hazard_api.NRI_URL,
                record_count=1 if county_risk else 0,
                evidence_class="observed" if county_risk else "fallback"
            )
            if pga_lookup is not None:
                snapshots["seismic"] = run.snapshot(
                    layer="seismic_pga", source_key="usgs_seismic",
                    endpoint_url="https://earthquake.usgs.gov/ws/designmaps/ashrae/conservative-site.json",
                    record_count=len(pga_lookup), evidence_class="observed"
                )

        # ── Scoring + prime zones ──────────────────────────────────────
        logger.info("Step 5: Scoring & clustering…")
        scored_gdf = grid_parser.calculate_composite_scores(grid_gdf)
        clustered_gdf, cluster_summaries = clustering_model.fit_prime_zones_dbscan(scored_gdf)

        prime_parcels = clustered_gdf[clustered_gdf["is_prime_zone"] == True]  # noqa: E712
        logger.info("Screening: %d cells, %d prime across %d zones.",
                    len(clustered_gdf), len(prime_parcels), len(cluster_summaries))
        for cid, s in cluster_summaries.items():
            logger.info("★ %s: %s parcels (%s km²) | avg %s/100 | placeholder capacity %s MW",
                        s["label"], s["parcel_count"], s["total_area_sq_km"],
                        s["avg_composite_score"], s["total_mw_capacity"])

        # ── Loudoun parcel qualification (pilot) ───────────────────────
        parcel_stats: Dict[str, Any] = {}
        if qualify_parcels_flag and state_code in PARCEL_PILOTS:
            logger.info("Step 6: Loudoun parcel qualification (cadastral gates)…")
            loudoun = LoudounParcelAPI()
            layers = loudoun.fetch_all(min_lon, min_lat, max_lon, max_lat)
            parcels_gdf = layers["parcels"]
            zoning_gdf, wetlands_gdf, nfhl_gdf = layers["zoning"], layers["wetlands"], layers["nfhl"]

            # NWI service down? Fall back to the official state geodatabase
            # (download-once clip) before conceding UNKNOWN wetland gates.
            wetlands_endpoint = loudoun.WETLANDS_URL
            if wetlands_gdf is None:
                wetlands_gdf, wetlands_endpoint = overlay_layers.fetch_nwi_wetlands(
                    min_lon, min_lat, max_lon, max_lat
                )
                if wetlands_gdf is not None:
                    logger.info("NWI wetlands served via the official geodatabase "
                                "fallback — gates will use it.")

            for layer_key, gdf, src in (
                ("parcels", parcels_gdf, "loudoun_parcels"),
                ("zoning", zoning_gdf, "loudoun_zoning"),
                ("wetlands", wetlands_gdf, "nwi_wetlands"),
                ("nfhl", nfhl_gdf, "loudoun_fema_flood"),
            ):
                if run is not None:
                    snapshots[layer_key] = run.snapshot(
                        layer=layer_key, source_key=src,
                        endpoint_url={
                            "parcels": loudoun.PARCELS_URL, "zoning": loudoun.ZONING_URL,
                            "wetlands": wetlands_endpoint, "nfhl": loudoun.NFHL_URL,
                        }[layer_key],
                        record_count=None if gdf is None else len(gdf),
                        evidence_class="observed",
                        quality=None if gdf is None else {"rows": int(len(gdf))},
                        notes="unavailable — gate recorded UNKNOWN" if gdf is None else None,
                    )
                elif gdf is None:
                    logger.warning("Layer %s unavailable — its gates will be UNKNOWN.", layer_key)

            if parcels_gdf is None:
                raise RuntimeError(
                    "Loudoun parcel layer unavailable — parcel qualification cannot "
                    "run (screening cells alone are not sufficient for publication "
                    "of a VA run with parcels enabled)."
                )

            # Verification layers: TIGER roads, PAD-US protected areas,
            # 3DEP slopes. Each degrades independently to UNKNOWN.
            logger.info("Step 6b: verification layers (TIGER roads, PAD-US, 3DEP slopes)…")
            roads_gdf = overlay_layers.fetch_tiger_roads(min_lon, min_lat, max_lon, max_lat)
            padus_gdf = overlay_layers.fetch_padus(min_lon, min_lat, max_lon, max_lat)
            slopes = None
            try:
                slopes = overlay_layers.sample_3dep_slopes(parcels_gdf)
            except Exception as e:  # noqa: BLE001
                logger.warning("3DEP slope sampling failed: %s", e)
                slopes = None

            for layer_key, count, src, endpoint, note in (
                ("roads", None if roads_gdf is None else len(roads_gdf),
                 "census_tiger_roads",
                 "https://tigerweb.geo.census.gov/arcgis/rest/services/TIGERweb/Transportation/MapServer",
                 None if roads_gdf is not None else "unavailable — gate recorded UNKNOWN"),
                ("padus", None if padus_gdf is None else len(padus_gdf),
                 "padus",
                 "https://www.sciencebase.gov/catalog/item/652d4f80d34e44db0e2ee45c",
                 (None if padus_gdf is not None
                  else "unavailable — gate recorded UNKNOWN")),
                ("slope",
                 None if slopes is None else sum(1 for v in slopes.values() if v[2] > 0),
                 "usgs_3dep",
                 "https://elevation.nationalmap.gov/arcgis/rest/services/3DEPElevation/ImageServer/getSamples",
                 (None if slopes is not None
                  else "unavailable — gate recorded UNKNOWN")),
            ):
                if run is not None:
                    snapshots[layer_key] = run.snapshot(
                        layer=layer_key, source_key=src, endpoint_url=endpoint,
                        record_count=count, evidence_class="observed",
                        quality=None if count is None else {"rows": int(count)},
                        notes=note,
                    )
                elif count is None:
                    logger.warning("Layer %s unavailable — its gates will be UNKNOWN.", layer_key)

            rules = run.load_rules(JURISDICTION) if run is not None else {}
            parcel_records, metric_rows, gate_rows, parcel_stats = qualify_parcels(
                parcels_gdf=parcels_gdf, zoning_gdf=zoning_gdf,
                wetlands_gdf=wetlands_gdf, nfhl_gdf=nfhl_gdf,
                lines_gdf=lines_gdf if power_live else None,
                subs_gdf=subs_gdf if power_live else None,
                rules=rules, state_code=state_code, county_name=county_name,
                snapshots=snapshots, retrieve_time=retrieve_time,
                roads_gdf=roads_gdf, padus_gdf=padus_gdf, slopes=slopes,
            )
            logger.info("Parcel qualification: %d parcels, %d metric rows, %d gate rows.",
                        len(parcel_records), len(metric_rows), len(gate_rows))
            if run is not None:
                run.stage_land_parcels(parcel_records)
                run.stage_parcel_metrics(metric_rows)
                run.stage_parcel_gates(gate_rows)

        # ── Stage screening outputs ────────────────────────────────────
        if output_geojson:
            logger.info("Saving GeoJSON results to: %s", output_geojson)
            clustered_gdf.to_file(output_geojson, driver="GeoJSON")

        if run is not None:
            logger.info("Staging screening outputs…")
            run.stage_grid_parcels(_grid_records(clustered_gdf))
            if power_live:
                run.stage_transmission_lines(_line_records(lines_gdf, state_code))
                run.stage_substations(_sub_records(subs_gdf, state_code))
            if wells_df is not None and not wells_df.empty:
                run.stage_observation_wells(_well_records(wells_df, state_code))

            # ── Atomic publication ─────────────────────────────────────
            logger.info("Promoting run atomically…")
            counts = run.promote()
            logger.info("PUBLISHED: %s", counts)
        else:
            logger.info("Dry-run mode — nothing staged or published.")

    except Exception as exc:  # noqa: BLE001
        if run is not None:
            run.fail(f"{type(exc).__name__}: {exc}\n{traceback.format_exc()}")
        logger.error("PIPELINE FAILED: %s", exc)
        logger.error(traceback.format_exc())
        raise

    return clustered_gdf, cluster_summaries


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="AI Data Center Site Selection Pipeline")
    parser.add_argument("--dry-run", action="store_true", help="Run locally without publishing to Supabase")
    parser.add_argument("--state", default="VA", help="State code (e.g. VA, TX, OH, OR)")
    parser.add_argument("--county", default=None, help="Override the preset county/region name")
    parser.add_argument("--bbox", default=None, help="Override bbox: min_lon,min_lat,max_lon,max_lat")
    parser.add_argument("--geojson", default=None, help="Output GeoJSON filepath")
    parser.add_argument("--no-parcels", action="store_true",
                        help="Skip cadastral parcel qualification (screening cells only)")

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

    try:
        run_pipeline(
            min_lon=min_lon, min_lat=min_lat, max_lon=max_lon, max_lat=max_lat,
            state_code=state, county_name=county, grid_operator=operator,
            dry_run=args.dry_run, output_geojson=args.geojson,
            trigger="scheduled" if os.getenv("CI") else "manual",
            qualify_parcels_flag=not args.no_parcels,
        )
    except SystemExit:
        raise
    except Exception:
        sys.exit(1)
