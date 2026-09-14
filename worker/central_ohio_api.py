"""
Central Ohio parcels — one adapter for several counties.

Every other jurisdiction here needed its own adapter because every county
publishes its own cadastre. Central Ohio does not: the City of Columbus
publishes one Parcels layer covering Delaware, Fairfield, Franklin, Licking,
Madison, Pickaway and Union — 848,070 parcels with a COUNTY column — so a
county joins by name rather than by a new fetcher.

This serves Fairfield, Union and Delaware. Franklin and Licking keep their
own adapters: both were built against county sources that carry evidence this
layer does not (Licking's township zoning and CAUV, Franklin's auditor join),
and replacing a richer source with a thinner one to share code would be a
downgrade dressed as a simplification.

WHAT THE PROBE FOUND, all of it handled below:

1.  Acreage is not in one field. ACRES is populated for Fairfield (and for
    Franklin and Licking), STATEDAREA for Delaware and Union, and neither for
    Madison or Pickaway, which is why those two are not served here. Both
    fields are in acres — checked on Licking rows carrying both, where they
    agree 1:1 (151.56/150.0, 94.42/95.0, 96.04/95.9) — and on Fairfield the
    two give the same 3,541 parcels at the 20-acre floor. The adapter prefers
    ACRES, falls back to STATEDAREA, and records which one answered so the
    dossier never implies a deed figure it did not read.

2.  Parcels are published as several polygons. Delaware has 111 such ids
    across 290 extra rows, Union 3 across 5; every sampled duplicate carries
    identical acreage, so they are one parcel's parts rather than distinct
    parcels sharing an id. They are unioned. Dropping the extras would keep
    the right acreage and the wrong shape, and the wetlands, floodway and
    slope gates all read shape.

3.  Union publishes 206 parcels with a blank PARCELID. They would collide on
    '' and trip the duplicate-id refusal in qualify_parcels, so they are
    dropped with a count logged.

4.  CLASSCD, CLASSDSCRP, USECD, PCLASS and PR_CLASSCD are Ohio AUDITOR
    PROPERTY-CLASS codes — a tax classification — not zoning districts. A
    field-name match on "class" or "use" picks them up, and mapping one into
    the zoning gate would produce confident verdicts from a tax roll. This
    adapter reads none of them.

ZONING IS NOT AVAILABLE, and that is structural rather than an omission.
Ohio zones by municipality and township, not by county, so there is no
county-wide layer for any of these three: Delaware publishes one township of
about nineteen, Union nothing county-wide, and Fairfield nothing — the
LancasterGIS zoning layers are the city of Lancaster's, and the county's own
CALU service is Current Agricultural Land Use. The regional service carries
no zoning either. zoning is None by construction, so the gate reads UNKNOWN
and says that the jurisdiction publishes no zoning layer rather than implying
a map with a gap in it.
"""

import logging
import random
import time
from typing import Any, Dict, List, Optional

import geopandas as gpd
import requests
from shapely.geometry import shape
from shapely.ops import unary_union

logger = logging.getLogger(__name__)

PARCELS_URL = ("https://maps.columbus.gov/arcgis/rest/services/CityServices/"
               "KeyLayers/MapServer/3/query")

# The COUNTY values the layer actually uses, verified against the service's
# own distinct values rather than assumed from the county name.
SERVED_COUNTIES = {
    "OH-FAIRFIELD": "Fairfield",
    "OH-UNION": "Union",
    "OH-DELAWARE": "Delaware",
}

# Madison and Pickaway are in the layer but carry no acreage in either field,
# so nothing here can decide their contiguous-acreage gate. They are named
# rather than silently absent: "not served" and "not present" are different
# facts, and a future reader should not have to rediscover which this is.
IN_LAYER_BUT_NO_ACREAGE = ("Madison", "Pickaway")


