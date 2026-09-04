"""
Loudoun County parcel qualification ingestion
---------------------------------------------
Fetches the real cadastral and regulatory layers for the Loudoun pilot:

1. Parcel boundaries — county LandRecords service (PIN + legal acreage).
2. Zoning ordinance districts — the county's authoritative digital zoning
   map (district code, name, ordinance vintage, use-table links).
3. NWI wetlands — USFWS National Wetlands Inventory polygons.
4. FEMA flood hazard zones — the county's FEMAFlood service, a mirror of
   the FEMA DFIRM flood hazard areas (S_Fld_Haz_Ar) for Loudoun
   (DFIRM_ID 51107C) including the regulatory floodway. The federal
   NFHL endpoint throttles county-sized envelope queries (500s /
   connection resets on pages >=500 records); the county mirror serves
   identical FLD_ZONE / ZONE_SUBTY / SFHA_TF attributes unthrottled.

All queries are envelope-bounded (EPSG:4326) and paginated. Unlike the
regional screening layers, these fetchers have NO synthetic fallback:
a failure marks the layer UNKNOWN instead of inventing values.
"""

from typing import Any, Dict, List, Optional, Tuple
import logging

import requests
import geopandas as gpd
from shapely.geometry import shape

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("loudoun_api")


class LoudounParcelAPI:
    """County cadastral + land/environmental gate layers for a survey bbox."""

    PARCELS_URL = (
        "https://logis.loudoun.gov/gis/rest/services/COL/LandRecords/MapServer/5/query"
    )
    ZONING_URL = (
        "https://logis.loudoun.gov/gis/rest/services/ZoningOrd/ZoningOrdinance/MapServer/0/query"
    )
    WETLANDS_URL = (
        "https://fwspublicservices.wim.usgs.gov/wetlandsarcgis/rest/services/"
        "Wetlands/MapServer/0/query"
    )
    NFHL_URL = (
        "https://logis.loudoun.gov/gis/rest/services/COL/FEMAFlood/MapServer/4/query"
    )

    # Source-side pre-filter on the county-recorded legal acreage. The
    # threshold is recorded in the run config; the contiguous-acreage gate
    # itself runs on the derived GIS acreage after fetch.
    MIN_SOURCE_ACRES = 20.0

    def __init__(self, timeout: int = 60, page_size: int = 2000):
        self.timeout = timeout
        self.page_size = page_size
        self._session = requests.Session()
        # A browser-style UA with a pipeline identifier: FEMA endpoints
        # reset connections from default library UAs; county and USGS
        # services accept it without issue.
        self._session.headers.update({
            "User-Agent": (
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                "AppleWebKit/537.36 (KHTML, like Gecko) DataCenterPipeline/3.0"
            ),
            "Accept": "application/json",
        })

    def fetch_all(
        self, min_lon: float, min_lat: float, max_lon: float, max_lat: float,
        min_acres: float = MIN_SOURCE_ACRES
    ) -> Dict[str, Optional[gpd.GeoDataFrame]]:
        """
        Fetches every parcel-qualification layer for the bbox. Returns a
        dict of layer → GeoDataFrame (None when a layer is unavailable —
        the caller records UNKNOWN, never a fallback).
        """
        bbox = f"{min_lon},{min_lat},{max_lon},{max_lat}"
        return {
            "parcels": self.fetch_parcels(bbox, min_acres),
            "zoning": self.fetch_zoning(bbox),
            "wetlands": self.fetch_wetlands(bbox),
            "nfhl": self.fetch_nfhl(bbox),
        }

    def fetch_parcels(self, bbox: str, min_acres: float) -> Optional[gpd.GeoDataFrame]:
        features = self._fetch_paginated(
            self.PARCELS_URL, bbox,
            out_fields="PA_MCPI,PA_LEGAL_ACRE,PA_TYPE,PA_UPD_DATE",
            where=f"PA_LEGAL_ACRE >= {min_acres}",
        )
        if features is None:
            return None
        rows = []
        for f in features:
            props = f.get("properties", {}) or {}
            geometry = f.get("geometry")
            pin = str(props.get("PA_MCPI") or "").strip()
            if not geometry or not pin:
                continue
            try:
                geom = shape(geometry)
            except Exception:  # noqa: BLE001
                continue
            if geom.is_empty or not geom.is_valid:
                geom = geom.buffer(0)
            if geom.is_empty:
                continue
            rows.append({
                "pin": pin,
                "legal_acreage": props.get("PA_LEGAL_ACRE"),
                "pa_type": props.get("PA_TYPE"),
                "geometry": geom,
            })
        if not rows:
            logger.warning("Loudoun parcels: no features returned.")
            return None
        gdf = gpd.GeoDataFrame(rows, crs="EPSG:4326")
        logger.info("Loudoun parcels: %d parcels >= %g acres (legal).", len(gdf), min_acres)
        return gdf

    def fetch_zoning(self, bbox: str) -> Optional[gpd.GeoDataFrame]:
        features = self._fetch_paginated(
            self.ZONING_URL, bbox,
            out_fields="ZO_ZONE,ZD_ZONE_NAME,ZO_ORDINANCE,ZO_ZONE_DATE,ZO_ZONE_ORD",
        )
        if features is None:
            return None
        rows = []
        for f in features:
            props = f.get("properties", {}) or {}
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
            rows.append({
                "zone": str(props.get("ZO_ZONE") or "").strip(),
                "zone_name": (props.get("ZD_ZONE_NAME") or "").strip(),
                "ordinance": str(props.get("ZO_ORDINANCE") or "").strip(),
                "geometry": geom,
            })
        if not rows:
            logger.warning("Loudoun zoning: no features returned.")
            return None
        gdf = gpd.GeoDataFrame(rows, crs="EPSG:4326")
        logger.info("Loudoun zoning: %d district polygons, %d districts.",
                    len(gdf), gdf["zone"].nunique())
        return gdf

    def fetch_wetlands(self, bbox: str) -> Optional[gpd.GeoDataFrame]:
        features = self._fetch_paginated(
            self.WETLANDS_URL, bbox, out_fields="OBJECTID,ATTRIBUTE"
        )
        if features is None:
            return None
        rows = []
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
            rows.append({
                "attribute": (f.get("properties", {}) or {}).get("ATTRIBUTE"),
                "geometry": geom,
            })
        if not rows:
            logger.info("NWI wetlands: no polygons in bbox (dry area is a valid result).")
            return gpd.GeoDataFrame([], columns=["attribute", "geometry"], crs="EPSG:4326")
        gdf = gpd.GeoDataFrame(rows, crs="EPSG:4326")
        logger.info("NWI wetlands: %d polygons in bbox.", len(gdf))
        return gdf

    def fetch_nfhl(self, bbox: str) -> Optional[gpd.GeoDataFrame]:
        features = self._fetch_paginated(
            self.NFHL_URL, bbox, out_fields="FLD_ZONE,ZONE_SUBTY,SFHA_TF"
        )
        if features is None:
            return None
        rows = []
        for f in features:
            props = f.get("properties", {}) or {}
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
            rows.append({
                "fld_zone": str(props.get("FLD_ZONE") or "").strip(),
                "zone_subty": str(props.get("ZONE_SUBTY") or "").strip().upper(),
                "geometry": geom,
            })
        if not rows:
            logger.info("FEMA flood zones: no hazard zones in bbox (mapped-but-dry is valid).")
            return gpd.GeoDataFrame([], columns=["fld_zone", "zone_subty", "geometry"], crs="EPSG:4326")
        gdf = gpd.GeoDataFrame(rows, crs="EPSG:4326")
        logger.info("FEMA flood zones (county FEMAFlood mirror): %d hazard-zone polygons in bbox.", len(gdf))
        return gdf

    # ── Internals ─────────────────────────────────────────────────────

    def _fetch_paginated(self, base_url: str, bbox: str, out_fields: str,
                         where: str = "1=1") -> Optional[List[Dict[str, Any]]]:
        """Pages an ArcGIS query in GeoJSON; None only on hard failure."""
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
                    "resultRecordCount": self.page_size,
                    "resultOffset": offset,
                }
                response = self._session.get(base_url, params=params, timeout=self.timeout)
                response.raise_for_status()
                data = response.json()
                if data.get("error"):
                    logger.warning("ArcGIS error from %s: %s", base_url, data["error"])
                    return None
                batch = data.get("features", [])
                features.extend(batch)
                # Some services cap resultRecordCount below the request
                # (e.g. FEMAFlood at 1000). ArcGIS GeoJSON responses then
                # set exceededTransferLimit — keep paging on that signal
                # instead of the (short) batch length.
                exceeded = bool(data.get("exceededTransferLimit"))
                if not batch or (len(batch) < self.page_size and not exceeded):
                    break
                offset += len(batch)
            return features
        except Exception as e:  # noqa: BLE001
            logger.warning("Layer fetch failed (%s): %s", base_url, e)
            return None
