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
import math
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
import network_evidence
from parcel_gates import qualify_parcels, RULE_VERSIONS
from runs import IngestionRun, load_rules_readonly
import overlay_layers

load_dotenv()

PIPELINE_VERSION = "3.0.0"

# Survey region presets, keyed by region slug (STATE-COUNTY). The slug is
# the region's identity in the database: promote swaps, uniqueness and
# supersession are scoped by region_key, so two counties of one state
# (OH-FRANKLIN, OH-LICKING) coexist instead of overwriting each other.
# bbox is (min_lon, min_lat, max_lon, max_lat).
REGION_PRESETS: Dict[str, Dict[str, Any]] = {
    "VA-LOUDOUN": {
        "state": "VA",
        "bbox": (-77.85, 38.75, -77.25, 39.25),
        "county": "Loudoun",
        "grid_operator": "PJM Interconnection",
    },
    "TX-TAYLOR": {
        "state": "TX",
        "bbox": (-100.05, 32.15, -99.45, 32.75),
        "county": "Taylor",
        "grid_operator": "ERCOT",
    },
    "OH-FRANKLIN": {
        "state": "OH",
        "bbox": (-83.15, 39.85, -82.55, 40.35),
        "county": "Franklin",
        "grid_operator": "PJM Interconnection",
    },
    # The west-Licking corridor: Jersey, Etna, Monroe and Harrison
    # townships along I-70, where the New Albany data-center campus and
    # the Intel site actually sit. 2,853 parcels at the 20-acre floor
    # (probed 2026-09-10) — the full county would be 5,271.
    "OH-LICKING": {
        "state": "OH",
        "bbox": (-82.75, 39.95, -82.40, 40.25),
        "county": "Licking",
        "grid_operator": "PJM Interconnection",
    },
    "OR-MORROW": {
        "state": "OR",
        "bbox": (-120.05, 45.55, -119.45, 46.15),
        "county": "Morrow",
        "grid_operator": "Bonneville Power Administration",
    },
}

# Equal-area projection for the screening grid. The parcel tier uses a
# local UTM zone, which is right for one county and wrong for a country;
# the screening grid spans four regions, so it measures in CONUS Albers.
SCREENING_PLANAR_CRS = "EPSG:5070"

# Regions with a cadastral parcel pilot, mapped to the jurisdiction whose
# rules and cost assumptions govern them. Adding a region is an adapter
# plus rows in constraint_rules and cost_assumptions — the engine itself
# is jurisdiction-agnostic.
PARCEL_PILOTS: Dict[str, str] = {
    "VA-LOUDOUN": "Loudoun County, VA",
    # Central Ohio is a PJM market, so power diligence, the national
    # overlays and PeeringDB all carry over unchanged.
    "OH-FRANKLIN": "Franklin County, OH",
    # Same PJM market as Franklin, plus a published township zoning layer
    # (the one thing Franklin lacks) and per-parcel CAUV evidence.
    "OH-LICKING": "Licking County, OH",
    # Abilene is in ERCOT, so unlike Ohio nothing from the PJM power
    # diligence layer carries over and that gate stays UNKNOWN.
    "TX-TAYLOR": "Taylor County, TX",
}

# One adapter per parcel-pilot region. Dispatch is by region slug, never
# state_code — the whole point of the re-key is that a state can host more
# than one diligenced county.
PARCEL_ADAPTERS: Dict[str, str] = {
    "VA-LOUDOUN": "loudoun",
    "OH-FRANKLIN": "franklin",
    "OH-LICKING": "licking",
    "TX-TAYLOR": "taylor",
}

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


def _text_or_none(v: Any) -> Optional[str]:
    """Empty and NaN both mean the source had nothing to say."""
    if v is None or (isinstance(v, float) and math.isnan(v)):
        return None
    t = str(v).strip()
    return t or None


def _round_or_none(v: Any, places: int) -> Optional[float]:
    if v is None:
        return None
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    return None if math.isnan(f) or math.isinf(f) else round(f, places)


def _int_or_none(v: Any) -> Optional[int]:
    f = _round_or_none(v, 0)
    return None if f is None else int(f)


