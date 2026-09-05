"""
Power diligence sources (Release 2) — PJM RTEP upgrades and queue activity.

The capacity question for a hyperscale parcel is not "how much land is
there" but "what does a dated source actually support":

1. RTEP upgrades (PJM, official, machine-readable): every Board-approved
   baseline / network / supplemental transmission upgrade, with the
   PJM Board approval date, the required-in-service date, and the
   projected/actual in-service (energization) dates. These are AREA-level
   evidence — they document regional reinforcements, never a
   parcel-specific MW figure.
2. PJM interconnection queue map points: observed evidence of
   interconnection activity near a parcel (queue id + facility voltage).
3. Utility territory (HIFLD Electric Retail Service Territories —
   fetched in overlay_layers): which utility actually serves the parcel.

No function in this module produces or supports a parcel-level MW
estimate. Capacity figures only ever appear as dated document facts
(power_documents / zone-level load forecasts).
"""

import logging
import re
from datetime import date, datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import geopandas as gpd
import pandas as pd
import requests
from shapely.geometry import shape

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("power_evidence")

# PJM "Project Status & Cost Allocation" dataset — the complete RTEP
# upgrade list (baseline, network, supplemental) with dates. Served as
# XML; the server truncates large responses, so the download resumes.
RTEP_XML_URL = (
    "https://www.pjm.com/pjmfiles/media/planning/"
    "projectConstruction-data/projectCostUpgrades.xml"
)
RTEP_PAGE = "https://www.pjm.com/planning/m/project-construction"

# PJM interconnection queue map (public ArcGIS service, points only:
# queue id + facility voltage — no MW/status attributes published here).
QUEUE_MAP_URL = (
    "https://gis.pjm.com/arcgis/rest/services/"
    "Renewables/Queue/MapServer/0/query"
)

BROWSER_UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) DataCenterPipeline/3.0"
)

# Substations / places that define the Loudoun transmission area for
# in_area tagging of RTEP records. Named from the RTEP record corpus
# itself (Loudoun, Brambleton, Goose Creek, Ashburn, Sterling Park,
# Aspen, Golden, North Star, Mint Springs, Poland Road, Evergreen,
# BECO, Paragon Park, Arcola, Dulles, Leesburg, Hamilton…).
AREA_KEYWORDS: List[str] = [
    "loudoun", "brambleton", "goose creek", "ashburn", "sterling", "arcola",
    "dulles", "leesburg", "hamilton", "purcellville", "waterford", "round hill",
    "aspen", "golden", "north star", "mint springs", "poland road",
    "evergreen", "beco", "paragon", "shellhorn", "travilah", "data center",
]

# RTEP statuses that mean an approved upgrade is not yet energized.
ACTIVE_STATUSES = ("EP", "UC", "PL")


def _parse_date(raw: Optional[str]) -> Optional[date]:
    """PJM publishes M/D/YYYY; a few rows carry 2-digit years."""
    if not raw:
        return None
    raw = raw.strip()
    for fmt in ("%m/%d/%Y", "%m/%d/%y"):
        try:
            return datetime.strptime(raw, fmt).date()
        except ValueError:
            continue
    return None


def _to_iso(d: Optional[date]) -> Optional[str]:
    return None if d is None else d.isoformat()


def _download_rtep_xml(dest: Path) -> Tuple[bool, int]:
    """
    Range-resumable download of the RTEP XML (the CDN truncates large
    responses). Returns (complete, bytes) where complete is True when the
    document ended with the closing </Upgrades> tag.
    """
    dest.parent.mkdir(parents=True, exist_ok=True)
    total: Optional[int] = None
    for attempt in range(120):
        have = dest.stat().st_size if dest.exists() else 0
        if total is not None and have >= total:
            break
        try:
            headers = {"User-Agent": BROWSER_UA}
            if have:
                headers["Range"] = f"bytes={have}-"
            with requests.get(RTEP_XML_URL, headers=headers, stream=True,
                              timeout=120) as r:
                if r.status_code == 416:
                    break
                r.raise_for_status()
                if r.status_code == 200:
                    # full-body restart (server ignored the range)
                    have = 0
                    dest.write_bytes(b"")
                cr = r.headers.get("Content-Range")
                if cr and "/" in cr:
                    total = int(cr.split("/")[1])
                with open(dest, "ab") as f:
                    for chunk in r.iter_content(1 << 16):
                        f.write(chunk)
        except Exception as e:  # noqa: BLE001
            logger.warning("RTEP download retry %d: %s", attempt + 1, e)
    size = dest.stat().st_size if dest.exists() else 0
    if size == 0:
        return False, 0
    with open(dest, "rb") as f:
        f.seek(max(0, size - 4096))
        tail = f.read().decode("utf-8", "replace")
    return "</Upgrades>" in tail, size


