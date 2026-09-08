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

ZONING IS NOT AVAILABLE. Ohio zones by municipality and township, not by
county, so there is no county-wide ordinance layer to read. The zoning
gate is therefore recorded UNKNOWN for every Franklin County parcel —
which is the honest result, and means no Ohio parcel can currently reach
an overall PASS. That is a real limitation of the jurisdiction's open
data, not a defect to be papered over with an assumption.
"""

import logging
import re
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
        Franklin County publishes cadastre and assessment together and
        publishes no county-wide zoning at all. Zoning is declared here
        with a null endpoint so the snapshot records that it was sought
        and does not exist, rather than silently omitting it.
        """
        return {
            "parcels": {"source_key": "franklin_tax_parcels", "endpoint": self.PARCELS_URL},
            "zoning": {"source_key": None, "endpoint": None},
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

        zoning is None by construction — see the module note. The engine
        already treats a missing layer as UNKNOWN rather than as a pass.
        """
        bbox = f"{min_lon},{min_lat},{max_lon},{max_lat}"
        return {
            "parcels": self.fetch_parcels(bbox, min_acres),
            "zoning": None,
            "wetlands": None,   # national NWI is fetched by the pipeline
            "nfhl": None,       # national NFHL is fetched by the pipeline
        }

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
        """Pages an ArcGIS query in GeoJSON; None only on hard failure."""
        features: List[Dict[str, Any]] = []
        offset = 0
        page = 1000
        try:
            while True:
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
                r.raise_for_status()
                data = r.json()
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
