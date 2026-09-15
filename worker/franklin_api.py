"""
Franklin County, Ohio parcel ingestion — the second parcel jurisdiction.

Central Ohio is a PJM market, so the whole power-diligence layer built for
Loudoun (RTEP upgrades, Board-approved cost, empirical schedule slip)
carries over unchanged, as do every national layer and PeeringDB. What
had to be written is the county-specific half.

Ohio publishes more in one place than Virginia does. The Auditor's tax
parcel service carries the boundary AND the assessment on the same
feature — land, building and total value, the CAUV land value, sale price
and date — so this jurisdiction needs no separate roll download. Two
companion layers have no Loudoun equivalent at all: recorded tax
abatements and TIF districts, which are incentives attached to the parcel
rather than to the state.

CAUV is Ohio's Current Agricultural Use Value programme, the analogue of
Virginia's land-use assessment: farmland is taxed on use value, and
converting it triggers recoupment of the tax deferred over the preceding
three years (Ohio Revised Code 5713.34). Same shape of liability as
Virginia's roll-back, different statute and a shorter look-back.

ZONING IS AVAILABLE, and this module said otherwise for a long time.

The note here used to read "ZONING IS NOT AVAILABLE... there is no
county-wide ordinance layer to read", and Franklin sat at 0% zoning on the
strength of it. That was wrong. Franklin County's Economic Development and
Planning department publishes a county zoning districts layer, and separate
layers for five of the seven townships that zone themselves. It was missed
because an ArcGIS Online title search does not surface them; tracing the
county's own zoning web map does.

Ohio zoning is still township business, but Franklin is the case where that
does not mean county silence. Its seventeen townships split:

  * TEN adopt the Franklin County Zoning Resolution — Brown, Clinton,
    Franklin, Hamilton, Mifflin, Madison, Norwich, Pleasant, Sharon and
    Truro — so one instrument and one layer cover all of them.
  * SEVEN zone themselves: Blendon, Jackson, Jefferson, Perry, Plain,
    Prairie and Washington. EDPGIS publishes a layer for five. Jackson and
    Jefferson publish none here, so their parcels stay UNKNOWN.

WHAT THE RESOLUTION DOES NOT SAY. The Franklin County Zoning Resolution as
amended to 2026 runs 298 pages and names no data-centre use anywhere —
"computer" appears only in "computer data entry error", and the
telecommunication-tower provision is ORC 303.211 towers, not data centres.
So the districts are ingested and the use table stays empty, exactly as
Delaware and Fauquier were done: a parcel knows its district and cites its
resolution, and the mapping drops in later as a row rather than a
re-survey.
"""

import logging
import random
import re
import time
from typing import Any, Dict, List, Optional

import geopandas as gpd
import requests
from shapely.geometry import shape

logger = logging.getLogger("franklin_api")


# Equal-area projection for the unit sanity check below. CONUS Albers is
# the standard choice for area measurement across the continental US.
AREA_CRS = "EPSG:5070"
SQFT_PER_ACRE = 43560.0


def _reconcile_legal_acreage(gdf: gpd.GeoDataFrame) -> gpd.GeoDataFrame:
    """
    STATEDAREA is not in one unit.

    The Auditor's "Legal Acres" field carries acres on some parcels and
    square feet on others — in this bbox, 367 of 993 are square feet, and
    the giveaway is a value about 43,560 times the mapped area. Taken at
    face value it produces parcels of a million acres.

    Each row is therefore checked against its own geometry: read as acres
    if that agrees with the polygon, read as square feet if that does, and
    left null if neither does. A null legal acreage is honest — the engine
    measures GIS acreage from the geometry regardless — where a wrong one
    would travel into every downstream figure.
    """
    measured = gdf.to_crs(AREA_CRS).geometry.area / 4046.8564224

    def pick(stated: Any, mapped: float) -> Optional[float]:
        if stated is None or mapped <= 0:
            return None
        try:
            v = float(stated)
        except (TypeError, ValueError):
            return None
        if v <= 0:
            return None
        # Legal and mapped acreage rarely agree exactly — surveyed calls
        # against a digitised boundary — so the band is deliberately wide.
        if 0.5 <= v / mapped <= 2.0:
            return v
        as_acres = v / SQFT_PER_ACRE
        if 0.5 <= as_acres / mapped <= 2.0:
            return as_acres
        return None

    gdf = gdf.copy()
    gdf["legal_acreage"] = [
        pick(v, m) for v, m in zip(gdf["legal_acreage"], measured)
    ]
    return gdf


