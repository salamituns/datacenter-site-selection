"""
Verification layer fetchers — federal-first overlays for every region.

1. TIGER roads (Census TIGERweb/Transportation): primary (S1100) and
   secondary (S1200) road segments for the road-access gate.
2. PAD-US 4.0 (USGS, official ScienceBase state geodatabase): protected
   areas for the protected-land gate. The national hosted ArcGIS layers
   are partial subsets, so the official geodatabase for the state being
   surveyed is resolved from the release manifest, downloaded once,
   clipped to the survey bbox, and cached per state.
3. FEMA NFHL (federal ArcGIS REST service): flood hazard zones for the
   floodway gate in any US county — the county-mirror-first, federal-
   fallback path (a county that mirrors NFHL locally still wins; the
   federal service is the floor for everyone else).
4. 3DEP slopes (USGS 3DEPElevation ImageServer getSamples): a 32x32
   elevation lattice per parcel envelope, converted to per-parcel slope
   statistics for the terrain gate. getSamples accepts envelopes, not
   multipoints, so this is one request per parcel (paced, threaded).
"""

from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import json
import logging
import os
import random
import tempfile
import time
import zipfile
from typing import Any, Dict, List, Optional, Tuple

import geopandas as gpd
import pandas as pd
import numpy as np
import requests
from shapely.geometry import shape

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("overlay_layers")

TIGER_URL = (
    "https://tigerweb.geo.census.gov/arcgis/rest/services/"
    "TIGERweb/Transportation/MapServer/{layer}/query"
)
# Primary Roads (S1100) = layer 2; Secondary Roads (S1200) = layer 6.
TIGER_LAYERS = {"primary": 2, "secondary": 6}


def _tiger_cache(state_code: str) -> Path:
    return Path(__file__).parent / "cache" / f"tiger_{state_code.lower()}_clip.gpkg"


# Canonical TIGER/Line county road shapefiles (same vintage the TIGERweb
# service serves). The Census WAF rate-blocks the REST service hard; this
# host has never blocked us, and the county file is one download.
TIGERLINE_ROADS_URL = (
    "https://www2.census.gov/geo/tiger/TIGER2024/ROADS/"
    "tl_2024_{fips}_roads.zip"
)
COUNTY_FIPS = {"VA": "51107", "OH": "39049", "TX": "48441"}
TIGER_ROAD_CLASSES = {"S1100": "primary", "S1200": "secondary"}


def _fetch_tigerline_roads(
    state_code: str, bbox_poly,
) -> Optional[gpd.GeoDataFrame]:
    """
    Primary + secondary roads from the county's TIGER/Line shapefile —
    the fallback when the TIGERweb REST service is WAF-blocked. None when
    the state has no mapped county (the caller then concedes UNKNOWN).
    """
    fips = COUNTY_FIPS.get(state_code.upper())
    if not fips:
        return None
    try:
        with tempfile.TemporaryDirectory() as tmp:
            zip_path = Path(tmp) / "roads.zip"
            url = TIGERLINE_ROADS_URL.format(fips=fips)
            logger.info("TIGER roads: service unavailable — downloading the "
                        "county TIGER/Line shapefile (%s)…", url.rsplit("/", 1)[-1])
            dl = requests.get(url, stream=True, timeout=600,
                              headers={"User-Agent": BROWSER_UA})
            dl.raise_for_status()
            with open(zip_path, "wb") as out:
                for chunk in dl.iter_content(chunk_size=1 << 20):
                    if chunk:
                        out.write(chunk)
            with zipfile.ZipFile(zip_path) as zf:
                zf.extractall(tmp)
            shp = next(Path(tmp).glob("*.shp"))
            full = gpd.read_file(str(shp))
            full = full.to_crs("EPSG:4326")
            mtfcc = full["MTFCC"].astype(str).str.strip() if "MTFCC" in full \
                else None
            if mtfcc is None:
                logger.warning("TIGER/Line roads: no MTFCC column.")
                return None
            keep = full[mtfcc.isin(TIGER_ROAD_CLASSES)]
            keep = keep[keep.geometry.intersects(bbox_poly)]
            if len(keep) == 0:
                logger.warning("TIGER/Line roads: no primary/secondary "
                               "segments in bbox.")
                return None
            name_col = next(
                (c for c in keep.columns if c.upper() == "FULLNAME"), None
            )
            return gpd.GeoDataFrame({
                "road_class": mtfcc.loc[keep.index].map(TIGER_ROAD_CLASSES)
                    .reset_index(drop=True),
                "mtfcc": keep["MTFCC"].astype(str).reset_index(drop=True),
                "name": (keep[name_col].astype(str).str.strip() if name_col
                         else "").reset_index(drop=True),
                "geometry": keep.geometry.reset_index(drop=True),
            }, crs="EPSG:4326")
    except Exception as e:  # noqa: BLE001
        logger.warning("TIGER/Line roads fetch failed: %s", e)
        return None

