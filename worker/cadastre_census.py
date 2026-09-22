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
import time
from typing import Any, Dict, List, Optional, Tuple

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
                    return resp.json()
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


def choose_layers(service_json: Dict[str, Any]
                  ) -> List[Dict[str, Any]]:
    """
    Which layers of a service to record: polygon layers, preferring names
    that say parcel/tax/cadastre, capped at two per service.
    """
    layers = service_json.get("layers") or []
    polygons = [l for l in layers
                if l.get("geometryType") == "esriGeometryPolygon"]
    named = [l for l in polygons
             if any(k in (l.get("name") or "").lower()
                    for k in ("parcel", "tax", "cadastre"))]
    chosen = named + [l for l in polygons if l not in named]
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
    named_first = sorted(
        root_layers,
        key=lambda l: 0 if any(k in (l.get("name") or "").lower()
                               for k in ("parcel", "tax", "cadastre")) else 1)
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


def _client() -> Any:
    """Service-role client, the same rule as the pipeline's: anon cannot
    write, by design, and the census writes operational rows."""
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
    args = parser.parse_args()

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
            for row in rows:
                (client.table("cadastre_sources")
                 .upsert(row, on_conflict="region_key,service_url,layer_id")
                 .execute())
    logger.info("Census done: %d region(s), %d failed", len(batch), failures)
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