def _grid_records(gdf: gpd.GeoDataFrame, region_key: str) -> List[Dict[str, Any]]:
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
            "region_key": region_key,
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
            # The measurement only. stg_grid_parcels has no composite_score
            # column and grid_parcels.composite_score is generated, so the
            # risked figure is the database's to compute, not the worker's
            # to send.
            "composite_score_unrisked": float(row["composite_score_unrisked"]),
            "evidence_coverage": float(row.get("evidence_coverage", 1.0)),
            "evidence_tier": str(row.get("evidence_tier", "screening")),
            "cluster_zone_id": int(row["cluster_zone_id"]),
            "cluster_label": str(row["cluster_label"]),
            "is_prime_zone": bool(row["is_prime_zone"]),
            "megawatt_capacity_estimate": None,
            # Interconnection. Absent rather than zero when PeeringDB was
            # unreachable or the cell matched nothing: zero networks would
            # read as "nothing here", which is a finding, not a gap.
            "ixp_nearest_facility": _text_or_none(row.get("ixp_facility")),
            "ixp_nearest_distance_miles": _round_or_none(row.get("ixp_distance_miles"), 3),
            "ixp_latency_floor_ms": _round_or_none(
                None if pd.isna(row.get("ixp_distance_miles"))
                else network_evidence.latency_floor_ms(float(row["ixp_distance_miles"])), 4),
            "ixp_networks_at_nearest": _int_or_none(row.get("ixp_net_count")),
            "ixp_facilities_within_25mi": _int_or_none(row.get("ixp_facilities_within_25mi")),
            "ixp_networks_within_25mi": _int_or_none(row.get("ixp_networks_within_25mi")),
            "ixp_best_networks_within_25mi": _int_or_none(row.get("ixp_best_networks_within_25mi")),
            "metadata": {
                "ingestion_version": PIPELINE_VERSION,
                "capacity_note": (
                    "No capacity estimate: a feasible MW figure requires a dated "
                    "source (utility study / PJM agreement). See power documents."
                ),
                "sources": ["HIFLD", "USGS NWIS", "NOAA ACIS", "FEMA NRI", "USGS seismic"],
            },
        })
    return records


def _line_records(lines_gdf: gpd.GeoDataFrame, state_code: str,
                  region_key: str) -> List[Dict[str, Any]]:
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
                "region_key": region_key,
                "owner": str(row.get("owner") or "Unknown Owner"),
                "voltage_kv": float(row["voltage_kv"]),
                "volt_class": str(row.get("volt_class") or ""),
                "line_name": str(row.get("line_name") or "Transmission Line"),
                "geom": f"SRID=4326;{part.wkt}",
            })
    return records


def _sub_records(subs_gdf: gpd.GeoDataFrame, state_code: str,
                 region_key: str) -> List[Dict[str, Any]]:
    return [{
        "feature_id": str(row["feature_id"]),
        "state_code": state_code,
        "region_key": region_key,
        "substation_name": str(row["substation_name"]),
        "voltage_kv": float(row["voltage_kv"]),
        "geom": f"SRID=4326;POINT({row.geometry.x} {row.geometry.y})",
    } for _, row in subs_gdf.iterrows()]


def _well_records(wells_df: pd.DataFrame, state_code: str,
                  region_key: str) -> List[Dict[str, Any]]:
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
            "region_key": region_key,
            "water_depth_ft": None if pd.isna(row["water_depth_ft"]) else float(row["water_depth_ft"]),
            "geom": f"SRID=4326;POINT({lon} {lat})",
        })
    return records


