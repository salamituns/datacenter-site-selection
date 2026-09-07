"""
Verification layer fetchers — the three pending gates of the Loudoun pilot.

1. TIGER roads (Census TIGERweb/Transportation): primary (S1100) and
   secondary (S1200) road segments for the road-access gate.
2. PAD-US 4.0 (USGS, official ScienceBase state geodatabase): protected
   areas for the protected-land gate. The national hosted ArcGIS layers
   are partial subsets, so the official Virginia GDB is downloaded once,
   clipped to the survey bbox, and cached as a GeoPackage; later runs
   reuse the clip.
3. 3DEP slopes (USGS 3DEPElevation ImageServer getSamples): a 32x32
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

# Official PAD-US 4.0 Virginia state geodatabase (ScienceBase).
PADUS_VA_URL = (
    "https://www.sciencebase.gov/catalog/file/get/"
    "652d4f80d34e44db0e2ee45c?f=__disk__b0%2Ff9%2F01%2F"
    "b0f9011ebcc5df4be4019382441f23e86f8bf598"
)
PADUS_CACHE = Path(__file__).parent / "cache" / "padus_va_clip.gpkg"

# Official NWI Virginia state geodatabase (USFWS ecosphere document
# server). Used only when the NWI REST service is unreachable — the
# WIM-hosted service has been serving error pages for extended periods.
NWI_SERVICE_URL = (
    "https://fwspublicservices.wim.usgs.gov/wetlandsarcgis/rest/services/"
    "Wetlands/MapServer/0/query"
)
NWI_VA_URL = (
    "https://documentst.ecosphere.fws.gov/wetlands/data/"
    "State-Downloads/VA_geodatabase_wetlands.zip"
)
NWI_CACHE = Path(__file__).parent / "cache" / "nwi_va_clip.gpkg"

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
    min_lon: float, min_lat: float, max_lon: float, max_lat: float
) -> Optional[gpd.GeoDataFrame]:
    """Primary + secondary road segments within the bbox (TIGERweb)."""
    session = requests.Session()
    session.headers.update({"User-Agent": BROWSER_UA, "Accept": "application/json"})
    bbox = f"{min_lon},{min_lat},{max_lon},{max_lat}"
    rows: List[Dict[str, Any]] = []
    for road_class, layer in TIGER_LAYERS.items():
        features = _paged_query(
            session, TIGER_URL.format(layer=layer), bbox,
            out_fields="BASENAME,MTFCC,RTTYP",
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
    if not rows:
        logger.warning("TIGER roads: no segments in bbox.")
        return None
    gdf = gpd.GeoDataFrame(rows, crs="EPSG:4326")
    logger.info("TIGER roads: %d segments (%d primary, %d secondary).",
                len(gdf), (gdf.road_class == "primary").sum(),
                (gdf.road_class == "secondary").sum())
    return gdf


def fetch_padus(
    min_lon: float, min_lat: float, max_lon: float, max_lat: float
) -> Optional[gpd.GeoDataFrame]:
    """
    PAD-US 4.0 protected areas within the bbox. Downloads the official
    Virginia geodatabase on first use and caches the bbox clip.
    """
    bbox_poly = _bbox_polygon(min_lon, min_lat, max_lon, max_lat)
    if PADUS_CACHE.exists():
        clip = gpd.read_file(PADUS_CACHE, layer="protected")
        logger.info("PAD-US: %d cached protected-area polygons.", len(clip))
        return clip if len(clip) else None
    try:
        PADUS_CACHE.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory() as tmp:
            zip_path = Path(tmp) / "padus_va.zip"
            logger.info("PAD-US: downloading Virginia geodatabase (~101 MB)…")
            dl = requests.get(PADUS_VA_URL, stream=True, timeout=900,
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
            # The combined inventory (fee + designation + easement) is the
            # screening-appropriate layer; fall back per-name if absent.
            preferred = [l for l in layers if "Combined" in l]
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
            if len(within) == 0:
                logger.info("PAD-US: no protected areas in bbox.")
                return None
            # Persist the raw layer for reuse, then return the clip.
            within.to_file(PADUS_CACHE, layer="protected")
            logger.info("PAD-US: %d protected-area polygons in bbox (cached).", len(within))
            return within
    except Exception as e:  # noqa: BLE001
        logger.warning("PAD-US fetch failed: %s", e)
        return None


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
    min_lon: float, min_lat: float, max_lon: float, max_lat: float
) -> Tuple[Optional[gpd.GeoDataFrame], str]:
    """
    NWI wetland polygons for the bbox. Tries the REST service first
    (fresh when healthy); when it is down, falls back to the official
    Virginia state geodatabase, downloaded once and clipped/cached.

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
    logger.warning("NWI service unreachable — falling back to the official "
                   "Virginia geodatabase (download once, cached).")
    try:
        if NWI_CACHE.exists():
            clip = gpd.read_file(NWI_CACHE, layer="wetlands")
            logger.info("NWI wetlands (cached clip): %d polygons.", len(clip))
            return clip, NWI_VA_URL
        NWI_CACHE.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory() as tmp:
            zip_path = Path(tmp) / "nwi_va.zip"
            logger.info("NWI: downloading Virginia geodatabase (~395 MB)…")
            dl = requests.get(NWI_VA_URL, stream=True, timeout=1800,
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
                return None, NWI_VA_URL
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
                return None, NWI_VA_URL
            out = gpd.GeoDataFrame({
                "attribute": clip[attr_col] if attr_col else None,
                "geometry": clip.geometry,
            }, crs="EPSG:4326")
            out.to_file(NWI_CACHE, layer="wetlands")
            logger.info("NWI wetlands (geodatabase clip): %d polygons (cached).", len(out))
            return out, NWI_VA_URL
    except Exception as e:  # noqa: BLE001
        logger.warning("NWI wetlands fetch failed: %s", e)
        return None, NWI_VA_URL


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
                 page_size: int = 1000) -> Optional[List[Dict[str, Any]]]:
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
            resp = session.get(url, params=params, timeout=90)
            resp.raise_for_status()
            data = resp.json()
            if data.get("error"):
                logger.warning("ArcGIS error from %s: %s", url, data["error"])
                return None
            batch = data.get("features", [])
            features.extend(batch)
            exceeded = bool(data.get("exceededTransferLimit"))
            if not batch or (len(batch) < page_size and not exceeded):
                break
            offset += len(batch)
        return features
    except Exception as e:  # noqa: BLE001
        logger.warning("Layer fetch failed (%s): %s", url, e)
        return None


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
