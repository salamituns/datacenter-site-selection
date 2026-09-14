"""
Fauquier County, Virginia parcel ingestion — the sixth parcel jurisdiction
and the third in PJM's Virginia territory.

Chosen over Stafford, Clarke and Fairfax on measurement, not proximity
(docs/virginia-expansion-shortlist.md): 4,202 parcels clear 20 acres and
1,007 clear 100, more qualifying inventory than Loudoun itself, and it is
the only candidate publishing a legal acreage figure rather than computed
geometry area.

The probe found three things this adapter exists to handle, each of which
would otherwise have produced a confident wrong answer rather than an error.

1.  ACREAGE is a String(50), not a number. It holds '0.777', but also '0'
    and ' '. A float() over the column would read '0' as zero acres, and
    zero acres FAILS the contiguous-acreage gate — a silent FAIL where the
    honest answer is UNKNOWN. 1,300 parcels (3.6%) carry a blank.

2.  378 parcels (1.0%) carry a blank PARCELID. They would all collide on
    ' ', and qualify_parcels refuses duplicate ids. They are dropped with a
    count logged, never de-duplicated into one arbitrary survivor.

3.  District_D is the MAGISTERIAL district — 'LEE', 'CENTER-WARRENTON',
    'SCOTT' — not zoning. A field-name match on "district" picks it up, and
    would have mapped election districts into the zoning gate. Zoning comes
    only from Zoning_Districts_DL, and this adapter reads District_D for
    nothing at all.

Zoning is fetched and mapped, but there is no use table yet. Fauquier's
ordinance was not retrievable (docs/fauquier-research.md): the county site
answers 403 to any fetcher, Municode serves a JavaScript shell, and the
secondary reporting — data centres confined to PCID and Business Park, a
March 2024 amendment requiring special exception above 50,000 sq ft — is
journalism, not an instrument. Without a constraint_rules row the zoning
gate reads UNKNOWN on every parcel, which is correct: this project has been
bitten three times by a rule version named for an amendment it does not
encode. The district polygons are ingested now so the rule drops in later
without a re-survey.

Water is UNKNOWN for the whole county and no proxy is offered. The Water
and Sanitation Authority publishes one static PDF dated 2017 and confirms
service by telephone; Waterlines_DL is National Hydrography Dataset stream
geometry, not mains, and matching on its name would have served a "water
available" verdict to every parcel near a creek.
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

# Fauquier publishes through its ArcGIS Online organisation. The county's
# own metadata on the zoning item: "The zoning layer constitutes the
# official zoning map for Fauquier County and is a component of the
# official zoning ordinance", owned by the Department of Community
# Development. The gis-agol.fauquiercounty.gov host that appears in search
# results does not resolve publicly; these do.
ORG = "https://services.arcgis.com/oAoeYJ1kqmAwcEC2/arcgis/rest/services"
PARCELS_URL = f"{ORG}/Tax_Parcels_DL/FeatureServer/0/query"
ZONING_URL = f"{ORG}/Zoning_Districts_DL/FeatureServer/0/query"

# Recorded on every zoning row so the dossier cites where the districts came
# from. It is NOT a use table: it names the map, not what the map permits.
ORDINANCE = ("Fauquier County Zoning Ordinance — official zoning map "
             "(Zoning_Districts_DL, Department of Community Development)")


class FauquierParcelAPI:
    """One adapter, the same contract as the other five jurisdictions."""

    PAGE_SIZE = 1000
    MIN_SOURCE_ACRES = 20.0

    PARCEL_FIELDS = "PARCELID,ACREAGE,VisionPID"
    ZONING_FIELDS = "ZONECLASS,ZONEDESC"

    def layer_sources(self) -> Dict[str, Dict[str, Optional[str]]]:
        """
        Fauquier publishes cadastre and county-wide zoning districts.
        Wetlands and flood hazard stay national and are fetched by the
        pipeline. Water is declared with a null endpoint rather than
        omitted: the snapshot then records that a water layer was sought
        and does not exist, which is a different fact from never looking.
        """
        return {
            "parcels": {"source_key": "fauquier_tax_parcels",
                        "endpoint": PARCELS_URL},
            "zoning": {"source_key": "fauquier_zoning_districts",
                       "endpoint": ZONING_URL},
            "wetlands": {"source_key": "nwi_wetlands", "endpoint": None},
            "nfhl": {"source_key": None, "endpoint": None},
            "water": {"source_key": None, "endpoint": None},
        }

    def fetch_all(self, min_lon: float, min_lat: float,
                  max_lon: float, max_lat: float,
                  min_acres: float = MIN_SOURCE_ACRES
                  ) -> Dict[str, Optional[gpd.GeoDataFrame]]:
        """A layer the county does not publish is None, never an empty frame."""
        bbox = f"{min_lon},{min_lat},{max_lon},{max_lat}"
        return {
            "parcels": self.fetch_parcels(bbox, min_acres),
            "zoning": self.fetch_zoning(bbox),
            "wetlands": None,   # national NWI, fetched by the pipeline
            "nfhl": None,       # national NFHL, fetched by the pipeline
        }

    # ------------------------------------------------------------------
    @staticmethod
    def _acres(raw: Any) -> Optional[float]:
        """
        ACREAGE as a number, or None where the county has not stated one.

        '0' and ' ' both become None. This is the whole point: a parcel of
        zero acres FAILS the contiguous-acreage gate, and a parcel whose
        acreage the county never recorded must CONCEDE it. Reading the
        first as the second is the silent-wrong-verdict failure the engine
        exists to avoid.
        """
        if raw is None:
            return None
        text = str(raw).strip()
        if not text:
            return None
        try:
            value = float(text)
        except ValueError:
            return None
        # A recorded 0 is indistinguishable from an unrecorded one here:
        # the county uses '0' as a filler on rows with no deed acreage, and
        # no real parcel is zero acres. Both concede.
        return value if value > 0 else None

    def fetch_parcels(self, bbox: str, min_acres: float
                      ) -> Optional[gpd.GeoDataFrame]:
        """
        Parcels at or above the acreage floor.

        The floor is pushed into the query with CAST — the service supports
        it, verified against the live layer — so the 20-acre filter costs
        one request rather than 36,205 rows over the wire. The Python-side
        check still runs: a CAST the service silently stops honouring would
        otherwise widen the survey without anyone noticing.
        """
        features = self._paged(
            PARCELS_URL, bbox, self.PARCEL_FIELDS,
            where=f"CAST(ACREAGE AS FLOAT) >= {min_acres}",
        )
        if features is None:
            return None

        rows: Dict[str, Dict[str, Any]] = {}
        blank_id = 0
        blank_acreage = 0
        below_floor = 0
        multipart = 0
        for f in features:
            props = f.get("properties") or {}
            pin = str(props.get("PARCELID") or "").strip()
            geometry = f.get("geometry")
            if not pin:
                # 378 of these county-wide. They would all collide on '' and
                # trip the duplicate-id refusal in qualify_parcels.
                blank_id += 1
                continue
            if not geometry:
                continue
            acres = self._acres(props.get("ACREAGE"))
            if acres is None:
                blank_acreage += 1
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
                # A parcel published as several polygons. Dropping the
                # extras would keep the right acreage and the wrong shape,
                # and the overlay gates — wetlands, floodway, slope — all
                # read the shape. Union the parts instead.
                multipart += 1
                rows[pin]["geometry"] = unary_union(
                    [rows[pin]["geometry"], geom])
                continue
            rows[pin] = {
                "pin": pin,
                "legal_acreage": acres,
                "vision_pid": str(props.get("VisionPID") or "").strip() or None,
                "geometry": geom,
            }

        if blank_id:
            logger.warning(
                "Fauquier parcels: %d features with a blank PARCELID were "
                "dropped. They cannot be identified, and keeping one of them "
                "would qualify an arbitrary parcel under an empty id.",
                blank_id)
        if blank_acreage:
            logger.info(
                "Fauquier parcels: %d features carried no usable ACREAGE "
                "('0' or blank) and are not surveyed — the county has not "
                "stated an acreage for them.", blank_acreage)
        if below_floor:
            logger.warning(
                "Fauquier parcels: %d features came back below the %.0f-acre "
                "floor despite the CAST filter — the service may have stopped "
                "honouring it. Filtered here.", below_floor, min_acres)
        if multipart:
            logger.info(
                "Fauquier parcels: %d extra polygons belonged to a parcel "
                "already seen and were unioned into it.", multipart)

        rows = self._collapse_co_extensive(rows)

        if not rows:
            logger.warning("Fauquier parcels: no qualifying features.")
            return None

        logger.info("Fauquier parcels: %d at or above %.0f acres.",
                    len(rows), min_acres)
        return gpd.GeoDataFrame(list(rows.values()), crs="EPSG:4326")

    def fetch_zoning(self, bbox: str) -> Optional[gpd.GeoDataFrame]:
        """
        The county-wide zoning districts.

        Ingested without a use table. Fauquier's ordinance could not be
        retrieved, so no constraint_rules row maps these classes to a
        data-centre permission and the zoning gate reads UNKNOWN. The
        districts are carried anyway so that adding the rule later is a row
        in a table rather than a re-survey.

        ZONEDESC is the county's own district name and is passed through
        verbatim; it is never used to infer what a district permits.
        """
        features = self._paged(ZONING_URL, bbox, self.ZONING_FIELDS)
        if features is None:
            return None
        rows: List[Dict[str, Any]] = []
        blank = 0
        for f in features:
            props = f.get("properties") or {}
            zone = str(props.get("ZONECLASS") or "").strip()
            geometry = f.get("geometry")
            if not geometry:
                continue
            if not zone:
                # The layer carries at least one blank ZONECLASS. An unnamed
                # district is an unknown district, not an unzoned one.
                blank += 1
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
                "zone_name": str(props.get("ZONEDESC") or "").strip() or None,
                "ordinance": ORDINANCE,
                "geometry": geom,
            })
        if blank:
            logger.info("Fauquier zoning: %d polygons with a blank ZONECLASS "
                        "were dropped — an unnamed district is unknown, not "
                        "unzoned.", blank)
        if not rows:
            logger.warning("Fauquier zoning: no district polygons.")
            return None
        logger.info("Fauquier zoning: %d district polygons, %d distinct "
                    "classes.", len(rows), len({r["zone"] for r in rows}))
        return gpd.GeoDataFrame(rows, crs="EPSG:4326")

    # ------------------------------------------------------------------
    @staticmethod
    def _collapse_co_extensive(rows: Dict[str, Dict[str, Any]]
                               ) -> Dict[str, Dict[str, Any]]:
        """
        Collapses ownership interests that are all the same piece of ground.

        Fauquier publishes condominium and similar divided interests as
        separate PARCELIDs under one base tax-map number, and stamps the
        PARENT TRACT's acreage on every one of them. Base 7809-78-6301
        carries 50 such parcels, each claiming 269.85 acres, whose geometry
        unions to 263.5 acres — one tract. Surveyed as published they would
        enter the shortlist as fifty separate 270-acre sites, 13,493 acres
        of candidate land on 263 acres of ground, every one passing the
        acreage gate.

        The rule is deliberately narrow, because collapsing two genuinely
        distinct parcels would be the worse error: same base tax-map number,
        identical claimed acreage, AND a union whose true area is close to
        that single claimed figure rather than to the sum. Three coincidences
        at once is one tract, not three neighbours.
        """
        groups: Dict[Any, List[str]] = {}
        for pin, row in rows.items():
            parts = pin.split("-")
            base = "-".join(parts[:3]) if len(parts) == 4 else pin
            groups.setdefault((base, round(row["legal_acreage"], 4)), []).append(pin)

        collapsed = 0
        for (base, acres), pins in groups.items():
            if len(pins) < 2:
                continue
            frame = gpd.GeoDataFrame(
                [{"geometry": rows[p]["geometry"]} for p in pins],
                crs="EPSG:4326").to_crs("EPSG:5070")
            union = unary_union(list(frame.geometry))
            union_acres = union.area / 4046.86
            # One tract if the union is about the claimed size; distinct
            # neighbours if it is about the sum of them.
            if union_acres > acres * 1.5:
                continue
            keeper = max(pins, key=lambda p: len(p))
            for p in pins:
                if p != keeper:
                    del rows[p]
            rows[keeper]["geometry"] = gpd.GeoSeries(
                [union], crs="EPSG:5070").to_crs("EPSG:4326").iloc[0]
            rows[keeper]["co_extensive_interests"] = len(pins)
            collapsed += len(pins) - 1
            logger.warning(
                "Fauquier parcels: base %s carried %d parcels each claiming "
                "%.2f acres whose geometry unions to %.1f acres — one tract "
                "published as divided interests. Collapsed to %s; %d would "
                "otherwise have entered the survey as separate sites.",
                base, len(pins), acres, union_acres, keeper, len(pins) - 1)
        if collapsed:
            logger.warning("Fauquier parcels: %d co-extensive interests "
                           "collapsed in total.", collapsed)
        return rows

    def _paged(self, base_url: str, bbox: str, out_fields: str,
               where: str = "1=1") -> Optional[List[Dict[str, Any]]]:
        """
        Pages an ArcGIS query in GeoJSON; None only on hard failure before
        any feature lands. A failed page is retried with backoff — one bad
        request must not cost a whole layer, and with it the run.
        """
        features: List[Dict[str, Any]] = []
        offset = 0
        attempts = 4
        r = None
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
                        f"status {r.status_code if r else '?'} after "
                        f"{attempts} attempts")
                if "error" in data:
                    logger.warning("Fauquier query error: %s", data["error"])
                    return None if not features else features
                batch = data.get("features", []) or []
                features.extend(batch)
                if len(batch) < self.PAGE_SIZE:
                    break
                offset += self.PAGE_SIZE
        except Exception as e:  # noqa: BLE001
            logger.warning("Fauquier query failed (%s).", e)
            return None if not features else features
        return features