def _text(block: str, tag: str) -> str:
    m = re.search(rf"<{tag}>\s*(.*?)\s*</{tag}>", block, re.S)
    return m.group(1).strip() if m else ""


def fetch_rtep_upgrades(state_code: str, area_keywords: Optional[List[str]] = None) -> Optional[pd.DataFrame]:
    """
    PJM RTEP upgrade records for the state (plus Dominion-zone records for
    VA, since the DOM zone crosses state lines). One row per upgrade with
    parsed dates and an in_area flag for the survey county's transmission
    area. Returns None when the dataset is unreachable — the power gate
    then records UNKNOWN.
    """
    keywords = [k.lower() for k in (area_keywords or AREA_KEYWORDS)]
    dest = Path(__file__).parent / "cache" / "pjm_project_cost_upgrades.xml"
    complete, size = _download_rtep_xml(dest)
    if size == 0:
        logger.warning("RTEP upgrade dataset unreachable.")
        return None
    if not complete:
        logger.warning("RTEP XML truncated by the server after %d bytes — "
                       "parsing complete records only.", size)

    data = dest.read_text(encoding="utf-8", errors="replace")
    blocks = re.findall(r"<Upgrade>.*?</Upgrade>", data, re.S)
    rows: List[Dict[str, Any]] = []
    for b in blocks:
        state_tokens = _text(b, "State").upper().split()
        owner = _text(b, "TransmissionOwner")
        # VA run: keep VA records plus Dominion-zone records (the zone
        # spans VA/MD/WV corridors feeding Data Center Alley).
        if state_code not in state_tokens and not (
            state_code == "VA" and owner.lower().startswith("dominion")
        ):
            continue
        description = _text(b, "Description")
        location = _text(b, "Location")
        haystack = f"{description} {location}".lower()
        substation = next((k for k in keywords if k in haystack), "")
        try:
            voltage = float(_text(b, "Voltage")) if _text(b, "Voltage") else None
        except ValueError:
            voltage = None
        try:
            cost = float(_text(b, "CostEstimate")) if _text(b, "CostEstimate") else None
        except ValueError:
            cost = None
        rows.append({
            "upgrade_id": _text(b, "UpgradeId"),
            "project_type": _text(b, "ProjectType") or "Unknown",
            "description": description,
            "transmission_owner": owner,
            "substation": substation or None,
            "in_area": any(k in haystack for k in keywords),
            "voltage_kv": voltage,
            "status": _text(b, "Status") or "Unknown",
            "equipment": _text(b, "Equipment") or None,
            "driver": _text(b, "Driver") or None,
            "cost_estimate_musd": cost,
            "board_approval_date": _to_iso(_parse_date(_text(b, "PJMBoardApprovalDate"))),
            "required_date": _to_iso(_parse_date(_text(b, "RequiredDate"))),
            "projected_in_service_date": _to_iso(_parse_date(_text(b, "ProjectedInServiceDate"))),
            "revised_in_service_date": _to_iso(_parse_date(_text(b, "RevisedInServiceDate"))),
            "actual_in_service_date": _to_iso(_parse_date(_text(b, "ActualInServiceDate"))),
            "source_updated": _to_iso(_parse_date(_text(b, "LastUpdated"))),
        })
    if not rows:
        logger.warning("RTEP dataset parsed but no %s records found.", state_code)
        return None
    df = pd.DataFrame(rows).drop_duplicates(subset=["upgrade_id"])
    area_active = df[df.in_area & df.status.isin(ACTIVE_STATUSES)]
    logger.info("PJM RTEP upgrades: %d %s/Dominion records (%d in-area, "
                "%d active in-area). Complete document: %s.",
                len(df), state_code, int(df.in_area.sum()), len(area_active),
                complete)
    return df