# Franklin County zoning, published by the county's Economic Development and
# Planning department (EDPGIS). Found by tracing the county's zoning web map;
# an ArcGIS Online title search does not surface these.
ZONING_HOST = ("https://services1.arcgis.com/7r2Wl09a1Apy459r"
               "/arcgis/rest/services/")

# The county layer covers the TEN townships that adopted the county
# resolution rather than writing their own, so it is labelled for the
# instrument rather than for any one township — naming one would imply the
# other nine were surveyed separately.
FRANKLIN_COUNTY_CODE_LABEL = "Franklin County resolution"

FRANKLIN_COUNTY_CODE_TOWNSHIPS = (
    "Brown", "Clinton", "Franklin", "Hamilton", "Mifflin",
    "Madison", "Norwich", "Pleasant", "Sharon", "Truro",
)

# Jackson and Jefferson zone themselves and publish no layer here, so their
# parcels stay UNKNOWN. Named rather than silently absent: "not published"
# and "not looked for" are different facts.
SELF_ZONING_WITHOUT_A_LAYER = ("Jackson", "Jefferson")

FRANKLIN_ZONING_SERVICES = (
    (FRANKLIN_COUNTY_CODE_LABEL,
     "Franklin_County_Zoning_Districts_Editing_20221201"),
    ("Blendon township",    "Blendon_Twp_Zoning"),
    ("Perry township",      "Perry_Twp_Zoning"),
    ("Plain township",      "Plain_Twp_Zoning"),
    ("Prairie township",    "Prairie_Twp_Zoning"),
    ("Washington township", "Washington_Twp_Zoning"),
)

FRANKLIN_ORDINANCE = ("Franklin County Zoning Resolution and township zoning "
                      "resolutions, published by Franklin County Economic "
                      "Development and Planning")

# Values that are not districts. "NOT IN JURISDICTION" is the county layer's
# own marker for land it does not zone — a municipality, or one of the seven
# townships that zone themselves — and mapping it as a district would invent
# a classification for land the county explicitly disclaims.
NON_DISTRICT_VALUES = {"", "NONE", "NOT IN JURISDICTION", "NULL"}


