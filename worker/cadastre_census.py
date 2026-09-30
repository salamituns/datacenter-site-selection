"""
The cadastre census — discovery for the parcel tier.

The parcel tier is nine regions of 554. The rest are screening cells:
ranked leads with no diligence underneath, because nobody has inventoried
which of those counties publish cadastral parcel data at all. This module
is that inventory, run as a machine instead of a hand-probe per county.

Two discovery paths, one verification rule:

  * COUNTY SEARCH — ArcGIS Online's public sharing index, the same index
    that surfaced every county service the nine adapters use. The search
    is fuzzy (anyone can publish anything), so hits are filtered and
    scored: parcel in title or tags, service types only, and the county's
    name showing up in the title or the publishing account.

  * STATE PROGRAMS — the six statewide services verified by hand before
    this module was written (NC OneMap, IndianaMap, NJ OGIS MOD-IV, OGRIP
    Ohio, MD iMap, TNMap) plus VGIN's Virginia file geodatabase, which is
    a download rather than a live service and is recorded as a candidate
    for exactly that reason. Commercial aggregators (Regrid, First
    American) are deliberately absent: the census records what a county
    or state publishes itself.

  * VERIFICATION — every candidate is checked against the region's own
    bounding box: the layer must describe itself as polygons, and a
    count query with the bbox as the envelope must answer. A count is
    presence proven. A service that answers with zero parcels in the
    bbox is still recorded, with its zero — that is a fact a deep probe
    wants before it spends an afternoon. A candidate that cannot be
    verified today is recorded as a candidate, because "found but
    uncheckable" is different from "nothing found".

The census does not decide buildability. It produces the queue: which
counties have verified public parcel sources, so a deep probe (the
five-question format in docs/licking-cadastre-probe.md) starts where the
data already is instead of where someone thought to look.

Progress is the table, not a file. A county is censused when it has a row
in cadastre_sources — including the none_found sentinel row — so re-runs
skip finished counties and a crash halfway loses nothing. Same doctrine
as pjm_screening, for the same reason: this project has been bitten three
times by second copies of facts the database already holds.
"""

from __future__ import annotations

import argparse
import logging
import os
import re
import time
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple
from pathlib import Path
from urllib.parse import urlparse

import requests

import region_registry

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("cadastre_census")

AGOL_SEARCH_URL = "https://www.arcgis.com/sharing/rest/search"
SERVICE_TYPES = {"Feature Service", "Map Service"}
REQUEST_PAUSE = 0.4        # seconds between HTTP calls, every host
REQUEST_TIMEOUT = 45
MAX_CANDIDATES_PER_REGION = 4
MAX_LAYERS_PER_SERVICE = 2

# The 15 jurisdictions of the PJM footprint. Used to build search queries
# ("parcels" AND "Adams County" AND "Indiana"); a fact about the footprint,
# stable the way the state list in pjm_screening is.
STATE_NAMES: Dict[str, str] = {
    "DC": "District of Columbia",
    "DE": "Delaware",
    "IL": "Illinois",
    "IN": "Indiana",
    "KY": "Kentucky",
    "MD": "Maryland",
    "MI": "Michigan",
    "NC": "North Carolina",
    "NJ": "New Jersey",
    "OH": "Ohio",
    "PA": "Pennsylvania",
    "TN": "Tennessee",
    "VA": "Virginia",
    "WV": "West Virginia",
}

# Statewide parcel programs, each verified by hand on 2026-09-22 before
# this table was written. (search query, note). MI/WV/KY/IL/PA are absent
# because no authoritative statewide service could be found — their
# coverage comes from the county search, which is exactly what the census
# is for. DE is absent as a program because FirstMap publishes per-county
# services that the county search finds on its own.
STATE_PROGRAM_SEARCHES: Dict[str, Tuple[str, str]] = {
    "NC": ('title:"North Carolina Parcels (Polygons)" AND owner:nconemap',
           "NC OneMap statewide standardized parcels"),
    "IN": ('title:"Parcel Boundaries of Indiana Current" AND owner:IndianaMap',
           "IndianaMap statewide parcel boundaries"),
    "NJ": ('title:"Parcels and MOD-IV Composite of New Jersey" AND owner:NJOGIS',
           "NJ OGIS statewide parcels joined to MOD-IV assessment"),
    "OH": ('title:"Ohio Statewide Parcels Public View" AND owner:ogrip_agol',
           "OGRIP statewide parcels public view"),
    "MD": ('title:"Maryland Parcel Boundaries" AND owner:mdimapdatacatalog',
           "MD iMap catalog statewide parcel boundaries"),
    "TN": ('title:"Tennessee Property Boundaries Public Use" AND owner:tnmap_oir',
           "TNMap statewide property boundaries, public use"),
}

# Download-only statewide sources. Recorded as candidates with this note:
# they cannot be bbox-counted over REST, so verification is a download
# away rather than a query away.
STATE_DOWNLOAD_SOURCES: Dict[str, Tuple[str, str, str]] = {
    # region prefix, (title, owner, note)
    "VA": ("Virginia Parcels", "VGIN",
           "VGIN statewide file geodatabase — downloadable, not REST-queryable; "
           "verification requires the download, not a count"),
}

SENTINEL_SERVICE_URL = "(none)"
SENTINEL_LAYER_ID = -1


class _ThrottledSession:
    """One session, one pause between every request, one retry."""

    UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
          "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0 Safari/537.36 "
          "cadastre-census/1.0")

    def __init__(self) -> None:
        self._session = requests.Session()
        self._session.headers["User-Agent"] = self.UA
        self._last = 0.0

    def get_json(self, url: str, params: Optional[Dict[str, Any]] = None
                 ) -> Optional[Dict[str, Any]]:
        for attempt in (1, 2):
            pause = REQUEST_PAUSE - (time.monotonic() - self._last)
            if pause > 0:
                time.sleep(pause)
            self._last = time.monotonic()
            try:
                resp = self._session.get(url, params=params,
                                         timeout=REQUEST_TIMEOUT)
                if resp.status_code == 200:
                    body = resp.json()
                    # ArcGIS Server reports a missing service as HTTP 200
                    # with {"error": {...}} as the whole body: Lexington's
                    # renamed parcel service read as "no polygon layer"
                    # instead of "did not answer" until this check.
                    if isinstance(body, dict) and set(body) == {"error"}:
                        logger.debug("service error on %s: %s", url,
                                     body["error"])
                        return None
                    return body
                logger.debug("HTTP %s on %s (attempt %d)",
                             resp.status_code, url, attempt)
                if resp.status_code < 500 and resp.status_code != 429:
                    return None  # a 403/404 will not get better; not an outage
            except (requests.RequestException, ValueError) as exc:
                logger.debug("%s on %s (attempt %d): %s",
                             type(exc).__name__, url, attempt, exc)
        return None


def _tokens(text: str) -> List[str]:
    """Lowercased words worth matching, length > 3 (the, county, etc. out)."""
    return [w for w in
            (t.strip('.,()').lower() for t in text.split())
            if len(w) > 3]


def score_candidate(item: Dict[str, Any], county: str, state_name: str
                    ) -> Optional[int]:
    """
    Relevance of one search hit, or None to reject.

    A hit must be a service and must say "parcel" in its title or tags —
    anything else is a map or an app, not a boundary layer. Past that,
    the score is where the county's identity shows up: title beats
    publishing account, and the county's own name beats the state's.
    """
    if item.get("type") not in SERVICE_TYPES:
        return None
    title = (item.get("title") or "").lower()
    tags = " ".join(item.get("tags") or []).lower()
    if "parcel" not in title and "parcel" not in tags:
        return None

    county_tokens = _tokens(county)
    state_tokens = _tokens(state_name)
    owner = (item.get("owner") or "").lower()

    score = 1  # parcel + service type already established
    if any(t in title for t in county_tokens):
        score += 2
    if any(t in owner for t in county_tokens):
        score += 1
    if any(t in title for t in state_tokens):
        score += 1
    # A county token somewhere is the floor: without it the hit is a
    # neighbouring county's service or a nationwide commercial layer.
    if not (any(t in title for t in county_tokens)
            or any(t in owner for t in county_tokens)):
        return None
    return score