def rtep_upsert_records(df: pd.DataFrame, state_code: str) -> List[Dict[str, Any]]:
    """Staging rows for power_rtep_upgrades (NaN-safe: pandas turns the
    XML's empty tags into NaN, which PostgREST rejects as JSON)."""

    def _clean(value: Any) -> Optional[Any]:
        if value is None or (isinstance(value, float) and pd.isna(value)):
            return None
        return value

    def _date(value: Any) -> Optional[str]:
        value = _clean(value)
        return None if value is None else str(value)

    def _num(value: Any) -> Optional[float]:
        value = _clean(value)
        return None if value is None else float(value)

    def _text(value: Any, width: int) -> Optional[str]:
        value = _clean(value)
        return None if value is None else str(value)[:width]

    return [{
        "upgrade_id": str(r.upgrade_id),
        "state_code": state_code,
        "project_type": str(r.project_type)[:20],
        "description": str(r.description) or "(no description published)",
        "transmission_owner": _text(r.transmission_owner, 80),
        "substation": _text(r.substation, 120),
        "in_area": bool(r.in_area),
        "voltage_kv": _num(r.voltage_kv),
        "status": str(r.status)[:16],
        "equipment": _text(r.equipment, 160),
        "driver": _text(r.driver, 240),
        "cost_estimate_musd": _num(r.cost_estimate_musd),
        "board_approval_date": _date(r.board_approval_date),
        "required_date": _date(r.required_date),
        "projected_in_service_date": _date(r.projected_in_service_date),
        "revised_in_service_date": _date(r.revised_in_service_date),
        "actual_in_service_date": _date(r.actual_in_service_date),
        "source_updated": _date(r.source_updated),
    } for r in df.itertuples()]


def fetch_pjm_queue_points(
    min_lon: float, min_lat: float, max_lon: float, max_lat: float
) -> Optional[gpd.GeoDataFrame]:
    """
    PJM interconnection queue points in the bbox (observed activity
    evidence: queue id + facility voltage). The public layer publishes no
    MW/status attributes, so none are claimed here.
    """
    session = requests.Session()
    session.headers.update({"User-Agent": BROWSER_UA, "Accept": "application/json"})
    rows: List[Dict[str, Any]] = []
    offset = 0
    bbox = f"{min_lon},{min_lat},{max_lon},{max_lat}"
    while True:
        params = {
            "where": "1=1", "geometry": bbox, "geometryType": "esriGeometryEnvelope",
            "inSR": 4326, "outSR": 4326, "outFields": "QUEUE_ID,VOLTAGE",
            "returnGeometry": "true", "f": "geojson",
            "resultRecordCount": 1000, "resultOffset": offset,
        }
        try:
            r = session.get(QUEUE_MAP_URL, params=params, timeout=90)
            r.raise_for_status()
            payload = r.json()
        except requests.exceptions.SSLError:
            logger.warning("PJM queue map TLS certificate rejected — retrying unverified.")
            try:
                r = session.get(QUEUE_MAP_URL, params=params, timeout=90, verify=False)
                r.raise_for_status()
                payload = r.json()
            except Exception as e:  # noqa: BLE001
                logger.warning("PJM queue map unavailable: %s", e)
                return None
        except Exception as e:  # noqa: BLE001
            logger.warning("PJM queue map unavailable: %s", e)
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
                "queue_id": str(props.get("QUEUE_ID") or ""),
                "voltage_kv": props.get("VOLTAGE"),
                "geometry": geom,
            })
        if len(feats) < 1000 or not payload.get("exceededTransferLimit"):
            break
        offset += 1000
    if not rows:
        logger.info("PJM queue map: no queue points in bbox.")
        return None
    gdf = gpd.GeoDataFrame(rows, crs="EPSG:4326")
    logger.info("PJM queue map: %d interconnection points in bbox.", len(gdf))
    return gdf
