"""
Federal-layer measurements for a county with no cadastre.

Metrics only, never verdicts. The gate thresholds are calibrated for parcels
-- floodway fails above 0.5% -- and a 10 km2 screening cell is roughly 250x
larger than a 10-acre parcel, so applying them unchanged would fail nearly
every cell in America and mean nothing. What a cell can honestly say is how
much of it each federal layer covers, and that is all this records.

Verdicts arrive when a county gets a cadastre, on thresholds that were
calibrated for the geometry they are judging.

Scope is CONUS: areas are measured in EPSG:5070, the equal-area projection the
screening grid already uses. Alaska, Hawaii and Puerto Rico would need their
own and are not covered.
"""

import logging
from typing import Any, Dict, List, Optional

import geopandas as gpd

import overlay_layers
from parcel_gates import _OverlapIndex

logger = logging.getLogger(__name__)

# Equal-area, CONUS. Matches pipeline.SCREENING_PLANAR_CRS: a national run
# cannot use the parcel tier's local UTM zone.
PLANAR_CRS = "EPSG:5070"


def measure(cells_gdf: gpd.GeoDataFrame,
            min_lon: float, min_lat: float, max_lon: float, max_lat: float,
            state_code: str) -> List[Dict[str, Any]]:
    """
    One dict of federal measurements per cell, in the order given.

    Every layer degrades independently: a layer that fails to fetch leaves its
    keys absent rather than zero, so "no wetland here" and "nobody looked" stay
    different facts.
    """
    planar = cells_gdf.to_crs(PLANAR_CRS)
    areas = planar.geometry.area

    wetlands, _ = overlay_layers.fetch_nwi_wetlands(
        min_lon, min_lat, max_lon, max_lat, state_code=state_code)
    nfhl, _ = overlay_layers.fetch_nfhl_floodzones(
        min_lon, min_lat, max_lon, max_lat, state_code=state_code)
    padus = overlay_layers.fetch_padus(
        min_lon, min_lat, max_lon, max_lat, state_code=state_code)
    roads = overlay_layers.fetch_tiger_roads(
        min_lon, min_lat, max_lon, max_lat, state_code=state_code)

    # Same subsetting the parcel tier uses, so a national number and a
    # diligenced one mean the same thing.
    floodway_ix = _OverlapIndex(
        nfhl[nfhl["zone_subty"] == "FLOODWAY"].to_crs(PLANAR_CRS)
        if nfhl is not None else None)
    floodplain_ix = _OverlapIndex(
        nfhl[(nfhl["zone_subty"] != "FLOODWAY")
             & nfhl["fld_zone"].str.upper().str.match(r"^(A|AE|AH|AO|A[0-9])")]
        .to_crs(PLANAR_CRS)
        if nfhl is not None else None)
    wetland_ix = _OverlapIndex(
        wetlands.to_crs(PLANAR_CRS) if wetlands is not None else None)
    padus_ix = _OverlapIndex(
        padus.to_crs(PLANAR_CRS) if padus is not None else None)

    road_km: Dict[int, float] = {}
    if roads is not None and len(roads):
        near = gpd.sjoin_nearest(planar[["geometry"]],
                                 roads.to_crs(PLANAR_CRS)[["geometry"]],
                                 how="left", distance_col="_d")
        # sjoin_nearest can return several ties for one cell; keep the first.
        near = near[~near.index.duplicated(keep="first")]
        road_km = {i: round(d / 1000.0, 3) for i, d in near["_d"].items()
                   if d == d}

    try:
        slopes = overlay_layers.sample_3dep_slopes(cells_gdf)
    except Exception as e:  # noqa: BLE001
        logger.warning("3DEP slope sampling failed: %s", e)
        slopes = None

    out: List[Dict[str, Any]] = []
    for pos, idx in enumerate(planar.index):
        geom, area = planar.geometry.iloc[pos], float(areas.iloc[pos])
        m: Dict[str, Any] = {}
        if nfhl is not None:
            m["floodway_pct"] = round(floodway_ix.fraction(geom, area), 3)
            m["floodplain_pct"] = round(floodplain_ix.fraction(geom, area), 3)
        if wetlands is not None:
            m["wetland_pct"] = round(wetland_ix.fraction(geom, area), 3)
        if padus is not None:
            m["protected_pct"] = round(padus_ix.fraction(geom, area), 3)
        if idx in road_km:
            m["nearest_road_km"] = road_km[idx]
        if slopes:
            s = slopes.get(idx)
            if s and s[2] > 0:
                m["slope_max_pct"] = round(s[0], 2) if s[0] is not None else None
                m["slope_median_pct"] = round(s[1], 2) if s[1] is not None else None
        out.append(m)

    logger.info(
        "National metrics: %d cells measured | layers: %s",
        len(out),
        ", ".join(n for n, g in (("nwi", wetlands), ("nfhl", nfhl),
                                 ("padus", padus), ("roads", roads),
                                 ("3dep", slopes)) if g is not None) or "none")
    return out