class FranklinParcelAPI:
    """Franklin County Auditor cadastral, assessment and incentive layers."""

    PARCELS_URL = (
        "https://gis.franklincountyohio.gov/hosting/rest/services/"
        "ParcelFeatures/Parcel_Features/FeatureServer/0/query"
    )
    ABATEMENTS_URL = (
        "https://gis.franklincountyohio.gov/hosting/rest/services/"
        "RealEstate/Abatements/FeatureServer/0/query"
    )
    TIF_URL = (
        "https://gis.franklincountyohio.gov/hosting/rest/services/"
        "RealEstate/TIF/FeatureServer/0/query"
    )

    # Matches the Loudoun pilot's floor so the two jurisdictions are
    # screened on the same threshold rather than on different ones.
    MIN_SOURCE_ACRES = 20.0

    # A real Franklin County parcel id is three digits, a dash, then six,
    # optionally suffixed. The layer also carries mapped areas that are not
    # parcels at all and share placeholder ids — OUT OF CO, VNP-RR,
    # VNP-WATER, VNP-KNOWN — for out-of-county slivers, railroad corridors
    # and water bodies. None of them carries an assessment, several share
    # one id, and left in they would be qualified as candidate sites: the
    # engine would have scored rivers and rail rights-of-way as land.
    PARCEL_ID_RE = re.compile(r"^\d{3}-\d{6}(-\d+)?$")

    PARCEL_FIELDS = (
        "PARCELID,STATEDAREA,ACRES,CLASSCD,CLASSDSCRP,"
        "LNDVALUEBASE,BLDVALUEBASE,TOTVALUEBASE,CAUVLNDBASE,CAUV,"
        "SALEPRICE,SALEDATE"
    )

    def layer_sources(self) -> Dict[str, Dict[str, Optional[str]]]:
        """
        Franklin County publishes cadastre and assessment together, and —
        contrary to what this adapter asserted for a long time — publishes
        zoning too: a county districts layer covering the ten townships that
        adopted the county resolution, plus five of the seven that zone
        themselves.
        """
        return {
            "parcels": {"source_key": "franklin_tax_parcels", "endpoint": self.PARCELS_URL},
            "zoning": {"source_key": "franklin_county_zoning",
                       "endpoint": ZONING_HOST},
            "wetlands": {"source_key": "nwi_wetlands", "endpoint": None},
            "nfhl": {"source_key": None, "endpoint": None},
        }

    def fetch_all(self, min_lon: float, min_lat: float,
                  max_lon: float, max_lat: float,
                  min_acres: float = MIN_SOURCE_ACRES
                  ) -> Dict[str, Optional[gpd.GeoDataFrame]]:
        """
        Every county layer for the bbox, keyed to match the Loudoun
        adapter so the qualification engine is indifferent to which
        jurisdiction it is running.

        Zoning now comes from the county layer plus five township layers —
        see the module note for which townships each covers.
        """
        bbox = f"{min_lon},{min_lat},{max_lon},{max_lat}"
        return {
            "parcels": self.fetch_parcels(bbox, min_acres),
            "zoning": self.fetch_zoning(),
            "wetlands": None,   # national NWI is fetched by the pipeline
            "nfhl": None,       # national NFHL is fetched by the pipeline
        }

    @staticmethod
    def _zoning_field(meta: Dict[str, Any]) -> Optional[str]:
        """
        The district-code field, preferring ZONING over ZONE48.

        Both exist on the county layer and on Blendon's, and on Blendon's
        ZONE48 is empty — every row is '' or 'None'. Taking the first field
        whose name looks plausible returns a township with no districts and
        no error, which reads as "nothing published" rather than "wrong
        column". Case varies too: Prairie and Perry write ZONING, Plain and
        Washington write Zoning.
        """
        names = [f["name"] for f in meta.get("fields", [])]
        for want in ("ZONING", "ZONE"):
            for n in names:
                if n.upper() == want:
                    return n
        return next((n for n in names if n.upper().endswith("ZONING")), None)

    @staticmethod
    def _label_field(meta: Dict[str, Any]) -> Optional[str]:
        names = [f["name"] for f in meta.get("fields", [])]
        return next((n for n in names
                     if n.upper() in ("ZONDESC", "ZONING_DESC", "DSC_ZONE")),
                    None)

    def fetch_zoning(self) -> Optional[gpd.GeoDataFrame]:
        """
        The county districts layer plus the five township layers.

        Every row carries its township, because a code means what the
        resolution that wrote it says: LI, CC, SO and R-4 all appear both in
        the county resolution and in a self-zoning township's own, and they
        are different instruments. The county layer's rows carry the
        resolution's name rather than a township's, since ten townships read
        it in common.

        A service that fails drops its township rather than the county.
        """
        rows: List[Dict[str, Any]] = []
        failed: List[str] = []
        skipped_non_district = 0
        for township, svc in FRANKLIN_ZONING_SERVICES:
            url = ZONING_HOST + svc + "/FeatureServer/0"
            try:
                meta = requests.get(url, params={"f": "json"}, timeout=90).json()
                if "error" in meta:
                    failed.append(township)
                    continue
                code_field = self._zoning_field(meta)
                if not code_field:
                    failed.append(township)
                    continue
                label_field = self._label_field(meta)
                out = ",".join(f for f in (code_field, label_field) if f)
                feats = self._paged_zoning(url, out)
                if feats is None:
                    failed.append(township)
                    continue
                kept = 0
                for f in feats:
                    props = f.get("properties") or {}
                    # The county layer carries at least one value mangled
                    # with embedded newlines ("PR-10\nPR-10\nPR-10\nPR-10"),
                    # so collapse whitespace before comparing anything.
                    raw = re.sub(r"\s+", " ", str(props.get(code_field) or "")).strip()
                    code = raw.split(" ")[0] if raw and " " in raw and \
                        len(set(raw.split(" "))) == 1 else raw
                    geometry = f.get("geometry")
                    if not code or code.upper() in NON_DISTRICT_VALUES:
                        skipped_non_district += 1
                        continue
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
                    label = (str(props.get(label_field) or "").strip()
                             if label_field else "")
                    rows.append({"zone": code,
                                 "zone_name": label or None,
                                 "township": township,
                                 "ordinance": FRANKLIN_ORDINANCE,
                                 "geometry": geom})
                    kept += 1
                logger.info("Franklin zoning: %s — %d polygons (%s).",
                            township, kept, code_field)
            except Exception as e:  # noqa: BLE001
                logger.warning("Franklin zoning: %s failed (%s).", township, e)
                failed.append(township)

        if skipped_non_district:
            logger.info(
                "Franklin zoning: %d polygons carried no district — blank, "
                "'None', or the county layer's own 'NOT IN JURISDICTION' "
                "marker for land it does not zone. Left unmapped rather than "
                "classified.", skipped_non_district)
        if failed:
            logger.warning("Franklin zoning: %d services did not answer (%s).",
                           len(failed), ", ".join(failed))
        logger.info("Franklin zoning: no layer for %s — those townships zone "
                    "themselves and publish nothing here, so their parcels "
                    "read UNKNOWN.",
                    " and ".join(SELF_ZONING_WITHOUT_A_LAYER))
        if not rows:
            logger.warning("Franklin zoning: no polygons from any service.")
            return None
        logger.info("Franklin zoning: %d polygons, %d sources, %d codes.",
                    len(rows), len({r["township"] for r in rows}),
                    len({r["zone"] for r in rows}))
        return gpd.GeoDataFrame(rows, crs="EPSG:4326")

    def _paged_zoning(self, url: str, out_fields: str
                      ) -> Optional[List[Dict[str, Any]]]:
        feats: List[Dict[str, Any]] = []
        offset = 0
        try:
            while True:
                r = requests.get(url + "/query", params={
                    "where": "1=1", "outFields": out_fields, "outSR": "4326",
                    "returnGeometry": "true", "f": "geojson",
                    "resultRecordCount": 2000, "resultOffset": offset,
                }, timeout=180)
                r.raise_for_status()
                data = r.json()
                if "error" in data:
                    return None if not feats else feats
                batch = data.get("features", []) or []
                feats.extend(batch)
                if len(batch) < 2000:
                    break
                offset += 2000
        except Exception as e:  # noqa: BLE001
            logger.warning("Franklin zoning query failed (%s).", e)
            return None if not feats else feats
        return feats

    def fetch_parcels(self, bbox: str, min_acres: float
                      ) -> Optional[gpd.GeoDataFrame]:
        """
        Parcels at or above the acreage floor, carrying their assessment.

        Assessment travels on the parcel feature here, so the values are
        as observed and as dated as the boundary itself.
        """
        features = self._paged(
            self.PARCELS_URL, bbox, self.PARCEL_FIELDS,
            where=f"ACRES >= {min_acres}",
        )
        if features is None:
            return None
        rows: List[Dict[str, Any]] = []
        skipped: List[str] = []
        for f in features:
            props = f.get("properties") or {}
            pin = str(props.get("PARCELID") or "").strip()
            geometry = f.get("geometry")
            if not pin or not geometry:
                continue
            try:
                geom = shape(geometry)
            except Exception:  # noqa: BLE001
                continue
            if geom.is_empty or not geom.is_valid:
                geom = geom.buffer(0)
            if geom.is_empty:
                continue
            # CAUV is a flag string in this service; anything other than a
            # clear negative is treated as enrolled, and the CAUV land
            # value is what quantifies it.
            if not self.PARCEL_ID_RE.match(pin):
                skipped.append(pin)
                continue
            cauv_flag = str(props.get("CAUV") or "").strip().upper()
            rows.append({
                "pin": pin,
                "legal_acreage": props.get("STATEDAREA"),
                "assessment_class": props.get("CLASSDSCRP"),
                "land_value": props.get("LNDVALUEBASE"),
                "building_value": props.get("BLDVALUEBASE"),
                "total_value": props.get("TOTVALUEBASE"),
                "cauv_land_value": props.get("CAUVLNDBASE"),
                "in_cauv": cauv_flag not in ("", "N", "NO", "0", "NONE"),
                "sale_price": props.get("SALEPRICE"),
                "sale_date": props.get("SALEDATE"),
                "geometry": geom,
            })
        if not rows:
            logger.warning("Franklin parcels: no features returned.")
            return None
        if skipped:
            logger.info("Franklin parcels: skipped %d non-parcel features (%s).",
                        len(skipped), ", ".join(sorted(set(skipped))))
        gdf = _reconcile_legal_acreage(gpd.GeoDataFrame(rows, crs="EPSG:4326"))
        resolved = int(gdf["legal_acreage"].notna().sum())
        logger.info("Franklin parcels: %d parcels >= %g acres (GIS); "
                    "legal acreage resolved for %d, left null for %d.",
                    len(gdf), min_acres, resolved, len(gdf) - resolved)
        return gdf

    def fetch_incentive_areas(self, min_lon: float, min_lat: float,
                              max_lon: float, max_lat: float
                              ) -> Dict[str, Optional[gpd.GeoDataFrame]]:
        """
        Recorded abatements and TIF districts as polygons.

        These are parcel-level incentives, which Virginia has no public
        equivalent of — there the programmes are statutory and statewide.
        A parcel inside one of these areas carries a benefit that its
        neighbour across the line does not.
        """
        bbox = f"{min_lon},{min_lat},{max_lon},{max_lat}"
        out: Dict[str, Optional[gpd.GeoDataFrame]] = {}
        for key, url in (("abatements", self.ABATEMENTS_URL), ("tif", self.TIF_URL)):
            feats = self._paged(url, bbox, "*")
            if not feats:
                out[key] = None
                continue
            rows = []
            for f in feats:
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
                rows.append({"props": f.get("properties") or {}, "geometry": geom})
            out[key] = (gpd.GeoDataFrame(rows, crs="EPSG:4326") if rows else None)
            logger.info("Franklin %s: %d areas.", key, len(rows))
        return out

    def parcel_incentives(self, min_lon: float, min_lat: float,
                          max_lon: float, max_lat: float,
                          parcels: Optional[gpd.GeoDataFrame] = None
                          ) -> Dict[str, Dict[str, Any]]:
        """
        Abatements and TIF standing, per parcel id.

        Ohio grants these at parcel level, which Virginia does not: there
        the data-centre exemption is statutory and identical statewide, so
        it differentiates nothing between two sites. Here a parcel inside a
        Community Reinvestment Area or a TIF district carries a benefit its
        neighbour across the line does not — and both carry an end year,
        so the benefit is a term rather than a permanent condition.

        Abatements join by parcel id, which the county publishes directly.
        TIF districts are polygons and are joined spatially.
        """
        areas = self.fetch_incentive_areas(min_lon, min_lat, max_lon, max_lat)
        out: Dict[str, Dict[str, Any]] = {}

        ab = areas.get("abatements")
        if ab is not None:
            for _, row in ab.iterrows():
                props = row["props"]
                pin = str(props.get("PARCELID") or "").strip()
                if not pin:
                    continue
                out.setdefault(pin, {})["abatement"] = {
                    "case_type": props.get("CaseType"),
                    "abatement_type": props.get("AbatementType"),
                    "district": props.get("IncentiveDistrict"),
                    "start_year": props.get("StartYear"),
                    "end_year": props.get("EndYear"),
                    "term_years": props.get("Term"),
                }

        tif = areas.get("tif")
        if tif is not None and parcels is not None and len(parcels) > 0:
            try:
                joined = gpd.sjoin(
                    parcels[["pin", "geometry"]], tif, how="left", predicate="intersects"
                )
                for _, row in joined.iterrows():
                    props = row.get("props")
                    if not isinstance(props, dict):
                        continue
                    out.setdefault(str(row["pin"]), {})["tif"] = {
                        "name": props.get("TIF_Name"),
                        "project_no": props.get("project_no"),
                        "first_year": props.get("First_Year"),
                        "last_year": props.get("Last_Year"),
                        "percent": props.get("Percent_of_TIF"),
                        "school_district": props.get("SchoolDistrict"),
                    }
            except Exception as e:  # noqa: BLE001
                logger.warning("TIF join failed (%s) — TIF standing omitted.", e)

        logger.info("Franklin incentives: %d parcels with an abatement or TIF standing.",
                    len(out))
        return out

    def _paged(self, base_url: str, bbox: str, out_fields: str,
               where: str = "1=1") -> Optional[List[Dict[str, Any]]]:
        """
        Pages an ArcGIS query in GeoJSON; None only on hard failure.
        A failed page is retried with backoff — the county service
        intermittently 5xx's mid-run, and without a retry a whole parcel
        layer (and with it the run) is lost to one bad request.
        """
        features: List[Dict[str, Any]] = []
        offset = 0
        page = 1000
        attempts = 4
        try:
            while True:
                data = None
                for attempt in range(attempts):
                    r = requests.get(base_url, params={
                        "where": where,
                        "geometry": bbox,
                        "geometryType": "esriGeometryEnvelope",
                        "inSR": "4326",
                        "outSR": "4326",
                        "outFields": out_fields,
                        "returnGeometry": "true",
                        "f": "geojson",
                        "resultRecordCount": page,
                        "resultOffset": offset,
                    }, timeout=120)
                    if r.status_code in (429, 500, 502, 503, 504):
                        if attempt < attempts - 1:
                            time.sleep(0.5 * (2 ** attempt) + random.uniform(0, 0.5))
                            continue
                    r.raise_for_status()
                    data = r.json()
                    break
                if data is None:
                    raise requests.HTTPError(f"status {r.status_code} after {attempts} attempts")
                if "error" in data:
                    logger.warning("Franklin query error: %s", data["error"])
                    return None if not features else features
                batch = data.get("features", []) or []
                features.extend(batch)
                if len(batch) < page:
                    break
                offset += page
        except Exception as e:  # noqa: BLE001
            logger.warning("Franklin query failed (%s).", e)
            return None if not features else features
        return features