# Words that mark a parcel layer as a SUBSET of the county's parcels.
# Boone County, KY publishes thirteen parcel layers in one service; the
# first two in list order are "Airport Owned Parcels" (1,148), and the
# complete "Tax Parcels" (54,873) sat untested behind them.
PARCEL_SUBSET_WORDS = (
    "owned", "hoa", "residential", "commercial", "industrial",
    "agricultural", "exempt", "public", "storm", "vacant", "nonconforming",
    "condo", "historic", "annex", "outline", "shaded", "dimension",
)


def layer_rank(name: str) -> int:
    """
    Order in which a service's layers are worth testing. 0: parcel-named
    and not a subset ("Tax Parcels", "All Parcel Types"); 1: tax/cadastre
    named; 2: a parcel subset ("Airport Owned Parcels"); 3: anything
    else. Lower first; ties keep the service's own order.
    """
    low = (name or "").lower()
    subset = any(w in low for w in PARCEL_SUBSET_WORDS)
    if "parcel" in low and not subset:
        return 0
    if any(k in low for k in ("tax", "cadastre")) and not subset:
        return 1
    if "parcel" in low:
        return 2
    return 3


def choose_layers(service_json: Dict[str, Any]
                  ) -> List[Dict[str, Any]]:
    """
    Which layers of a service to record: polygon layers, the county's
    complete parcel layer before any subset of it, capped at two.
    """
    layers = service_json.get("layers") or []
    polygons = [l for l in layers
                if l.get("geometryType") == "esriGeometryPolygon"]
    chosen = sorted(polygons, key=lambda l: layer_rank(l.get("name")))
    return chosen[:MAX_LAYERS_PER_SERVICE]


# How many layers to describe individually when a root does not say which
# are polygons. MapServer roots list id and name only — geometryType is a
# layer-level fact — and services can carry dozens of layers, so the
# probe is capped and prefers names that say parcel/tax/cadastre.
MAX_LAYER_PROBES = 12


def _polygon_layers(session: _ThrottledSession, service_url: str,
                    svc: Optional[Dict[str, Any]]
                    ) -> Tuple[List[Dict[str, Any]], bool]:
    """
    Polygon layers of a service, asking the layers themselves when the
    root does not say. Returns (layers, root_answered): a service whose
    root answered but has no polygons is a different fact from one whose
    root did not answer at all, and both are recorded rather than
    dropped.

    A URL that ends in a layer id (MD iMap's statewide item points at
    .../MapServer/0, not at the service root) answers with a layer
    document — geometryType at the top, no layers array — and that is
    one polygon layer, not zero.
    """
    if svc is None:
        return [], False
    if "layers" not in svc and svc.get("geometryType"):
        tail = service_url.rstrip("/").rsplit("/", 1)[-1]
        layer_id = int(tail) if tail.isdigit() else 0
        return [{"id": layer_id, "name": svc.get("name"),
                 "geometryType": svc["geometryType"],
                 "url": service_url, "detail": svc}], True
    chosen = choose_layers(svc)
    if chosen:
        return chosen, True
    root_layers = svc.get("layers") or []
    named_first = sorted(root_layers, key=lambda l: layer_rank(l.get("name")))
    found: List[Dict[str, Any]] = []
    for layer in named_first[:MAX_LAYER_PROBES]:
        detail = layer_detail(session, service_url, layer) or {}
        if detail.get("geometryType") == "esriGeometryPolygon":
            found.append({"id": layer["id"], "name": layer.get("name"),
                          "geometryType": "esriGeometryPolygon",
                          "detail": detail})
            if len(found) >= MAX_LAYERS_PER_SERVICE:
                break
    return found, True


def _layer_query_url(service_url: str, layer: Dict[str, Any]) -> str:
    """A layer's query endpoint. A layer carried in from a URL that
    points at it directly (.../MapServer/0) already ends where the id
    would be appended, so it brings its own URL."""
    if layer.get("url"):
        return layer["url"].rstrip("/") + "/query"
    return f"{service_url.rstrip('/')}/{layer['id']}/query"


def count_in_bbox(session: _ThrottledSession, service_url: str,
                  layer: Dict[str, Any],
                  bbox: Tuple[float, float, float, float]
                  ) -> Optional[int]:
    """
    Feature count intersecting the region bbox, or None if the layer will
    not answer. This is the verification: presence proven by count.
    """
    envelope = ("{},{},{},{}".format(*bbox))
    data = session.get_json(
        _layer_query_url(service_url, layer),
        params={
            "where": "1=1",
            # the full spec name, not the esriEnvelope short form: strict
            # services (OGRIP's Ohio statewide among them) 400 on the
            # short form, and a 400 is not an outage, it is a wrong query
            "geometryType": "esriGeometryEnvelope",
            "geometry": envelope,
            "inSR": "4326",
            "spatialRel": "esriSpatialRelIntersects",
            "returnCountOnly": "true",
            "f": "json",
        })
    if data is None or "count" not in data:
        return None
    return int(data["count"])


