"""
Hazard Risk Ingestion Module
----------------------------
Fetches real geological and hydro-meteorological hazard data for a survey:

1. Seismic — USGS National Seismic Hazard Model via the ASCE 7-16 design
   web service. Returns the uniform-hazard Peak Ground Acceleration
   (2% probability of exceedance in 50 years, site class BC) per grid
   centroid, cached at ~11 km precision (PGA varies smoothly at that
   scale, so neighboring 3.16 km cells share a lookup).
2. FEMA National Risk Index (NRI) — county-level riverine/coastal
   flooding and hurricane risk scores (0-100) from the public NRI
   Counties layer. Inland counties report no coastal/hurricane risk,
   which is preserved as 0.

Both fetchers degrade to None so grid_parser keeps its deterministic
synthetic model when a service is unreachable.
"""

from typing import Dict, List, Optional, Any
import logging
import math

import pandas as pd
import requests

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("hazard_api")

# NRI queries by full state name.
STATE_NAMES: Dict[str, str] = {
    "VA": "Virginia",
    "TX": "Texas",
    "OH": "Ohio",
    "OR": "Oregon",
}


class HazardAPI:
    """Queries USGS seismic hazard and FEMA NRI county risk for a survey."""

    # ASCE 7-16 design service; `pgauh` is the uniform-hazard PGA in g.
    USGS_URL = "https://earthquake.usgs.gov/ws/building-codes/asce7-16/calculate"
    NRI_URL = (
        "https://services.arcgis.com/XG15cJAlne2vxtgt/arcgis/rest/services/"
        "National_Risk_Index_Counties/FeatureServer/0/query"
    )

    def __init__(self, timeout: int = 20):
        self.timeout = timeout
        self._session = requests.Session()
        self._pga_cache: Dict[str, float] = {}

    # ── Seismic (PGA) ──────────────────────────────────────────────────

    def fetch_pga(self, lon: float, lat: float) -> Optional[float]:
        """Uniform-hazard PGA (g) for a point, cached at ~11 km precision."""
        key = f"{lon:.1f},{lat:.1f}"
        if key in self._pga_cache:
            return self._pga_cache[key]

        try:
            response = self._session.get(
                self.USGS_URL,
                params={
                    "latitude": f"{lat:.4f}",
                    "longitude": f"{lon:.4f}",
                    "siteClass": "BC",
                    "riskCategory": "III",
                },
                timeout=self.timeout,
            )
            response.raise_for_status()
            data = response.json().get("response", {}).get("data", {})
            pga = data.get("pgauh")
            if pga is None:
                pga = data.get("pga")
            if pga is not None:
                pga = round(float(pga), 4)
                self._pga_cache[key] = pga
                return pga
        except Exception as e:
            logger.warning(f"USGS design service query failed ({key}): {e}")
        return None

    def fetch_pga_for_grid(self, grid_gdf: pd.DataFrame) -> Optional[Dict[str, float]]:
        """PGA lookup keyed by centroid for every unique ~11 km cell."""
        lookup: Dict[str, float] = {}
        centroids = grid_gdf["centroid"]
        points = set((round(c.x, 1), round(c.y, 1)) for c in centroids)

        for lon_r, lat_r in sorted(points):
            pga = self.fetch_pga(lon_r, lat_r)
            if pga is None:
                # Any hard failure means the service is unusable for this
                # run — caller falls back to the synthetic model entirely
                # rather than mixing real and synthetic per parcel.
                return None
            lookup[f"{lon_r:.1f},{lat_r:.1f}"] = pga

        logger.info(f"USGS seismic hazard: {len(points)} unique PGA points for {len(grid_gdf)} parcels.")
        return lookup

    @staticmethod
    def pga_key(lon: float, lat: float) -> str:
        """Key matching fetch_pga_for_grid's ~11 km precision."""
        return f"{round(lon, 1):.1f},{round(lat, 1):.1f}"

    # ── FEMA NRI (county flood / hurricane) ────────────────────────────

    def fetch_county_risk(self, state_code: str, county_name: str) -> Optional[Dict[str, float]]:
        """
        NRI county risk scores: riverine/coastal flooding (whichever is
        higher) and hurricane, both 0-100. None when the service fails
        so the caller falls back to the synthetic model.
        """
        state_name = STATE_NAMES.get(state_code.upper())
        if not state_name:
            logger.warning(f"No NRI state name mapping for '{state_code}'.")
            return None

        try:
            response = self._session.get(
                self.NRI_URL,
                params={
                    "where": f"STATE='{state_name}' AND COUNTY='{county_name}'",
                    "outFields": "STATE,COUNTY,CFLD_RISKS,IFLD_RISKS,HRCN_RISKS",
                    "f": "json",
                },
                timeout=self.timeout,
            )
            response.raise_for_status()
            features = response.json().get("features", [])
            if not features:
                logger.warning(f"NRI returned no county row for {county_name}, {state_name}.")
                return None

            attrs = features[0]["attributes"]
            coastal = attrs.get("CFLD_RISKS")
            riverine = attrs.get("IFLD_RISKS")
            hurricane = attrs.get("HRCN_RISKS")

            # Inland counties legitimately have no coastal/hurricane risk.
            candidates = [v for v in (coastal, riverine) if v is not None]
            flood = max(candidates) if candidates else 0.0

            result = {
                "flood_risk_score": round(float(flood), 1),
                "hurricane_risk_score": round(float(hurricane or 0.0), 1),
            }
            logger.info(
                f"FEMA NRI for {county_name}, {state_name}: flood {result['flood_risk_score']}/100, "
                f"hurricane {result['hurricane_risk_score']}/100."
            )
            return result
        except Exception as e:
            logger.warning(f"NRI county query failed ({county_name}, {state_name}): {e}")
            return None


if __name__ == "__main__":
    api = HazardAPI()
    pga = api.fetch_pga(-77.5, 39.0)
    print(f"PGA for Loudoun VA: {pga} g")
    for code, county in (("VA", "Loudoun"), ("TX", "Taylor"), ("OH", "Franklin"), ("OR", "Morrow")):
        print(code, api.fetch_county_risk(code, county))