# PAD-US 4.0 "State Downloads" release (USGS ScienceBase). One zip per
# state (PADUS4_0_State_{XX}_GDB.zip); the manifest of file URLs is read
# from the item at runtime, so every state resolves through the same
# release instead of a hard-coded disk id for one state.
#
# The fetcher is state-parameterized for correctness, not convenience:
# the cache used to be a single Virginia clip shared by every region, so
# a Texas run received Virginia's polygons, found no overlap, and
# awarded protected-land PASS verdicts on the wrong state's data.
PADUS_RELEASE_ITEM = "652d4f80d34e44db0e2ee45c"
PADUS_MANIFEST_URL = (
    f"https://www.sciencebase.gov/catalog/item/{PADUS_RELEASE_ITEM}"
    "?format=json&fields=files,title"
)
PADUS_FILE_PATTERN = "PADUS4_0_State_{state}_GDB.zip"


def _padus_cache(state_code: str) -> Path:
    return Path(__file__).parent / "cache" / f"padus_{state_code.lower()}_clip.gpkg"

# FEMA National Flood Hazard Layer — the federal ArcGIS REST service
# (Flood Hazard Zones, layer 28: S_Fld_Haz_Ar polygons with FLD_ZONE and
# ZONE_SUBTY, including the regulatory floodway). One adapter decides
# the floodway gate in any US county; counties that mirror NFHL locally
# (Loudoun's FEMAFlood) still win when they publish, and this service is
# the fallback for everyone else. The legacy /gis/nfhl/ path is dead —
# the service now lives under /arcgis/.
NFHL_FEDERAL_URL = (
    "https://hazards.fema.gov/arcgis/rest/services/public/NFHL/"
    "MapServer/28/query"
)


def _nfhl_cache(state_code: str) -> Path:
    return Path(__file__).parent / "cache" / f"nfhl_{state_code.lower()}_clip.gpkg"

# Official NWI Virginia state geodatabase (USFWS ecosphere document
# server). Used only when the NWI REST service is unreachable — the
# WIM-hosted service has been serving error pages for extended periods.
NWI_SERVICE_URL = (
    "https://fwspublicservices.wim.usgs.gov/wetlandsarcgis/rest/services/"
    "Wetlands/MapServer/0/query"
)
# USFWS publishes one geodatabase per state at a predictable path. It is
# parameterised because the fallback must serve the state actually being
# surveyed: clipping Virginia's file to an Ohio bbox returns nothing,
# which would read as "no wetlands here" and pass the gate on the wrong
# state's data.
NWI_STATE_URL_TEMPLATE = (
    "https://documentst.ecosphere.fws.gov/wetlands/data/"
    "State-Downloads/{state}_geodatabase_wetlands.zip"
)


def _nwi_state_url(state_code: str) -> str:
    return NWI_STATE_URL_TEMPLATE.format(state=state_code.upper())


def _nwi_cache(state_code: str) -> Path:
    return Path(__file__).parent / "cache" / f"nwi_{state_code.lower()}_clip.gpkg"

THREEDEP_URL = (
    "https://elevation.nationalmap.gov/arcgis/rest/services/"
    "3DEPElevation/ImageServer/getSamples"
)

# HIFLD Electric Retail Service Territories — which utility serves a
# parcel (investor-owned / cooperative / municipal). Sourced 2023.
UTILITY_TERRITORY_URL = (
    "https://services6.arcgis.com/BAJNi3EgCdtQ1BCG/arcgis/rest/services/"
    "Electric_Retail_Service_Territories/FeatureServer/0/query"
)

BROWSER_UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) DataCenterPipeline/3.0"
)