def run_pipeline(
    region_key: str = "VA-LOUDOUN",
    min_lon: float = -77.85,
    min_lat: float = 38.75,
    max_lon: float = -77.25,
    max_lat: float = 39.25,
    county_name: Optional[str] = None,
    grid_operator: Optional[str] = None,
    dry_run: bool = False,
    output_geojson: Optional[str] = None,
    trigger: str = "manual",
    qualify_parcels_flag: bool = True,
) -> Tuple[gpd.GeoDataFrame, Dict[int, Dict[str, Any]]]:
    """
    Executes the screening pipeline (+ parcel qualification where the
    region has a pilot) and publishes the complete run atomically.
    Raises on failure.

    Regions are identified by slug (STATE-COUNTY, e.g. OH-FRANKLIN). The
    slug scopes promotion: publishing one county never touches a sibling
    county of the same state. State-scoped artefacts (PAD-US, TIGER,
    PJM RTEP) are still keyed by the state half of the slug.
    """
    preset = REGION_PRESETS.get(region_key, {})
    state_code = region_key.split("-", 1)[0]
    county_name = county_name or preset.get("county", "Regional")
    grid_operator = grid_operator or preset.get("grid_operator", "PJM Interconnection")
    logger.info("=" * 75)
    logger.info("DATA CENTER SITE SELECTION PIPELINE v%s", PIPELINE_VERSION)
    logger.info("Target Region: %s [%s, %s, %s, %s]",
                region_key, min_lon, min_lat, max_lon, max_lat)
    logger.info("=" * 75)

    client = None if dry_run else _get_supabase_client()
    run = None
    if client is not None:
        run = IngestionRun(
            client, region_code=region_key, pipeline_version=PIPELINE_VERSION,
            trigger=trigger,
            config={
                "region_key": region_key,
                "bbox": [min_lon, min_lat, max_lon, max_lat],
                "county": county_name,
                "grid_operator": grid_operator,
                "parcels": qualify_parcels_flag and region_key in PARCEL_PILOTS,
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
        # Which survey this region gets is a property of its configuration,
        # known before any of it runs — so the zone labels, the cluster
        # summaries and the log lines all agree from the start rather than
        # being corrected downstream. How much of that survey resolves is a
        # property of the run, and is measured later as evidence_coverage.
        evidence_tier = (
            "parcel" if qualify_parcels_flag and region_key in PARCEL_PILOTS
            else "screening"
        )
        logger.info("Step 5: Scoring & clustering…")
        scored_gdf = grid_parser.calculate_composite_scores(grid_gdf)
        clustered_gdf, cluster_summaries = clustering_model.fit_prime_zones_dbscan(
            scored_gdf, evidence_tier=evidence_tier
        )

        # ── Interconnection, every region ──────────────────────────────
        # PeeringDB is national and the screening grid covers all four
        # regions, so this runs here rather than only on the parcel tier —
        # which exists for two of them. Power says whether a site can be
        # built; interconnection says whether it is worth building, and a
        # region with no parcel pilot still deserves that answer.
        screening_facilities = network_evidence.fetch_facilities()
        if screening_facilities is not None:
            planar_cells = clustered_gdf.to_crs(SCREENING_PLANAR_CRS)
            near_cells = network_evidence.nearest_facilities(
                planar_cells, screening_facilities, SCREENING_PLANAR_CRS
            )
            if near_cells is not None:
                clustered_gdf = clustered_gdf.join(
                    near_cells[["facility", "net_count", "distance_miles",
                                "facilities_within_25mi", "networks_within_25mi",
                                "best_networks_within_25mi"]].add_prefix("ixp_")
                )
                # A region can be entirely outside the metro radius —
                # Taylor County is 138 miles from the nearest facility — in
                # which case the whole column is NaN and max() is NaN too.
                # That is the finding, not an error, so it is reported
                # rather than cast.
                best = clustered_gdf["ixp_best_networks_within_25mi"].max()
                logger.info(
                    "Interconnection: %d/%d cells matched a facility; "
                    "best peering in reach across the region: %s.",
                    int(clustered_gdf["ixp_facility"].notna().sum()),
                    len(clustered_gdf),
                    "none within 25 mi" if pd.isna(best)
                    else f"{int(best)} networks",
                )
        else:
            logger.warning("PeeringDB unavailable — screening interconnection omitted.")

        prime_parcels = clustered_gdf[clustered_gdf["is_prime_zone"] == True]  # noqa: E712
        logger.info("Screening: %d cells, %d prime across %d zones.",
                    len(clustered_gdf), len(prime_parcels), len(cluster_summaries))
        for cid, s in cluster_summaries.items():
            logger.info("★ %s: %s parcels (%s km²) | avg %s/100",
                        s["label"], s["parcel_count"], s["total_area_sq_km"],
                        s["avg_composite_score"])

        # ── Loudoun parcel qualification (pilot) ───────────────────────
        parcel_stats: Dict[str, Any] = {}
        # How much of the region's parcel survey resolved. Stays 0.0 where
        # there is no parcel tier — which is why it is read alongside
        # evidence_tier and never instead of it: a region with no parcels
        # and a region whose gates all came back UNKNOWN both sit at 0.0,
        # and they are different facts.
        evidence_coverage = 0.0
        if qualify_parcels_flag and region_key in PARCEL_PILOTS:
            jurisdiction = PARCEL_PILOTS[region_key]
            logger.info("Step 6: %s parcel qualification (cadastral gates)…",
                        jurisdiction)
            # One adapter per jurisdiction, one contract: fetch_all returns
            # the same four keys, and a layer the county does not publish
            # comes back None so the engine records UNKNOWN rather than
            # inventing a verdict. Dispatch is by region slug — a state
            # can host more than one diligenced county.
            adapter = PARCEL_ADAPTERS[region_key]
            if adapter == "franklin":
                from franklin_api import FranklinParcelAPI
                county_api: Any = FranklinParcelAPI()
            elif adapter == "taylor":
                from taylor_api import TaylorParcelAPI
                county_api = TaylorParcelAPI()
            elif adapter == "licking":
                from licking_api import LickingParcelAPI
                county_api = LickingParcelAPI()
            elif adapter == "loudoun":
                county_api = LoudounParcelAPI()
            else:
                raise RuntimeError(
                    f"No parcel adapter registered for region {region_key}.")
            layers = county_api.fetch_all(min_lon, min_lat, max_lon, max_lat)
            parcels_gdf = layers["parcels"]
            zoning_gdf, wetlands_gdf, nfhl_gdf = layers["zoning"], layers["wetlands"], layers["nfhl"]

            # NWI service down? Fall back to the official state geodatabase
            # (download-once clip) before conceding UNKNOWN wetland gates.
            # Parcel-level incentives, where the jurisdiction grants them.
            # Virginia's are statutory and statewide, so only Ohio has any.
            parcel_incentives: Dict[str, Dict[str, Any]] = {}
            if hasattr(county_api, "parcel_incentives") and parcels_gdf is not None:
                parcel_incentives = county_api.parcel_incentives(
                    min_lon, min_lat, max_lon, max_lat, parcels_gdf
                )

            layer_src = county_api.layer_sources()
            wetlands_endpoint = layer_src["wetlands"]["endpoint"]
            if wetlands_gdf is None:
                wetlands_gdf, wetlands_endpoint = overlay_layers.fetch_nwi_wetlands(
                    min_lon, min_lat, max_lon, max_lat, state_code=state_code
                )
                if wetlands_gdf is not None:
                    logger.info("NWI wetlands served via the official geodatabase "
                                "fallback — gates will use it.")

            # NFHL: county mirror first (Loudoun's FEMAFlood), the federal
            # FEMA service as the floor for everyone else. One federal
            # adapter decides the floodway gate in any US county — every
            # parcel outside Loudoun was UNKNOWN only because nothing
            # queried it.
            nfhl_src = layer_src["nfhl"]["source_key"]
            nfhl_endpoint = layer_src["nfhl"]["endpoint"]
            if nfhl_gdf is None:
                nfhl_gdf, nfhl_endpoint = overlay_layers.fetch_nfhl_floodzones(
                    min_lon, min_lat, max_lon, max_lat, state_code=state_code
                )
                if nfhl_gdf is not None:
                    nfhl_src = "fema_nfhl"
                    logger.info("NFHL flood zones served via the federal FEMA "
                                "service — gates will use it.")

            for layer_key, gdf in (
                ("parcels", parcels_gdf),
                ("zoning", zoning_gdf),
                ("wetlands", wetlands_gdf),
                ("nfhl", nfhl_gdf),
            ):
                src = layer_src[layer_key]["source_key"]
                endpoint = layer_src[layer_key]["endpoint"]
                if layer_key == "wetlands":
                    endpoint = wetlands_endpoint
                elif layer_key == "nfhl":
                    src, endpoint = nfhl_src, nfhl_endpoint
                # A layer the jurisdiction does not publish has no source
                # to attribute; its gates are UNKNOWN and there is nothing
                # to snapshot.
                if run is not None and src is not None:
                    snapshots[layer_key] = run.snapshot(
                        layer=layer_key, source_key=src,
                        endpoint_url=endpoint,
                        record_count=None if gdf is None else len(gdf),
                        evidence_class="observed",
                        quality=None if gdf is None else {"rows": int(len(gdf))},
                        notes="unavailable — gate recorded UNKNOWN" if gdf is None else None,
                    )
                elif gdf is None:
                    logger.warning("Layer %s unavailable — its gates will be UNKNOWN.", layer_key)

            if parcels_gdf is None:
                # A jurisdiction with a parcel pilot must produce parcels.
                # Publishing screening cells alone would quietly retire
                # every parcel already live for the region, because the
                # promote deactivates any parcel the run did not restage.
                raise RuntimeError(
                    f"{jurisdiction} parcel layer unavailable — parcel "
                    f"qualification cannot run, and publishing {region_key} "
                    f"on screening cells alone would deactivate the "
                    f"region's existing parcels."
                )

            # Verification layers: TIGER roads, PAD-US protected areas,
            # 3DEP slopes. Each degrades independently to UNKNOWN.
            logger.info("Step 6b: verification layers (TIGER roads, PAD-US, 3DEP slopes)…")
            roads_gdf = overlay_layers.fetch_tiger_roads(
                min_lon, min_lat, max_lon, max_lat, state_code=state_code,
                region_key=region_key)
            padus_gdf = overlay_layers.fetch_padus(
                min_lon, min_lat, max_lon, max_lat, state_code=state_code)
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

            # A dry run reads the same rule rows a publish would (read-only,
            # world-readable table) rather than the built-in defaults: the
            # zoning default was another county's use table, and the engine
            # now refuses a zoning-supplying run with no rule of its own —
            # a refusal the dry run must be able to see past, not trip on.
            rules = (run.load_rules(jurisdiction) if run is not None
                     else load_rules_readonly(jurisdiction))

            # Power diligence (Release 2): serving utility, PJM RTEP
            # upgrade evidence, queue activity. Each degrades to UNKNOWN
            # independently — and no MW figure is ever asserted without a
            # dated source.
            logger.info("Step 6c: power diligence (utility territory, PJM RTEP upgrades, queue activity)…")
            import power_evidence
            utility_gdf = overlay_layers.fetch_utility_territories(
                min_lon, min_lat, max_lon, max_lat
            )
            rtep_df = None
            try:
                rtep_df = power_evidence.fetch_rtep_upgrades(state_code)
            except Exception as e:  # noqa: BLE001
                logger.warning("PJM RTEP upgrade fetch failed: %s", e)
            queue_gdf = power_evidence.fetch_pjm_queue_points(
                min_lon, min_lat, max_lon, max_lat
            )
            # Approved county data-center applications (observed) and the
            # curated parcel utility evidence behind them (dated public
            # records — the only path to a power_capacity PASS).
            apps_gdf = power_evidence.fetch_legislative_applications(
                min_lon, min_lat, max_lon, max_lat
            )
            parcel_evidence = (
                run.fetch_power_parcel_evidence() if run is not None else {}
            )

            # Water availability (Release 3): the region's published
            # service-area boundary (provider is config data — see
            # water_evidence.WATER_PROVIDERS): serving areas, an explicit
            # not-served polygon where the utility publishes one, and
            # per-area connection records. A region with no provider
            # configured stays UNKNOWN.
            import water_evidence
            water_gdf = water_evidence.fetch_water_service_areas(
                region_key, min_lon, min_lat, max_lon, max_lat
            )
            water_spec = water_evidence.WATER_PROVIDERS.get(region_key)
            if run is not None and water_spec is not None:
                snapshots["water_service_areas"] = run.snapshot(
                    layer="water_service_areas",
                    source_key=water_spec["source_key"],
                    endpoint_url=water_spec["layers"][0]["url"],
                    record_count=None if water_gdf is None else len(water_gdf),
                    evidence_class="observed",
                    quality=(None if water_gdf is None else {
                        "rows": int(len(water_gdf)),
                        "water_serving": int(
                            water_gdf.service_type.isin(("W", "Both")).sum()),
                    }),
                    notes=(None if water_gdf is not None
                           else "unavailable — water gates recorded UNKNOWN"),
                )
            elif water_gdf is None and water_spec is not None:
                logger.warning("%s service areas unavailable — water gates "
                               "will be UNKNOWN.", water_spec["utility_name"])

            # Commercial underwriting (Release 4b): the county assessment
            # roll — land and improvement value, the taxable base, the
            # county's own estimated levy, and the land-use deferral that
            # carries a roll-back liability on conversion.
            import assessment_evidence
            assessments = assessment_evidence.fetch_assessments()
            if run is not None:
                snapshots["assessment"] = run.snapshot(
                    layer="assessment",
                    source_key="loudoun_assessment_roll",
                    endpoint_url=assessment_evidence.ASSESSMENT_XLSX_URL,
                    record_count=None if assessments is None else len(assessments),
                    evidence_class="observed",
                    quality=(None if assessments is None else {
                        "rows": int(len(assessments)),
                        "assessment_year": assessment_evidence.ASSESSMENT_YEAR,
                        "in_land_use_deferral": int(
                            (assessments["deferred_value"].fillna(0) > 0).sum()),
                    }),
                    notes=(None if assessments is not None
                           else "unavailable — assessment values recorded UNKNOWN"),
                )
            elif assessments is None:
                logger.warning("Assessment roll unavailable — value metrics will be UNKNOWN.")

            # Cost assumptions (Release 4c): the versioned, cited inputs
            # behind every estimated figure. Absent, the estimates are
            # skipped rather than computed from hard-coded numbers.
            import underwriting
            assumptions = underwriting.load_assumptions(client, jurisdiction)

            # Interconnection (Release 5): PeeringDB's public register of
            # where networks actually meet. Power decides whether a site can
            # be built; interconnection decides whether it is worth building.
            facilities = network_evidence.fetch_facilities()
            if run is not None:
                snapshots["interconnection"] = run.snapshot(
                    layer="interconnection",
                    source_key="peeringdb_facilities",
                    endpoint_url=network_evidence.PEERINGDB_FAC_URL,
                    record_count=None if facilities is None else len(facilities),
                    evidence_class="observed",
                    quality=(None if facilities is None else {
                        "facilities": int(len(facilities)),
                        "networks_present_total": int(facilities.net_count.sum()),
                    }),
                    notes=(None if facilities is not None
                           else "unavailable — interconnection metrics omitted"),
                )
            elif facilities is None:
                logger.warning("PeeringDB unavailable — interconnection metrics omitted.")

            for layer_key, src, endpoint, count, note in (
                ("utility_territories", "hifld_utility_territories",
                 overlay_layers.UTILITY_TERRITORY_URL,
                 None if utility_gdf is None else len(utility_gdf),
                 None if utility_gdf is not None else "unavailable — serving-utility metric skipped"),
                ("rtep_upgrades", "pjm_rtep_upgrades",
                 power_evidence.RTEP_XML_URL,
                 None if rtep_df is None else len(rtep_df),
                 None if rtep_df is not None else "unavailable — power gate recorded UNKNOWN"),
                ("pjm_queue", "pjm_queue_map",
                 power_evidence.QUEUE_MAP_URL,
                 None if queue_gdf is None else len(queue_gdf),
                 None if queue_gdf is not None else "unavailable — queue-activity metric skipped"),
                ("county_applications", "loudoun_legislative_applications",
                 power_evidence.LEGISLATIVE_APPS_URL,
                 None if apps_gdf is None else len(apps_gdf),
                 None if apps_gdf is not None else "unavailable — application metrics skipped"),
            ):
                if run is not None:
                    quality = None if count is None else {"rows": int(count)}
                    if layer_key == "rtep_upgrades" and count is not None:
                        quality = {
                            "rows": int(count),
                            "in_area": int(rtep_df["in_area"].sum()),
                            "active_in_area": int(
                                (rtep_df["in_area"]
                                 & rtep_df["status"].isin(
                                     rules.get("power_capacity", {}).get("params", {})
                                     .get("active_statuses", ["EP", "UC", "PL"]))
                                 ).sum()
                            ),
                        }
                    snapshots[layer_key] = run.snapshot(
                        layer=layer_key, source_key=src, endpoint_url=endpoint,
                        record_count=count, evidence_class="observed",
                        quality=quality, notes=note,
                    )
                elif count is None:
                    logger.warning("Power layer %s unavailable — power gates will be UNKNOWN.", layer_key)

            if rtep_df is not None and run is not None:
                run.stage_power_rtep_upgrades(
                    power_evidence.rtep_upsert_records(rtep_df, state_code)
                )

            parcel_records, metric_rows, gate_rows, parcel_stats = qualify_parcels(
                parcels_gdf=parcels_gdf, zoning_gdf=zoning_gdf,
                wetlands_gdf=wetlands_gdf, nfhl_gdf=nfhl_gdf,
                lines_gdf=lines_gdf if power_live else None,
                subs_gdf=subs_gdf if power_live else None,
                rules=rules, state_code=state_code, county_name=county_name,
                snapshots=snapshots, retrieve_time=retrieve_time,
                region_key=region_key,
                roads_gdf=roads_gdf, padus_gdf=padus_gdf, slopes=slopes,
                utility_gdf=utility_gdf, rtep_df=rtep_df, queue_gdf=queue_gdf,
                apps_gdf=apps_gdf, parcel_evidence=parcel_evidence,
                water_gdf=water_gdf, assessments=assessments,
                assumptions=assumptions, facilities=facilities,
                parcel_incentives=parcel_incentives,
            )
            logger.info("Parcel qualification: %d parcels, %d metric rows, %d gate rows.",
                        len(parcel_records), len(metric_rows), len(gate_rows))
            # Evidence coverage: the share of this region's parcel gates
            # the current diligence can decide. Computed from the run's
            # own gate rows, never assumed — also in dry-run, so the
            # local output matches what a publish would store.
            total_gates = len(gate_rows)
            decided_gates = sum(1 for g in gate_rows if g["status"] != "UNKNOWN")
            evidence_coverage = (
                round(decided_gates / total_gates, 3) if total_gates else 0.0
            )
            if run is not None:
                run.stage_land_parcels(parcel_records)
                run.stage_parcel_metrics(metric_rows)
                run.stage_parcel_gates(gate_rows)

        # ── Evidence tier and coverage weighting ───────────────────────
        # Ranking is lexicographic: evidence tier first, score second. A
        # parcel-tier site out-ranks a screening-tier one whatever the two
        # scores are, so the score itself never has to carry that job.
        #
        # Within the parcel tier the composite is still scaled by coverage,
        # so a region deciding 6 of 9 gates carries at most two-thirds of
        # its screening score. That factor is well behaved there — it is
        # only ever a fraction of a real survey.
        #
        # A screening-tier region keeps its composite unscaled. Multiplying
        # it by a coverage of 0.0 was not a penalty but an annihilator: it
        # threw away observed screening evidence and flattened the region's
        # internal ranking to a single value. Absent parcel diligence is not
        # a measurement of zero, and this engine does not write it as one.
        clustered_gdf["evidence_coverage"] = evidence_coverage
        clustered_gdf["evidence_tier"] = evidence_tier

        # Only the measurement is written. grid_parcels.composite_score is a
        # generated column — round(unrisked × coverage) inside the parcel
        # tier, unrisked outside it — so the database performs the risking
        # and the worker cannot overwrite a measurement with a product. That
        # is the whole point: the annihilator that flattened Morrow County's
        # 330 composites to a single 0.00 is now unreachable from here.
        #
        # It also ends a rounding divergence rather than papering over it.
        # numpy's .round() is half-to-even and SQL round() is half away from
        # zero, so the two disagreed wherever a product landed on an exact
        # half-cent — 70.00 × 0.995 = 69.65 gave 69.6 here and 69.7 there.
        # With one side gone there is nothing left to disagree.
        clustered_gdf["composite_score_unrisked"] = (
            clustered_gdf["composite_score"].round(1)
        )

        if evidence_tier == "parcel":
            logger.info(
                "Evidence tier: parcel — %.1f%% of parcel gates decided; "
                "the database risks the composite by %.3f.",
                evidence_coverage * 100, evidence_coverage)
        else:
            logger.info(
                "Evidence tier: screening — no parcel survey in this region. "
                "Composites left unscaled; the tier, not the score, keeps "
                "these cells below every parcel-tier site.")

        # ── Stage screening outputs ────────────────────────────────────
        if output_geojson:
            logger.info("Saving GeoJSON results to: %s", output_geojson)
            clustered_gdf.to_file(output_geojson, driver="GeoJSON")

        if run is not None:
            logger.info("Staging screening outputs…")
            run.stage_grid_parcels(_grid_records(clustered_gdf, region_key))
            if power_live:
                run.stage_transmission_lines(
                    _line_records(lines_gdf, state_code, region_key))
                run.stage_substations(
                    _sub_records(subs_gdf, state_code, region_key))
            if wells_df is not None and not wells_df.empty:
                run.stage_observation_wells(
                    _well_records(wells_df, state_code, region_key))

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
    parser.add_argument("--region", default="VA-LOUDOUN",
                        help="Region slug (e.g. VA-LOUDOUN, OH-FRANKLIN, TX-TAYLOR, OR-MORROW). "
                             "A legacy bare state code maps to that state's one preset.")
    parser.add_argument("--county", default=None, help="Override the preset county/region name")
    parser.add_argument("--bbox", default=None, help="Override bbox: min_lon,min_lat,max_lon,max_lat")
    parser.add_argument("--geojson", default=None, help="Output GeoJSON filepath")
    parser.add_argument("--no-parcels", action="store_true",
                        help="Skip cadastral parcel qualification (screening cells only)")

    args = parser.parse_args()
    region_key = args.region.upper()

    # A bare state code cannot name a region any more — one state can host
    # several diligenced counties — but the four legacy codes each had
    # exactly one preset, so they map unambiguously.
    if region_key in ("VA", "TX", "OH", "OR"):
        legacy = [k for k, v in REGION_PRESETS.items() if v["state"] == region_key]
        if not legacy:
            raise SystemExit(f"No region preset for state '{region_key}'. "
                             "Pass a region slug like OH-LICKING.")
        region_key = legacy[0]
        logger.warning("--region %s is a legacy state code; running %s.",
                       args.region.upper(), region_key)

    preset = REGION_PRESETS.get(region_key, {})

    if args.bbox:
        try:
            min_lon, min_lat, max_lon, max_lat = [float(x) for x in args.bbox.split(",")]
        except ValueError:
            raise SystemExit("--bbox must be four comma-separated numbers: min_lon,min_lat,max_lon,max_lat")
    elif preset.get("bbox"):
        min_lon, min_lat, max_lon, max_lat = preset["bbox"]
    else:
        raise SystemExit(f"No bbox preset for region '{region_key}'. Pass --bbox min_lon,min_lat,max_lon,max_lat.")

    county = args.county or preset.get("county", "Regional")
    operator = preset.get("grid_operator", "PJM Interconnection")

    try:
        run_pipeline(
            region_key=region_key,
            min_lon=min_lon, min_lat=min_lat, max_lon=max_lon, max_lat=max_lat,
            county_name=county, grid_operator=operator,
            dry_run=args.dry_run, output_geojson=args.geojson,
            trigger="scheduled" if os.getenv("CI") else "manual",
            qualify_parcels_flag=not args.no_parcels,
        )
    except SystemExit:
        raise
    except Exception:
        sys.exit(1)
