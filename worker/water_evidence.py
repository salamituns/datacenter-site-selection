"""
Water availability evidence — published utility service-area boundaries.

Water is the gate that does not generalise: floodplain, wetlands, slope,
protected land and roads are federal layers, but a water service boundary
is published by whoever runs the pipes — a county authority in Loudoun, a
district-and-city pair in Licking, a service authority in Prince William.
So the provider is data, not prose: each region names its utility and its
layers here, and every polygon is normalised into one contract before the
engine sees it:

  area_name     the utility's own name for the area (or the operator,
                where the layer encodes which utility runs that polygon)
  service_type  "W" / "WW" / "Both"
  comment       the utility's own statement, or None — never an empty
                string, because the no-new-connections branch reads that
                text and "" would say nothing only by accident
  provider      the utility that operates the polygon — row-level where
                the layer encodes it (a joint district/city layer), the
                region's utility where it does not
  last_edited   a dated fact, one way or another: the service's edit
                timestamp, or the layer's recorded vintage when the
                service exposes none (a boundary dated by its own name
                is weaker evidence and must not appear as "edited None")
  not_served    True only inside a polygon the utility itself published
                as NOT served; absence from a service layer is never
                evidence of non-service

A region with no provider configured fetches None, and the gate records
UNKNOWN — never a favourable default. Incorporated towns and districts
outside a published boundary stay UNKNOWN for the same reason.
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

# ServiceType values that carry public water service (vs wastewater-only).
WATER_SERVICE_TYPES = ("W", "Both")
# ServiceType values that carry public wastewater service (companion metric).
WASTEWATER_SERVICE_TYPES = ("WW", "Both")

# ── the provider registry ────────────────────────────────────────────
# One entry per region that has a published boundary. Anything absent
# here has no water source configured and stays UNKNOWN.
WATER_PROVIDERS: Dict[str, Dict[str, Any]] = {
    "VA-LOUDOUN": {
        "utility_name": "Loudoun Water",
        "source_key": "loudoun_water_service_area",
        "layers": [{
            "url": ("https://gportal.loudounwater.org/gis/rest/services/"
                    "Boundary/MapServer/2/query"),
            "area_name_field": "AreaName",
            "service_type_field": "ServiceType",
            "comment_field": "Comment",
            "edited_field": "last_edited_date",
            "page_size": 100,
        }],
        # The utility's explicit non-service polygon (AreaName).
        "not_served_area_name": "NOT Served by LW",
        "provider_from_row": False,
    },
    # The Southwest Licking district — renamed Licking Regional Water
    # District in 2024 — publishes a JOINT boundary for itself and the
    # Pataskala Utility Department, dated June 2021, as two layers (water,
    # wastewater) with no type column and no edit timestamp. Provider is
    # row-level here: Name holds which utility operates each polygon, not
    # a zone label, and mapping it to area_name alone would attribute
    # Pataskala-operated parcels to the district.
    "OH-LICKING": {
        "utility_name": "Licking Regional Water District",
        "source_key": "licking_lrwd_water_service",
        "layers": [
            {"url": ("https://services3.arcgis.com/iHpkStKZmEoDkIuv/arcgis/"
                     "rest/services/Water_Service_2021_view/FeatureServer/0/query"),
             "area_name_field": "Name",
             "service_type_field": None,
             "constant_service_type": "W",
             "comment_field": None,
             "edited_field": None,
             "page_size": 1000},
            {"url": ("https://services3.arcgis.com/iHpkStKZmEoDkIuv/arcgis/"
                     "rest/services/Waste_Water_Service_2021/FeatureServer/0/query"),
             "area_name_field": "Name",
             "service_type_field": None,
             "constant_service_type": "WW",
             "comment_field": None,
             "edited_field": None,
             "page_size": 1000},
        ],
        "not_served_area_name": None,
        "provider_from_row": True,
        "provider_name_map": {
            "SWLCWSD": "Licking Regional Water District (formerly SWLCWSD)",
            "Pataskala Utility Department": "Pataskala Utility Department",
            "Joint": "SWLCWSD and the Pataskala Utility Department (joint)",
        },
        # The service exposes no edit timestamp, so the vintage is recorded
        # as an explicit dated fact from the layer's own name rather than
        # left to read "edited None".
        "layer_vintage": "2021-06",
        "vintage_basis": ("the layer's own name (Water_Service_2021, June "
                          "2021); the service exposes no edit timestamp"),
    },
}


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


def _text_or_none(v: Optional[Any]) -> Optional[str]:
    """A trimmed string, or None — empty and NaN both mean nothing was said.

    The contract requires comment/area_name to be None rather than "" so
    the no-new-connections branch never reads a blank as a statement.
    """
    if v is None:
        return None
    if isinstance(v, float) and v != v:  # NaN from a pandas-typed source
        return None
    t = str(v).strip()
    return t or None


def _row_provider(spec: Dict[str, Any], props: Dict[str, Any],
                  area_name: Optional[str]) -> str:
    """The utility operating this polygon — row-level where the layer
    encodes it, the region's configured utility where it does not."""
    if not spec.get("provider_from_row"):
        return str(spec["utility_name"])
    mapping = spec.get("provider_name_map") or {}
    if area_name and area_name in mapping:
        return str(mapping[area_name])
    return str(spec["utility_name"])