def fetch_tiger_roads(
    min_lon: float, min_lat: float, max_lon: float, max_lat: float,
    state_code: str = "VA",
) -> Optional[gpd.GeoDataFrame]:
    """
    Primary + secondary road segments within the bbox (TIGERweb). The clip
    is cached per state: TIGER is a yearly vintage, and the Census WAF
    rate-blocks aggressively — a successful fetch persists, and a later
    outage falls back to the cache instead of regressing decided
    road-access gates to UNKNOWN.
    """
    bbox_poly = _bbox_polygon(min_lon, min_lat, max_lon, max_lat)
    session = requests.Session()
    session.headers.update({"User-Agent": BROWSER_UA, "Accept": "application/json"})
    bbox = f"{min_lon},{min_lat},{max_lon},{max_lat}"
    rows: List[Dict[str, Any]] = []
    for road_class, layer in TIGER_LAYERS.items():
        features = _paged_query(
            session, TIGER_URL.format(layer=layer), bbox,
            out_fields="BASENAME,MTFCC,RTTYP",
            attempts=3, page_pause=0.5,
        )
        if features is None:
            logger.warning("TIGER %s roads unavailable this run.", road_class)
            continue
        for f in features:
            geometry = f.get("geometry")
            if not geometry:
                continue
            try:
                geom = shape(geometry)
            except Exception:  # noqa: BLE001
                continue
            if geom.is_empty:
                continue
            props = f.get("properties", {}) or {}
            rows.append({
                "road_class": road_class,
                "mtfcc": str(props.get("MTFCC") or ""),
                "name": str(props.get("BASENAME") or "").strip(),
                "geometry": geom,
            })
    if rows:
        gdf = gpd.GeoDataFrame(rows, crs="EPSG:4326")
        _save_cached_clip(_tiger_cache(state_code), gdf, bbox_poly)
        logger.info("TIGER roads: %d segments (%d primary, %d secondary) — cached.",
                    len(gdf), (gdf.road_class == "primary").sum(),
                    (gdf.road_class == "secondary").sum())
        return gdf
    # Live fetch failed entirely — fall back to the cached clip rather
    # than conceding UNKNOWN gates for data we already verified once.
    cached = _load_cached_clip(_tiger_cache(state_code), bbox_poly)
    if cached is not None:
        logger.info("TIGER roads: service unavailable — using the cached clip "
                    "(%d segments).", len(cached))
        return cached
    # No cache either (first run for the state during an outage) — the
    # county's TIGER/Line shapefile is the canonical fallback.
    tigerline = _fetch_tigerline_roads(state_code, bbox_poly)
    if tigerline is not None:
        _save_cached_clip(_tiger_cache(state_code), tigerline, bbox_poly)
        logger.info("TIGER roads: %d segments from the TIGER/Line county "
                    "shapefile (%d primary, %d secondary) — cached.",
                    len(tigerline), (tigerline.road_class == "primary").sum(),
                    (tigerline.road_class == "secondary").sum())
        return tigerline
    logger.warning("TIGER roads: no segments in bbox and no usable cache.")
    return None


def _padus_state_url(state_code: str) -> Optional[str]:
    """
    Resolves the PAD-US 4.0 geodatabase download URL for a state from the
    ScienceBase release manifest. Returns None when the manifest is
    unreachable or the state's file is absent — the gate stays UNKNOWN
    rather than guessing.
    """
    try:
        r = requests.get(PADUS_MANIFEST_URL, timeout=60,
                         headers={"User-Agent": BROWSER_UA, "Accept": "application/json"})
        r.raise_for_status()
        wanted = PADUS_FILE_PATTERN.format(state=state_code.upper())
        for f in r.json().get("files", []):
            if f.get("name") == wanted:
                return f.get("url")
        logger.warning("PAD-US: %r not in the ScienceBase release manifest.", wanted)
        return None
    except Exception as e:  # noqa: BLE001
        logger.warning("PAD-US manifest fetch failed: %s", e)
        return None


