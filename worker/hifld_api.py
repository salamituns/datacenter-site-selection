"""
HIFLD Power Grid Ingestion Module
---------------------------------
Fetches real electric transmission infrastructure from the Homeland
Infrastructure Foundation-Level Data (HIFLD) open ArcGIS FeatureServers,
bounded to a survey bbox:

1. Electric_Power_Transmission_Lines — 115 kV+ AC lines in service,
   with owner, voltage, and endpoint substation names.
2. Electric_Substations — named transmission substations with
   min/max operating voltage.

Queries use esriGeometryEnvelope intersection in EPSG:4326 with
paginated GeoJSON responses. When the services are unreachable or
return no features, callers fall back to the synthetic corridor
template (see grid_parser._generate_mock_hifld_corridors).
"""

from typing import Dict, List, Optional, Tuple, Any
import logging

import requests
import geopandas as gpd
from shapely.geometry import shape

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("hifld_api")


class HIFLDPowerAPI:
    """Queries HIFLD electric power transmission layers for a survey bbox."""

    TRANSMISSION_URL = (
        "https://services1.arcgis.com/Hp6G80Pky0om7QvQ/ArcGIS/rest/services/"
        "Electric_Power_Transmission_Lines/FeatureServer/0/query"
    )
    SUBSTATIONS_URL = (
        "https://services5.arcgis.com/HDRa0B57OVrv2E1q/ArcGIS/rest/services/"
        "Electric_Substations/FeatureServer/0/query"
    )

    # HIFLD substations include distribution-class sites; a 100 kV floor
    # keeps the "nearest substation" metric transmission-relevant.
    MIN_VOLTAGE_KV = 100.0

    def __init__(self, timeout: int = 30, page_size: int = 1000):
        self.timeout = timeout
        self.page_size = page_size
        self._session = requests.Session()

    def fetch_power_by_bbox(
        self,
        min_lon: float,
        min_lat: float,
        max_lon: float,
        max_lat: float
    ) -> Tuple[Optional[gpd.GeoDataFrame], Optional[gpd.GeoDataFrame]]:
        """
        Returns (transmission_lines_gdf, substations_gdf) clipped to the
        bbox and filtered to transmission voltages. Returns (None, None)
        when the services are unavailable so callers can fall back.
        """
        bbox = f"{min_lon},{min_lat},{max_lon},{max_lat}"

        lines = self._fetch_paginated(
            self.TRANSMISSION_URL,
            bbox,
            out_fields="VOLTAGE,VOLT_CLASS,OWNER,SUB_1,SUB_2,TYPE,STATUS",
        )
        subs = self._fetch_paginated(
            self.SUBSTATIONS_URL,
            bbox,
            out_fields="NAME,TYPE,MAX_VOLT,MIN_VOLT",
        )

        if lines is None or subs is None:
            return None, None

        lines_gdf = self._lines_to_gdf(lines)
        subs_gdf = self._subs_to_gdf(subs)

        if lines_gdf is None or subs_gdf is None or len(lines_gdf) == 0 or len(subs_gdf) == 0:
            logger.warning("HIFLD returned no usable power features for this bbox.")
            return None, None

        logger.info(
            "HIFLD fetched %d transmission lines and %d substations (>= %g kV) for bbox [%s].",
            len(lines_gdf), len(subs_gdf), self.MIN_VOLTAGE_KV, bbox
        )
        return lines_gdf, subs_gdf

    # ── Internals ─────────────────────────────────────────────────────

    def _fetch_paginated(self, base_url: str, bbox: str, out_fields: str) -> Optional[List[Dict[str, Any]]]:
        """Pages through an ArcGIS FeatureServer query; None on hard failure."""
        features: List[Dict[str, Any]] = []
        offset = 0
        try:
            while True:
                params = {
                    "where": "1=1",
                    "geometry": bbox,
                    "geometryType": "esriGeometryEnvelope",
                    "inSR": "4326",
                    "outSR": "4326",
                    "outFields": out_fields,
                    "f": "geojson",
                    "resultRecordCount": self.page_size,
                    "resultOffset": offset,
                }
                response = self._session.get(base_url, params=params, timeout=self.timeout)
                response.raise_for_status()
                data = response.json()

                batch = data.get("features", [])
                features.extend(batch)

                if len(batch) < self.page_size:
                    break
                offset += self.page_size

            return features
        except Exception as e:
            logger.warning(f"HIFLD query failed ({base_url.split('/rest/')[0]}): {e}")
            return None

    def _lines_to_gdf(self, features: List[Dict[str, Any]]) -> Optional[gpd.GeoDataFrame]:
        """Builds a transmission-line GeoDataFrame filtered to in-service AC lines."""
        rows = []
        for feature in features:
            try:
                props = feature.get("properties", {}) or {}
                geometry = feature.get("geometry")
                if geometry is None:
                    continue

                status = str(props.get("STATUS") or "").upper()
                if status and "IN SERVICE" not in status:
                    continue

                line_type = str(props.get("TYPE") or "").upper()
                if line_type and not line_type.startswith("AC"):
                    continue

                voltage = self._parse_voltage(props.get("VOLTAGE"))
                if voltage is None or voltage < self.MIN_VOLTAGE_KV:
                    continue

                geom = shape(geometry)
                rows.append({
                    "voltage_kv": voltage,
                    "volt_class": props.get("VOLT_CLASS"),
                    "owner": props.get("OWNER"),
                    "line_name": f"{props.get('SUB_1') or 'Origin'} → {props.get('SUB_2') or 'Terminus'}",
                    "geometry": geom,
                })
            except Exception:
                continue

        if not rows:
            return None
        return gpd.GeoDataFrame(rows, crs="EPSG:4326")

    def _subs_to_gdf(self, features: List[Dict[str, Any]]) -> Optional[gpd.GeoDataFrame]:
        """Builds a substation GeoDataFrame filtered to transmission voltages."""
        rows = []
        for feature in features:
            try:
                props = feature.get("properties", {}) or {}
                geometry = feature.get("geometry")
                if geometry is None:
                    continue

                max_volt = self._parse_voltage(props.get("MAX_VOLT"))
                if max_volt is None or max_volt < self.MIN_VOLTAGE_KV:
                    continue

                name = str(props.get("NAME") or "Unnamed Substation").strip()
                if name.upper().startswith("UNKNOWN"):
                    name = "Unnamed Substation"

                rows.append({
                    "substation_name": name,
                    "voltage_kv": float(max_volt),
                    "geometry": shape(geometry),
                })
            except Exception:
                continue

        if not rows:
            return None
        return gpd.GeoDataFrame(rows, crs="EPSG:4326")

    @staticmethod
    def _parse_voltage(value: Any) -> Optional[float]:
        """Normalizes HIFLD voltage values ('230', 230, '220-287', None) to kV."""
        if value is None:
            return None
        try:
            return float(value)
        except (ValueError, TypeError):
            # Ranged classes like "220-287" — take the upper bound.
            text = str(value)
            parts = [p for p in text.replace("-", " ").split() if p.replace(".", "").isdigit()]
            if parts:
                try:
                    return float(parts[-1])
                except ValueError:
                    return None
            return None


if __name__ == "__main__":
    api = HIFLDPowerAPI()
    lines, subs = api.fetch_power_by_bbox(-77.85, 38.75, -77.25, 39.25)
    if lines is not None and subs is not None:
        print("Loudoun survey bbox:")
        print(f"  Lines: {len(lines)} | example: {lines.iloc[0]['line_name']} ({lines.iloc[0]['voltage_kv']} kV, {lines.iloc[0]['owner']})")
        print(f"  Substations: {len(subs)} | example: {subs.iloc[0]['substation_name']} ({subs.iloc[0]['voltage_kv']} kV)")
    else:
        print("HIFLD unavailable — pipeline would fall back to synthetic corridors.")
