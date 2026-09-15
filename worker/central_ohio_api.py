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

ZONING: Delaware publishes it, Union and Fairfield do not.

An earlier pass concluded that none of the three published zoning, and that
was wrong for Delaware. Nobody names these services the way a searcher would
guess — they are `porterzon`, `harlemzon`, `sciotozon`, one per township,
owned by a named individual at the planning commission rather than by an
organisation account — so an ArcGIS Online title search returns a single
township and invites the wrong conclusion. Tracing the county's public zoning
web map to its `operationalLayers` returns all sixteen services, 3,510
polygons, covering every one of Delaware's eighteen townships.

For Fairfield and Union zoning stays None: Fairfield genuinely publishes none
at any level (checked the county ArcGIS server, the RPC, AGOL for the county
and for Greenfield specifically) and Union has not been traced yet. The gate
then reads UNKNOWN and says the jurisdiction publishes no zoning layer rather
than implying a map with a gap in it.
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

# Delaware County zoning, one feature service per township, found by tracing
# the county's public zoning web map rather than by searching for them. Layer
# ids are not all 0 — Porter is 382, Oxford 383, the county service 385 —
# because these were published out of a single enterprise map document, so
# each entry carries its own path rather than a name plus an assumed suffix.
DELAWARE_ZONING_HOST = ("https://services2.arcgis.com/ziXVKVy3BiopMCCU"
                        "/arcgis/rest/services/")

# Thompson, Radnor and Marlboro adopted the COUNTY code under ORC 303 rather
# than writing their own, so one service carries all three. Its township is
# recorded as the county code itself: the three read the same instrument, and
# labelling a polygon with one township's name would imply the other two were
# surveyed separately.
DELAWARE_COUNTY_CODE_LABEL = "Delaware County code"

DELAWARE_ZONING_SERVICES = (
    ("Berkshire township", "Berkshire_Zoning/FeatureServer/0"),
    ("Berlin township",    "Berlin_Zoning/FeatureServer/0"),
    ("Brown township",     "Brown_Township_Zoning/FeatureServer/0"),
    ("Concord township",   "concordzon/FeatureServer/0"),
    ("Delaware township",  "delawarezon/FeatureServer/0"),
    ("Genoa township",     "Genoa_Zoning/FeatureServer/0"),
    ("Harlem township",    "harlemzon/FeatureServer/0"),
    ("Kingston township",  "kingstonzon/FeatureServer/0"),
    ("Liberty township",   "Liberty_Zoning/FeatureServer/0"),
    ("Orange township",    "orangezon/FeatureServer/0"),
    ("Oxford township",    "oxfordzon/FeatureServer/383"),
    ("Porter township",    "porterzon/FeatureServer/382"),
    ("Scioto township",    "sciotozon/FeatureServer/0"),
    ("Trenton township",   "Trenton_Zoning/FeatureServer/0"),
    ("Troy township",      "troyzon/FeatureServer/0"),
    (DELAWARE_COUNTY_CODE_LABEL,
     "Thompson_Radnor_Marlboro_Zoning/FeatureServer/385"),
)