def fetch_padus(
    min_lon: float, min_lat: float, max_lon: float, max_lat: float,
    state_code: str = "VA",
) -> Optional[gpd.GeoDataFrame]:
    """
    PAD-US 4.0 protected areas within the bbox, from the official USGS
    state geodatabase for the state actually being surveyed. The state's
    file is resolved from the ScienceBase release manifest, downloaded
    once, clipped to the bbox, and cached per state.

    state_code is required for correctness, not convenience: PAD-US
    ships one geodatabase per state, and the wrong state's polygons
    produce zero overlap — protected-land PASS verdicts on data that
    never covered the parcels. An empty clip from the correct state's
    inventory is a real answer (no protected areas here): the layer is
    returned present and empty, and the gate decides PASS.
    """
    bbox_poly = _bbox_polygon(min_lon, min_lat, max_lon, max_lat)
    cached = _load_cached_clip(_padus_cache(state_code), bbox_poly)
    if cached is not None:
        logger.info("PAD-US (%s): %d cached protected-area polygons.",
                    state_code.upper(), len(cached))
        return cached
    url = _padus_state_url(state_code)
    if url is None:
        return None
    try:
        with tempfile.TemporaryDirectory() as tmp:
            zip_path = Path(tmp) / "padus_state.zip"
            logger.info("PAD-US: downloading %s geodatabase…",
                        PADUS_FILE_PATTERN.format(state=state_code.upper()))
            dl = requests.get(url, stream=True, timeout=1800,
                              headers={"User-Agent": BROWSER_UA})
            dl.raise_for_status()
            with open(zip_path, "wb") as out:
                for chunk in dl.iter_content(chunk_size=1 << 20):
                    if chunk:
                        out.write(chunk)
            with zipfile.ZipFile(zip_path) as zf:
                zf.extractall(tmp)
            gdb_dirs = list(Path(tmp).glob("*.gdb"))
            if not gdb_dirs:
                logger.warning("PAD-US: no geodatabase in the archive.")
                return None
            gdb = str(gdb_dirs[0])
            import pyogrio

            layers = [l[0] for l in pyogrio.list_layers(gdb)]
            # The combined inventory (DOD + tribal + NGP + fee +
            # designation + easement) is the screening-appropriate layer —
            # conservation easements are exactly the protected-land risk
            # a Fee-only read would miss. The feature class is named
            # "PADUS4_0Comb_DOD_Trib_NGP_Fee_Desig_Ease_State_XX" ("Comb",
            # not "Combined"); Marine is offshore and excluded.
            preferred = [
                l for l in layers
                if "Comb" in l and "Marine" not in l and "_" in l
            ]
            layer_name = preferred[0] if preferred else layers[0]
            logger.info("PAD-US: reading layer %r from %s", layer_name, Path(gdb).name)
            full = gpd.read_file(gdb, layer=layer_name)
            cols = _pick_columns(
                full,
                unit="Unit_Nm", manager="Mang_Name", mgr_type="Mang_Type",
                gap="GAP_Sts", category="Category",
            )
            clip = gpd.GeoDataFrame(cols, geometry="geometry", crs=full.crs)
            clip = clip.to_crs("EPSG:4326")
            within = clip[clip.geometry.intersects(bbox_poly)]
            # Persist the clip (with its bbox) for reuse, then return it.
            # Empty is cached too: "no protected areas in this bbox" is a
            # decided answer from the correct state's inventory.
            _save_cached_clip(_padus_cache(state_code), within, bbox_poly)
            logger.info("PAD-US (%s): %d protected-area polygons in bbox (cached).",
                        state_code.upper(), len(within))
            return within
    except Exception as e:  # noqa: BLE001
        logger.warning("PAD-US fetch failed: %s", e)
        return None


def fetch_nfhl_floodzones(
    min_lon: float, min_lat: float, max_lon: float, max_lat: float,
    state_code: str = "VA",
) -> Tuple[Optional[gpd.GeoDataFrame], str]:
    """
    FEMA flood hazard zones for the bbox from the federal NFHL REST
    service (Flood Hazard Zones layer: FLD_ZONE, ZONE_SUBTY, SFHA_TF),
    with the same output contract as a county NFHL mirror. Paged with
    retry/backoff — the service throttles — and the bbox clip is cached
    per state.

    Returns (geodataframe_or_None, endpoint). An empty frame is a real
    answer (mapped-but-dry county): the layer is present and the gate
    decides. None means the service could not be queried this run — the
    gate stays UNKNOWN.
    """
    bbox_poly = _bbox_polygon(min_lon, min_lat, max_lon, max_lat)
    cached = _load_cached_clip(_nfhl_cache(state_code), bbox_poly)
    if cached is not None:
        logger.info("NFHL flood zones (cached clip, %s): %d polygons.",
                    state_code.upper(), len(cached))
        return cached, NFHL_FEDERAL_URL
    session = requests.Session()
    session.headers.update({"User-Agent": BROWSER_UA, "Accept": "application/json"})
    # The service 500s on queries that page deep over a large envelope
    # (observed at offsets ≥ 5000 regardless of page size, and
    # intermittently lower). Rather than paging one big bbox, the bbox is
    # tiled: each tile pages shallowly, and a tile that still fails is
    # subdivided further. OBJECTID is fetched so straddling polygons
    # returned by two tiles are deduplicated.
    features = _nfhl_tiled_query(
        session, min_lon, min_lat, max_lon, max_lat, depth=0)
    if features is None:
        logger.warning("NFHL federal service unavailable this run.")
        return None, NFHL_FEDERAL_URL
    rows: List[Dict[str, Any]] = []
    seen_ids = set()
    for f in features:
        geometry = f.get("geometry")
        if not geometry:
            continue
        try:
            geom = shape(geometry)
        except Exception:  # noqa: BLE001
            continue
        if geom.is_empty or not geom.is_valid:
            geom = geom.buffer(0)
        if geom.is_empty:
            continue
        props = f.get("properties", {}) or {}
        oid = props.get("OBJECTID")
        if oid is not None:
            if oid in seen_ids:
                continue
            seen_ids.add(oid)
        rows.append({
            "fld_zone": str(props.get("FLD_ZONE") or "").strip(),
            "zone_subty": str(props.get("ZONE_SUBTY") or "").strip().upper(),
            "geometry": geom,
        })
    gdf = gpd.GeoDataFrame(
        rows if rows else [],
        columns=["fld_zone", "zone_subty", "geometry"], crs="EPSG:4326",
    )
    _save_cached_clip(_nfhl_cache(state_code), gdf, bbox_poly)
    logger.info("NFHL flood zones (federal service, %s): %d polygons in bbox (cached).",
                state_code.upper(), len(gdf))
    return gdf, NFHL_FEDERAL_URL


