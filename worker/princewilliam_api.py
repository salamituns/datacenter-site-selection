"""
Prince William County, Virginia parcel ingestion — the fifth parcel
jurisdiction, and the second in PJM's Virginia territory.

Phase 1 probe (docs/princewilliam-cadastre-probe.md) settled the shape,
and it is Franklin's shape with one exception: the county's GTS service
publishes a nightly Real Estate Assessments join on the parcel polygons
("Parcel CAMA Public") — owner, deed acreage, use code, living area —
but deliberately not assessed values. The roll as published to the
public is per-parcel on the Assessor's Aumentum portal, and no bulk
extract exists anywhere in county GIS or open data. Assessment value
metrics therefore record UNKNOWN for every PW parcel rather than a
number: the underwriting block prices from nothing rather than invent,
and the roll-back exposure stays an estimated metric that never fires
on data that does not exist.

Where PW differs from the other jurisdictions, the probe is why:

* Identity is nearly clean. `GPIN` is unique on every real parcel; the
  only duplicated value is the placeholder `9999-99-9999` (2,712
  right-of-way slivers that self-identify with `TaxMapNumber = 'ROW'`,
  no acreage, no use code). The where clause filters it at query time.
* Acreage is uniformly acres, all inline — `CAMA_DeedAcre`, `Acreage`
  and `CAMA_TaxAcreage1` agree within 2% on all but 1.5% of rows. No
  square-feet contamination, no second table, no join. The per-row
  reconciliation still runs: agreement is a reason to check, not a
  reason to trust one field.
* Zoning IS published — one county-wide layer with 31 district codes
  and a per-feature edit date, measured at 962/962 coverage of the
  >=20-acre candidates. The layer carries no district names (its name
  field holds the rezoning case), so names come from the county's own
  zoning ordinance, Chapter 32, verified section by section — never
  from the case name. Towns (Dumfries, Occoquan, Haymarket, Quantico)
  are mapped as `TWN`, a placeholder the use table must treat as an
  unknown jurisdiction, never a guessed class.

Nothing here is keyed on state_code: two Virginia counties now run
side by side, and the Loudoun water provider never appears in a PW
rationale (water_evidence.WATER_PROVIDERS keys the utility by region).
"""

import logging
import random
import re
import time
from typing import Any, Dict, List, Optional

import geopandas as gpd
import requests
from shapely.geometry import shape

from franklin_api import _reconcile_legal_acreage

logger = logging.getLogger("princewilliam_api")


# District names from the Prince William County Zoning Ordinance (Code of
# Prince William County, Chapter 32), verified against the ordinance's own
# section titles — NOT from the zoning layer, whose name field holds the
# rezoning case that created the polygon. Codes not in this map (the
# conditional C-suffixed variants, and the TWN/FED/CTY placeholders) fall
# back to the code itself, which reads honestly as "the code, unresolved"
# rather than as a name nobody published.
DISTRICT_NAMES: Dict[str, str] = {
    "A-1": "Agricultural",
    "SR-1": "Semi-Rural Residential",
    "SR-3": "Semi-Rural Residential",
    "SR-5": "Semi-Rural Residential",
    "R-2": "Suburban Residential",
    "R-4": "Suburban Residential",
    "R-6": "Suburban Residential",
    "R-16": "Suburban Residential",
    "R-30": "Urban Residential",
    "RPC": "Residential Planned Community",
    "PMR": "Planned Mixed Residential",
    "MXD-U": "Mixed Use",
    "V": "Village",
    "B-1": "General Business",
    "B-2": "Neighborhood Business",
    "B-3": "Convenience Retail",
    "O(L)": "Office Low-Rise",
    "O(M)": "Office Mid-Rise",
    "O(H)": "Office High-Rise",
    "O(F)": "Office/Flex",
    "M-1": "Heavy Industrial",
    "M-2": "Light Industrial",
    "M/T": "Industrial/Transportation",
    "PBD": "Planned Business District",
    "PMD": "Planned Mixed Use District",
}

ORDINANCE = "Prince William County Zoning Ordinance (Code of Prince William County, Ch. 32)"


