"""
Licking County, Ohio parcel ingestion — the third parcel jurisdiction.

Phase 1 probe (docs/licking-cadastre-probe.md) settled the shape, and it
is Franklin's shape: one ArcGIS FeatureServer whose parcel features carry
the CAMA assessment inline — land, improvement and total value, CAUV land
value and acres, abated improvement value, TIF standing, three transfer
records. No separate roll to download, no join to fake.

Where Licking differs from Franklin, the probe is why:

* Identity is clean. `Parcel` is unique on every non-null row; the 1,180
  null rows are fully-null slivers that filter themselves out, so there
  is no VNP-WATER trap and no placeholder-id collapse.
* Acreage is uniformly acres (`TaxAcres` legal, `GISAcres` measured),
  verified per row — no square-feet contamination. The reconciliation
  still runs, because small-parcel rounding is a reason to check, not a
  reason to trust.
* Zoning IS published — the one thing Franklin lacks. It is township
  zoning: 25 per-township layers under Planning/Zoning, six of which are
  a single blanket `UZ` (Unzoned) polygon. Municipal zoning (Newark,
  Granville, Pataskala, Johnstown) is not in the service, so parcels
  inside a municipality get no district and the gate records UNKNOWN —
  the honest result for a parcel whose ordinance the county does not
  publish.

CAUV is Ohio's Current Agricultural Use Value programme (ORC 5713.34):
farmland taxed on use value, conversion triggers recoupment of three
years of deferred tax. Licking is stronger evidence than Franklin here —
`CAUVAcres` and `CAUVLandValue` are explicit per-parcel columns, so
enrollment is read, not inferred from a class code.

Nothing in this adapter is keyed on state_code: after the region re-key
a state is not a unique region, and two Ohio counties run side by side.
"""

import logging
import random
import time
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

import geopandas as gpd
import pandas as pd
import requests
from shapely.geometry import shape

from franklin_api import _reconcile_legal_acreage

logger = logging.getLogger("licking_api")


def _text_or_none(v: Any) -> Optional[str]:
    """
    A clean string or None — pandas' string dtype renders a missing value
    as NaN, and str(NaN) is "nan", which is how a null TIF flag would
    become a district named "nan". Missing is missing.
    """
    if v is None:
        return None
    try:
        if pd.isna(v):
            return None
    except (TypeError, ValueError):
        pass
    s = str(v).strip()
    return s or None