NFHL_MAX_DEPTH = 3  # a county bbox split 8x8 at most


def _nfhl_tiled_query(
    session: requests.Session, min_lon: float, min_lat: float,
    max_lon: float, max_lat: float, depth: int,
) -> Optional[List[Dict[str, Any]]]:
    """Flood-hazard features for a tile; subdivides on failure."""
    bbox = f"{min_lon},{min_lat},{max_lon},{max_lat}"
    features = _paged_query(
        session, NFHL_FEDERAL_URL, bbox,
        out_fields="OBJECTID,FLD_ZONE,ZONE_SUBTY,SFHA_TF",
        page_size=200, attempts=3, page_pause=1.0,
    )
    if features is not None:
        return features
    if depth >= NFHL_MAX_DEPTH:
        logger.warning("NFHL tile failed at max depth: %s", bbox)
        return None
    logger.warning("NFHL tile query failed (%s) — subdividing.", bbox)
    mid_lon, mid_lat = (min_lon + max_lon) / 2, (min_lat + max_lat) / 2
    quads = (
        (min_lon, min_lat, mid_lon, mid_lat),
        (mid_lon, min_lat, max_lon, mid_lat),
        (min_lon, mid_lat, mid_lon, max_lat),
        (mid_lon, mid_lat, max_lon, max_lat),
    )
    out: List[Dict[str, Any]] = []
    for q in quads:
        sub = _nfhl_tiled_query(session, *q, depth=depth + 1)
        if sub is None:
            return None
        out.extend(sub)
    return out


def fetch_utility_territories(
    min_lon: float, min_lat: float, max_lon: float, max_lat: float
) -> Optional[gpd.GeoDataFrame]:
    """
    Electric utility retail service territories overlapping the bbox
    (HIFLD, sourced 2023). One polygon per utility; the name/type feeds
    the per-parcel serving-utility metric and the power-capacity gate.
    """
    session = requests.Session()
    session.headers.update({"User-Agent": BROWSER_UA, "Accept": "application/json"})
    features = _paged_query(
        session, UTILITY_TERRITORY_URL,
        f"{min_lon},{min_lat},{max_lon},{max_lat}",
        out_fields="NAME,TYPE,STATE,SOURCEDATE,SUMMR_PEAK",
    )
    if features is None:
        logger.warning("Utility territory layer unavailable this run.")
        return None
    rows: List[Dict[str, Any]] = []
    for f in features:
        geometry = f.get("geometry")
        if not geometry:
            continue
        try:
            geom = shape(geometry)
        except Exception:  # noqa: BLE001
            continue
        if geom.is_empty:
            continue
        props = f.get("properties", {}) or {}
        name = str(props.get("NAME") or "").strip()
        if not name or name.upper().startswith("UNKNOWN"):
            continue
        rows.append({
            "utility_name": name,
            "utility_type": str(props.get("TYPE") or "").strip().lower().replace(" ", "_"),
            "geometry": geom,
        })
    if not rows:
        logger.warning("Utility territories: no named polygons in bbox.")
        return None
    gdf = gpd.GeoDataFrame(rows, crs="EPSG:4326")
    logger.info("Utility territories: %d utilities overlapping the bbox: %s",
                len(gdf), ", ".join(sorted(gdf.utility_name.unique())[:8]))
    return gdf