def layer_detail(session: _ThrottledSession, service_url: str,
                 layer: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """The layer's own description: geometry, paging limit, SR. A layer
    probed or carried in during polygon selection already has it."""
    if layer.get("detail"):
        return layer["detail"]
    if layer.get("url"):
        return session.get_json(layer["url"], params={"f": "json"})
    return session.get_json(f"{service_url.rstrip('/')}/{layer['id']}",
                            params={"f": "json"})


def _row(region_key: str, state: str, county: str, via: str,
         title: str, owner: str, item: Optional[Dict[str, Any]],
         service_url: str, layer_id: int,
         geometry_type: Optional[str] = None,
         record_count: Optional[int] = None,
         max_record_count: Optional[int] = None,
         evidence: str = "candidate", notes: Optional[str] = None
         ) -> Dict[str, Any]:
    row: Dict[str, Any] = {
        "region_key": region_key,
        "state_code": state,
        "county_name": county,
        "discovered_via": via,
        "title": title,
        "owner": owner,
        "service_url": service_url,
        "layer_id": layer_id,
        "evidence_class": evidence,
        "notes": notes,
    }
    if item:
        row["item_id"] = item.get("id")
    if geometry_type:
        row["geometry_type"] = geometry_type
    if record_count is not None:
        row["record_count"] = record_count
    if max_record_count is not None:
        row["max_record_count"] = max_record_count
    return row


def census_region(session: _ThrottledSession, region_key: str, county: str,
                  state: str, bbox: Tuple[float, float, float, float],
                  state_program_items: List[Dict[str, Any]]
                  ) -> List[Dict[str, Any]]:
    """
    One region: search, filter, verify, and return the rows to write.
    Pure with respect to the database — the caller persists.
    """
    state_name = STATE_NAMES.get(state, state)
    rows: List[Dict[str, Any]] = []

    # ── county search ────────────────────────────────────────────────
    queries = [f'parcels AND "{county}" AND "{state_name}"']
    # Virginia's independent cities share names with counties; a query
    # for "Fairfax" alone finds the county's service, the city's, and
    # both are relevant. A "city" variant is only worth a second request
    # when the first found nothing.
    results: List[Dict[str, Any]] = []
    for q in queries:
        data = session.get_json(AGOL_SEARCH_URL, params={
            "q": q, "num": 25, "f": "json"})
        hits = (data or {}).get("results") or []
        scored = []
        for item in hits:
            s = score_candidate(item, county, state_name)
            if s is not None:
                scored.append((s, item))
        if scored:
            scored.sort(key=lambda pair: -pair[0])
            results = [item for _, item in
                       scored[:MAX_CANDIDATES_PER_REGION]]
            break

    for item in results:
        service_url = item.get("url")
        if not service_url:
            continue
        svc = session.get_json(service_url, params={"f": "json"})
        if svc is None:
            rows.append(_row(region_key, state, county, "county_search",
                             item.get("title") or "", item.get("owner") or "",
                             item, service_url, -1,
                             notes="service root did not answer"))
            continue
        chosen, _ = _polygon_layers(session, service_url, svc)
        if not chosen:
            rows.append(_row(region_key, state, county, "county_search",
                             item.get("title") or "", item.get("owner") or "",
                             item, service_url, -1,
                             notes="no polygon layer found in service"))
            continue
        for layer in chosen:
            detail = layer_detail(session, service_url, layer) or {}
            count = count_in_bbox(session, service_url, layer, bbox)
            if count is None:
                rows.append(_row(region_key, state, county, "county_search",
                                 item.get("title") or "",
                                 item.get("owner") or "",
                                 item, service_url, layer["id"],
                                 geometry_type=detail.get("geometryType"),
                                 max_record_count=detail.get("maxRecordCount"),
                                 notes="layer did not answer a bbox count"))
            else:
                rows.append(_row(region_key, state, county, "county_search",
                                 item.get("title") or "",
                                 item.get("owner") or "",
                                 item, service_url, layer["id"],
                                 geometry_type=detail.get("geometryType"),
                                 record_count=count,
                                 max_record_count=detail.get("maxRecordCount"),
                                 evidence="verified",
                                 notes=(None if count else
                                        "verified service, zero features "
                                        "intersect the region bbox")))

    # ── state program ────────────────────────────────────────────────
    for item in state_program_items:
        service_url = item.get("url")
        if not service_url:
            continue
        svc = session.get_json(service_url, params={"f": "json"})
        if svc is None:
            # A statewide service that will not answer is still a fact
            # about the county's data supply — recorded, never dropped
            rows.append(_row(region_key, state, county, "state_program",
                             item.get("title") or "", item.get("owner") or "",
                             item, service_url, -1,
                             evidence="candidate",
                             notes="statewide service root did not answer"))
            continue
        chosen, _ = _polygon_layers(session, service_url, svc)
        if not chosen:
            rows.append(_row(region_key, state, county, "state_program",
                             item.get("title") or "", item.get("owner") or "",
                             item, service_url, -1,
                             evidence="candidate",
                             notes="statewide service has no polygon layer"))
            continue
        for layer in chosen:
            detail = layer_detail(session, service_url, layer) or {}
            count = count_in_bbox(session, service_url, layer, bbox)
            rows.append(_row(region_key, state, county, "state_program",
                             item.get("title") or "", item.get("owner") or "",
                             item, service_url, layer["id"],
                             geometry_type=(detail.get("geometryType")
                                            or layer.get("geometryType")),
                             record_count=count,
                             max_record_count=detail.get("maxRecordCount"),
                             evidence=("verified" if count is not None
                                       else "candidate"),
                             notes=STATE_PROGRAM_SEARCHES.get(
                                 state, ("", ""))[1] or None))

    # ── the sentinel ─────────────────────────────────────────────────
    if not rows:
        # The claim is exactly what was searched: the ArcGIS Online
        # index. Counties that self-host ArcGIS Server without
        # publishing to ArcGIS Online are invisible to this search —
        # Loudoun (logis.loudoun.gov) and Licking
        # (gis.lickingcounty.gov), both live adapters, would be
        # none_found here too. A none_found row is "not in the index",
        # never "does not exist".
        rows.append(_row(region_key, state, county, "county_search",
                         "(no parcel service in the ArcGIS Online index)",
                         "(search)",
                         None, SENTINEL_SERVICE_URL, SENTINEL_LAYER_ID,
                         evidence="none_found",
                         notes="not indexed on ArcGIS Online; a self-hosted "
                               "county GIS may still exist"))
    return rows


# ── the second pass: web maps → self-hosted services ─────────────────────
#
# The first pass could not see a county that runs its own ArcGIS Server
# without registering it in ArcGIS Online. The index does hold that
# county's web maps, and a web map is a JSON document listing the layer
# URLs it draws — so the county's own maps point at its own server.

WEB_MAP_SENTINEL_URL = "(none: web maps)"
MAX_WEB_MAPS_PER_REGION = 40

# Self-hosted statewide parcel services, found while probing for the
# second pass (2026-09-28) and invisible to the first because neither is
# registered in ArcGIS Online. Direct layer URLs: there is nothing to
# search for. (layer URL, title, owner, note)
SELF_HOSTED_STATE_PROGRAMS: Dict[str, List[Tuple[str, str, str, str]]] = {
    "WV": [("https://services.wvgis.wvu.edu/arcgis/rest/services/"
            "Planning_Cadastre/WV_Parcels/MapServer/0",
            "WVParcels", "WVGISTC",
            "WV GIS Technical Center statewide parcels, compiled from county "
            "assessors and the WV Property Tax Division; self-hosted, not in "
            "the ArcGIS Online index")],
    "PA": [("https://gis.dep.pa.gov/depgisprd/rest/services/"
            "Parcels/PA_Parcels/MapServer/0",
            "PA Parcels", "PA DEP",
            "PA DEP statewide parcel layer, self-described as a PARTIAL "
            "dataset: a count here proves presence in the bbox, not "
            "county-complete coverage"),
           # PASDA's own statewide compilation (dataset 1696, "Pennsylvania
           # Parcels (Available)", August 2026 build), on apps.pasda — a
           # different host from the mapservices.pasda server the pool
           # crawls. Also self-described incomplete; it and PA DEP each
           # carry counties the other lacks (measured 2026-09-30).
           ("https://apps.pasda.psu.edu/arcgis/rest/services/"
            "PA_Parcels/MapServer/1",
            "PA Parcels", "PASDA",
            "PASDA (Penn State) statewide parcels, dataset 1696, compiled "
            "from county submissions and self-described incomplete; the "
            "Source and Date fields name each county's submission")],
    # The REST face of the statewide file the first pass could only record
    # as a download candidate (STATE_DOWNLOAD_SOURCES). Found 2026-09-29;
    # the host the search index still names, gismaps.vdem.virginia.gov,
    # no longer resolves — vginmaps is where the service lives now.
    "VA": [("https://vginmaps.vdem.virginia.gov/arcgis/rest/services/"
            "VA_Base_Layers/VA_Parcels/FeatureServer/0",
            "Virginia Parcels", "VGIN",
            "VGIN statewide parcels, aggregated from each locality's data-call "
            "submission; not edge-matched across localities, and each "
            "locality's vintage is its own last submission (LASTUPDATE)")],
}


def is_self_hosted(url: str) -> bool:
    """A URL on a county's or state's own server, not ArcGIS Online's
    hosting. Hosted services were the first pass's whole search space;
    what a web map adds there is re-uploads, not publishers."""
    host = urlparse(url).netloc.lower().split(":")[0]
    if not host:
        return False
    return not (host.endswith("arcgis.com") or host.endswith("arcgisonline.com"))


def is_parcel_layer(title: str, url: str) -> bool:
    """
    Whether a web-map layer is worth a bbox count as a parcel source.

    Web maps carry everything a county draws — roads, zoning, flood
    zones, school districts — and the URL path is often more honest than
    the title a map author typed. A False here costs a missed county; a
    True costs a count query, and the count still has to prove polygons
    in the bbox before anything is recorded as verified.
    """
    text = f"{title} {urlparse(url).path}".lower()
    # "parcel" is the one word a boundary layer reliably carries, in the
    # title or the service path; "tax" alone names districts as often as
    # parcels, so it counts only as "taxmap"/"tax map".
    if not any(k in text for k in ("parcel", "taxmap", "tax map", "cadastre")):
        return False
    # survey grids and district boundaries share the vocabulary but are
    # not ownership: PLSS (BLM's "Cadastral" folder), and anything drawn
    # as a district or a point/label layer of parcels
    return not any(k in text for k in ("plss", "survey system", "district",
                                       "label", "annotation", "point"))


def _walk_layers(layers: Optional[List[Dict[str, Any]]]):
    """Operational layers nest (group layers); walk the whole tree."""
    for layer in layers or []:
        yield layer
        yield from _walk_layers(layer.get("layers"))


def web_map_layer_urls(web_map: Dict[str, Any]) -> List[Tuple[str, str]]:
    """(title, url) of every self-hosted parcel layer one web map draws,
    in the map's own order."""
    found: List[Tuple[str, str]] = []
    for layer in _walk_layers(web_map.get("operationalLayers")):
        url = (layer.get("url") or "").strip()
        title = layer.get("title") or ""
        if url and is_self_hosted(url) and is_parcel_layer(title, url):
            found.append((title, url))
    return found


def _normalise_layer_url(url: str) -> str:
    """One spelling per layer: logis.loudoun.gov/GIS/... and /gis/... are
    the same layer, drawn by different maps with different case."""
    parts = urlparse(url.rstrip("/"))
    return f"{parts.scheme}://{parts.netloc.lower()}{parts.path}"


def discover_web_map_urls(session: _ThrottledSession, county: str,
                          state_name: str,
                          cap: int = MAX_CANDIDATES_PER_REGION,
                          ) -> List[Tuple[str, str, Dict[str, Any]]]:
    """
    Self-hosted parcel layer URLs referenced by the county's web maps:
    (title, url, the web-map item that referenced it). Deduplicated by
    normalised URL — twenty maps drawing the county's parcel layer are
    one source, credited to the first map that drew it.
    """
    data = session.get_json(AGOL_SEARCH_URL, params={
        "q": f'"{county}" "{state_name}" type:"Web Map"',
        "num": MAX_WEB_MAPS_PER_REGION, "f": "json"})
    seen: Dict[str, Tuple[str, str, Dict[str, Any]]] = {}
    for item in (data or {}).get("results") or []:
        web_map = session.get_json(
            f"https://www.arcgis.com/sharing/rest/content/items/"
            f"{item['id']}/data", params={"f": "json"})
        if not isinstance(web_map, dict):
            continue
        for title, url in web_map_layer_urls(web_map):
            key = _normalise_layer_url(url)
            if key not in seen:
                seen[key] = (title, key, item)
    return list(seen.values())[:cap]


# ── the targeted pass: counties whose recorded layers do not cover them ──
#
# Outline coverage found 77 regions whose "verified" layers cover under a
# quarter of the county or are not parcel-sized at all. Two of them,
# looked at by hand, had a good layer the census had recorded wrongly:
# Kenton's hid behind the candidate cap, Fayette's behind a renamed
# service. The targeted pass does those two things for every such region.

TARGETED_CANDIDATE_CAP = 12

# A catalog of county parcel endpoints on ArcGIS Online: items titled
# "Parcels - <ST> - <County> County", 1,079 of them nationwide on
# 2026-09-30, each pointing at the publisher's own service — county and
# PVA servers, regional development districts, LINK-GIS. The account
# carries no description, so it is used as an INDEX only: the recorded
# publisher is the endpoint's host, and every layer passes the same
# polygon, count and outline checks as anything the census finds itself.
CATALOG_OWNERS = ("GDITAdmin",)


_CATALOG_CACHE: Dict[Tuple[str, str], List[Dict[str, Any]]] = {}


def _county_key(name: str) -> str:
    """A county name reduced to letters: "La Salle", "LaSalle", "Jo
    Daviess", "DeKalb" and "De Kalb" each compare equal to their other
    spelling. Census and catalog do not spell them alike. Only "county"
    is dropped: Virginia has Richmond County AND Richmond City, and a
    key that dropped "city" would let either answer for the other."""
    name = re.sub(r"\bcounty\b", "", (name or "").lower())
    return re.sub(r"[^a-z]", "", name)


def _catalog_state(session: _ThrottledSession, owner: str, state: str
                   ) -> List[Dict[str, Any]]:
    """Every catalog item for a state, fetched once per run: the search
    index's title matching is fuzzy about spacing, a paged state listing
    is not."""
    key = (owner, state)
    if key not in _CATALOG_CACHE:
        items, start = [], 1
        while start and start > 0:
            data = session.get_json(AGOL_SEARCH_URL, params={
                "q": f'owner:{owner} title:"Parcels - {state}"',
                "num": 100, "start": start, "f": "json"}) or {}
            items += data.get("results") or []
            start = data.get("nextStart", -1)
        _CATALOG_CACHE[key] = items
    return _CATALOG_CACHE[key]


def catalog_urls(session: _ThrottledSession, county: str, state: str
                 ) -> List[Tuple[str, str, Dict[str, Any]]]:
    """(title, url, item) of catalog entries for this county. The title
    must be "Parcels - ST - <County>[ County]" and the county part must
    equal this county's name letter for letter — spacing aside — so a
    neighbour's or a joint entry can never answer for it."""
    want = _county_key(county)
    prefix = f"parcels - {state.lower()} - "
    found = []
    for owner in CATALOG_OWNERS:
        for item in _catalog_state(session, owner, state):
            title = (item.get("title") or "").strip()
            if not title.lower().startswith(prefix) or not item.get("url"):
                continue
            if _county_key(title[len(prefix):]) == want:
                found.append((title, item["url"], item))
    return found


def abbreviated_search(session: _ThrottledSession, county: str, state: str
                       ) -> List[Dict[str, Any]]:
    """
    The first pass's service search, with the state abbreviation beside
    its name. Kentucky's services say "Ky PVA Hardin Parcels", not
    "Kentucky": a query that required the full name never saw them.
    Hits are scored and floored exactly as the first pass's.
    """
    state_name = STATE_NAMES.get(state, state)
    data = session.get_json(AGOL_SEARCH_URL, params={
        "q": f'parcel* "{county}" ({state} OR "{state_name}")',
        "num": 25, "f": "json"}) or {}
    scored = []
    for item in data.get("results") or []:
        sc = score_candidate(item, county, state_name)
        if sc is not None and item.get("url"):
            scored.append((sc, item))
    scored.sort(key=lambda pair: -pair[0])
    return [item for _, item in scored[:MAX_CANDIDATES_PER_REGION]]
MAX_DIRECTORY_SERVICES = 200


def _services_root(url: str) -> Optional[str]:
    """The .../rest/services root of an ArcGIS Server URL, or None."""
    i = url.lower().find("/rest/services")
    return url[:i + len("/rest/services")] if i >= 0 else None


_DIRECTORY_CACHE: Dict[str, List[Tuple[str, str]]] = {}


def list_host_services(session: _ThrottledSession, url: str
                       ) -> List[Tuple[str, str]]:
    """(name, service URL) of every Map/Feature service on the server that
    `url` lives on, folders one level deep; cached per server for the run,
    since a regional host is asked about many counties."""
    root = _services_root(url)
    if not root:
        return []
    if root.lower() in _DIRECTORY_CACHE:
        return _DIRECTORY_CACHE[root.lower()]
    top = session.get_json(root, params={"f": "json"}) or {}
    services = list(top.get("services") or [])
    for folder in (top.get("folders") or [])[:40]:
        sub = session.get_json(f"{root}/{folder}", params={"f": "json"}) or {}
        services += sub.get("services") or []
        if len(services) >= MAX_DIRECTORY_SERVICES:
            break
    listed = [(svc.get("name") or "", f"{root}/{svc.get('name')}/{svc['type']}")
              for svc in services[:MAX_DIRECTORY_SERVICES]
              if svc.get("type") in ("MapServer", "FeatureServer")]
    _DIRECTORY_CACHE[root.lower()] = listed
    return listed


def crawl_host_directory(session: _ThrottledSession, url: str
                         ) -> List[Tuple[str, str]]:
    """
    (name, service URL) of every parcel-named service on the server that
    `url` lives on. A county's web maps can point at a service the server
    has since renamed — Lexington's maps still draw parcels/MapServer, its
    directory lists property/MapServer — and the directory is the server's
    own current word on what it publishes.
    """
    # "property" names Lexington's parcel service; the layer check
    # (polygons, a count, then coverage) decides whether it is one
    return [(n, u) for n, u in list_host_services(session, url)
            if is_parcel_layer(n, "") or "property" in n.lower()]


def pooled_host_services(session: _ThrottledSession, county: str,
                         state_hosts: List[str]) -> List[Tuple[str, str, str]]:
    """
    (name, url, root) of services on any server known in the state whose
    NAME carries the county's own name — a regional host (Bluegrass ADD
    keeps Boyle's parcels in a Boyle/ folder) answering for a member
    county the census never tied it to. The name filter is what keeps a
    neighbour's layer out; the outline check still decides.
    """
    tokens = _tokens(county)
    out = []
    for root in state_hosts:
        for name, url in list_host_services(session, root):
            low = name.lower()
            if any(t in low for t in tokens) and (
                    is_parcel_layer(name, "") or "pva" in low
                    or "property" in low):
                out.append((name, url, root))
    return out


def census_region_targeted(session: _ThrottledSession, region_key: str,
                           county: str, state: str,
                           bbox: Tuple[float, float, float, float],
                           known_urls: List[str],
                           state_hosts: Optional[List[str]] = None,
                           ) -> List[Dict[str, Any]]:
    """
    One region the census has recorded wrongly or not at all: statewide
    program, web maps with the cap raised, and the service directories of
    every self-hosted server already tied to the region. Rows already
    recorded are upserted in place; coverage is measured afterwards.
    """
    state_name = STATE_NAMES.get(state, state)
    rows: List[Dict[str, Any]] = []
    seen: set = set()

    for url, title, owner, note in SELF_HOSTED_STATE_PROGRAMS.get(state, []):
        seen.add(_normalise_layer_url(url))
        rows += _verify_url(session, region_key, state, county,
                            "state_program", title, owner, None, url, bbox,
                            note=note)

    extra_urls: List[str] = []
    for title, url, item in catalog_urls(session, county, state):
        extra_urls.append(url)
        key = _normalise_layer_url(url)
        if key in seen:
            continue
        seen.add(key)
        rows += _verify_url(
            session, region_key, state, county, "catalog", title,
            urlparse(url).netloc.lower(), item, url, bbox,
            note=f"catalogued by {item.get('owner')} (item {item.get('id')}); "
                 f"publisher is the endpoint's host, not the catalog")

    for item in abbreviated_search(session, county, state):
        extra_urls.append(item["url"])
        key = _normalise_layer_url(item["url"])
        if key in seen:
            continue
        seen.add(key)
        rows += _verify_url(
            session, region_key, state, county, "county_search",
            item.get("title") or "", item.get("owner") or "", item,
            item["url"], bbox,
            note="found by the abbreviated-state search (targeted pass)")

    hosts_seen: set = set()
    web = discover_web_map_urls(session, county, state_name,
                                cap=TARGETED_CANDIDATE_CAP)
    for title, url, item in web:
        seen.add(_normalise_layer_url(url))
        rows += _verify_url(
            session, region_key, state, county, "web_map",
            title or urlparse(url).netloc, urlparse(url).netloc.lower(),
            item, url, bbox,
            note=f"referenced by web map {item.get('id')} ({item.get('owner')})")

    for url in [u for _, u, _ in web] + known_urls + extra_urls:
        if not is_self_hosted(url):
            continue
        root = _services_root(url)
        if not root or root.lower() in hosts_seen:
            continue
        hosts_seen.add(root.lower())
        for name, svc_url in crawl_host_directory(session, url):
            key = _normalise_layer_url(svc_url)
            if key in seen:
                continue
            seen.add(key)
            rows += _verify_url(
                session, region_key, state, county, "host_directory",
                name, urlparse(svc_url).netloc.lower(), None, svc_url, bbox,
                note=f"listed in the service directory of {root}, a server "
                     f"already tied to this region")

    for name, svc_url, root in pooled_host_services(session, county,
                                                    state_hosts or []):
        key = _normalise_layer_url(svc_url)
        if key in seen:
            continue
        seen.add(key)
        rows += _verify_url(
            session, region_key, state, county, "host_directory",
            name, urlparse(svc_url).netloc.lower(), None, svc_url, bbox,
            note=f"named for this county in the service directory of "
                 f"{root}, a server known elsewhere in the state")
    return rows


def _verify_url(session: _ThrottledSession, region_key: str, state: str,
                county: str, via: str, title: str, owner: str,
                item: Optional[Dict[str, Any]], url: str,
                bbox: Tuple[float, float, float, float],
                note: Optional[str] = None) -> List[Dict[str, Any]]:
    """The first pass's verification rule, for a URL rather than a search
    hit: polygon layers, a bbox count, and a recorded row either way."""
    svc = session.get_json(url, params={"f": "json"})
    if svc is None:
        return [_row(region_key, state, county, via, title, owner, item, url,
                     -1, notes="service did not answer")]
    chosen, _ = _polygon_layers(session, url, svc)
    if not chosen:
        return [_row(region_key, state, county, via, title, owner, item, url,
                     -1, notes="no polygon layer at this URL")]
    rows = []
    for layer in chosen:
        detail = layer_detail(session, url, layer) or {}
        count = count_in_bbox(session, url, layer, bbox)
        rows.append(_row(
            region_key, state, county, via, title, owner, item, url,
            layer["id"],
            geometry_type=detail.get("geometryType") or layer.get("geometryType"),
            record_count=count,
            max_record_count=detail.get("maxRecordCount"),
            evidence="verified" if count is not None else "candidate",
            notes=(note if count else
                   "layer did not answer a bbox count" if count is None else
                   "verified service, zero features intersect the region bbox")))
    return rows


def census_region_web_maps(session: _ThrottledSession, region_key: str,
                           county: str, state: str,
                           bbox: Tuple[float, float, float, float]
                           ) -> List[Dict[str, Any]]:
    """
    The second pass for one region: self-hosted statewide program first
    (one query, no search), then the county's web maps. Always returns at
    least one row — the web-map sentinel when nothing was found — so the
    region reads as second-passed and a re-run skips it.
    """
    state_name = STATE_NAMES.get(state, state)
    rows: List[Dict[str, Any]] = []

    for url, title, owner, note in SELF_HOSTED_STATE_PROGRAMS.get(state, []):
        rows += _verify_url(session, region_key, state, county,
                            "state_program", title, owner, None, url, bbox,
                            note=note)

    for title, url, item in discover_web_map_urls(session, county, state_name):
        rows += _verify_url(
            session, region_key, state, county, "web_map",
            title or urlparse(url).netloc,
            # the publisher is the host, not the map's author: a student's
            # web map pointing at logis.loudoun.gov found Loudoun's server
            urlparse(url).netloc.lower(), item, url, bbox,
            note=f"referenced by web map {item.get('id')} "
                 f"({item.get('owner')})")

    # The sentinel answers for the web-map search alone: a statewide
    # program verifying here says nothing about the county's own maps,
    # and without a web_map row the region would never read as passed.
    if not any(r["discovered_via"] == "web_map" for r in rows):
        rows.append(_row(region_key, state, county, "web_map",
                         "(no self-hosted parcel layer in the county's web maps)",
                         "(search)", None, WEB_MAP_SENTINEL_URL,
                         SENTINEL_LAYER_ID, evidence="none_found",
                         notes=f"searched up to {MAX_WEB_MAPS_PER_REGION} "
                               "indexed web maps; a county that publishes "
                               "no web map to ArcGIS Online stays unseen"))
    return rows


def _web_map_targets(client: Any) -> Tuple[set, set]:
    """(regions with a verified source, regions already second-passed).
    The second pass runs on regions in neither set."""
    verified, passed, page, size = set(), set(), 0, 1000
    while True:
        res = (client.table("cadastre_sources")
               .select("region_key,evidence_class,discovered_via")
               .order("id").range(page * size, page * size + size - 1)
               .execute())
        for r in res.data:
            if r["evidence_class"] == "verified":
                verified.add(r["region_key"])
            if r["discovered_via"] == "web_map":
                passed.add(r["region_key"])
        if len(res.data) < size:
            return verified, passed
        page += 1


# ── outline coverage: does a verified layer cover THIS county? ───────────
#
# A bbox count cannot tell a county's own layer from a neighbour's layer
# reaching into the box — bboxes of adjacent counties overlap. Coverage
# asks the layer at points spread across the county's own outline whether
# a parcel is there. A county's own layer hits most of them (the misses
# are roads and water); a neighbour's hits the few near the shared edge.

COVERAGE_POINTS = 24
# Points keep this far inside the outline, so the 1:20m generalisation of
# the boundary cannot put a point in the neighbouring county.
COVERAGE_INSET_M = 800
# Water is subtracted from the outline before the grid is laid: a point in
# Pamlico Sound has no parcel under it, and read as a miss it made the NC
# sound counties look partly covered (Dare 0.292) when the layer was whole.
# The margin keeps points off the shoreline, where the county's parcel
# edge and the Census water edge are drawn by different hands.
WATER_MARGIN_M = 100
# Which measurement a row holds. Rows measured another way are re-measured
# by the next --outline run, so the column never mixes two methods.
OUTLINE_METHOD = "grid24-inset800m-water-excluded"

# The county's TIGER/Line area-water shapefile, on the host the road-access
# fallback already uses (overlay_layers.TIGERLINE_ROADS_URL): never blocked,
# one download per county, cached.
TIGERLINE_AREAWATER_URL = (
    "https://www2.census.gov/geo/tiger/TIGER{year}/AREAWATER/"
    "tl_{year}_{fips}_areawater.zip"
)
# Current vintage first, then the one before it. The Census WAF has
# refused a single file outright — Gloucester County, VA's 2024 water
# ("Request Rejected", while its neighbours and its own 2023 file download
# normally). The prior year's official file is the fallback, as the county
# shapefile is for roads: a different public file, not a way round the
# refusal, and a county's bays and rivers do not move in a year.
AREAWATER_VINTAGES = (2024, 2023)
AREAWATER_CACHE_DIR = Path(__file__).parent / "cache" / "areawater"


def county_water(region_key: str):
    """
    The county's area water, dissolved, in EPSG:5070; an empty geometry
    for a county with none. Raises when the file cannot be had — the
    caller fails the row rather than measure it without water removed.
    """
    import tempfile
    import zipfile
    from pathlib import Path

    import geopandas as gpd
    from shapely.geometry import GeometryCollection

    import region_registry as rr

    fips = rr.county_fips(region_key)
    if not fips:
        raise ValueError(f"{region_key}: no county FIPS")
    cache = AREAWATER_CACHE_DIR / f"{fips}.gpkg"
    if cache.exists():
        water = gpd.read_file(cache)
    else:
        water, refused = None, []
        for year in AREAWATER_VINTAGES:
            url = TIGERLINE_AREAWATER_URL.format(year=year, fips=fips)
            resp = requests.get(url, timeout=300,
                                headers={"User-Agent": _ThrottledSession.UA})
            # a refusal arrives as HTTP 200 with an HTML page, not a zip
            if (resp.status_code != 200
                    or not resp.content.startswith(b"PK")):
                refused.append(f"{year}: HTTP {resp.status_code}, "
                               f"{resp.headers.get('content-type')}")
                continue
            with tempfile.TemporaryDirectory() as tmp:
                zip_path = Path(tmp) / "water.zip"
                zip_path.write_bytes(resp.content)
                with zipfile.ZipFile(zip_path) as zf:
                    zf.extractall(tmp)
                shp = next(Path(tmp).glob("*.shp"))
                water = (gpd.read_file(str(shp))[["geometry"]]
                         .to_crs("EPSG:5070"))
            if refused:
                logger.info("%s area water: %s refused (%s); using the "
                            "TIGER %d file", region_key,
                            AREAWATER_VINTAGES[0], "; ".join(refused), year)
            break
        if water is None:
            raise ValueError(f"no area-water file answered ({'; '.join(refused)})")
        cache.parent.mkdir(parents=True, exist_ok=True)
        water.to_file(cache, driver="GPKG")
    if water.empty:
        return GeometryCollection()
    return water.to_crs("EPSG:5070").geometry.union_all()


def coverage_points(outline, n: int = COVERAGE_POINTS, water=None
                    ) -> List[Tuple[float, float]]:
    """
    Up to n (lon, lat) points on a regular grid inside the inset outline,
    less any water (EPSG:5070) — deterministic so a re-check asks the same
    points. The grid densifies until it holds n points, then n are taken
    evenly from it.
    """
    import geopandas as gpd
    from shapely.geometry import Point

    projected = gpd.GeoSeries([outline], crs="EPSG:4326").to_crs("EPSG:5070")
    inner = projected.iloc[0].buffer(-COVERAGE_INSET_M)
    if inner.is_empty:  # a county narrower than the inset: use it whole
        inner = projected.iloc[0]
    if water is not None and not water.is_empty:
        dry = inner.difference(water.buffer(WATER_MARGIN_M))
        # a county that is nearly all water keeps its outline rather than
        # measure nothing; the method column still says water was removed
        if not dry.is_empty:
            inner = dry
    minx, miny, maxx, maxy = inner.bounds
    inside: List[Any] = []
    for side in range(6, 60, 2):
        dx, dy = (maxx - minx) / side, (maxy - miny) / side
        inside = [Point(minx + (i + 0.5) * dx, miny + (j + 0.5) * dy)
                  for j in range(side) for i in range(side)]
        inside = [p for p in inside if inner.contains(p)]
        if len(inside) >= n:
            break
    step = max(1, len(inside) / n)
    picked = [inside[int(k * step)] for k in range(min(n, len(inside)))]
    lonlat = gpd.GeoSeries(picked, crs="EPSG:5070").to_crs("EPSG:4326")
    return [(round(p.x, 6), round(p.y, 6)) for p in lonlat]


def parcel_at(session: _ThrottledSession, query_url: str,
              lon: float, lat: float) -> Optional[bool]:
    """Whether the layer has a parcel under one point; None if it will
    not answer."""
    data = session.get_json(query_url, params={
        "where": "1=1",
        "geometryType": "esriGeometryPoint",
        "geometry": f"{lon},{lat}",
        "inSR": "4326",
        "spatialRel": "esriSpatialRelIntersects",
        "returnCountOnly": "true",
        "f": "json",
    })
    if data is None or "count" not in data:
        return None
    return int(data["count"]) > 0


def outline_coverage(session: _ThrottledSession, query_url: str,
                     points: List[Tuple[float, float]]
                     ) -> Tuple[Optional[float], int]:
    """(share of answered points that hit a parcel, points answered).
    Coverage is None when fewer than half the points answered — a layer
    that refuses most questions has not been measured."""
    answers = [parcel_at(session, query_url, lon, lat) for lon, lat in points]
    answered = [a for a in answers if a is not None]
    if len(answered) < max(1, len(points) // 2):
        return None, len(answered)
    return round(sum(answered) / len(answered), 3), len(answered)


def _row_query_url(row: Dict[str, Any]) -> str:
    """The query endpoint of a recorded row: a URL that already ends in
    its layer id is used as-is, a service root gets the id appended."""
    url = row["service_url"].rstrip("/")
    tail = url.rsplit("/", 1)[-1]
    if tail.isdigit() and int(tail) == row["layer_id"]:
        return url + "/query"
    return f"{url}/{row['layer_id']}/query"


def _main_outline(args: argparse.Namespace) -> int:
    """Measure outline coverage for verified rows that have a count and
    are unmeasured or measured by an older OUTLINE_METHOD (--redo
    re-measures everything). --via narrows to one discovery path,
    --state to one state."""
    import region_registry as rr

    client = _client()
    rows, page, size = [], 0, 1000
    while True:
        q = (client.table("cadastre_sources")
             .select("id,region_key,service_url,layer_id,record_count,"
                     "discovered_via,outline_coverage,outline_method")
             .eq("evidence_class", "verified").gt("record_count", 0))
        if args.via:
            q = q.eq("discovered_via", args.via)
        if args.state:
            q = q.eq("state_code", args.state.upper())
        res = q.order("id").range(page * size, page * size + size - 1).execute()
        rows += res.data
        if len(res.data) < size:
            break
        page += 1
    if not args.redo:
        # unmeasured rows, and rows measured by an older method
        rows = [r for r in rows if r.get("outline_method") != OUTLINE_METHOD]
    rows = rows[:args.limit]
    logger.info("Outline coverage: %d row(s)%s", len(rows),
                " (dry run)" if args.dry_run else "")

    session = _ThrottledSession()
    points_by_region: Dict[str, List[Tuple[float, float]]] = {}
    failures = 0
    for i, row in enumerate(rows, 1):
        key = row["region_key"]
        if key not in points_by_region:
            outline = rr.county_geometry(key)
            try:
                water = county_water(key) if outline is not None else None
                points_by_region[key] = (coverage_points(outline, water=water)
                                         if outline is not None else [])
            except Exception as exc:
                # never measure without the water removed: a row measured
                # the old way would sit in the column as though it weren't
                logger.warning("[%d/%d] %s area water unavailable (%s) — skipped",
                               i, len(rows), key, exc)
                points_by_region[key] = []
        points = points_by_region[key]
        if not points:
            logger.warning("[%d/%d] %s has no sample points — skipped",
                           i, len(rows), key)
            failures += 1
            continue
        cov, answered = outline_coverage(session, _row_query_url(row), points)
        logger.info("[%d/%d] %s %s  coverage=%s (%d/%d answered)  %s",
                    i, len(rows), key, row["discovered_via"], cov, answered,
                    len(points), row["service_url"])
        if args.dry_run:
            continue
        try:
            (client.table("cadastre_sources")
             .update({"outline_coverage": cov, "outline_points": answered,
                      "outline_method": OUTLINE_METHOD,
                      "outline_checked_at":
                          datetime.now(timezone.utc).isoformat()})
             .eq("id", row["id"]).execute())
        except Exception as exc:  # fail the row, never the run
            logger.warning("[%d/%d] %s persistence failed: %s", i, len(rows), key, exc)
            failures += 1
    logger.info("Outline coverage done: %d row(s), %d failed", len(rows), failures)
    return 1 if failures else 0


def _client() -> Any:
    """Service-role client, the same rule as the pipeline's: anon cannot
    write, by design, and the census writes operational rows."""
    # the census paths that never import pipeline must still see .env
    from dotenv import load_dotenv
    load_dotenv()
    url = os.getenv("SUPABASE_URL")
    key = os.getenv("SUPABASE_SERVICE_ROLE_KEY")
    if not url or not key:
        raise SystemExit(
            "SUPABASE_SERVICE_ROLE_KEY is required to record the census "
            "(run with --dry-run to only search and verify).")
    from supabase import create_client
    return create_client(url, key)


def _censused_regions(client: Any) -> set:
    try:
        page, size, keys = 0, 1000, set()
        while True:
            res = (client.table("cadastre_sources")
                   .select("region_key")
                   .order("region_key")
                   .offset(page * size).limit(size).execute())
            batch = [r["region_key"] for r in res.data]
            keys.update(batch)
            if len(batch) < size:
                return keys
            page += 1
    except Exception as exc:  # table missing, key missing — treat as none
        logger.warning("Could not read censused regions (%s); "
                       "treating all as uncensused", exc)
        return set()


def _state_program_items(session: _ThrottledSession, state: str
                         ) -> List[Dict[str, Any]]:
    """Search once per state for the statewide program, plus the
    download-only sources recorded as candidates without a search."""
    items: List[Dict[str, Any]] = []
    if state in STATE_PROGRAM_SEARCHES:
        query, _ = STATE_PROGRAM_SEARCHES[state]
        data = session.get_json(AGOL_SEARCH_URL,
                                params={"q": query, "num": 3, "f": "json"})
        for item in (data or {}).get("results") or []:
            if item.get("type") in SERVICE_TYPES:
                items.append(item)
                break
    if state in STATE_DOWNLOAD_SOURCES:
        title, owner, note = STATE_DOWNLOAD_SOURCES[state]
        items.append({"title": title, "owner": owner, "url": None,
                      "id": None, "_download_note": note})
    return items


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Census public cadastral parcel sources, county by county.")
    parser.add_argument("--state", default=None,
                        help="two-letter state code to census (default: all)")
    parser.add_argument("--limit", type=int, default=10,
                        help="regions to census this run")
    parser.add_argument("--redo", action="store_true",
                        help="re-census regions that already have rows")
    parser.add_argument("--dry-run", action="store_true",
                        help="search and verify, write nothing")
    parser.add_argument("--list", action="store_true",
                        help="list censused/remaining counts and exit")
    parser.add_argument("--web-maps", action="store_true",
                        help="second pass: regions with no verified source, "
                             "searched through their web maps and the "
                             "self-hosted statewide programs")
    parser.add_argument("--outline", action="store_true",
                        help="measure verified rows' coverage of the county's "
                             "own outline (settles bbox-neighbour matches)")
    parser.add_argument("--via", default=None,
                        choices=["county_search", "state_program", "web_map"],
                        help="with --outline: one discovery path only")
    parser.add_argument("--include-unsourced", action="store_true",
                        help="with --targeted: also regions with no verified "
                             "row at all")
    parser.add_argument("--targeted", action="store_true",
                        help="regions with no verified layer covering 0.75 "
                             "of the county: statewide program, web maps with "
                             "the cap raised, and known servers' directories")
    args = parser.parse_args()
    if args.targeted:
        return _main_targeted(args)
    if args.outline:
        return _main_outline(args)
    if args.web_maps:
        return _main_web_maps(args)

    from pipeline import PARCEL_PILOTS

    regions = region_registry.pjm_screening_regions()
    # The nine parcel-pilot regions already have what the census looks
    # for: a live cadastral adapter. Census the other 545.
    targets = [r for r in regions if r not in PARCEL_PILOTS]
    if args.state:
        prefix = args.state.upper() + "-"
        targets = [r for r in targets if r.startswith(prefix)]
    if not args.list and not args.dry_run:
        client = _client()
        done = _censused_regions(client) if not args.redo else set()
    else:
        client, done = None, set()

    if args.list:
        remaining = [r for r in targets if r not in done]
        print(f"censused: {len(done)}   remaining: {len(remaining)}")
        for r in remaining[:20]:
            print(" ", r)
        return 0

    session = _ThrottledSession()
    # One program search per state in this batch.
    programs: Dict[str, List[Dict[str, Any]]] = {}
    for state in sorted({r.split("-", 1)[0] for r in targets}):
        programs[state] = _state_program_items(session, state)
        for item in programs[state]:
            logger.info("State program for %s: %s (%s)",
                        state, item.get("title"), item.get("owner"))

    batch = [r for r in targets if r not in done][:args.limit]
    logger.info("Census batch: %d region(s)%s", len(batch),
                " (dry run)" if args.dry_run else "")

    failures = 0
    for i, region_key in enumerate(batch, 1):
        region = region_registry.resolve(region_key)
        if region is None:
            logger.warning("[%d/%d] %s did not resolve — skipped",
                           i, len(batch), region_key)
            failures += 1
            continue
        state = region_key.split("-", 1)[0]
        prog_items = programs.get(state, [])
        # Download-only program items carry their note and no URL; they
        # are recorded per region as candidates without a verification.
        dl = [p for p in prog_items if p.get("url") is None]
        live = [p for p in prog_items if p.get("url") is not None]
        try:
            rows = census_region(session, region_key, region.county,
                                 state, region.bbox, live)
        except Exception as exc:
            logger.warning("[%d/%d] %s census failed: %s",
                           i, len(batch), region_key, exc)
            failures += 1
            continue
        for item in dl:
            rows.append(_row(region_key, state, region.county,
                             "state_program", item["title"], item["owner"],
                             None, SENTINEL_SERVICE_URL, 0,
                             evidence="candidate",
                             notes=item["_download_note"]))
        if not any(r["evidence_class"] != "none_found" for r in rows) and dl:
            # a download candidate replaces a none_found sentinel
            rows = [r for r in rows
                    if r["evidence_class"] != "none_found"]
        verified = sum(1 for r in rows if r["evidence_class"] == "verified")
        candidates = sum(1 for r in rows if r["evidence_class"] == "candidate")
        logger.info("[%d/%d] %s (%s): %d verified, %d candidate row(s)",
                    i, len(batch), region_key, region.county,
                    verified, candidates)
        if client is not None:
            # A census region is expensive to recompute and cheap to
            # re-record; a blip on the write path must fail the region,
            # never the run — 240 regions of verified work died to a
            # single ConnectTimeout here on the first full pass.
            try:
                for row in rows:
                    (client.table("cadastre_sources")
                     .upsert(row, on_conflict="region_key,service_url,layer_id")
                     .execute())
            except Exception as exc:
                logger.warning("[%d/%d] %s persistence failed: %s",
                               i, len(batch), region_key, exc)
                failures += 1
                continue
    logger.info("Census done: %d region(s), %d failed", len(batch), failures)
    return 1 if failures else 0


def _persist(client: Any, rows: List[Dict[str, Any]]) -> None:
    for row in rows:
        (client.table("cadastre_sources")
         .upsert(row, on_conflict="region_key,service_url,layer_id")
         .execute())


def _targeted_regions(client: Any
                      ) -> Tuple[List[str], set, Dict[str, List[str]]]:
    """
    (regions with verified rows but no parcel-sized layer covering 0.75 of
    the county, every region with a verified row, {region: every URL
    already recorded for it}).
    """
    covered, verified, urls = set(), set(), {}
    page, size = 0, 1000
    while True:
        res = (client.table("cadastre_sources")
               .select("region_key,evidence_class,record_count,"
                       "outline_coverage,service_url")
               .order("id").range(page * size, page * size + size - 1)
               .execute())
        for r in res.data:
            key = r["region_key"]
            if r["service_url"].startswith("http"):
                urls.setdefault(key, []).append(r["service_url"])
            if r["evidence_class"] != "verified":
                continue
            verified.add(key)
            if ((r["record_count"] or 0) >= 1000
                    and r["outline_coverage"] is not None
                    and float(r["outline_coverage"]) >= 0.75):
                covered.add(key)
        if len(res.data) < size:
            break
        page += 1
    return sorted(verified - covered), verified, urls


def _state_host_pool(session: _ThrottledSession, state: str,
                     urls: Dict[str, List[str]]) -> List[str]:
    """Every self-hosted ArcGIS Server root known in the state: recorded
    anywhere in the census, or listed by the endpoint catalog."""
    known = [u for key, us in urls.items()
             if key.startswith(state + "-") for u in us]
    for owner in CATALOG_OWNERS:
        data = session.get_json(AGOL_SEARCH_URL, params={
            "q": f'owner:{owner} title:"Parcels - {state} -"',
            "num": 100, "f": "json"}) or {}
        known += [it["url"] for it in data.get("results") or [] if it.get("url")]
    roots = {}
    for u in known:
        root = _services_root(u) if is_self_hosted(u) else None
        if root:
            roots.setdefault(root.lower(), root)
    return sorted(roots.values())


def _main_targeted(args: argparse.Namespace) -> int:
    """The targeted pass, then outline coverage of whatever it recorded."""
    from pipeline import PARCEL_PILOTS

    client = _client()
    wrong, verified, urls = _targeted_regions(client)
    targets = [r for r in wrong if r not in PARCEL_PILOTS]
    if args.include_unsourced:
        # searched by the first pass (it has a row, the sentinel at least)
        # and never verified anything
        targets += sorted(r for r in _censused_regions(client)
                          if r not in PARCEL_PILOTS and r not in verified)
    if args.state:
        targets = [r for r in targets if r.startswith(args.state.upper() + "-")]
    if args.list:
        print(f"targeted: {len(targets)}")
        for r in targets[:40]:
            print(" ", r)
        return 0
    targets = targets[:args.limit]
    logger.info("Targeted pass: %d region(s)%s", len(targets),
                " (dry run)" if args.dry_run else "")

    session = _ThrottledSession()
    pools = {st: _state_host_pool(session, st, urls)
             for st in sorted({t.split("-", 1)[0] for t in targets})}
    for st, pool in pools.items():
        logger.info("Host pool for %s: %d self-hosted server(s)", st, len(pool))
    failures = 0
    for i, key in enumerate(targets, 1):
        region = region_registry.resolve(key)
        if region is None:
            failures += 1
            continue
        state = key.split("-", 1)[0]
        try:
            rows = census_region_targeted(session, key, region.county, state,
                                          region.bbox, urls.get(key, []),
                                          state_hosts=pools.get(state))
        except Exception as exc:
            logger.warning("[%d/%d] %s targeted pass failed: %s",
                           i, len(targets), key, exc)
            failures += 1
            continue
        big = [r for r in rows if r["evidence_class"] == "verified"
               and (r.get("record_count") or 0) >= 1000]
        logger.info("[%d/%d] %s: %d row(s), %d parcel-sized", i, len(targets),
                    key, len(rows), len(big))
        if not args.dry_run and rows:
            try:
                _persist(client, rows)
            except Exception as exc:  # fail the region, never the run
                logger.warning("[%d/%d] %s persistence failed: %s",
                               i, len(targets), key, exc)
                failures += 1
    logger.info("Targeted pass done: %d region(s), %d failed",
                len(targets), failures)
    if args.dry_run:
        return 1 if failures else 0
    # measure what was just recorded: new rows have no outline_method
    args.via, args.redo, args.limit = None, False, 100000
    return max(1 if failures else 0, _main_outline(args))


def _main_web_maps(args: argparse.Namespace) -> int:
    """The second pass. Targets come from the table, like the first pass's
    progress: first-passed, still unverified, not yet web-map-passed."""
    from pipeline import PARCEL_PILOTS

    regions = [r for r in region_registry.pjm_screening_regions()
               if r not in PARCEL_PILOTS]
    if args.state:
        regions = [r for r in regions
                   if r.startswith(args.state.upper() + "-")]
    client = _client()  # the targets are read from the table, dry run too
    first_passed = _censused_regions(client)
    verified, passed = _web_map_targets(client)
    targets = [r for r in regions if r in first_passed
               and r not in verified and (args.redo or r not in passed)]
    if args.list:
        print(f"second pass remaining: {len(targets)}")
        for r in targets[:20]:
            print(" ", r)
        return 0

    session = _ThrottledSession()
    batch = targets[:args.limit]
    logger.info("Web-map pass: %d region(s)%s", len(batch),
                " (dry run)" if args.dry_run else "")
    failures = 0
    for i, region_key in enumerate(batch, 1):
        region = region_registry.resolve(region_key)
        if region is None:
            logger.warning("[%d/%d] %s did not resolve — skipped",
                           i, len(batch), region_key)
            failures += 1
            continue
        state = region_key.split("-", 1)[0]
        try:
            rows = census_region_web_maps(session, region_key, region.county,
                                          state, region.bbox)
        except Exception as exc:
            logger.warning("[%d/%d] %s web-map pass failed: %s",
                           i, len(batch), region_key, exc)
            failures += 1
            continue
        for r in rows:
            if r["evidence_class"] != "none_found":
                logger.info("    %s %s %s", r["evidence_class"],
                            r.get("record_count"), r["service_url"])
        logger.info("[%d/%d] %s (%s): %d verified",
                    i, len(batch), region_key, region.county,
                    sum(r["evidence_class"] == "verified" for r in rows))
        if not args.dry_run:
            try:
                _persist(client, rows)
            except Exception as exc:  # fail the region, never the run
                logger.warning("[%d/%d] %s persistence failed: %s",
                               i, len(batch), region_key, exc)
                failures += 1
    logger.info("Web-map pass done: %d region(s), %d failed",
                len(batch), failures)
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