DELAWARE_ORDINANCE = ("Delaware County township zoning resolutions, published "
                      "by the Delaware County Regional Planning Commission")


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
            "zoning": ({"source_key": "delaware_township_zoning",
                        "endpoint": DELAWARE_ZONING_HOST}
                       if self.county == "Delaware"
                       else {"source_key": None, "endpoint": None}),
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
            # Delaware publishes township zoning; Fairfield and Union do not.
            "zoning": (self.fetch_zoning()
                       if self.county == "Delaware" else None),
            "wetlands": None,   # national NWI, fetched by the pipeline
            "nfhl": None,       # national NFHL, fetched by the pipeline
        }

    # ------------------------------------------------------------------
    @staticmethod
    def _zoning_fields(meta: Dict[str, Any]) -> tuple:
        """
        (code_field, name_field) for one township's service.

        The sixteen services share a shape but not a schema: each is a join of
        zoning polygons to a district table, and the join prefixes every field
        with the source name — Scioto_Zoning_ZONING, berkshirezon_ZONING,
        Troy_Zoning_DSC_ZONE. Matching on the suffix rather than hard-coding
        sixteen names means a service renamed upstream still resolves.

        The county service is the exception and is handled by the caller: its
        {prefix}_Zoning field holds an integer row id, not a district code.
        """
        names = [f["name"] for f in meta.get("fields", [])]
        code = next((n for n in names
                     if n.upper().endswith("_ZONING")
                     and not n.startswith(("Zoning__", "Zoning2__"))), None)
        label = next((n for n in names if n.upper().endswith("_DSC_ZONE")), None)
        if label is None:
            label = next((n for n in names
                          if n.endswith("__Zoning_District")), None)
        return code, label

    def fetch_zoning(self) -> Optional[gpd.GeoDataFrame]:
        """
        Delaware's township zoning, sixteen services normalised into one frame.

        Every row carries its township, and that is not decoration: FR-1, A-1
        and PC appear in several townships, each under its own resolution, so
        the same code can mean different things a mile apart. The engine
        already has the mechanism — district_classes keyed "CODE|Township"
        outranks the flat lists — and it only works if the frame says which
        township a polygon belongs to.

        A service that fails leaves its township absent rather than failing the
        county: a parcel there then reads UNKNOWN, which is true, instead of
        taking a neighbouring township's use table.
        """
        rows: List[Dict[str, Any]] = []
        failed: List[str] = []
        for township, path in DELAWARE_ZONING_SERVICES:
            url = DELAWARE_ZONING_HOST + path
            try:
                meta = requests.get(url, params={"f": "json"}, timeout=90).json()
                if "error" in meta:
                    failed.append(township)
                    continue
                if township == DELAWARE_COUNTY_CODE_LABEL:
                    # Its own *_Zoning field is a row id; the district code
                    # lives in the joined column, padded with trailing spaces.
                    code_field = next(
                        (f["name"] for f in meta.get("fields", [])
                         if f["name"].endswith("__Zoning_District")), None)
                    name_field = None
                else:
                    code_field, name_field = self._zoning_fields(meta)
                if not code_field:
                    failed.append(township)
                    continue
                out = ",".join(f for f in (code_field, name_field) if f)
                feats = self._paged_url(url, out)
                if feats is None:
                    failed.append(township)
                    continue
                kept = 0
                for f in feats:
                    props = f.get("properties") or {}
                    code = str(props.get(code_field) or "").strip()
                    geometry = f.get("geometry")
                    if not code or not geometry:
                        continue
                    try:
                        geom = shape(geometry)
                    except Exception:  # noqa: BLE001
                        continue
                    if geom.is_empty or not geom.is_valid:
                        geom = geom.buffer(0)
                    if geom.is_empty:
                        continue
                    label = (str(props.get(name_field) or "").strip()
                             if name_field else "")
                    rows.append({"zone": code,
                                 "zone_name": label or None,
                                 "township": township,
                                 "ordinance": DELAWARE_ORDINANCE,
                                 "geometry": geom})
                    kept += 1
                logger.info("Delaware zoning: %s — %d polygons (%s).",
                            township, kept, code_field)
            except Exception as e:  # noqa: BLE001
                logger.warning("Delaware zoning: %s failed (%s).", township, e)
                failed.append(township)

        if failed:
            logger.warning(
                "Delaware zoning: %d of %d services did not answer (%s). "
                "Parcels in those townships read UNKNOWN rather than taking a "
                "neighbouring township's use table.",
                len(failed), len(DELAWARE_ZONING_SERVICES), ", ".join(failed))
        if not rows:
            logger.warning("Delaware zoning: no polygons from any service.")
            return None
        logger.info("Delaware zoning: %d polygons across %d townships, "
                    "%d distinct district codes.",
                    len(rows), len({r["township"] for r in rows}),
                    len({r["zone"] for r in rows}))
        return gpd.GeoDataFrame(rows, crs="EPSG:4326")

    def _paged_url(self, url: str, out_fields: str
                   ) -> Optional[List[Dict[str, Any]]]:
        """Pages any ArcGIS layer in GeoJSON. Used by the zoning fetch."""
        features: List[Dict[str, Any]] = []
        offset = 0
        try:
            while True:
                r = requests.get(url + "/query", params={
                    "where": "1=1", "outFields": out_fields,
                    "outSR": "4326", "returnGeometry": "true", "f": "geojson",
                    "resultRecordCount": self.PAGE_SIZE,
                    "resultOffset": offset,
                }, timeout=180)
                r.raise_for_status()
                data = r.json()
                if "error" in data:
                    return None if not features else features
                batch = data.get("features", []) or []
                features.extend(batch)
                if len(batch) < self.PAGE_SIZE:
                    break
                offset += self.PAGE_SIZE
        except Exception as e:  # noqa: BLE001
            logger.warning("Delaware zoning query failed (%s).", e)
            return None if not features else features
        return features

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