def fetch_nwi_wetlands(
    min_lon: float, min_lat: float, max_lon: float, max_lat: float,
    state_code: str = "VA",
) -> Tuple[Optional[gpd.GeoDataFrame], str]:
    """
    NWI wetland polygons for the bbox. Tries the REST service first
    (fresh when healthy); when it is down, falls back to that state's
    official geodatabase, downloaded once and clipped/cached.

    state_code is required for correctness, not convenience. The fallback
    used to be Virginia's file unconditionally, so an Ohio run whose
    service call failed clipped Virginia wetlands to an Ohio bbox, found
    none, and reported the layer present — a wetland gate passing on the
    wrong state's data.

    Returns (geodataframe_or_None, endpoint_that_served). A None return
    means both routes failed — the gate stays UNKNOWN.
    """
    # 1. Live service probe (tiny query, short timeout).
    session = requests.Session()
    session.headers.update({"User-Agent": BROWSER_UA, "Accept": "application/json"})
    probe = _paged_query(
        session, NWI_SERVICE_URL,
        f"{min_lon},{min_lat},{max_lon},{max_lat}",
        out_fields="OBJECTID,ATTRIBUTE", page_size=100,
    )
    if probe is not None:
        rows = []
        for f in probe:
            geometry = f.get("geometry")
            if not geometry:
                continue
            try:
                geom = shape(geometry)
            except Exception:  # noqa: BLE001
                continue
            if geom.is_empty or not geom.is_valid:
                geom = geom.buffer(0)
            if not geom.is_empty:
                rows.append({
                    "attribute": (f.get("properties", {}) or {}).get("ATTRIBUTE"),
                    "geometry": geom,
                })
        gdf = gpd.GeoDataFrame(
            rows if rows else [], columns=["attribute", "geometry"], crs="EPSG:4326"
        )
        logger.info("NWI wetlands (service): %d polygons in bbox.", len(gdf))
        return gdf, NWI_SERVICE_URL

    # 2. Official state geodatabase, cached clip.
    logger.warning("NWI service unreachable — falling back to the official %s "
                   "geodatabase (download once, cached).", state_code.upper())
    try:
        if _nwi_cache(state_code).exists():
            clip = gpd.read_file(_nwi_cache(state_code), layer="wetlands")
            logger.info("NWI wetlands (cached clip): %d polygons.", len(clip))
            return clip, _nwi_state_url(state_code)
        _nwi_cache(state_code).parent.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory() as tmp:
            zip_path = Path(tmp) / "nwi_va.zip"
            logger.info("NWI: downloading Virginia geodatabase (~395 MB)…")
            dl = requests.get(_nwi_state_url(state_code), stream=True, timeout=1800,
                              headers={"User-Agent": BROWSER_UA})
            dl.raise_for_status()
            with open(zip_path, "wb") as out:
                for chunk in dl.iter_content(chunk_size=1 << 20):
                    if chunk:
                        out.write(chunk)
            with zipfile.ZipFile(zip_path) as zf:
                zf.extractall(tmp)
            gdb_dirs = list(Path(tmp).glob("*.gdb"))
            if not gdb_dirs:
                logger.warning("NWI: no geodatabase in the archive.")
                return None, _nwi_state_url(state_code)
            gdb = str(gdb_dirs[0])
            import pyogrio

            layers = [l[0] for l in pyogrio.list_layers(gdb)]
            # The state GDB ships boundary + metadata layers alongside the
            # wetland features (e.g. 'Virginia', 'VA_Wetlands',
            # 'VA_Wetlands_Project_Metadata') — pick the feature layer.
            preferred = [
                l for l in layers
                if "wetland" in l.lower() and "metadata" not in l.lower()
                and "project" not in l.lower()
            ]
            layer_name = preferred[0] if preferred else layers[0]
            logger.info("NWI: reading layer %r from %s", layer_name, Path(gdb).name)
            info = pyogrio.read_info(gdb, layer=layer_name)
            from pyproj import CRS
            src_crs = CRS.from_user_input(info["crs"])
            if src_crs.to_epsg() != 4326:
                from pyproj import Transformer
                tf = Transformer.from_crs("EPSG:4326", src_crs, always_xy=True)
                bx0, by0 = tf.transform(min_lon, min_lat)
                bx1, by1 = tf.transform(max_lon, max_lat)
                read_bbox = (min(bx0, bx1), min(by0, by1), max(bx0, bx1), max(by0, by1))
            else:
                read_bbox = (min_lon, min_lat, max_lon, max_lat)
            full = gpd.read_file(gdb, layer=layer_name, bbox=read_bbox)
            attr_col = next(
                (c for c in full.columns if c.upper() == "ATTRIBUTE"), None
            )
            clip = full.to_crs("EPSG:4326")
            if len(clip) == 0:
                logger.info("NWI: no wetland polygons in bbox.")
                return None, _nwi_state_url(state_code)
            out = gpd.GeoDataFrame({
                "attribute": clip[attr_col] if attr_col else None,
                "geometry": clip.geometry,
            }, crs="EPSG:4326")
            out.to_file(_nwi_cache(state_code), layer="wetlands")
            logger.info("NWI wetlands (geodatabase clip): %d polygons (cached).", len(out))
            return out, _nwi_state_url(state_code)
    except Exception as e:  # noqa: BLE001
        logger.warning("NWI wetlands fetch failed: %s", e)
        return None, _nwi_state_url(state_code)


# One request per parcel, so this dominates the verification step. The
# ceiling is USGS tolerance, not our CPU: too many workers earns 429s and
# 5xxs, which without a retry become silently missing slope statistics.
# Tunable without a code change; raise it only alongside the success rate
# logged at the end of the sampling run.
THREEDEP_WORKERS = int(os.getenv("THREEDEP_WORKERS", "12"))
THREEDEP_ATTEMPTS = int(os.getenv("THREEDEP_ATTEMPTS", "3"))
_THREEDEP_RETRY_STATUS = {429, 500, 502, 503, 504}


