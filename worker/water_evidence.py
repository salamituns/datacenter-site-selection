"""
Water availability evidence — Loudoun Water's published service-area boundary.

Loudoun Water (LCSA) publishes its water / wastewater service areas, the
Central System, and an explicit "NOT Served by LW" boundary on its public
ArcGIS server. These polygons are the observed, dated basis for the
water_availability parcel gate:

  * ServiceType "W" or "Both"  → the area provides public water service
  * AreaName "NOT Served by LW" → the utility's own record of where it
    does NOT provide service (rural wells / other providers)
  * per-feature last_edited_date → the layer's dated provenance

Incorporated towns run their own municipal systems and are not covered by
this layer — parcels inside towns stay UNKNOWN, never a favorable default.
"""

import logging
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

import geopandas as gpd
import requests
from shapely.geometry import shape

logger = logging.getLogger("water_evidence")

BROWSER_UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
)

WATER_SERVICE_AREA_URL = (
    "https://gportal.loudounwater.org/gis/rest/services/"
    "Boundary/MapServer/2/query"
)

# ServiceType values that carry public water service (vs wastewater-only).
WATER_SERVICE_TYPES = ("W", "Both")
# ServiceType values that carry public wastewater service (companion metric).
WASTEWATER_SERVICE_TYPES = ("WW", "Both")
# The utility's explicit non-service polygon (AreaName).
NOT_SERVED_AREA_NAME = "NOT Served by LW"


def _to_iso_date(epoch_ms: Optional[Any]) -> Optional[str]:
    """ArcGIS epoch-milliseconds field → ISO date (timezone-safe)."""
    if epoch_ms is None:
        return None
    try:
        return datetime.fromtimestamp(
            int(epoch_ms) / 1000.0, tz=timezone.utc
        ).date().isoformat()
    except (TypeError, ValueError, OSError):
        return None


def fetch_water_service_areas(
    min_lon: float, min_lat: float, max_lon: float, max_lat: float
) -> Optional[gpd.GeoDataFrame]:
    """
    Loudoun Water service-area polygons in the bbox (observed evidence:
    area name, service type, owner, comment, boundary, last-edited date).
    Returns None when the layer is unavailable — the gate then reports
    UNKNOWN, never silence.
    """
    session = requests.Session()
    session.headers.update({"User-Agent": BROWSER_UA, "Accept": "application/json"})
    bbox = f"{min_lon},{min_lat},{max_lon},{max_lat}"
    rows: List[Dict[str, Any]] = []
    offset = 0
    while True:
        params = {
            "where": "1=1", "geometry": bbox, "geometryType": "esriGeometryEnvelope",
            "inSR": 4326, "outSR": 4326,
            "outFields": ("OBJECTID,AreaName,SystemName,ServiceType,Owner,"
                          "Comment,DateOnLine,last_edited_date"),
            "returnGeometry": "true", "f": "geojson",
            "resultRecordCount": 100, "resultOffset": offset,
        }
        try:
            r = session.get(WATER_SERVICE_AREA_URL, params=params, timeout=90)
            r.raise_for_status()
            payload = r.json()
        except Exception as e:  # noqa: BLE001
            logger.warning("Loudoun Water service-area layer unavailable: %s", e)
            return None
        feats = payload.get("features") or []
        for f in feats:
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
                "area_name": str(props.get("AreaName") or ""),
                "system_name": str(props.get("SystemName") or ""),
                "service_type": (str(props.get("ServiceType"))
                                 if props.get("ServiceType") else None),
                "owner": str(props.get("Owner") or ""),
                "comment": str(props.get("Comment") or ""),
                "date_online": _to_iso_date(props.get("DateOnLine")),
                "last_edited": _to_iso_date(props.get("last_edited_date")),
                "geometry": geom,
            })
        if len(feats) < 100 or not payload.get("exceededTransferLimit"):
            break
        offset += 100
    if not rows:
        logger.info("Loudoun Water service areas: no polygons in bbox.")
        return None
    gdf = gpd.GeoDataFrame(rows, crs="EPSG:4326")
    n_water = int(gdf.service_type.isin(WATER_SERVICE_TYPES).sum())
    logger.info(
        "Loudoun Water service areas: %d polygons (%d water-serving) in bbox.",
        len(gdf), n_water,
    )
    return gdf