class PrinceWilliamParcelAPI:
    """Prince William County cadastral + CAMA join, Planning zoning districts."""

    PARCELS_URL = (
        "https://gisweb.pwcva.gov/arcgis/rest/services/"
        "GTS/CAMA_Parcels/MapServer/4/query"
    )
    ZONING_URL = (
        "https://gisweb.pwcva.gov/arcgis/rest/services/"
        "Planning/Zoning/MapServer/5/query"
    )

    # Same floor as every other parcel jurisdiction, so all counties are
    # screened on one threshold.
    MIN_SOURCE_ACRES = 20.0

    # Verified against the live service (probe, 2026-09-11): pages cap at
    # 2,000, resultOffset is honoured, and partial pages do NOT set
    # exceededTransferLimit — the short-page break is the one that fires.
    PAGE_SIZE = 2000

    # A real GPIN is four digits, dash, two, dash, four (the county's grid
    # coordinate id, e.g. 7302-03-9126). The placeholder 9999-99-9999
    # matches the shape, so it is excluded explicitly in the where clause
    # rather than by pattern — the filter must be visible at the query.
    GPIN_RE = re.compile(r"^\d{4}-\d{2}-\d{4}$")

    PARCEL_FIELDS = (
        "OBJECTID,GPIN,TaxMapNumber,ParcelRecordationStatus,"
        "Acreage,CAMA_DeedAcre,CAMA_TaxAcreage1,CAMA_USECODE,CAMA_SQFTABV"
    )
    ZONING_FIELDS = (
        "OBJECTID,ZoningDistrict,ZoningCaseName,ZoningCaseNumber,"
        "last_edited_date"
    )

    # The ROW placeholder that shares one GPIN across 2,712 slivers.
    PLACEHOLDER_GPIN = "9999-99-9999"

    def layer_sources(self) -> Dict[str, Dict[str, Optional[str]]]:
        """
        PW publishes cadastre (with the CAMA join) and county-wide zoning;
        wetlands and flood hazard stay national (NWI, FEMA NFHL) and are
        fetched by the pipeline. Assessment is declared with a null
        endpoint so the snapshot records that it was sought and does not
        exist as a bulk publication, rather than silently omitting it.
        """
        return {
            "parcels": {"source_key": "pwc_tax_parcels", "endpoint": self.PARCELS_URL},
            "zoning": {"source_key": "pwc_zoning_districts",
                       "endpoint": self.ZONING_URL},
            "wetlands": {"source_key": "nwi_wetlands", "endpoint": None},
            "nfhl": {"source_key": None, "endpoint": None},
        }

    def fetch_all(self, min_lon: float, min_lat: float,
                  max_lon: float, max_lat: float,
                  min_acres: float = MIN_SOURCE_ACRES
                  ) -> Dict[str, Optional[gpd.GeoDataFrame]]:
        """
        Every county layer for the bbox, keyed to the one adapter contract:
        a layer the county does not publish is None, never an empty frame.
        """
        bbox = f"{min_lon},{min_lat},{max_lon},{max_lat}"
        return {
            "parcels": self.fetch_parcels(bbox, min_acres),
            "zoning": self.fetch_zoning(bbox),
            "wetlands": None,   # national NWI is fetched by the pipeline
            "nfhl": None,       # national NFHL is fetched by the pipeline
        }

    def fetch_parcels(self, bbox: str, min_acres: float
                      ) -> Optional[gpd.GeoDataFrame]:
        """
        Parcels at or above the acreage floor, carrying the CAMA join.

        Assessed values are NOT on this feature — the county publishes the
        roll only per-parcel on its Aumentum portal — so no value columns
        are read here and none are invented. The use code (the REA's own
        property classification) is the assessment evidence this layer
        actually carries.
        """
        features = self._paged(
            self.PARCELS_URL, bbox, self.PARCEL_FIELDS,
            where=(f"Acreage >= {min_acres} "
                   f"AND GPIN <> '{self.PLACEHOLDER_GPIN}'"),
        )
        if features is None:
            return None
        rows: Dict[str, Dict[str, Any]] = {}
        skipped: List[str] = []
        dupes = 0
        for f in features:
            props = f.get("properties") or {}
            pin = str(props.get("GPIN") or "").strip()
            geometry = f.get("geometry")
            if not pin or not geometry:
                continue
            if pin == self.PLACEHOLDER_GPIN:
                # The where clause excludes it at query time; this is the
                # belt to that braces, so a mocked or changed where clause
                # can never qualify a ROW sliver as land.
                skipped.append(pin)
                continue
            if not self.GPIN_RE.match(pin):
                # A row here means the county has started using another
                # non-GPIN value, and it is skipped loudly rather than
                # silently qualified as land.
                skipped.append(pin)
                continue
            if pin in rows:
                # The probe found GPIN unique on every real parcel (the
                # only duplicate was the placeholder, filtered above), so
                # a duplicate here means the service changed — say so.
                dupes += 1
                continue
            try:
                geom = shape(geometry)
            except Exception:  # noqa: BLE001
                continue
            if geom.is_empty or not geom.is_valid:
                geom = geom.buffer(0)
            if geom.is_empty:
                continue
            # Deed acreage first, the recorded legal figure; the plain
            # Acreage is the same value on all but 1.5% of rows and serves
            # as the fallback where the deed figure is null.
            legal = props.get("CAMA_DeedAcre")
            if legal is None:
                legal = props.get("Acreage")
            use_code = str(props.get("CAMA_USECODE") or "").strip() or None
            rows[pin] = {
                "pin": pin,
                "legal_acreage": legal,
                "assessment_class": use_code,
                "tax_map_number": str(props.get("TaxMapNumber") or "").strip() or None,
                "recordation_status": str(
                    props.get("ParcelRecordationStatus") or "").strip() or None,
                "geometry": geom,
            }
        if dupes:
            logger.warning(
                "PW parcels: %d duplicate GPINs from the source — kept the "
                "first of each. The probe found GPIN unique on real parcels; "
                "the service has changed and the adapter should be re-checked.",
                dupes)
        if skipped:
            logger.info("PW parcels: skipped %d non-GPIN features (%s).",
                        len(skipped), ", ".join(sorted(set(skipped))[:6]))
        if not rows:
            logger.warning("PW parcels: no features returned.")
            return None
        gdf = _reconcile_legal_acreage(gpd.GeoDataFrame(list(rows.values()), crs="EPSG:4326"))
        resolved = int(gdf["legal_acreage"].notna().sum())
        logger.info("PW parcels: %d parcels >= %g acres (deed); "
                    "legal acreage resolved for %d, left null for %d.",
                    len(gdf), min_acres, resolved, len(gdf) - resolved)
        return gdf

    def fetch_zoning(self, bbox: str) -> Optional[gpd.GeoDataFrame]:
        """
        The county-wide zoning district layer.

        One layer, 31 district codes, per-feature edit dates. The name
        field on the layer holds the rezoning case, not the district, so
        district names come from the ordinance map above; an unknown code
        keeps the code itself as its name — which reads as unresolved
        rather than as a name nobody published. TWN/FED/CTY placeholders
        pass through as codes; classifying them is the use table's job
        (TWN is a town whose ordinance the county does not publish, and
        the gate records UNKNOWN, never a guessed class).
        """
        features = self._paged(
            self.ZONING_URL, bbox, self.ZONING_FIELDS,
            where="ZoningDistrict IS NOT NULL",
        )
        if not features:
            logger.warning("PW zoning: no district polygons returned.")
            return None
        rows: List[Dict[str, Any]] = []
        for f in features:
            props = f.get("properties") or {}
            zone = str(props.get("ZoningDistrict") or "").strip()
            if not zone:
                continue
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
                "zone": zone,
                "zone_name": DISTRICT_NAMES.get(zone, zone),
                "ordinance": ORDINANCE,
                # The rezoning case that created the polygon, kept as a
                # detail: it is what the county's own mapper shows.
                "case_name": str(props.get("ZoningCaseName") or "").strip() or None,
                "case_number": str(props.get("ZoningCaseNumber") or "").strip() or None,
                "geometry": geom,
            })
        if not rows:
            logger.warning("PW zoning: no usable district polygons.")
            return None
        unmapped = sorted({r["zone"] for r in rows if r["zone"] not in DISTRICT_NAMES})
        if unmapped:
            logger.info("PW zoning: %d districts without an ordinance name "
                        "map entry (kept the code): %s",
                        len(unmapped), ", ".join(unmapped))
        logger.info("PW zoning: %d district polygons, %d distinct codes.",
                    len(rows), len({r["zone"] for r in rows}))
        return gpd.GeoDataFrame(rows, crs="EPSG:4326")

    def _paged(self, base_url: str, bbox: str, out_fields: str,
               where: str = "1=1") -> Optional[List[Dict[str, Any]]]:
        """
        Pages an ArcGIS query in GeoJSON; None only on hard failure before
        any feature lands. A failed page is retried with backoff — one bad
        request must not cost a whole layer (and with it the run).
        """
        features: List[Dict[str, Any]] = []
        offset = 0
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
                        "resultRecordCount": self.PAGE_SIZE,
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
                    raise requests.HTTPError(
                        f"status {r.status_code} after {attempts} attempts")
                if "error" in data:
                    logger.warning("PW query error: %s", data["error"])
                    return None if not features else features
                batch = data.get("features", []) or []
                features.extend(batch)
                if len(batch) < self.PAGE_SIZE:
                    break
                offset += self.PAGE_SIZE
        except Exception as e:  # noqa: BLE001
            logger.warning("PW query failed (%s).", e)
            return None if not features else features
        return features