def sample_3dep_slopes(
    parcels_gdf: gpd.GeoDataFrame,
    workers: int = THREEDEP_WORKERS,
    timeout: int = 90,
    attempts: int = THREEDEP_ATTEMPTS,
) -> Optional[Dict[Any, Tuple[Optional[float], Optional[float], int]]]:
    """
    Per-parcel slope statistics from the 3DEP bare-earth DEM.

    getSamples returns a lattice (capped 32x32) over an envelope, one
    request per parcel. Slope is derived from the lattice gradient with
    meter-scaled spacing (cos(lat) corrected). Returns a dict keyed by
    the parcel index: (slope_max_pct, slope_median_pct, n_samples);
    entries are (None, None, 0) for parcels whose sampling failed — the
    gate stays UNKNOWN for those, never a guessed value.

    A throttled or briefly failing request is retried with exponential
    backoff and jitter. An answer of "no elevation here" is not retried:
    it is a real result, and only a transport or server failure earns
    another attempt. Without this, raising the worker count would buy
    speed by converting throttling into missing gates.
    """
    session_local = _ThreadLocalSession(timeout)

    # Each task reports its own retry count and the main thread sums them:
    # a shared counter would be a read-modify-write across workers.
    def one(item) -> Tuple[Any, Optional[float], Optional[float], int, int]:
        idx, geom = item
        minx, miny, maxx, maxy = geom.bounds
        if not (maxx > minx and maxy > miny):
            return idx, None, None, 0, 0
        params = {
            "geometry": json.dumps({
                "xmin": minx, "ymin": miny, "xmax": maxx, "ymax": maxy,
                "spatialReference": {"wkid": 4326},
            }),
            "geometryType": "esriGeometryEnvelope",
            "returnFirstValueOnly": "true",
            "f": "json",
        }
        retries = 0
        for attempt in range(attempts):
            try:
                r = session_local.get().get(THREEDEP_URL, params=params, timeout=timeout)
                if r.status_code in _THREEDEP_RETRY_STATUS:
                    raise requests.HTTPError(f"status {r.status_code}")
                r.raise_for_status()
                data = r.json()
                samples = data.get("samples", [])
                if data.get("error") or not samples:
                    # A real answer, not a failure — do not spend retries.
                    return idx, None, None, 0, retries
                stats = _slope_from_samples(samples, midlat=(miny + maxy) / 2)
                return idx, stats[0], stats[1], stats[2], retries
            except Exception:  # noqa: BLE001
                retries += 1
                if attempt == attempts - 1:
                    return idx, None, None, 0, retries
                time.sleep(0.4 * (2 ** attempt) + random.uniform(0, 0.3))
        return idx, None, None, 0, retries

    items = list(parcels_gdf.geometry.items())
    out: Dict[Any, Tuple[Optional[float], Optional[float], int]] = {}
    done = 0
    retried = 0
    with ThreadPoolExecutor(max_workers=workers) as pool:
        for idx, smax, smed, n, retries in pool.map(one, items):
            out[idx] = (smax, smed, n)
            retried += retries
            done += 1
            if done % 250 == 0:
                logger.info("3DEP slopes: %d/%d parcels sampled.", done, len(items))
    ok = sum(1 for v in out.values() if v[2] > 0)
    logger.info(
        "3DEP slopes: %d/%d parcels have slope statistics "
        "(%d workers, %d transient failures retried).",
        ok, len(items), workers, retried,
    )
    return out


# ── internals ─────────────────────────────────────────────────────────


class _ThreadLocalSession:
    """One requests.Session per worker thread (sessions are not shared)."""

    def __init__(self, timeout: int):
        import threading

        self._local = threading.local()
        self._timeout = timeout

    def get(self) -> requests.Session:
        s = getattr(self._local, "session", None)
        if s is None:
            s = requests.Session()
            s.headers.update({"User-Agent": BROWSER_UA, "Accept": "application/json"})
            self._local.session = s
        return s