class CentralOhioParcelAPI:
    """One adapter, one county at a time, the same contract as the rest."""

    PAGE_SIZE = 2000
    MIN_SOURCE_ACRES = 20.0
    PARCEL_FIELDS = "PARCELID,ACRES,STATEDAREA,COUNTY"

    def __init__(self, region_key: str):
        county = SERVED_COUNTIES.get((region_key or "").upper())
        if county is None:
            raise ValueError(
                f"{region_key} is not served by the Central Ohio parcels "
                f"layer. Served: {', '.join(sorted(SERVED_COUNTIES))}. "
                f"{' and '.join(IN_LAYER_BUT_NO_ACREAGE)} are in the layer but "
                f"publish no acreage in either field.")
        self.region_key = region_key.upper()
        self.county = county

    def layer_sources(self) -> Dict[str, Dict[str, Optional[str]]]:
        """
        Zoning is declared with a null endpoint rather than omitted: the
        snapshot then records that a zoning source was sought and does not
        exist, which is a different fact from never having looked.
        """
        return {
            "parcels": {"source_key": "central_ohio_parcels",
                        "endpoint": PARCELS_URL},
            "zoning": {"source_key": None, "endpoint": None},
            "wetlands": {"source_key": "nwi_wetlands", "endpoint": None},
            "nfhl": {"source_key": None, "endpoint": None},
        }

    def fetch_all(self, min_lon: float, min_lat: float,
                  max_lon: float, max_lat: float,
                  min_acres: float = MIN_SOURCE_ACRES
                  ) -> Dict[str, Optional[gpd.GeoDataFrame]]:
        bbox = f"{min_lon},{min_lat},{max_lon},{max_lat}"
        return {
            "parcels": self.fetch_parcels(bbox, min_acres),
            "zoning": None,     # Ohio zones by township; see the module note
            "wetlands": None,   # national NWI, fetched by the pipeline
            "nfhl": None,       # national NFHL, fetched by the pipeline
        }

    @staticmethod
    def _acres(props: Dict[str, Any]) -> tuple:
        """
        (acres, which_field), or (None, None) where neither is stated.

        ACRES first because it is the auditor's own figure where published;
        STATEDAREA is the same unit and is all that Delaware and Union carry.
        A zero in either is not zero acres, it is an unstated one, and the
        difference matters: zero FAILS the acreage gate where the honest
        answer is to concede it.
        """
        for field in ("ACRES", "STATEDAREA"):
            raw = props.get(field)
            if raw is None:
                continue
            try:
                value = float(raw)
            except (TypeError, ValueError):
                continue
            if value > 0:
                return value, field
        return None, None

    def fetch_parcels(self, bbox: str, min_acres: float
                      ) -> Optional[gpd.GeoDataFrame]:
        features = self._paged(
            bbox,
            where=(f"COUNTY='{self.county}' AND "
                   f"(ACRES >= {min_acres} OR STATEDAREA >= {min_acres})"),
        )
        if features is None:
            return None

        rows: Dict[str, Dict[str, Any]] = {}
        blank_id = no_acreage = below_floor = multipart = 0
        for f in features:
            props = f.get("properties") or {}
            pin = str(props.get("PARCELID") or "").strip()
            geometry = f.get("geometry")
            if not pin:
                blank_id += 1
                continue
            if not geometry:
                continue
            acres, field = self._acres(props)
            if acres is None:
                no_acreage += 1
                continue
            if acres < min_acres:
                below_floor += 1
                continue
            try:
                geom = shape(geometry)
            except Exception:  # noqa: BLE001
                continue
            if geom.is_empty or not geom.is_valid:
                geom = geom.buffer(0)
            if geom.is_empty:
                continue
            if pin in rows:
                multipart += 1
                rows[pin]["geometry"] = unary_union(
                    [rows[pin]["geometry"], geom])
                continue
            rows[pin] = {
                "pin": pin,
                "legal_acreage": acres,
                "acreage_field": field,
                "geometry": geom,
            }

        if blank_id:
            logger.warning(
                "%s parcels: %d features with a blank PARCELID were dropped — "
                "they cannot be identified, and keeping one would qualify an "
                "arbitrary parcel under an empty id.", self.county, blank_id)
        if no_acreage:
            logger.info("%s parcels: %d features stated no acreage in either "
                        "ACRES or STATEDAREA and are not surveyed.",
                        self.county, no_acreage)
        if below_floor:
            logger.warning(
                "%s parcels: %d features came back below the %.0f-acre floor "
                "despite the server-side filter. Filtered here.",
                self.county, below_floor, min_acres)
        if multipart:
            logger.info("%s parcels: %d extra polygons belonged to a parcel "
                        "already seen and were unioned into it.",
                        self.county, multipart)
        if not rows:
            logger.warning("%s parcels: no qualifying features.", self.county)
            return None

        gdf = gpd.GeoDataFrame(list(rows.values()), crs="EPSG:4326")
        self._reconcile(gdf)
        used = gdf["acreage_field"].value_counts().to_dict()
        logger.info("%s parcels: %d at or above %.0f acres (acreage from %s).",
                    self.county, len(gdf), min_acres,
                    ", ".join(f"{k} x{v}" for k, v in used.items()))
        return gdf

    @staticmethod
    def _reconcile(gdf: gpd.GeoDataFrame) -> None:
        """
        Does the acreage the county states agree with the ground it draws?

        This is the check that caught Fauquier, where fifty condominium
        interests each carried their parent tract's acreage and the survey
        would have claimed 13,493 acres on 263 acres of land. It is kept here
        as a general check rather than as a rule about condominiums: any
        source whose stated acreage and drawn geometry disagree in bulk is
        telling us something, and a 51-fold overstatement is not subtle.
        """
        claimed = float(gdf["legal_acreage"].sum())
        drawn = float(gdf.to_crs("EPSG:5070").geometry.area.sum() / 4046.86)
        if drawn <= 0:
            return
        drift = abs(claimed - drawn) / drawn
        if drift > 0.10:
            logger.warning(
                "Acreage reconciliation: the source states %.0f acres across "
                "these parcels but draws %.0f (%.0f%% apart). Stated acreage "
                "and geometry should agree closely; a large gap means the "
                "source is double-counting shared ground or the geometry is "
                "not what the acreage describes. Worth reading before this "
                "county is trusted.", claimed, drawn, drift * 100)
        else:
            logger.info("Acreage reconciliation: %.0f acres stated, %.0f "
                        "drawn (%.1f%% apart).", claimed, drawn, drift * 100)

    def _paged(self, bbox: str, where: str) -> Optional[List[Dict[str, Any]]]:
        """
        Pages an ArcGIS query in GeoJSON; None only on hard failure before any
        feature lands. A failed page is retried with backoff — one bad request
        must not cost a whole layer, and with it the run.
        """
        features: List[Dict[str, Any]] = []
        offset = 0
        attempts = 4
        r = None
        try:
            while True:
                data = None
                for attempt in range(attempts):
                    r = requests.get(PARCELS_URL, params={
                        "where": where,
                        "geometry": bbox,
                        "geometryType": "esriGeometryEnvelope",
                        "inSR": "4326",
                        "outSR": "4326",
                        "outFields": self.PARCEL_FIELDS,
                        "returnGeometry": "true",
                        "f": "geojson",
                        "resultRecordCount": self.PAGE_SIZE,
                        "resultOffset": offset,
                    }, timeout=180)
                    if r.status_code in (429, 500, 502, 503, 504):
                        if attempt < attempts - 1:
                            time.sleep(0.5 * (2 ** attempt) + random.uniform(0, 0.5))
                            continue
                    r.raise_for_status()
                    data = r.json()
                    break
                if data is None:
                    raise requests.HTTPError(
                        f"status {r.status_code if r else '?'} after "
                        f"{attempts} attempts")
                if "error" in data:
                    logger.warning("Central Ohio query error: %s", data["error"])
                    return None if not features else features
                batch = data.get("features", []) or []
                features.extend(batch)
                if len(batch) < self.PAGE_SIZE:
                    break
                offset += self.PAGE_SIZE
        except Exception as e:  # noqa: BLE001
            logger.warning("Central Ohio query failed (%s).", e)
            return None if not features else features
        return features