def fetch_water_service_areas(
    region_key: str,
    min_lon: float, min_lat: float, max_lon: float, max_lat: float,
) -> Optional[gpd.GeoDataFrame]:
    """
    The region's published water/wastewater service-area polygons, in the
    bbox, normalised to the contract above. Returns None when the region
    has no provider configured or the layer is unavailable — the gate
    then reports UNKNOWN, never silence.
    """
    spec = WATER_PROVIDERS.get(region_key)
    if spec is None:
        logger.info("No water provider configured for %s — water gates "
                    "stay UNKNOWN.", region_key)
        return None

    session = requests.Session()
    session.headers.update({"User-Agent": BROWSER_UA, "Accept": "application/json"})
    bbox = f"{min_lon},{min_lat},{max_lon},{max_lat}"
    rows: List[Dict[str, Any]] = []
    for layer in spec["layers"]:
        rows.extend(_fetch_layer(session, spec, layer, bbox))
    if not rows:
        logger.info("%s service areas: no polygons in bbox.",
                    spec["utility_name"])
        return None
    gdf = gpd.GeoDataFrame(rows, crs="EPSG:4326")
    n_water = int(gdf.service_type.isin(WATER_SERVICE_TYPES).sum())
    logger.info(
        "%s service areas: %d polygons (%d water-serving, %d not-served) "
        "in bbox; boundary dated %s (%s).",
        spec["utility_name"], len(gdf), n_water,
        int(gdf.not_served.sum()),
        max((r["last_edited"] for r in rows if r["last_edited"]), default="?"),
        rows[0]["edited_basis"] if rows else "?",
    )
    return gdf


def _fetch_layer(session, spec: Dict[str, Any], layer: Dict[str, Any],
                 bbox: str) -> List[Dict[str, Any]]:
    url = layer["url"]
    page_size = int(layer.get("page_size", 100))
    area_field = layer.get("area_name_field")
    type_field = layer.get("service_type_field")
    comment_field = layer.get("comment_field")
    edited_field = layer.get("edited_field")
    out_fields = "OBJECTID"
    for f in (area_field, type_field, comment_field, edited_field):
        if f:
            out_fields += f",{f}"
    rows: List[Dict[str, Any]] = []
    offset = 0
    while True:
        params = {
            "where": "1=1", "geometry": bbox,
            "geometryType": "esriGeometryEnvelope", "inSR": 4326, "outSR": 4326,
            "outFields": out_fields, "returnGeometry": "true", "f": "geojson",
            "resultRecordCount": page_size, "resultOffset": offset,
        }
        try:
            r = session.get(url, params=params, timeout=90)
            r.raise_for_status()
            payload = r.json()
        except Exception as e:  # noqa: BLE001
            logger.warning("%s service-area layer unavailable: %s",
                           spec["utility_name"], e)
            return []
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
            area_name = (_text_or_none(props.get(area_field))
                         if area_field else None)
            service_type = (
                _text_or_none(props.get(type_field)) if type_field
                else layer.get("constant_service_type"))
            edited = (_to_iso_date(props.get(edited_field))
                      if edited_field else None)
            if edited:
                edited_basis = "service_edit_timestamp"
            elif spec.get("layer_vintage"):
                # Requirement: the date must appear. A layer that exposes
                # no edit timestamp carries its recorded vintage instead,
                # honestly labelled — never a silent null.
                edited, edited_basis = spec["layer_vintage"], "layer_vintage"
            else:
                edited, edited_basis = None, "none"
            rows.append({
                "area_name": area_name,
                "service_type": service_type,
                "comment": (_text_or_none(props.get(comment_field))
                            if comment_field else None),
                "provider": _row_provider(spec, props, area_name),
                "last_edited": edited,
                "edited_basis": edited_basis,
                # The vintage's own explanation, when the date comes from
                # the layer name rather than a service timestamp — the
                # rationale quotes it so the weaker evidence is visible.
                "edited_note": (spec.get("vintage_basis")
                                if edited_basis == "layer_vintage" else None),
                "not_served": bool(
                    area_name is not None
                    and area_name == spec.get("not_served_area_name")),
                "geometry": geom,
            })
        if len(feats) < page_size or not payload.get("exceededTransferLimit"):
            break
        offset += page_size
    return rows