def _paged_query(session: requests.Session, url: str, bbox: str,
                 out_fields: str, where: str = "1=1",
                 page_size: int = 1000, attempts: int = 1,
                 page_pause: float = 0.0) -> Optional[List[Dict[str, Any]]]:
    """
    Pages an ArcGIS query in GeoJSON. attempts > 1 retries a failed page
    with backoff (for services that throttle); page_pause spaces pages
    out. None only on hard failure after all attempts.
    """
    features: List[Dict[str, Any]] = []
    offset = 0
    try:
        while True:
            params = {
                "where": where,
                "geometry": bbox,
                "geometryType": "esriGeometryEnvelope",
                "inSR": "4326",
                "outSR": "4326",
                "outFields": out_fields,
                "returnGeometry": "true",
                "f": "geojson",
                "resultRecordCount": page_size,
                "resultOffset": offset,
            }
            data = None
            for attempt in range(attempts):
                resp = session.get(url, params=params, timeout=90)
                if resp.status_code in (429, 500, 502, 503, 504):
                    if attempt < attempts - 1:
                        time.sleep(0.5 * (2 ** attempt) + random.uniform(0, 0.5))
                        continue
                resp.raise_for_status()
                data = resp.json()
                break
            if data is None:
                raise requests.HTTPError(f"status {resp.status_code} after {attempts} attempts")
            if data.get("error"):
                logger.warning("ArcGIS error from %s: %s", url, data["error"])
                return None
            batch = data.get("features", [])
            features.extend(batch)
            exceeded = bool(data.get("exceededTransferLimit"))
            if not batch or (len(batch) < page_size and not exceeded):
                break
            offset += len(batch)
            if page_pause:
                time.sleep(page_pause)
        return features
    except Exception as e:  # noqa: BLE001
        logger.warning("Layer fetch failed (%s): %s", url, e)
        return None


def _load_cached_clip(path: Path, bbox_poly) -> Optional[gpd.GeoDataFrame]:
    """
    Loads a bbox clip cache. The cache records the bbox it was clipped
    to; a request the cached bbox does not fully contain is a miss (the
    clip would silently under-cover the survey area). Returns None on a
    miss — including caches written before bbox metadata existed.
    """
    if not path.exists():
        return None
    try:
        cov = gpd.read_file(path, layer="clip_bbox")
        if len(cov) == 0 or not cov.geometry.iloc[0].contains(bbox_poly):
            return None
        return gpd.read_file(path, layer="clip")
    except Exception:  # noqa: BLE001
        return None


def _save_cached_clip(path: Path, clip: gpd.GeoDataFrame, bbox_poly) -> None:
    """Writes a clip cache with its bbox coverage polygon."""
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        if path.exists():
            path.unlink()
        clip.to_file(path, layer="clip")
        gpd.GeoDataFrame({"geometry": [bbox_poly]}, crs="EPSG:4326") \
            .to_file(path, layer="clip_bbox")
    except Exception as e:  # noqa: BLE001
        logger.warning("Clip cache write failed (%s): %s", path.name, e)


def _bbox_polygon(min_lon, min_lat, max_lon, max_lat):
    from shapely.geometry import box

    return box(min_lon, min_lat, max_lon, max_lat)


def _pick_columns(df: gpd.GeoDataFrame, **wanted: str) -> Dict[str, Any]:
    """Select present source columns under stable output names."""
    out: Dict[str, Any] = {}
    for out_name, source_name in wanted.items():
        if source_name in df.columns:
            out[out_name] = df[source_name]
        else:
            out[out_name] = pd.Series([None] * len(df), index=df.index)
    out["geometry"] = df.geometry
    return out


def _slope_from_samples(samples: List[Dict[str, Any]], midlat: float
                        ) -> Tuple[Optional[float], Optional[float], int]:
    """Max/median slope (percent) from a getSamples lattice."""
    xs = sorted({round(s["location"]["x"], 9) for s in samples})
    ys = sorted({round(s["location"]["y"], 9) for s in samples})
    if len(xs) < 2 or len(ys) < 2:
        return None, None, len(samples)
    xi = {x: i for i, x in enumerate(xs)}
    yi = {y: i for i, y in enumerate(ys)}
    z = np.full((len(ys), len(xs)), np.nan)
    for s in samples:
        try:
            v = s.get("value")
            if v is None:
                continue
            z[yi[round(s["location"]["y"], 9)], xi[round(s["location"]["x"], 9)]] = float(v)
        except (KeyError, ValueError, TypeError):
            continue
    if np.isnan(z).all():
        return None, None, len(samples)
    dx_deg = np.mean(np.diff(xs)) if len(xs) > 1 else 0.0
    dy_deg = np.mean(np.diff(ys)) if len(ys) > 1 else 0.0
    if dx_deg <= 0 or dy_deg <= 0:
        return None, None, len(samples)
    dx_m = dx_deg * 111_320.0 * np.cos(np.radians(midlat))
    dy_m = dy_deg * 110_574.0
    dzdx = np.gradient(z, dx_m, axis=1)
    dzdy = np.gradient(z, dy_m, axis=0)
    slope_pct = np.sqrt(dzdx ** 2 + dzdy ** 2) * 100.0
    valid = slope_pct[~np.isnan(slope_pct)]
    if valid.size == 0:
        return None, None, len(samples)
    return float(np.max(valid)), float(np.median(valid)), int(valid.size)
