"""
Interconnection evidence — where the networks actually are.

Power decides whether a data centre can be built; interconnection decides
whether it is worth building. Loudoun is Data Center Alley because Equinix
Ashburn sits inside it carrying over five hundred networks, not because
the land is unusually good.

PeeringDB is the industry's own public register of interconnection
facilities: carrier hotels and colocation sites, with coordinates and, for
each one, how many networks, carriers and exchanges are actually present.
Operators maintain their own entries, so counts are a record of who is
there rather than an estimate of who might be.

Two things are derived from it per parcel:

  * distance to the nearest facility, and how connected that facility is
  * a latency floor — the round trip light itself needs over that
    distance through fibre

The floor is computed on the great-circle distance with no allowance for
routing, which makes it a bound rather than a forecast: no fibre path can
be shorter than the straight line, so no equipment, carrier or contract
can beat this number. Real routes run perhaps 1.3 to 1.5 times longer and
add switching on top, so the honest reading is "cannot be better than",
never "will be".
"""

import json
import logging
import os
from pathlib import Path
from typing import Any, Dict, List, Optional

import geopandas as gpd
import pandas as pd
import requests
from shapely.geometry import Point

logger = logging.getLogger("network_evidence")

PEERINGDB_FAC_URL = "https://www.peeringdb.com/api/fac"
PEERINGDB_CACHE = Path(__file__).parent / "cache" / "peeringdb_facilities_us.json"

# Speed of light in single-mode fibre. c / n, with n = 1.4682 for standard
# SMF-28 at 1550 nm — the refractive index, not a modelling choice.
C_KM_S = 299_792.458
FIBRE_INDEX = 1.4682
# Round trip: out and back, in milliseconds per kilometre.
RTT_MS_PER_KM = 2.0 * 1000.0 / (C_KM_S / FIBRE_INDEX)

# Radius for the density measure. Metro interconnection is generally
# reachable inside this without long-haul transport.
DENSITY_RADIUS_MILES = 25.0
METRES_PER_MILE = 1609.344


def fetch_facilities(country: str = "US", refresh: bool = False
                     ) -> Optional[gpd.GeoDataFrame]:
    """
    Interconnection facilities with coordinates and presence counts.

    Cached on disk — the register is small and changes slowly. Returns
    None when unreachable, in which case the caller records the network
    metrics as absent rather than inferring connectivity from geography.
    """
    try:
        if refresh or not PEERINGDB_CACHE.exists():
            PEERINGDB_CACHE.parent.mkdir(parents=True, exist_ok=True)
            logger.info("Fetching PeeringDB facilities (%s)…", country)
            r = requests.get(
                PEERINGDB_FAC_URL,
                params={"country": country},
                headers={"Accept": "application/json"},
                timeout=120,
            )
            r.raise_for_status()
            PEERINGDB_CACHE.write_text(json.dumps(r.json()), encoding="utf-8")

        raw = json.loads(PEERINGDB_CACHE.read_text(encoding="utf-8")).get("data", [])
    except Exception as e:  # noqa: BLE001
        logger.warning("PeeringDB unavailable (%s) — network metrics omitted.", e)
        return None

    rows: List[Dict[str, Any]] = []
    for f in raw:
        lat, lon = f.get("latitude"), f.get("longitude")
        if lat is None or lon is None or f.get("status") != "ok":
            continue
        rows.append({
            "facility": f.get("name"),
            "operator": f.get("org_name"),
            "city": f.get("city"),
            "state": f.get("state"),
            "net_count": int(f.get("net_count") or 0),
            "carrier_count": int(f.get("carrier_count") or 0),
            "ix_count": int(f.get("ix_count") or 0),
            "updated": f.get("updated"),
            "geometry": Point(float(lon), float(lat)),
        })
    if not rows:
        logger.warning("PeeringDB returned no usable facilities — metrics omitted.")
        return None
    gdf = gpd.GeoDataFrame(rows, geometry="geometry", crs="EPSG:4326")
    logger.info("PeeringDB: %d facilities, %d networks present in total.",
                len(gdf), int(gdf.net_count.sum()))
    return gdf


def latency_floor_ms(distance_miles: float) -> float:
    """
    Round-trip milliseconds light needs over this straight-line distance
    through fibre. A floor: no route is shorter than the straight line.
    """
    return distance_miles * 1.609344 * RTT_MS_PER_KM


def nearest_facilities(planar_parcels: gpd.GeoDataFrame,
                       facilities: Optional[gpd.GeoDataFrame],
                       planar_crs: str) -> Optional[pd.DataFrame]:
    """
    Nearest facility per parcel, plus interconnection density nearby.

    Returned indexed like the parcel frame, so the caller joins by index.
    None when the register is unavailable — absent, not zero, because zero
    would read as "no connectivity here" rather than "not looked up".
    """
    if facilities is None or len(facilities) == 0:
        return None
    try:
        fac = facilities.to_crs(planar_crs)
        near = gpd.sjoin_nearest(
            planar_parcels[["geometry"]], fac, how="left", distance_col="dist_m"
        )
        # sjoin_nearest emits one row per tie; the first is enough and the
        # index must stay one-to-one with the parcels.
        near = near[~near.index.duplicated(keep="first")]

        # Density needs every facility inside the radius, so this is a
        # buffered intersects join. sjoin_nearest with max_distance returns
        # only the single closest match and would report one facility where
        # a metro has twenty.
        ring = planar_parcels[["geometry"]].copy()
        ring["geometry"] = ring.geometry.buffer(DENSITY_RADIUS_MILES * METRES_PER_MILE)
        hits = gpd.sjoin(ring, fac, how="left", predicate="intersects")
        within = hits.groupby(level=0).agg(
            facilities_within=("net_count", "count"),
            networks_within=("net_count", "sum"),
            # The largest facility in reach, which is the one that decides
            # whether real peering is available. The closest facility can be
            # a single-tenant room while a major carrier hotel sits a mile
            # further out.
            best_networks_within=("net_count", "max"),
        )

        out = pd.DataFrame({
            "facility": near["facility"],
            "operator": near["operator"],
            "city": near["city"],
            "net_count": near["net_count"],
            "carrier_count": near["carrier_count"],
            "ix_count": near["ix_count"],
            "updated": near["updated"],
            "distance_miles": near["dist_m"] / METRES_PER_MILE,
        })
        out["facilities_within_25mi"] = within["facilities_within"]
        out["networks_within_25mi"] = within["networks_within"]
        out["best_networks_within_25mi"] = within["best_networks_within"]
        return out
    except Exception as e:  # noqa: BLE001
        logger.warning("Facility join failed (%s) — network metrics omitted.", e)
        return None