class LickingParcelAPI:
    """Licking County Auditor cadastral + assessment, Planning township zoning."""

    PARCELS_URL = (
        "https://gis.lickingcounty.gov/server/rest/services/"
        "Auditor/Parcels/FeatureServer/0/query"
    )
    ZONING_SERVICE_URL = (
        "https://gis.lickingcounty.gov/server/rest/services/"
        "Planning/Zoning/FeatureServer"
    )

    # Same floor as the Loudoun and Franklin pilots, so all parcel
    # jurisdictions are screened on one threshold.
    MIN_SOURCE_ACRES = 20.0

    # Verified against the live service (probe, 2026-09-10): pages cap at
    # 2,000 and resultOffset is honoured. Asking for more than 2,000 is
    # silently truncated, so this is a hard contract, not a courtesy.
    PAGE_SIZE = 2000

    PARCEL_FIELDS = (
        "OBJECTID,Parcel,OwnerName,Township,TaxAcres,GISAcres,CAUVAcres,"
        "LUC,Landuse,Class,MarketLandValue,MarketImpValue,MarketTotalValue,"
        "NetTotalValue,CAUVLandValue,AbatedImpValue,TIF,YearBuilt,"
        "T1SaleAmount,T1Date,T1Valid"
    )

    ZONING_FIELDS = (
        "ZoningClass,ZoningDescription,ZoningOverlay,Township,Resolution,URL"
    )

    def layer_sources(self) -> Dict[str, Dict[str, Optional[str]]]:
        """
        Licking publishes cadastre, assessment and township zoning; the
        wetland and floodway layers stay national (NWI, FEMA NFHL) and are
        fetched by the pipeline, so their keys are null here.
        """
        return {
            "parcels": {"source_key": "licking_tax_parcels", "endpoint": self.PARCELS_URL},
            "zoning": {"source_key": "licking_township_zoning",
                       "endpoint": self.ZONING_SERVICE_URL},
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
        Parcels at or above the acreage floor, carrying their assessment.

        The where clause does three jobs at query time: the acreage floor,
        the null-Parcel sliver filter, and (via the server) the spatial
        clip — so the transfer is one pass of small pages.
        """
        features = self._paged(
            self.PARCELS_URL, bbox, self.PARCEL_FIELDS,
            where=f"Parcel IS NOT NULL AND TaxAcres >= {min_acres}",
        )
        if features is None:
            return None
        rows: Dict[str, Dict[str, Any]] = {}
        dupes = 0
        for f in features:
            props = f.get("properties") or {}
            pin = str(props.get("Parcel") or "").strip()
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
            if pin in rows:
                # The probe found Parcel unique county-wide, so a
                # duplicate here means the service changed — say so
                # loudly rather than deciding which copy to keep quietly.
                dupes += 1
                continue
            cauv_acres = props.get("CAUVAcres") or 0
            cauv_land = props.get("CAUVLandValue") or 0
            rows[pin] = {
                "pin": pin,
                "legal_acreage": props.get("TaxAcres"),
                "assessment_class": props.get("Class"),
                "township": props.get("Township"),
                "land_value": props.get("MarketLandValue"),
                "building_value": props.get("MarketImpValue"),
                "total_value": props.get("MarketTotalValue"),
                "cauv_land_value": props.get("CAUVLandValue"),
                "in_cauv": bool(cauv_acres > 0 or cauv_land > 0),
                "abated_improvement_value": props.get("AbatedImpValue"),
                "tif_standing": props.get("TIF"),
                "sale_price": props.get("T1SaleAmount"),
                "sale_date": _epoch_ms_to_iso(props.get("T1Date")),
                "geometry": geom,
            }
        if dupes:
            logger.warning(
                "Licking parcels: %d duplicate Parcel ids from the source — "
                "kept the first of each. The probe found Parcel unique; the "
                "service has changed and the adapter should be re-checked.",
                dupes)
        if not rows:
            logger.warning("Licking parcels: no features returned.")
            return None
        gdf = _reconcile_legal_acreage(gpd.GeoDataFrame(list(rows.values()), crs="EPSG:4326"))
        resolved = int(gdf["legal_acreage"].notna().sum())
        logger.info("Licking parcels: %d parcels >= %g acres (legal); "
                    "legal acreage resolved for %d, left null for %d.",
                    len(gdf), min_acres, resolved, len(gdf) - resolved)
        return gdf

    def fetch_zoning(self, bbox: str) -> Optional[gpd.GeoDataFrame]:
        """
        Township zoning as one concatenated layer.

        The county publishes one layer per township under Planning/Zoning
        (24 zoned townships plus single-polygon `UZ` Unzoned layers for the
        six that administer none). The layer list is discovered from the
        service root rather than hardcoded, so a township added or retired
        by the county flows through without an adapter change.

        A parcel in a municipality draws no polygon from any township
        layer, so it keeps no district and the gate records UNKNOWN —
        municipal zoning (Newark, Granville, Pataskala, Johnstown) is not
        in this service and is never guessed at.
        """
        layers = self._zoning_layer_ids()
        if layers is None:
            return None
        rows: List[Dict[str, Any]] = []
        for layer_id, layer_name in layers:
            feats = self._paged(
                f"{self.ZONING_SERVICE_URL}/{layer_id}/query",
                bbox, self.ZONING_FIELDS,
                where="ZoningClass IS NOT NULL",
            )
            if not feats:
                logger.info("Licking zoning: no districts from layer %s (%s).",
                            layer_id, layer_name)
                continue
            for f in feats:
                props = f.get("properties") or {}
                zone = str(props.get("ZoningClass") or "").strip()
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
                township = str(props.get("Township") or layer_name).strip()
                resolution = str(props.get("Resolution") or "").strip()
                rows.append({
                    "zone": zone,
                    "zone_name": str(props.get("ZoningDescription") or zone),
                    "ordinance": (f"{township} Township Zoning Resolution "
                                  + (f"({resolution})" if resolution else "")).strip(),
                    "township": township,
                    "overlay": props.get("ZoningOverlay"),
                    "geometry": geom,
                })
        if not rows:
            logger.warning("Licking zoning: no district polygons returned.")
            return None
        logger.info("Licking zoning: %d districts across %d township layers.",
                    len(rows), len(layers))
        return gpd.GeoDataFrame(rows, crs="EPSG:4326")

    def parcel_incentives(self, min_lon: float, min_lat: float,
                          max_lon: float, max_lat: float,
                          parcels: Optional[gpd.GeoDataFrame] = None
                          ) -> Dict[str, Dict[str, Any]]:
        """
        Abatement and TIF standing per parcel, from the roll itself.

        Unlike Franklin these need no companion layers: `AbatedImpValue`
        and `TIF` travel on the parcel feature (the TIF field carries the
        district's name where one applies, e.g. "Etna Twp JEDD2 -
        Southgate", and "No" where none does). Neither field publishes a
        term or end year, so none is reported — an incentive without a
        published end is underwritten as standing, not as expiring.
        """
        out: Dict[str, Dict[str, Any]] = {}
        if parcels is None or len(parcels) == 0:
            return out
        for _, row in parcels.iterrows():
            pin = str(row["pin"])
            abated = row.get("abated_improvement_value")
            if abated is not None and pd.notna(abated) and float(abated) > 0:
                out.setdefault(pin, {})["abatement"] = {
                    "abatement_type": "abated improvement value (auditor roll)",
                    "abated_improvement_value": float(abated),
                }
            tif = _text_or_none(row.get("tif_standing"))
            if tif and tif.upper() != "NO":
                out.setdefault(pin, {})["tif"] = {"name": tif}
        if out:
            logger.info("Licking incentives: %d parcels with an abatement or "
                        "TIF standing.", len(out))
        return out

    def _zoning_layer_ids(self) -> Optional[List[tuple]]:
        """Township layer (id, name) pairs from the service root."""
        try:
            r = requests.get(
                f"{self.ZONING_SERVICE_URL}",
                params={"f": "json"}, timeout=60)
            r.raise_for_status()
            data = r.json()
            return [(l["id"], l["name"]) for l in data.get("layers", [])]
        except Exception as e:  # noqa: BLE001
            logger.warning("Licking zoning service unavailable (%s).", e)
            return None

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
                    logger.warning("Licking query error: %s", data["error"])
                    return None if not features else features
                batch = data.get("features", []) or []
                features.extend(batch)
                if len(batch) < self.PAGE_SIZE:
                    break
                offset += self.PAGE_SIZE
        except Exception as e:  # noqa: BLE001
            logger.warning("Licking query failed (%s).", e)
            return None if not features else features
        return features


def _epoch_ms_to_iso(v: Any) -> Optional[str]:
    """ArcGIS esriFieldTypeDate (epoch milliseconds) to an ISO date, or None."""
    if v is None:
        return None
    try:
        return datetime.fromtimestamp(float(v) / 1000.0, tz=timezone.utc) \
            .strftime("%Y-%m-%d")
    except (TypeError, ValueError, OSError, OverflowError):
        return None
